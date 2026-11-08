"""The HOT tier's mention set is read from the frequency index, and a corpus's first 5,001 keywords cost an index read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``corpus_mention_titles`` ran ``ORDER BY coalesce(frequency, 0) DESC, term LIMIT 5001`` every wiki drain. No
index serves an expression, so it scanned and sorted every keyword: 9.5 s on average over 224 calls on the
2.26 million keywords of the 16 Oct 2026 bundles (max 78 s), a read snapshot held the whole time. The
order is now ``frequency DESC, term``, which ``idx_keyword_frequency`` serves.

The ORDER of the answer is the contract this file holds (most frequent first, ties by term, the cap reported); the PLAN is the
property the change exists for, so it is read from SQLite itself, not from the source text.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Keyword
from src.wiki import hotset


@pytest.fixture
def corpus(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'hot-mentions.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as db:
        yield db, engine


def _seed(db, rows):
    for term, frequency in rows:
        db.add(Keyword(term=term, normalized_term=term.lower(), frequency=frequency))
    db.commit()


def test_the_most_frequent_terms_come_first_ties_by_term_and_a_null_frequency_last(corpus):
    db, _engine = corpus
    _seed(
        db,
        [("delta", 5), ("alpha", 5), ("bravo", 9), ("zulu", None), ("echo", 0), ("charlie", 2), ("yankee", None)],
    )
    titles, capped = hotset.corpus_mention_titles(db, limit=4)
    assert titles == {"bravo", "alpha", "delta", "charlie"}, "frequency 9, then the two 5s by term, then 2"
    assert capped is True, "seven keywords, four taken: the cap was hit and the caller is told"
    everything, capped_all = hotset.corpus_mention_titles(db, limit=7)
    assert everything == {"bravo", "alpha", "delta", "charlie", "echo", "zulu", "yankee"} and capped_all is False


def test_the_cap_is_reported_exactly_at_the_boundary(corpus):
    db, _engine = corpus
    _seed(db, [(f"t{i:02d}", 100 - i) for i in range(6)])
    titles, capped = hotset.corpus_mention_titles(db, limit=6)
    assert len(titles) == 6 and capped is False, "as many as the limit is not a truncation"
    titles, capped = hotset.corpus_mention_titles(db, limit=5)
    assert titles == {f"t{i:02d}" for i in range(5)} and capped is True


def _statement_of_the_read(db, engine):
    """The statement ``corpus_mention_titles`` sends, with its parameters, as SQLite received it."""
    seen: list[tuple[str, object]] = []

    def grab(_conn, _cursor, statement, parameters, _context, _many):
        if "FROM keywords" in statement:
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", grab)
    try:
        hotset.corpus_mention_titles(db, limit=10)
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    assert len(seen) == 1, "the mention set is ONE statement"
    return seen[0]


def test_the_read_is_served_by_the_frequency_index_and_sorts_nothing_but_ties(corpus):
    """The property the change is for. The plan, asked of SQLite on the very statement the function sent: it walks
    ``idx_keyword_frequency`` and sorts only the right part of the ORDER BY (the ties). The old form's plan was a bare
    SCAN with USE TEMP B-TREE FOR ORDER BY, a sort of every keyword."""
    db, engine = corpus
    _seed(db, [(f"t{i}", i % 7) for i in range(50)])
    statement, parameters = _statement_of_the_read(db, engine)
    with engine.connect() as conn:
        plan = [str(r[-1]) for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).fetchall()]
    joined = " | ".join(plan)
    assert "idx_keyword_frequency" in joined, joined
    assert "USE TEMP B-TREE FOR ORDER BY" not in joined, "a full sort of every keyword is the cost this removed: " + joined
    assert not any(p.startswith("SCAN keywords") and "USING" not in p for p in plan), joined


def test_the_old_expression_form_is_the_one_the_plan_check_would_catch(corpus):
    """Non-vacuity: the plan check above reddens on the form it replaced, so a return to the expression cannot pass quietly."""
    db, engine = corpus
    _seed(db, [(f"t{i}", i % 7) for i in range(50)])
    old = (
        "SELECT keywords.term FROM keywords WHERE keywords.term IS NOT NULL "
        "ORDER BY coalesce(keywords.frequency, 0) DESC, keywords.term LIMIT 11 OFFSET 0"
    )
    with engine.connect() as conn:
        plan = " | ".join(str(r[-1]) for r in conn.execute(text("EXPLAIN QUERY PLAN " + old)).fetchall())
    assert "USE TEMP B-TREE FOR ORDER BY" in plan and "idx_keyword_frequency" not in plan, plan


# ---- the mention set is reused for a time derived from what the read cost (Windows run 2026-11-07: 1,516 reads, mean 8.4 s) ----


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _cache_with_reads(monkeypatch, cost_s, clock):
    cache = hotset.MentionCache(monotonic=clock)
    reads = []

    def fake(corpus, *, limit=hotset.MENTION_LIMIT):
        reads.append(limit)
        clock.t += cost_s
        return {"alpha"}, False

    monkeypatch.setattr(hotset, "corpus_mention_titles", fake)
    monkeypatch.setattr(hotset, "_log_mention_plan", lambda *a, **k: None)
    return cache, reads


class _Corpus:
    def __init__(self, url="sqlite:///a.db"):
        self._url = url

    def get_bind(self):
        class B:
            pass

        b = B()
        b.url = self._url
        return b


def test_a_slow_read_is_reused_for_a_time_derived_from_its_cost(monkeypatch):
    clock = _Clock()
    cache, reads = _cache_with_reads(monkeypatch, 8.4, clock)
    corpus = _Corpus()
    cache.get(corpus)
    clock.t += 98  # the drain's cadence: well inside 8.4 / 0.01 = 840 s
    cache.get(corpus)
    assert reads == [hotset.MENTION_LIMIT], "the second drain did not read"
    clock.t += 840
    cache.get(corpus)
    assert len(reads) == 2, "past the derived window it reads again"


def test_a_fast_read_barely_caches(monkeypatch):
    clock = _Clock()
    cache, reads = _cache_with_reads(monkeypatch, 0.01, clock)
    corpus = _Corpus()
    cache.get(corpus)
    clock.t += 98
    cache.get(corpus)
    assert len(reads) == 2, "a 10 ms read is re-read at the next drain (window 1 s)"


def test_another_corpus_or_limit_is_never_answered_from_the_cache(monkeypatch):
    clock = _Clock()
    cache, reads = _cache_with_reads(monkeypatch, 8.4, clock)
    cache.get(_Corpus("sqlite:///a.db"))
    cache.get(_Corpus("sqlite:///b.db"))
    cache.get(_Corpus("sqlite:///b.db"), limit=10)
    assert len(reads) == 3


def test_a_failed_read_raises_and_keeps_nothing(monkeypatch):
    clock = _Clock()
    cache = hotset.MentionCache(monotonic=clock)

    def boom(corpus, *, limit=0):
        raise RuntimeError("locked")

    monkeypatch.setattr(hotset, "corpus_mention_titles", boom)
    with pytest.raises(RuntimeError):
        cache.get(_Corpus())
    assert cache._held is None


def test_a_slow_read_logs_the_query_plan_once(corpus, monkeypatch, caplog):
    import logging

    db, _engine = corpus

    clock = _Clock()
    cache = hotset.MentionCache(monotonic=clock)
    real = hotset.corpus_mention_titles

    def slow(corpus, *, limit=hotset.MENTION_LIMIT):
        clock.t += hotset.SLOW_MENTION_READ_S + 1
        return real(corpus, limit=limit)

    monkeypatch.setattr(hotset, "corpus_mention_titles", slow)
    with caplog.at_level(logging.WARNING, logger="wiki.hotset"):
        cache.get(db, limit=4)
        clock.t += 10_000
        cache.get(db, limit=4)
    plans = [r.getMessage() for r in caplog.records if "query plan" in r.getMessage()]
    assert len(plans) == 1, "the plan is logged once per process"
    assert "keywords" in plans[0].lower() or "idx_keyword_frequency" in plans[0]


def test_build_hot_sets_reads_the_mentions_through_the_cache_it_is_given(monkeypatch):
    clock = _Clock()
    cache, reads = _cache_with_reads(monkeypatch, 5.0, clock)
    monkeypatch.setattr(hotset, "followed_page_ids_by_edition", lambda _lane, editions: {e: (set(), set()) for e in editions})
    monkeypatch.setattr(hotset, "tracked_titles", lambda _corpus, _edition: set())
    for _ in range(3):
        sets, report = hotset.build_hot_sets(corpus=_Corpus(), lane=object(), editions=("en",), mention_cache=cache)
    assert len(reads) == 1, "three drains, one read"
    assert report["editions"]["en"] is not None and "en" in sets
    # without a cache every call reads (the unchanged default)
    reads.clear()
    for _ in range(2):
        hotset.build_hot_sets(corpus=_Corpus(), lane=object(), editions=("en",))
    assert len(reads) == 2
