"""A re-index writes only what changed (the re-index drain, 2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``index_article`` used to delete every mention row of an article and insert them all
again. It now reads the article's rows once, compares them with the rows the pass
produces and writes the difference. What must hold, and is pinned here:

* the END STATE is the one delete-then-insert produced (rows, counters, top keyword),
  for every shape of change;
* an unchanged row is not touched (same id, same ``created_at``); a changed row keeps its
  id and is stamped now; a gone row is deleted; a new row is inserted;
* "unchanged" compares EVERY stored column, so a column added to the model later is
  compared by default and this file fails until someone decides about it;
* the article's deletes, updates and inserts are one transaction: a rollback leaves the
  article exactly as it was;
* the drain says how much of its rewrite was real (rows kept, updated, removed, added).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.store as store
from src.analytics.extract import ExtractedTerm
from src.analytics.store import index_article, reindex_articles
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_MT = KeywordMention.__table__


class _Ex:
    """An extractor that returns whatever terms it was last told to."""

    name = "fake"

    def __init__(self, terms=()):
        self.terms = list(terms)

    def extract(self, text, language=None, **kw):
        return list(self.terms)


def _t(norm, count=1, offset=0, kind="term"):
    return ExtractedTerm(term=norm, normalized=norm, kind=kind, count=count, first_offset=offset)


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="s.test"))
    s.commit()
    return s


def _article(s, h, *, language="en", country=None):
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1,
                title="T", content="body", hash=h, language=language, country=country,
                created_at=datetime.now(UTC))
    s.add(a)
    s.commit()
    return a


def _rows(s, article_id=None):
    """{keyword_id: (id, count, first_offset, observed_on, country, city, language, source_id,
    extractor, created_at)} for one article (or {(article, keyword): ...} for all)."""
    q = select(_MT)
    if article_id is not None:
        q = q.where(_MT.c.article_id == article_id)
    out = {}
    for r in s.execute(q):
        key = r.keyword_id if article_id is not None else (r.article_id, r.keyword_id)
        out[key] = (r.id, r.count, r.first_offset, r.observed_on, r.country, r.city, r.language,
                    r.source_id, r.extractor, r.created_at)
    return out


def _payload(rows):
    """The same rows without their id and created_at: what a delete-then-insert also produces."""
    return {k: v[1:9] for k, v in rows.items()}


def _counters(s):
    return {k.normalized_term: (k.mention_count, k.article_count) for k in s.query(Keyword)}


def _live_counters(s):
    return {
        k.normalized_term: (
            int(s.execute(select(func.coalesce(func.sum(_MT.c.count), 0)).where(_MT.c.keyword_id == k.id)).scalar()),
            int(s.execute(select(func.count()).select_from(_MT).where(_MT.c.keyword_id == k.id)).scalar()),
        )
        for k in s.query(Keyword)
    }


def _legacy_write(session, article_id, old_rows, new_rows, *, now):
    """The write every pass made before: drop all of the article's rows, insert all."""
    removed = session.execute(_MT.delete().where(_MT.c.article_id == article_id)).rowcount
    if new_rows:
        session.execute(_MT.insert(), new_rows)
    return {"kept": 0, "updated": 0, "removed": int(removed or 0), "added": len(new_rows)}


# --------------------------------------------------------------------------- the compared set


def test_the_compared_columns_are_every_stored_column_but_identity_and_write_time():
    """Adding a column to KeywordMention changes this set; the failure is the prompt to
    decide that the new column is compared (the default) and that the pass writes it."""
    assert store._MENTION_PAYLOAD == (
        "count", "first_offset", "observed_on", "country", "city", "language", "source_id", "extractor",
    )
    assert set(store._MENTION_PAYLOAD) | set(store._MENTION_IDENTITY) == {c.name for c in _MT.columns}


def test_every_row_a_pass_produces_carries_every_compared_column(monkeypatch):
    """A column the pass did not write would compare as 'unchanged' forever against the stored
    default; so the rows handed to the diff must carry the whole set."""
    s = _session()
    a = _article(s, "a")
    seen: list[list[dict]] = []
    real = store._write_mention_diff

    def spy(session, article_id, old_rows, new_rows, **kw):
        seen.append(new_rows)
        return real(session, article_id, old_rows, new_rows, **kw)

    monkeypatch.setattr(store, "_write_mention_diff", spy)
    index_article(s, a, extractor=_Ex([_t("x", 2), _t("y")]), country=None, city=None)
    assert seen and all(set(store._MENTION_PAYLOAD) <= set(row) for row in seen[0])


# --------------------------------------------------------------------------- the end state


_SCENARIOS = {
    "same": ([_t("a", 2), _t("b", 1, 5)], [_t("a", 2), _t("b", 1, 5)]),
    "counts changed": ([_t("a", 2), _t("b")], [_t("a", 4), _t("b", 3)]),
    "offset changed": ([_t("a", 2, 1)], [_t("a", 2, 9)]),
    "terms removed": ([_t("a"), _t("b"), _t("c")], [_t("b")]),
    "terms added": ([_t("a")], [_t("a"), _t("b"), _t("c", 7)]),
    "all vanish": ([_t("a"), _t("b")], []),
    "disjoint": ([_t("a"), _t("b")], [_t("c"), _t("d")]),
    "a mix": ([_t("a", 2), _t("b"), _t("c", 4)], [_t("a", 2), _t("c", 5), _t("d")]),
    "entity kind": ([_t("a")], [_t("a", 1, 0, "person")]),
}


@pytest.mark.parametrize("defer", [False, True], ids=["counters-inline", "counters-deferred"])
@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_the_end_state_is_what_delete_then_insert_produced(name, defer, monkeypatch):
    first, second = _SCENARIOS[name]
    ends = []
    for legacy in (False, True):
        s = _session()
        arts = [_article(s, f"a{i}") for i in range(3)]
        ex = _Ex(first)
        for a in arts:
            index_article(s, a, extractor=ex, country="fr", city="Paris")
        s.commit()
        if legacy:
            monkeypatch.setattr(store, "_write_mention_diff", _legacy_write)
        # the second pass: a different engine's output, a different country, one article's language
        arts[1].language = "de"
        s.commit()
        ex.terms = list(second)
        for a in arts:
            index_article(s, a, extractor=ex, country="de", city=None, maintain_counters=not defer)
        s.commit()
        ends.append((_payload(_rows(s)), _live_counters(s),
                     {a.id: (a.top_keyword_id, a.top_keyword_count, a.top_keyword_tied_n) for a in arts}))
        monkeypatch.undo()
    assert ends[0] == ends[1], f"scenario {name!r}: the diff write ended elsewhere than delete-then-insert"


def test_the_stored_counters_equal_the_live_group_by_after_an_inline_diff_reindex():
    s = _session()
    arts = [_article(s, f"a{i}") for i in range(4)]
    ex = _Ex([_t("a", 2), _t("b"), _t("c", 3)])
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    ex.terms = [_t("a", 5), _t("c", 3), _t("d")]
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    live = _live_counters(s)
    stored = _counters(s)
    assert {k: v for k, v in stored.items() if v != (0, 0)} == {k: v for k, v in live.items() if v != (0, 0)}


# --------------------------------------------------------------------------- what is touched


def test_unchanged_rows_keep_id_and_created_at_changed_rows_keep_id_and_are_stamped_gone_rows_go():
    s = _session()
    a = _article(s, "a")
    ex = _Ex([_t("keep", 2, 3), _t("change", 1), _t("gone", 4)])
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    kw = {k.normalized_term: k.id for k in s.query(Keyword)}
    before = _rows(s, a.id)
    # make the stored write time visibly old so "stamped now" is unambiguous
    old = datetime(2020, 1, 1)
    s.execute(_MT.update().values(created_at=old))
    s.commit()
    ex.terms = [_t("keep", 2, 3), _t("change", 9), _t("new", 1)]
    tally = index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    after = _rows(s, a.id)

    assert tally["mentions_kept"] == 1 and tally["mentions_updated"] == 1
    assert tally["mentions_removed"] == 1 and tally["mentions_added"] == 1
    assert tally["mentions"] == 3, "mentions keeps meaning: the rows the article now has"
    assert after[kw["keep"]][0] == before[kw["keep"]][0] and after[kw["keep"]][9] == old
    assert after[kw["change"]][0] == before[kw["change"]][0], "a changed row keeps its id"
    assert after[kw["change"]][1] == 9 and after[kw["change"]][9] > old, "... and is stamped now"
    assert kw["gone"] not in after
    new_id = after[next(k.id for k in s.query(Keyword) if k.normalized_term == "new")][0]
    assert new_id not in {after[kw["keep"]][0], after[kw["change"]][0]}, (
        "a new row takes a free id (SQLite may hand back the one a deleted max row freed, as it always did)"
    )


@pytest.mark.parametrize("column,change", [
    ("country", {"country": "de"}),
    ("language", {"language": "de"}),
])
def test_a_change_in_any_denormalised_column_alone_is_a_change(column, change):
    """Same keywords, same counts: only an article-level fact the mention copies has moved."""
    s = _session()
    a = _article(s, "a", language="en", country="fr")
    ex = _Ex([_t("a", 2), _t("b")])
    index_article(s, a, extractor=ex, country="fr", city=None)
    s.commit()
    before = _rows(s, a.id)
    for k, v in change.items():
        setattr(a, k, v)
    s.commit()
    tally = index_article(s, a, extractor=ex, country=a.country, city=None)
    s.commit()
    after = _rows(s, a.id)
    assert tally["mentions_kept"] == 0 and tally["mentions_updated"] == 2, column
    assert {k: v[0] for k, v in after.items()} == {k: v[0] for k, v in before.items()}, "same ids"
    assert all(v[4 if column == "country" else 6] == change[column] for v in after.values())


def test_the_extractor_name_and_source_id_and_city_and_observed_date_are_compared_too():
    s = _session()
    a = _article(s, "a")
    a.published_at = datetime(2024, 3, 1, tzinfo=UTC)
    s.commit()
    ex = _Ex([_t("a")])
    index_article(s, a, extractor=ex, country=None, city="Lyon")
    s.commit()

    def again(**kw):
        return index_article(s, a, extractor=kw.pop("ex", ex), country=None, city=kw.pop("city", "Lyon"))["mentions_updated"]

    assert again() == 0  # nothing moved: nothing written
    assert again(city="Nice") == 1
    other = _Ex([_t("a")])
    other.name = "newer"
    assert again(ex=other, city="Nice") == 1
    a.published_at = datetime(2024, 3, 2, tzinfo=UTC)
    s.commit()
    assert again(ex=other, city="Nice") == 1
    a.source_id = 2
    s.add(Source(id=2, name="S2", domain="s2.test"))
    s.commit()
    assert again(ex=other, city="Nice") == 1


def test_a_brand_new_article_takes_the_plain_insert():
    s = _session()
    a = _article(s, "a")
    tally = index_article(s, a, extractor=_Ex([_t("a"), _t("b", 3)]), country=None, city=None)
    s.commit()
    assert (tally["mentions_kept"], tally["mentions_updated"], tally["mentions_removed"], tally["mentions_added"]) == (0, 0, 0, 2)


def test_without_a_known_old_set_the_whole_set_is_replaced():
    """Two rows for one keyword cannot be diffed (the unique index forbids it; if a file held
    that, the old delete-then-insert shape is the safe one)."""
    s = _session()
    a = _article(s, "a")
    index_article(s, a, extractor=_Ex([_t("a"), _t("b")]), country=None, city=None)
    s.commit()
    rows = [dict(keyword_id=r.keyword_id, article_id=a.id, count=7, first_offset=0, observed_on=None,
                 country=None, city=None, language=None, source_id=1, extractor="fake",
                 created_at=datetime.now(UTC)) for r in s.execute(select(_MT))]
    out = store._write_mention_diff(s, a.id, None, rows, now=datetime.now(UTC))
    s.commit()
    assert out == {"kept": 0, "updated": 0, "removed": 2, "added": 2}
    assert {v[1] for v in _rows(s, a.id).values()} == {7}


# --------------------------------------------------------------------------- one transaction


def test_a_rolled_back_pass_leaves_the_article_exactly_as_it_was():
    """The article's deletes, updates and inserts ride the caller's transaction: nothing of a
    pass is visible until its commit, and a rollback restores every id and created_at."""
    s = _session()
    a = _article(s, "a")
    ex = _Ex([_t("keep"), _t("change", 1), _t("gone", 2)])
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    before = _rows(s, a.id)
    ex.terms = [_t("keep"), _t("change", 5), _t("new")]
    index_article(s, a, extractor=ex, country=None, city=None, commit=False)
    assert _rows(s, a.id) != before  # visible inside the transaction
    s.rollback()
    assert _rows(s, a.id) == before


def test_a_failure_part_way_through_a_batch_leaves_every_article_whole(monkeypatch):
    """A batch commits several articles together. One that fails after its mention rows were
    staged rolls the batch back and is redone one at a time; the end state is the clean one."""
    s = _session()
    arts = [_article(s, f"a{i}") for i in range(4)]
    ex = _Ex([_t("a", 2), _t("b"), _t("c", 3)])
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    ex.terms = [_t("a", 5), _t("c", 3), _t("d")]
    real = store._stamp_index_engine
    state = {"n": 0}

    def flaky(session, article, *a, **kw):
        state["n"] += 1
        if state["n"] == 3:  # the third article of the first pass, after its rows were staged
            raise RuntimeError("boom after the mention rows were written")
        return real(session, article, *a, **kw)

    monkeypatch.setattr(store, "_stamp_index_engine", flaky)
    stats: dict = {}
    out = reindex_articles(s, extractor=ex, article_ids=[a.id for a in arts], commit_batch=4, stats=stats,
                           workers=0)
    monkeypatch.undo()
    assert out["failed"] == 1 and out["reindexed"] == 3
    # every article is wholly the old rows or wholly the new rows, never a mix
    old_set = {"a": 2, "b": 1, "c": 3}
    new_set = {"a": 5, "c": 3, "d": 1}
    kw = {k.id: k.normalized_term for k in s.query(Keyword)}
    states = []
    for a in arts:
        got = {kw[k]: v[1] for k, v in _rows(s, a.id).items()}
        assert got in (old_set, new_set), got
        states.append(got == new_set)
    assert states.count(False) == 1 and states.count(True) == 3


# --------------------------------------------------------------------------- what the drain says


def test_the_drain_reports_rows_kept_updated_removed_added_and_where_the_time_went():
    s = _session()
    arts = [_article(s, f"a{i}") for i in range(3)]
    ex = _Ex([_t("a", 2), _t("b"), _t("c", 3)])
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    ex.terms = [_t("a", 2), _t("c", 9), _t("d")]  # per article: a kept, c updated, b removed, d added
    stats: dict = {}
    reindex_articles(s, extractor=ex, article_ids=[a.id for a in arts], commit_batch=2, stats=stats,
                     workers=0)
    assert (stats["mentions_kept"], stats["mentions_updated"], stats["mentions_removed"], stats["mentions_added"]) == (3, 3, 3, 3)
    assert stats["mentions_written"] == stats["mentions_kept"] + stats["mentions_updated"] + stats["mentions_added"]
    assert set(stats["apply_split"]) >= {"mentions_read_s", "mentions_write_s", "www_s"}
    assert all(v >= 0 for v in stats["apply_split"].values())


def test_a_rolled_back_batch_is_not_counted_twice():
    s = _session()
    arts = [_article(s, f"a{i}") for i in range(3)]
    ex = _Ex([_t("a"), _t("b")])
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    ex.terms = [_t("a"), _t("c")]
    real = s.commit
    fired = {"n": 0}

    def commit_once_fails():
        fired["n"] += 1
        if fired["n"] == 1:
            raise RuntimeError("the first batch commit fails")
        return real()

    s.commit = commit_once_fails  # type: ignore[method-assign]
    stats: dict = {}
    reindex_articles(s, extractor=ex, article_ids=[a.id for a in arts], commit_batch=3, stats=stats, workers=0)
    s.commit = real  # type: ignore[method-assign]
    assert (stats["mentions_kept"], stats["mentions_removed"], stats["mentions_added"]) == (3, 3, 3)


def test_the_run_metrics_carry_the_new_numbers():
    from src.api import backup_v2 as bv2

    run: dict = {}
    for _ in range(2):
        bv2._accumulate(
            run,
            {"articles": 2, "mentions_written": 10, "mentions_kept": 6, "mentions_updated": 1,
             "mentions_removed": 2, "mentions_added": 3, "wall_s": 1.0,
             "apply_split": {"mentions_write_s": 0.25, "www_s": 0.5}},
            commit_batch=200, idle=True,
        )
    out = bv2._drain_metrics(run)
    assert out is not None
    assert (out["mentions_kept"], out["mentions_updated"], out["mentions_removed"], out["mentions_added"]) == (12, 2, 4, 6)
    assert out["apply_split"] == {"mentions_write_s": 0.5, "www_s": 1.0}


def test_a_run_that_walked_a_batch_always_ends_with_its_epoch_bump():
    """A RESUMED drain whose articles were all finished by the run that was killed before it
    could bump: nothing re-indexed this time, and the end bump must still land (the start bump
    already did; rows changed in place after a mid-run rollup are invalidated only by it)."""
    from src.api import backup_v2 as bv2

    src = open(bv2.__file__, encoding="utf-8").read()
    assert "if batches:\n            _bump(\"reindex-resume:end\")" in src


def test_the_diff_write_uses_no_row_scan_beyond_the_articles_own_index():
    """The old-row read is one indexed lookup on article_id, never a scan."""
    from sqlalchemy import text

    s = _session()
    q = "EXPLAIN QUERY PLAN SELECT id, keyword_id, count, first_offset, observed_on, country, city, language, source_id, extractor FROM keyword_mentions WHERE article_id = 1"
    plan = " ".join(str(r[3]) for r in s.execute(text(q)))
    assert "SCAN keyword_mentions" not in plan and "ix_mention_article" in plan, plan
