"""The story read holds a chunk of articles at a time, not every mention of the period (audit 0.5.0, A-003).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``article_keyword_sets`` used to run ONE ``.all()`` over every keyword mention of the period and build a
second copy per article before the ``max_articles`` cap was applied. A yearly edition on a corpus younger
than a year is the whole table: 2.0 to 3.1 GB of transient Python heap on the machines the field runs on.
The read now takes the period's article ids from the clock index, reads their mentions
``_ARTICLE_CHUNK`` articles at a time and keeps only the richest ``max_articles`` sets as they arrive.

The answer must not change, so every test here is a comparison with ``_old_sets`` below, a copy of the
read this replaced (the one-statement version with the same stoplist and top-N rules). The memory test
fails against that copy and passes against the new read, so it is not a test of its own construction.

Open facts the tests do not cover: the field-scale figures (measured by ``audit-0.5.0/inputs/remeasure-stories-export``),
and quarantined articles, which this read has never left out (D22 is the slice that does).
"""

from __future__ import annotations

import gc
import math
import random
import tracemalloc
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import and_, create_engine, event
from sqlalchemy.orm import Session

from src.bulletin import stories
from src.bulletin.period import resolve_period
from src.bulletin.stories import (
    _richest_sets,
    _stories_deadline_s,
    article_keyword_sets,
    build_stories,
)
from src.database.derived_views import KeywordMentionRead
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.database.stand_in import ARTICLE_HASH_PREFIX, ARTICLE_REASON, not_a_stand_in_article_id

_P = resolve_period("weekly", end=date(2026, 8, 1))
_HIDDEN = ["mathcal", "mathbf", "mathbb", "mathrm", "fig", "supplementary", "crossref"]
_VISIBLE = [f"term{i:02d}" for i in range(45)]


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _old_sets(session, period) -> dict[int, set[int]]:
    """The read this replaced: every mention of the period in one statement, then the stoplist, then the top 12."""
    from src.analytics.queries import _hidden_predicate

    rows = (
        session.query(KeywordMentionRead.article_id, KeywordMentionRead.keyword_id, KeywordMentionRead.count)
        .filter(
            and_(KeywordMentionRead.observed_on >= period.start, KeywordMentionRead.observed_on < period.end),
            not_a_stand_in_article_id(KeywordMentionRead.article_id),
        )
        .all()
    )
    is_hidden = _hidden_predicate()
    distinct = sorted({int(kid) for _aid, kid, _cnt in rows})
    hidden_ids: set[int] = set()
    for i in range(0, len(distinct), 900):
        for kid, norm in session.query(Keyword.id, Keyword.normalized_term).filter(
            Keyword.id.in_(distinct[i : i + 900])
        ):
            if is_hidden(norm):
                hidden_ids.add(int(kid))
    per: dict[int, list[tuple[int, int]]] = {int(aid): [] for aid, _kid, _cnt in rows}
    for aid, kid, cnt in rows:
        if int(kid) in hidden_ids:
            continue
        per.setdefault(int(aid), []).append((int(cnt or 0), int(kid)))
    out: dict[int, set[int]] = {}
    for aid, pairs in per.items():
        pairs.sort(key=lambda p: (-p[0], p[1]))
        out[aid] = {kid for _c, kid in pairs[: stories._TERMS_PER_ARTICLE]}
    return out


def _old_bound(sets: dict[int, set[int]], max_articles: int) -> tuple[dict[int, set[int]], int, int]:
    compared = {a: s for a, s in sets.items() if s}
    with_terms = len(compared)
    if len(compared) > max_articles:
        keep = sorted(compared, key=lambda a: (-len(compared[a]), a))[:max_articles]
        compared = {a: compared[a] for a in keep}
    return compared, len(sets), with_terms


def _world(session, *, articles: int, seed: int = 7, mentions: tuple[int, int] = (1, 30)) -> dict[str, list[int]]:
    """A corpus with the shapes the read has to get right.

    In the period (2026-07-25 to 2026-07-31): ordinary articles with 1 to 30 mentions of 45 visible and 7 hidden
    keywords, counts 1 to 4 so there are ties at every cut; an article whose every keyword is hidden; an article
    with no mention row; a quarantined article (kept, as before); one with no ``published_at`` (its ``created_at``
    is the clock); a stand-in (left out); one at the period's first instant (in), one a second before it ends (in) and
    one at the instant it ends (out).
    Outside it: articles a week early and a week late, with mentions.
    """
    rng = random.Random(seed)
    src = Source(name="Only", domain="only.test")
    session.add(src)
    session.flush()
    kw: dict[str, int] = {}
    for term in _HIDDEN + _VISIBLE:
        k = Keyword(term=term, normalized_term=term, language="en")
        session.add(k)
        session.flush()
        kw[term] = k.id
    made: dict[str, list[int]] = {k: [] for k in ("period", "hidden_only", "bare", "quarantined", "undated", "stand_in", "outside", "first_instant", "last_second", "end_instant")}
    counter = [0]

    def article(kind: str, when: datetime, *, published: bool = True, quarantined: bool = False, stand_in: bool = False) -> Article:
        counter[0] += 1
        i = counter[0]
        art = Article(
            url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=src.id, title=f"A{i}", content=f"body {i}",
            hash=(f"{ARTICLE_HASH_PREFIX}{i})" if stand_in else f"{i:064d}"),
            published_at=when if published else None, created_at=when, quarantined=quarantined or stand_in,
            quarantine_reason=ARTICLE_REASON if stand_in else None,
        )
        session.add(art)
        session.flush()
        made[kind].append(art.id)
        return art

    def mention(art: Article, term: str, count: int, when: datetime) -> None:
        session.add(KeywordMention(keyword_id=kw[term], article_id=art.id, count=count, observed_on=when.date(), source_id=src.id))

    start = datetime(_P.start.year, _P.start.month, _P.start.day)
    for _ in range(articles):
        when = start + timedelta(days=rng.randrange(7), hours=rng.randrange(24))
        art = article("period", when)
        terms = rng.sample(_VISIBLE + _HIDDEN, rng.randint(*mentions))
        for term in terms:
            mention(art, term, rng.randint(1, 4), when)
    when = start + timedelta(days=2)
    art = article("hidden_only", when)
    for term in _HIDDEN[:4]:
        mention(art, term, 3, when)
    article("bare", when)
    art = article("quarantined", when, quarantined=True)
    for term in _VISIBLE[:6]:
        mention(art, term, 2, when)
    art = article("undated", when, published=False)
    for term in _VISIBLE[3:9]:
        mention(art, term, 2, when)
    art = article("stand_in", when, stand_in=True)
    for term in _VISIBLE[:5]:
        mention(art, term, 2, when)
    # the period is [start, end): its first instant is in, the instant the next period starts at is not
    end = datetime(_P.end.year, _P.end.month, _P.end.day)
    for kind, when in (("first_instant", start), ("last_second", end - timedelta(seconds=1)), ("end_instant", end)):
        art = article(kind, when)
        for term in _VISIBLE[10:16]:
            mention(art, term, 2, when)
    for early in (start - timedelta(days=3), start + timedelta(days=8)):
        art = article("outside", early)
        for term in _VISIBLE[:8]:
            mention(art, term, 2, early)
    session.commit()
    return made


@pytest.fixture()
def world():
    s = _session()
    made = _world(s, articles=130)
    try:
        yield s, made
    finally:
        s.close()


# --------------------------------------------------------------------------------------------- same answer


@pytest.mark.parametrize("chunk", [1, 7, 900])
def test_the_chunked_read_gives_the_one_statement_read_exactly(world, monkeypatch, chunk):
    s, made = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", chunk)
    new, old = article_keyword_sets(s, _P), _old_sets(s, _P)
    assert new == old
    # the shapes the corpus was built to contain are all in the comparison, so equality is not vacuous
    assert made["hidden_only"][0] in new and new[made["hidden_only"][0]] == set()
    assert made["bare"][0] not in new
    assert made["quarantined"][0] in new
    assert made["undated"][0] in new
    assert made["stand_in"][0] not in new
    assert made["first_instant"][0] in new and made["last_second"][0] in new and made["end_instant"][0] not in new
    assert not set(made["outside"]) & set(new)
    assert any(len(v) == stories._TERMS_PER_ARTICLE for v in new.values()), "some article is cut at the top 12"


def test_the_stoplist_verdicts_survive_being_forgotten_between_chunks(world, monkeypatch):
    """A verdict is a pure function of the term, so emptying the table when it fills changes nothing."""
    s, _ = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 5)
    monkeypatch.setattr(stories, "_VERDICTS_KEPT", 3)
    assert article_keyword_sets(s, _P) == _old_sets(s, _P)


def test_the_verdict_table_is_emptied_when_it_fills(world, monkeypatch):
    """The table is what keeps resident memory flat in the number of distinct keywords, so emptying it must really happen:
    with a tiny table each chunk is judged afresh, with the default each keyword is judged once."""
    s, _ = world
    import src.analytics.queries as queries

    real = queries._hidden_predicate
    calls: list[int] = []

    def counting():
        inner = real()

        def is_hidden(term):
            calls.append(1)
            return inner(term)

        return is_hidden

    monkeypatch.setattr(queries, "_hidden_predicate", counting)
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 5)
    article_keyword_sets(s, _P)
    judged_once = len(calls)
    calls.clear()
    monkeypatch.setattr(stories, "_VERDICTS_KEPT", 3)
    article_keyword_sets(s, _P)
    assert judged_once <= len(_HIDDEN) + len(_VISIBLE)
    assert len(calls) > 2 * judged_once


@pytest.mark.parametrize("bound", [0, 1, 2, 5, 40, 10_000])
def test_the_richest_sets_are_the_ones_the_sorted_slice_kept(world, monkeypatch, bound):
    s, _ = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 11)
    kept, total, with_terms = _richest_sets(s, _P, bound)
    expect, e_total, e_with = _old_bound(_old_sets(s, _P), bound)
    assert (kept, total, with_terms) == (expect, e_total, e_with)
    assert len(kept) <= max(bound, 0)


def test_the_edition_numbers_are_the_old_ones(world, monkeypatch):
    s, _ = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 13)
    for bound in (3, 40, 4000):
        out = build_stories(s, _P, max_articles=bound)
        compared, total, with_terms = _old_bound(_old_sets(s, _P), bound)
        assert out["articles_in_period"] == total
        assert out["articles_compared"] == len(compared)
        assert out["comparison_bounded"] is (with_terms > bound)
        clusters = stories.cluster_articles(compared)[:12]
        assert [st["article_ids"] for st in out["stories"]] == clusters
        if bound >= 40:
            assert clusters, "the comparison must have produced stories, or equality of two empty lists proves nothing"


# --------------------------------------------------------------------------------------------- the stated differences


def test_the_period_follows_the_articles_clock_where_the_old_read_followed_each_mentions_date():
    """The two differences audit 0.5.0 A-003 states, pinned so they are decisions on the record and not surprises.

    The old read chose MENTION rows by their ``observed_on`` (the date stamped when the article was indexed); the new one chooses
    ARTICLES by ``coalesce(published_at, created_at)`` (how ``period.py`` defines the period) and reads all of their mentions. They
    agree for every article whose clock has not moved since it was indexed, which is the whole of ``_world``. They differ for:

    * ``healed``: the clock is inside the period but its mentions are dated a week earlier (the law corpus's heal cleared
      ``published_at`` without re-indexing until 0.5.1 item 39, and a store that ran it keeps the stale stamps): the new read has
      it, the old did not;
    * ``undated``: the clock is inside, the mentions carry no date at all: the new read has it, the old did not;
    * ``moved_out``: the mentions are dated inside, the clock has since moved a week later: the old read had it, the new does not;
    * ``orphan``: mention rows whose article row is gone, dated inside: the old read counted them, the new does not.
    """
    s = _session()
    made = _world(s, articles=20)
    src = s.query(Source).one()
    term = {k.term: k.id for k in s.query(Keyword)}
    start = datetime(_P.start.year, _P.start.month, _P.start.day)
    inside, week_early, week_late = start + timedelta(days=3), start - timedelta(days=4), start + timedelta(days=11)

    def add(label: str, clock: datetime, observed: date | None) -> int:
        art = Article(
            url=f"https://d/{label}", canonical_url=f"https://d/{label}", source_id=src.id, title=label, content=label,
            hash=f"{label:0<64}"[:64], published_at=clock, created_at=clock,
        )
        s.add(art)
        s.flush()
        for t in _VISIBLE[:5]:
            s.add(KeywordMention(keyword_id=term[t], article_id=art.id, count=2, observed_on=observed, source_id=src.id))
        return art.id

    healed = add("healed", inside, week_early.date())
    undated = add("undated-mentions", inside, None)
    moved_out = add("moved-out", week_late, inside.date())
    orphan = 10_000_000
    for t in _VISIBLE[:5]:
        s.add(KeywordMention(keyword_id=term[t], article_id=orphan, count=2, observed_on=inside.date(), source_id=src.id))
    s.commit()

    new, old = article_keyword_sets(s, _P), _old_sets(s, _P)
    assert {healed, undated} <= set(new) and not ({healed, undated} & set(old))
    assert moved_out in old and moved_out not in new
    assert orphan in old and orphan not in new
    # nothing else differs: the rest of the answer is the old one exactly
    ours = {healed, undated, moved_out, orphan}
    assert {a: v for a, v in new.items() if a not in ours} == {a: v for a, v in old.items() if a not in ours}
    assert set(made["period"]) <= set(new)
    s.close()


# --------------------------------------------------------------------------------------------- the bound


def _mention_statements(session):
    seen: list[tuple[str, tuple]] = []

    def grab(conn, cursor, statement, parameters, context, executemany):
        if "keyword_mentions" in statement:
            seen.append((statement, tuple(parameters)))

    event.listen(session.get_bind(), "before_cursor_execute", grab)
    return seen


def test_no_statement_reads_the_mentions_of_more_than_one_chunk(world, monkeypatch):
    s, made = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 10)
    seen = _mention_statements(s)
    build_stories(s, _P)
    in_period = len(made["period"]) + len(made["hidden_only"]) + len(made["bare"]) + len(made["quarantined"]) + len(made["undated"]) + len(made["first_instant"]) + len(made["last_second"])
    assert seen, "the read must have touched keyword_mentions"
    for statement, params in seen:
        assert "article_id IN" in statement, "a read of the mentions that is not bounded to a chunk of articles"
        assert len(params) <= 10
    assert len(seen) == math.ceil(in_period / 10)


def test_the_mention_read_is_served_by_the_covering_article_index(world, monkeypatch):
    """The plan of the statement the read ACTUALLY issues (captured as it runs), not of one written beside it."""
    s, _ = world
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 10)
    seen = _mention_statements(s)
    build_stories(s, _P)
    assert seen
    statement, params = seen[0]
    plan = " ".join(str(r[3]) for r in s.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params))
    assert "COVERING INDEX ix_mention_article_count" in plan, plan


@contextmanager
def _peak():
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        yield lambda: tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_resident_memory_does_not_follow_the_length_of_the_period(monkeypatch):
    """500 articles and 2,000 articles of 25 mentions each, the same 20 kept: what the new read adds with the length of the period
    is a small part of what the old one adds. Compared as GROWTH (peak at 2,000 minus peak at 500), so the fixed costs both share
    (the stoplist, the verdict table, the interpreter's own caches) cancel; a first small build warms them so that they are
    not charged to the first measurement. Measured on this machine: the old read grows by 9.7 MB, the new one by 0.3 MB."""
    monkeypatch.setattr(stories, "_ARTICLE_CHUNK", 50)
    warm = _session()
    _world(warm, articles=5)
    build_stories(warm, _P, max_articles=20)
    warm.close()
    peaks: dict[tuple[str, int], int] = {}
    for n in (500, 2000):
        s = _session()
        _world(s, articles=n, mentions=(25, 25))
        with _peak() as peak:
            build_stories(s, _P, max_articles=20)
            peaks["new", n] = peak()
        with _peak() as peak:
            _old_sets(s, _P)
            peaks["old", n] = peak()
        s.close()
    grew_old = peaks["old", 2000] - peaks["old", 500]
    grew_new = peaks["new", 2000] - peaks["new", 500]
    assert grew_old > 0
    assert grew_new < 0.25 * grew_old, peaks
    assert peaks["new", 2000] < 0.35 * peaks["old", 2000], peaks


# --------------------------------------------------------------------------------------------- the deadline


def test_the_mention_read_runs_inside_a_statement_deadline(world, monkeypatch):
    s, _ = world
    import src.database.maintenance as maintenance

    log: list[str] = []
    real = maintenance.statement_deadline
    taken: list[float | None] = []

    @contextmanager
    def spy(session, seconds=None):
        taken.append(seconds)
        log.append("enter")
        with real(session, seconds):
            yield
        log.append("exit")

    real_richest = stories._richest_sets

    def richest(*a, **k):
        log.append("read")
        return real_richest(*a, **k)

    monkeypatch.setattr(maintenance, "statement_deadline", spy)
    monkeypatch.setattr(stories, "_richest_sets", richest)
    monkeypatch.setenv("OO_BULLETIN_STORIES_DEADLINE_S", "45")
    out = build_stories(s, _P)
    assert log == ["enter", "read", "exit"]
    assert taken == [45.0]
    assert out["read_bound"]["deadline_s"] == 45.0
    assert out["read_bound"]["articles_per_read"] == stories._ARTICLE_CHUNK
    assert out["read_bound"]["max_articles"] == 4000


@pytest.mark.parametrize(
    ("value", "expect"),
    [
        (None, stories._DEADLINE_DEFAULT_S),
        ("45", 45.0),
        ("0.5", 0.5),
        ("abc", stories._DEADLINE_DEFAULT_S),
        ("0", stories._DEADLINE_DEFAULT_S),
        ("-5", stories._DEADLINE_DEFAULT_S),
        ("nan", stories._DEADLINE_DEFAULT_S),
        ("inf", stories._DEADLINE_DEFAULT_S),
        ("99999", 3600.0),
    ],
)
def test_the_deadline_setting_is_clamped(monkeypatch, value, expect):
    if value is None:
        monkeypatch.delenv("OO_BULLETIN_STORIES_DEADLINE_S", raising=False)
    else:
        monkeypatch.setenv("OO_BULLETIN_STORIES_DEADLINE_S", value)
    assert _stories_deadline_s() == expect


def test_a_read_that_is_really_out_of_time_is_stopped_and_the_same_read_with_time_is_not(monkeypatch):
    """The deadline is on the read: with next to no time the progress handler stops it and ``StatementTimeout`` comes out of
    ``build_stories`` (the progress handler fires every 20,000 opcodes, so the world is big enough to reach one); with the default
    the same world completes. Without ``statement_deadline`` around ``_richest_sets`` the first half fails."""
    from src.database.maintenance import StatementTimeout

    s = _session()
    _world(s, articles=700, mentions=(25, 25))
    monkeypatch.setenv("OO_BULLETIN_STORIES_DEADLINE_S", "1e-9")
    with pytest.raises(StatementTimeout):
        build_stories(s, _P)
    monkeypatch.delenv("OO_BULLETIN_STORIES_DEADLINE_S")
    out = build_stories(s, _P)
    assert out["articles_in_period"] >= 700
    s.close()


def test_a_read_that_runs_out_of_time_leaves_the_edition_without_stories(monkeypatch):
    """The deadline's exception is not caught by the read: the edition's own guard records it and the document is still whole."""
    from src.bulletin.edition import build_edition
    from src.database.maintenance import StatementTimeout

    s = _session()
    _world(s, articles=5)

    def boom(*_a, **_k):
        raise StatementTimeout("the statement ran out of time")

    monkeypatch.setattr(stories, "_richest_sets", boom)
    with pytest.raises(StatementTimeout):
        build_stories(s, _P)
    edition = build_edition(s, _P)
    assert edition["stories"] == {"stories": [], "error": "StatementTimeout"}
    s.close()
