"""The article-list browse reads no article row it does not show, and its plan is pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Diagnostics round of 2026-09-30, rank 9: on 8 of 16 instances one statement of 24 to 424 s was 91 to
99.6 % of the slowest ``GET /api/articles`` call, and the call began 8 to 28 s after the unlock.
The statement was ``SELECT articles.id, articles.url, articles.canonical_url, ...``: every column,
``content`` included.

WHAT WAS MEASURED (a 40,000-article, 2 GB synthetic store from ``src/testing/corpus_gen.py``, ~50 KB
an article, plaintext, caches dropped between a shape's first run and the rest; cold / warm ms):

    shape                                   before          after (id-first + index-only gate)
    first page, 100 rows                    107 / 3         3 / 2
    a page 20,000 rows deep                 715 / 40        15 / 4
    a source filter, 1,000 rows             100 / 6         5 / 3
    sort by title                           881 / 42        897 / 42   (3 / 3 with idx_article_title_nocase)
    language filter                         1,284 / 56      1,349 / 60 (3 / 3 with idx_article_language_published)

Two causes, both in the shape of the statement and not in a cache:

  1. ``quarantined IS NOT 1`` cannot use an index, so the planner read each candidate ROW to test it,
     and ``quarantined`` sits AFTER ``content`` in the record: reading it walks the whole overflow chain
     of the body. Every row a scan stepped over paid that, including every row an OFFSET skipped. The
     exclusion is now ``id NOT IN (SELECT id FROM articles WHERE quarantined IS 1)``, answered by the
     covering ``idx_article_quarantined`` and tested by id, so the default browse's plan went from
     ``SCAN ... USING INDEX idx_article_published_at`` to ``SCAN ... USING COVERING INDEX
     idx_article_published_at``: no article row is read for any row the scan passes over.
  2. The query selected whole rows, so any ordering an index does not give (a language filter, a title
     sort) put every matching row's BODY in the sorter. A paged browse now asks for ids and loads the
     page's rows by id (the text path's shape since S2.5), so the sorter carries an id.

A title sort and a language filter read one row per candidate until an index covers them
(``published_at`` and ``language`` also sit after ``content``). The two indexes are
``src/database/article_indexes.py``'s (``idx_article_language_published`` and ``idx_article_title_nocase``,
built once at start-up as a task-manager job, R128): with them the id-first page statement is answered
from the index alone (the plan tests below pin both), and without them the shape is no worse than it
was. The 3 ms figures are from that module's own measurement; this file pins the plans, not the times.

What the tests pin, each with its negative space: the answer is the OLD answer for every order, filter,
direction, page and the include-quarantined view (the reference below is the old statement, verbatim in
shape); a pre-migration NULL flag is kept; the plan has no table scan and no sort for the default browse and
the deepest page and for a language filter and a title sort (with their indexes); the statements that
select ``content`` carry an id list no longer than the page; a stand-in row is left out of every view,
including the one that includes quarantined rows; the export (``limit=None``) is untouched.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source

main = pytest.importorskip("src.api.main")  # CI/venv with crypto; skips on a bare sandbox

N = 360
SORTS = [None, "date", "title", "source", "language", "words", "sentiment", "top_keyword"]


@pytest.fixture
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'browse.db'}", future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add_all(
        [
            Source(name="Alpha", domain="a.test", tags="news,world", source_type="news"),
            Source(name="beta", domain="b.test", tags="news", source_type="news"),
            Source(name="Gamma", domain="g.test", tags="law", source_type="law"),
        ]
    )
    s.flush()
    base = datetime(2025, 1, 1, tzinfo=UTC)
    for i in range(N):
        s.add(
            Article(
                url=f"u{i}",
                canonical_url=f"u{i}",
                source_id=1 + i % 3,
                title=("Zeta " if i % 5 == 0 else "apple " if i % 5 == 1 else "Mango ") + str(i),
                content="body " * 50,
                hash=f"h{i:05d}",
                language=("en", "fr", "de")[i % 3] if i % 7 else None,
                published_at=None if i % 11 == 0 else base + timedelta(hours=i // 2),  # ties + NULLs
                created_at=base,
                word_count=None if i % 13 == 0 else (i * 7) % 50,
                sentiment_score=None if i % 9 == 0 else ((i % 21) - 10) / 10.0,
                top_keyword_count=(i * 3) % 17,
                quarantined=i % 10 == 3,
            )
        )
    s.commit()
    # Every state the column can hold: judged-true, judged-false, and never judged (NULL, the
    # pre-migration state). Written in SQL because the ORM applies the column's default to an
    # explicit None.
    s.execute(text("UPDATE articles SET quarantined = NULL WHERE id % 4 = 0 AND quarantined = 0"))
    s.commit()
    yield s
    s.close()
    eng.dispose()


def _reference(session, *, language=None, source=None, start_date=None, end_date=None, tags=None,
               source_type=None, sort_by=None, sort_dir=None, limit=None, offset=0,
               include_quarantined=False):
    """The browse as it was: ONE statement over whole ``Article`` rows with the
    ``quarantined IS NOT 1`` condition, ordered and cut in the database."""
    from sqlalchemy import and_

    filters = main._structured_filters(
        session, source=source, start_date=start_date, end_date=end_date, language=language,
        tags=tags, provenance=None, source_type=source_type,
    )
    q = session.query(Article)
    if not include_quarantined:
        q = q.filter(Article.quarantined.isnot(True))
    if filters:
        q = q.filter(and_(*filters))
    total = q.count()
    if sort_by == "source":
        q = q.outerjoin(Source, Article.source_id == Source.id)
        col = Source.name.collate("NOCASE")
    elif sort_by == "title":
        col = Article.title.collate("NOCASE")
    elif sort_by == "language":
        col = Article.language
    elif sort_by == "top_keyword":
        col = Article.top_keyword_count
    elif sort_by == "words":
        col = Article.word_count
    elif sort_by == "sentiment":
        col = Article.sentiment_score
    else:
        col = Article.published_at
    descending = (sort_dir or "desc").lower() != "asc"
    q = q.order_by(col.desc() if descending else col.asc(), Article.id.desc())
    if limit is not None:
        q = q.offset(offset).limit(limit)
    return [a.id for a in q.all()], total


def _new(session, **kw):
    from src.api.search_filters import AdvancedSearch

    include_quarantined = kw.pop("include_quarantined", False)
    rows, total = main._query_articles(
        session,
        query=None,
        source=kw.pop("source", None),
        start_date=kw.pop("start_date", None),
        end_date=kw.pop("end_date", None),
        language=kw.pop("language", None),
        tags=kw.pop("tags", None),
        limit=kw.pop("limit", None),
        offset=kw.pop("offset", 0),
        adv=AdvancedSearch(include_quarantined=include_quarantined),
        **kw,
    )
    return [a.id for a in rows], total


# --------------------------------------------------------------------------- #
#  The answer is the old answer
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sort_by", SORTS)
@pytest.mark.parametrize("sort_dir", ["desc", "asc"])
def test_every_ordering_returns_the_old_page_and_the_old_total(db, sort_by, sort_dir):
    """MUTATION TARGET. Same ids, same order (ties broken by id, NULLs where SQLite puts them), same
    total, for every sort and both directions, on a corpus with true, false and NULL flags."""
    for limit, offset in ((25, 0), (25, 50), (40, 330), (1000, 0)):
        want = _reference(db, sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset)
        got = _new(db, sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset)
        assert got == want, (sort_by, sort_dir, limit, offset)


@pytest.mark.parametrize(
    "kw",
    [
        {"language": "en"},
        {"language": "fr", "sort_by": "title"},
        {"source": "Alpha"},
        {"source": "beta", "sort_by": "words", "sort_dir": "asc"},
        {"tags": "news"},
        {"tags": "law,world"},
        {"source_type": "news"},
        {"source_type": "law", "sort_by": "source"},
        {"start_date": "2025-01-02", "end_date": "2025-01-05"},
        {"start_date": "2025-01-03", "language": "de", "sort_by": "sentiment"},
        {"source_type": "does-not-exist"},
    ],
)
def test_every_filter_returns_the_old_page_and_the_old_total(db, kw):
    for limit, offset in ((20, 0), (20, 20), (500, 0)):
        want = _reference(db, limit=limit, offset=offset, **kw)
        got = _new(db, limit=limit, offset=offset, **kw)
        assert got == want, (kw, limit, offset)


def test_the_quarantine_exclusion_keeps_a_never_judged_row_and_drops_a_judged_one(db):
    """``quarantined IS NOT 1`` kept NULL and 0 and dropped 1; so does the id-list form."""
    ids, total = _new(db, limit=1000)
    flags = {a.id: a.quarantined for a in db.query(Article).all()}
    assert {None, False} <= {flags[i] for i in ids} and True not in {flags[i] for i in ids}
    assert total == len(ids) == sum(1 for f in flags.values() if f is not True)
    assert any(f is None for f in flags.values()), "the fixture holds no never-judged row"


def test_the_include_quarantined_view_shows_every_row_and_nothing_is_dropped_by_the_gate(db):
    want = _reference(db, limit=1000, include_quarantined=True)
    got = _new(db, limit=1000, include_quarantined=True)
    assert got == want and got[1] == N


def test_the_include_quarantined_view_leaves_a_stand_in_out(db):
    """A stand-in row (a place-holder a repair wrote for a lost article, never data) is quarantined, so the default
    view leaves it out through the id list; the view that INCLUDES quarantined rows must still leave it out. The page
    statement used to drop the whole gate there, which showed the place-holder as an article."""
    from src.database.stand_in import ARTICLE_REASON, lost_text

    stand_in = Article(
        url=lost_text("articles", 9001), canonical_url=lost_text("articles", 9001), source_id=1,
        title=lost_text("articles", 9001), content="", hash="(lost articles 9001)",
        created_at=datetime(2025, 1, 1, tzinfo=UTC), quarantined=True, quarantine_reason=ARTICLE_REASON,
    )
    db.add(stand_in)
    db.commit()
    for include in (False, True):
        ids, total = _new(db, limit=1000, include_quarantined=include)
        assert stand_in.id not in ids, include
        assert total == (N if include else sum(1 for a in db.query(Article).all() if a.quarantined is not True)), include


def test_the_export_path_is_the_old_single_statement(db):
    """``limit=None`` is every match with its body, for the export: unchanged, and still in order."""
    for sort_by in (None, "title"):
        assert _new(db, sort_by=sort_by) == _reference(db, sort_by=sort_by)


# --------------------------------------------------------------------------- #
#  The plan, and what is selected
# --------------------------------------------------------------------------- #
@pytest.fixture
def statements(db):
    """Every statement the browse runs, as ``(sql, params)``, captured at the cursor."""
    seen: list[tuple[str, tuple]] = []
    eng = db.get_bind()

    @event.listens_for(eng, "before_cursor_execute")
    def _grab(_conn, _cur, statement, parameters, _ctx, _many):
        seen.append((statement, tuple(parameters)))

    yield seen
    event.remove(eng, "before_cursor_execute", _grab)


def _selects_body(sql: str) -> bool:
    """A statement that returns article bodies. The corpus total wraps the column list in a
    ``SELECT count(*)`` and never reads one (SQLite drops the unused columns), so it is not one."""
    return "articles.content" in sql and "count(" not in sql.lower()


def _plan(db, sql, params):
    with db.get_bind().connect() as conn:
        rows = conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [r[3] for r in rows]


def _page_statement(statements):
    """The statement that orders and cuts the page: the one with ``LIMIT``."""
    [(sql, params)] = [s for s in statements if " LIMIT " in s[0] and "count(" not in s[0].lower()]
    return sql, params


@pytest.mark.parametrize("offset", [0, 300])
def test_the_default_browse_plan_reads_no_article_row_and_sorts_nothing(db, statements, offset):
    """MUTATION TARGET. The first page and the deepest page: an index-only scan in the order asked
    for, with the quarantine list built once. A table scan, a plain (non-covering) index scan or a
    sorter here is the regression: each reads the body of every row the scan passes over."""
    _new(db, limit=25, offset=offset)
    sql, params = _page_statement(statements)
    plan = _plan(db, sql, params)
    assert any("USING COVERING INDEX idx_article_published_at" in p for p in plan), plan
    assert not any(p.startswith("SCAN articles") and "COVERING INDEX" not in p for p in plan), plan
    assert not any("TEMP B-TREE" in p for p in plan), plan
    assert any("idx_article_quarantined" in p or "idx_article_feed_scan" in p for p in plan), plan


@pytest.mark.parametrize(
    ("kw", "index"),
    [
        ({"language": "en"}, "idx_article_language_published"),
        ({"language": "fr", "sort_by": "date", "sort_dir": "asc"}, "idx_article_language_published"),
        ({"sort_by": "title"}, "idx_article_title_nocase"),
        ({"sort_by": "title", "sort_dir": "asc"}, "idx_article_title_nocase"),
    ],
)
def test_a_language_filter_and_a_title_sort_are_answered_from_their_index(db, statements, kw, index):
    """MUTATION TARGET. With the two indexes of ``article_indexes.py`` the id-first page statement walks an
    index that holds everything it needs (no article row, no sorter); a page statement that selects the row
    again, or an ordering the index does not give, shows up here as a plain scan or a temporary b-tree."""
    _new(db, limit=25, offset=50, **kw)
    sql, params = _page_statement(statements)
    plan = _plan(db, sql, params)
    assert any(f"COVERING INDEX {index}" in p for p in plan), plan
    # An ascending order with the id still descending sorts the TIES of the first key only ("RIGHT PART OF ORDER BY",
    # ids in the sorter); a full "USE TEMP B-TREE FOR ORDER BY" is a sort of every candidate.
    assert not any(p.startswith("USE TEMP B-TREE") and "RIGHT PART" not in p for p in plan), plan
    if kw.get("sort_dir", "desc") == "desc":
        assert not any("TEMP B-TREE" in p for p in plan), plan


def test_the_page_statement_selects_no_body_and_the_bodies_come_with_the_page_ids_only(
    db, statements
):
    """MUTATION TARGET. ``content`` is selected only by a statement that names ids, and no more of
    them than the page holds: no sorter, scan or skipped row ever carries a body."""
    _new(db, limit=25, offset=50, language="en", sort_by="title")
    sql, _params = _page_statement(statements)
    assert "articles.content" not in sql and "articles.compressed_content" not in sql
    with_body = [(s, p) for s, p in statements if _selects_body(s)]
    assert with_body, "the page's rows were never loaded"
    for s, p in with_body:
        assert re.search(r"articles\.id IN \(", s), s
        assert 0 < len(p) <= 25, "a statement that selects bodies named more ids than the page"


def test_a_page_deeper_than_the_corpus_loads_nothing(db, statements):
    ids, total = _new(db, limit=25, offset=10_000)
    assert ids == [] and total > 0
    assert not [s for s, _ in statements if _selects_body(s)], "no ids, no row load"


def test_a_thousand_row_page_loads_in_chunks_under_the_variable_ceiling(db, statements):
    """The loader is chunked: a caller that asks for a thousand rows or more never builds one
    statement with a thousand bound variables."""
    from src.api import main as m

    ids = [a.id for a in db.query(Article.id)]
    rows = m._load_articles_in_order(db, ids * 3)  # 3 x N ids, with repeats
    assert [a.id for a in rows] == ids * 3
    sizes = [len(p) for s, p in statements if _selects_body(s)]
    assert sorted(sizes) == [len(ids) * 3 - m._FTS_ID_CHUNK, m._FTS_ID_CHUNK], "one statement per chunk"
