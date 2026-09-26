"""Whole-table reads the UI can start hold one chunk of rows, not the table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Five reads a click can start used to hold an entire table in Python at once, about four
objects per row: the Groups view and the Observatory's member resolution (every keyword,
when a group has a hand-added member), a source's discovery trail and the cited-sources
preview (every external link), and the most-cited-domains panel (every link). On a
3.9 GB machine, 13.5 million objects in 25 seconds was the end of a session (crash
bundle, 2026-09-26). They now read through ``keyset_scan``.

THE PROPERTY IS MEASURED, not inferred from the code: each read's peak Python memory is
taken with ``tracemalloc`` at N rows and again at 4N. A read that holds the table grows
about fourfold; a chunked read stays flat. Every table here is built so that the answer
itself stays the same size as the table grows (nothing matches, or everything cites one
domain from one article), so the only thing that can grow is what the read holds.
"""

from __future__ import annotations

import gc
import tracemalloc

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import query as query_mod
from src.database.models import ArticleLink, Base, Keyword
from src.database.query import keyset_scan

_CHUNK = 500
_SMALL = 4_000
_LARGE = 4 * _SMALL


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'k.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _grow_keywords(s, upto: int) -> None:
    """Keywords ``term 1`` .. ``term upto`` (idempotent across calls: only adds)."""
    s.execute(sa.text(
        "WITH RECURSIVE c(i) AS (SELECT (SELECT coalesce(max(id), 0) + 1 FROM keywords) "
        "UNION ALL SELECT i + 1 FROM c WHERE i < :upto) "
        "INSERT INTO keywords (id, term, normalized_term, language) "
        "SELECT i, 'term ' || i, 'term ' || i, 'en' FROM c"
    ), {"upto": upto})
    s.commit()


def _one_article(s) -> int:
    s.execute(sa.text("INSERT INTO sources (id, name, domain) VALUES (1, 'S', 's.test')"))
    s.execute(sa.text(
        "INSERT INTO articles (id, url, canonical_url, source_id, content, hash) "
        "VALUES (1, 'https://s.test/a', 'https://s.test/a', 1, 'x', 'h1')"
    ))
    s.commit()
    return 1


def _grow_links(s, upto: int) -> None:
    """External links from article 1, every one to ``cited.example.com`` (a distinct
    path each), so the per-domain answer is ONE domain with ONE citing article at any
    table size."""
    s.execute(sa.text(
        "WITH RECURSIVE c(i) AS (SELECT (SELECT coalesce(max(id), 0) + 1 FROM article_links) "
        "UNION ALL SELECT i + 1 FROM c WHERE i < :upto) "
        "INSERT INTO article_links (id, article_id, url, normalized_url, link_type) "
        "SELECT i, 1, 'https://cited.example.com/p/' || i, "
        "'https://cited.example.com/p/' || i, 'external' FROM c"
    ), {"upto": upto})
    s.commit()


def _peak_bytes(fn) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _growth(s, grow, read) -> float:
    """Peak memory of ``read`` at 4N rows over its peak at N rows (after a warm-up, so
    statement compilation and imports are not counted as growth)."""
    grow(s, _SMALL)
    read()
    small = _peak_bytes(read)
    grow(s, _LARGE)
    large = _peak_bytes(read)
    return large / small


# --------------------------- keyset_scan itself --------------------------- #


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 9, 10])
def test_every_row_once_in_id_order_across_chunk_edges(db, n):
    """Including an empty table, a table smaller than a chunk, and a table that is an
    exact multiple of the chunk size (where an off-by-one repeats or drops a row)."""
    if n:
        _grow_keywords(db, n)
    ids = [r[0] for r in keyset_scan(db.query(Keyword.id, Keyword.term), Keyword.id, chunk=3)]
    assert ids == list(range(1, n + 1))


def test_a_filter_is_kept_on_every_chunk(db):
    _grow_keywords(db, 20)
    q = db.query(Keyword.id).filter(Keyword.id % 2 == 0)
    assert [r[0] for r in keyset_scan(q, Keyword.id, chunk=3)] == list(range(2, 21, 2))


def test_each_chunk_is_its_own_bounded_statement(db):
    """What releases SQLite's read mark between chunks: each chunk is a separate
    statement with a LIMIT, run to completion, never one cursor held open."""
    _grow_keywords(db, 10)
    seen: list[str] = []

    @sa.event.listens_for(db.get_bind(), "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _params, _context, _many):
        if "FROM keywords" in statement:
            seen.append(statement)

    list(keyset_scan(db.query(Keyword.id), Keyword.id, chunk=4))
    assert len(seen) == 3, seen  # 4 + 4 + 2 rows; a short chunk ends the scan
    assert all("LIMIT" in s and "ORDER BY keywords.id" in s for s in seen)


# ---------------- the five reads: memory flat as the table grows ---------------- #


@pytest.fixture()
def small_chunks(monkeypatch):
    monkeypatch.setattr(query_mod, "KEYSET_CHUNK", _CHUNK)


def test_the_groups_view_does_not_hold_every_keyword(db, small_chunks):
    from src.api.insights import _supergroup_totals

    # A hand-added FAMILY member is what makes the Groups view scan every keyword.
    def read():
        _supergroup_totals(db, {("no such family", None)})

    assert _growth(db, _grow_keywords, read) < 2.0


def test_the_observatory_member_resolution_does_not_hold_every_keyword(db, small_chunks):
    from src.analytics.supergroup_stats import resolve_member_keyword_ids

    def read():
        resolve_member_keyword_ids(db, [("no such family", None)])

    assert _growth(db, _grow_keywords, read) < 2.0


def test_a_sources_discovery_trail_does_not_hold_every_link(db, small_chunks):
    from src.discovery.source_trail import _first_citing_article

    _one_article(db)

    def read():
        assert _first_citing_article(db, "nobody-cites-this.example.org") is None

    assert _growth(db, _grow_links, read) < 2.0


def test_the_cited_sources_preview_does_not_hold_every_link(db, small_chunks):
    from src.discovery.cited_sources import cited_domain_stats

    _one_article(db)

    def read():
        stats = cited_domain_stats(db)
        assert list(stats) == ["cited.example.com"]

    assert _growth(db, _grow_links, read) < 2.0


def test_the_most_cited_domains_panel_does_not_hold_every_link(db, small_chunks):
    from src.api import heavy
    from src.api.link_analysis import top_cited

    _one_article(db)
    heavy._reset_for_tests()

    def read():
        out = top_cited(by="domain", window_days=None, min_citations=1, limit=50, db=db)
        assert [i["domain"] for i in out["items"]] == ["cited.example.com"]
        assert out["items"][0]["citations"] == 1

    try:
        assert _growth(db, _grow_links, read) < 2.0
    finally:
        heavy._reset_for_tests()


def test_most_cited_counts_distinct_articles_without_the_sql_distinct(db):
    """The whole-table read used SELECT DISTINCT; the chunked one does not, because the
    per-domain SETS already count an article once. Pin that a repeated (url, article)
    pair and two URLs of one domain from one article still count ONE citation."""
    from src.api import heavy
    from src.api.link_analysis import top_cited

    _one_article(db)
    db.execute(sa.text(
        "INSERT INTO articles (id, url, canonical_url, source_id, content, hash) "
        "VALUES (2, 'https://s.test/b', 'https://s.test/b', 1, 'x', 'h2')"
    ))
    for aid, url in [
        (1, "https://a.example.net/x"), (1, "https://a.example.net/x"),  # repeated pair
        (1, "https://a.example.net/y"),  # same domain, second URL, same article
        (2, "https://a.example.net/x"),
        (2, "https://b.example.net/z"),
    ]:
        db.add(ArticleLink(article_id=aid, url=url, normalized_url=url, link_type="external"))
    db.commit()
    heavy._reset_for_tests()
    try:
        out = top_cited(by="domain", window_days=None, min_citations=1, limit=50, db=db)
    finally:
        heavy._reset_for_tests()
    assert [(i["domain"], i["citations"]) for i in out["items"]] == [
        ("a.example.net", 2), ("b.example.net", 1),
    ]


def test_most_cited_ties_are_broken_by_name(db):
    """A tie at the ``limit`` cut is decided by name, never by the order rows happen to
    be read in: here the later-named domain is the one read first."""
    from src.api import heavy
    from src.api.link_analysis import top_cited

    _one_article(db)
    for url in ("https://z.example.net/1", "https://a.example.net/1"):
        db.add(ArticleLink(article_id=1, url=url, normalized_url=url, link_type="external"))
    db.commit()
    heavy._reset_for_tests()
    try:
        out = top_cited(by="domain", window_days=None, min_citations=1, limit=1, db=db)
    finally:
        heavy._reset_for_tests()
    assert [i["domain"] for i in out["items"]] == ["a.example.net"]
