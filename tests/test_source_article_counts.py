"""Per-source article counts read from indexes alone (field test 2026-11-14, row 59).

``/api/insights/source-types`` and the content-type and tag options of ``/api/insights/latest`` used to
count with a join the planner served by reading every article row, text included; on the field stores
both answered 503 at the 60 s deadline after an unlock. These tests pin the three things the change
must keep: the SAME numbers as the old joins (edge cases included), plans that never touch an article
row, and a fallback that only a missing index takes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

sa = pytest.importorskip("sqlalchemy")

from sqlalchemy import func, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.analytics import source_article_counts as sac  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402

NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=30)


@pytest.fixture()
def s():
    eng = sa.create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng, future=True)()
    sess.add_all(
        [
            Source(id=1, name="a", domain="a.test", source_type="news", tags="news,europe"),
            Source(id=2, name="b", domain="b.test", source_type=None, tags=None),
            Source(id=3, name="c", domain="c.test", source_type="", tags=""),  # '' stays '' under COALESCE
            Source(id=4, name="d", domain="d.test", source_type="News", tags="europe"),  # case differs from 1
            Source(id=5, name="e", domain="e.test", source_type="wiki", tags="a,a"),  # a repeated tag
            Source(id=6, name="f", domain="f.test", source_type="law", tags="x"),  # no article at all
        ]
    )
    sess.flush()
    # the model's defaults fill a None in; a source restored or merged from elsewhere can still carry NULLs
    sess.execute(text("UPDATE sources SET source_type = NULL, tags = NULL WHERE id = 2"))
    n = 0
    # (source_id, quarantined, age): source 99 has no source row (the inner join drops it).
    for sid in (1, 2, 3, 4, 5, 99):
        for q in (None, False, True):
            for age in (timedelta(minutes=5), timedelta(days=29, hours=23), timedelta(days=30, hours=1), timedelta(days=200)):
                n += 1
                sess.add(
                    Article(
                        id=n, url=f"https://x/{n}", canonical_url=f"https://x/{n}", source_id=sid, title=f"t{n}",
                        content="body " * 50, hash=f"h{n}", created_at=NOW - age, quarantined=q,
                    )
                )
    sess.commit()
    return sess


def _old_source_type_facets(sess) -> dict[str, int]:
    """The join ``queries.source_type_facets`` ran before, verbatim, as the reference."""
    out: dict[str, int] = {}
    for st, c in (
        sess.query(Source.source_type, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.quarantined.isnot(True))
        .group_by(Source.source_type)
    ):
        key = (st or "").strip().lower() or "untyped"
        out[key] = out.get(key, 0) + int(c)
    return out


def _old_facet_options(sess, since):
    """The two joins ``latest._facet_options`` ran before, verbatim, as the reference."""
    from src.analytics.latest import _split_tags

    types: dict[str, int] = {}
    for st, c in (
        sess.query(func.coalesce(Source.source_type, "news"), func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= since)
        .group_by(func.coalesce(Source.source_type, "news"))
    ):
        types[st] = int(c)
    tags: dict[str, int] = {}
    for tg, c in (
        sess.query(Source.tags, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= since, Source.tags.isnot(None))
        .group_by(Source.tags)
    ):
        for t in _split_tags(tg):
            tags[t] = tags.get(t, 0) + int(c)
    return types, tags


def test_source_type_facets_match_the_old_join(s):
    from src.analytics.queries import SOURCE_TYPE_UNTYPED, source_type_facets

    got = {f["source_type"]: f["articles"] for f in source_type_facets(s)["facets"]}
    want = {(SOURCE_TYPE_UNTYPED if k == "untyped" else k): v for k, v in _old_source_type_facets(s).items()}
    assert got == want
    assert got["news"] == 16  # sources 1 and 4 fold together after lowercasing, quarantined left out


def test_latest_facet_options_match_the_old_joins(s):
    from src.analytics.latest import _facet_options

    types, tags_out = _facet_options(s, SINCE)
    old_types, old_tags = _old_facet_options(s, SINCE)
    assert types == old_types
    assert {t["tag"]: t["articles"] for t in tags_out} == old_tags
    assert "" in types and "news" in types and "News" in types  # COALESCE kept '' and the case, as the GROUP BY did
    assert sum(types.values()) == 5 * 3 * 2  # 5 sources with a row x 3 quarantine states x 2 ages inside 30 days


def test_the_window_boundary_compares_like_the_orm_filter(s):
    # one article exactly at the boundary, one a microsecond before it
    s.add_all(
        [
            Article(id=10_001, url="u1", canonical_url="u1", source_id=1, content="x", hash="b1", created_at=SINCE),
            Article(id=10_002, url="u2", canonical_url="u2", source_id=1, content="x", hash="b2",
                    created_at=SINCE - timedelta(microseconds=1)),
        ]
    )
    s.commit()
    orm = dict(s.query(Article.source_id, func.count(Article.id)).filter(Article.created_at >= SINCE).group_by(Article.source_id).all())
    assert sac.counts_by_source_since(s, SINCE) == orm


def _plan(sess, sql: str, **params) -> list[str]:
    return [str(r[-1]) for r in sess.execute(text("EXPLAIN QUERY PLAN " + sql), params).all()]


@pytest.mark.parametrize("sql", [sac._ALL_TIME_UNQUARANTINED, sac._SINCE])
def test_the_plans_never_read_an_article_row(s, sql):
    steps = [p for p in _plan(s, sql, since="2026-01-01") if "articles" in p]
    assert steps, "the plan names the articles table"
    for step in steps:
        # every step on the table is an index-only one; a row read shows as a bare SCAN/SEARCH articles,
        # a non-covering index, or a primary-key lookup
        assert "COVERING INDEX" in step, step


def test_the_old_plans_did_read_rows(s):
    # the negative twin: the statements the fallback runs are the slow plans this change avoids,
    # so the INDEXED BY is what makes the difference (on a store without statistics, as the field's are)
    for stmt in (sac._fallback_unquarantined(), sac._fallback_since(SINCE)):
        sql = str(stmt.compile(s.get_bind(), compile_kwargs={"literal_binds": True}))
        steps = [p for p in _plan(s, sql) if "articles" in p]
        assert any("COVERING INDEX" not in p for p in steps), steps


def test_the_functions_run_the_forced_plans_on_a_store_that_has_the_indexes(s):
    # what the functions EXECUTE, not only the constants: a broken index check would fall back to the slow
    # plan silently, with every count still right (the independent read's finding)
    assert sac._have(s, "idx_article_feed_scan") is True
    assert sac._have(s, "idx_article_source_id", "idx_article_created_at") is True
    assert sac._have(s, "idx_article_feed_scan", "no_such_index_here") is False
    seen: list[str] = []

    def _spy(conn, cursor, statement, *args):
        seen.append(statement)

    sa.event.listen(s.get_bind(), "before_cursor_execute", _spy)
    try:
        sac.unquarantined_counts_by_source(s)
        sac.counts_by_source_since(s, SINCE)
    finally:
        sa.event.remove(s.get_bind(), "before_cursor_execute", _spy)
    counted = [q for q in seen if "count(*)" in q and "sqlite_master" not in q]
    assert len(counted) == 2 and all("INDEXED BY" in q for q in counted), counted


@pytest.mark.parametrize("index", ["idx_article_feed_scan", "idx_article_source_id", "idx_article_created_at"])
def test_a_missing_index_falls_back_to_the_same_counts(s, index):
    before = (sac.unquarantined_counts_by_source(s), sac.counts_by_source_since(s, SINCE))
    s.execute(text(f"DROP INDEX {index}"))
    after = (sac.unquarantined_counts_by_source(s), sac.counts_by_source_since(s, SINCE))
    assert after == before


def test_an_error_of_the_statement_is_raised_and_not_retried(s, monkeypatch):
    real = s.execute
    calls: list[str] = []

    def boom(stmt, *a, **k):
        if "sqlite_master" in str(stmt):
            return real(stmt, *a, **k)
        calls.append(str(stmt))
        raise OperationalError(str(stmt), {}, Exception("interrupted"))

    monkeypatch.setattr(s, "execute", boom)
    with pytest.raises(OperationalError):
        sac.unquarantined_counts_by_source(s)
    with pytest.raises(OperationalError):
        sac.counts_by_source_since(s, SINCE)
    assert len(calls) == 2  # one attempt each: a deadlined scan is never run a second time with the slow plan
