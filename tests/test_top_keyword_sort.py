"""Sorting and reporting an article's OWN top keyword (rulings 20-23, 38, 39).

Two different questions share a table column and must never be mixed:
``keyword_count`` orders by how often the keyword you SEARCHED appears, while
``top_keyword`` orders by how often the keyword THIS ARTICLE talks about most appears.
The second is precomputed at index time, so it is available for an article nobody
searched for -- and its three fields (term, count, tie width) only mean anything
together, which is what most of this file is about.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from src.api.main import _article_row, _query_articles, _top_keyword_terms

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001  # pragma: no cover - crypto extra absent in the bare sandbox
    _HAVE_MAIN = False

from src.database.models import Article, Base, Keyword, Source

pytestmark = pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="Paper", domain="p.test")
    s.add(src)
    s.commit()
    # Three keywords, deliberately not in count order, so an id-ordered answer and a
    # count-ordered answer differ.
    kws = [Keyword(term="flood", normalized_term="flood"),
           Keyword(term="drought", normalized_term="drought"),
           Keyword(term="levee", normalized_term="levee")]
    s.add_all(kws)
    s.commit()
    flood, drought, levee = (k.id for k in kws)

    def art(i, top_id, count, tied=1):
        return Article(
            title=f"a{i}", url=f"https://p.test/{i}", canonical_url=f"https://p.test/{i}",
            hash=f"h{i}", source_id=src.id,
            content="body", published_at=datetime(2026, 1, 1, tzinfo=UTC),
            top_keyword_id=top_id, top_keyword_count=count, top_keyword_tied_n=tied,
        )

    s.add_all([
        art(1, flood, 12),
        art(2, drought, 3),
        art(3, levee, 40, tied=2),      # a TIE: levee is one of two at 40
        art(4, None, None, None),       # never indexed -- no measurement at all
    ])
    s.commit()
    try:
        yield s, {"flood": flood, "drought": drought, "levee": levee}
    finally:
        s.close()


def _q(session, **kw):
    """The endpoint's own call shape (mirrors tests/test_search_sort.py's `_titles`)."""
    return _query_articles(
        session, query=kw.pop("query", None), source=None, start_date=None,
        end_date=None, language=None, tags=None, limit=100, offset=0, **kw,
    )


# --------------------------------------------------------------------------- #
#  the ordering
# --------------------------------------------------------------------------- #
def test_browse_orders_by_the_articles_own_top_keyword_count(db):
    s, _ = db
    rows, total = _q(s, sort_by="top_keyword", sort_dir="desc")
    assert total == 4
    assert [a.title for a in rows][:3] == ["a3", "a1", "a2"]


def test_ascending_is_the_other_direction_not_a_different_rule(db):
    s, _ = db
    rows, _ = _q(s, sort_by="top_keyword", sort_dir="asc")
    counts = [a.top_keyword_count for a in rows]
    assert [c for c in counts if c is not None] == [3, 12, 40]


def test_a_never_indexed_article_is_kept_not_dropped(db):
    """It is missing a MEASUREMENT, not missing keywords. A sort is an ordering of the
    corpus; silently shrinking it would make the list disagree with every count beside
    it."""
    s, _ = db
    rows, total = _q(s, sort_by="top_keyword", sort_dir="desc")
    assert total == 4
    assert "a4" in [a.title for a in rows]


def test_the_two_keyword_sorts_are_different_questions(db):
    """`keyword_count` needs a resolved SEARCHED keyword and answers nothing without one;
    `top_keyword` never needs one, because the answer was precomputed at index time.

    The discriminating case is a corpus with no resolved keyword: if the two sorts were
    the same mechanism wearing two names, both would come back in top-count order.
    """
    s, _ = db
    top = [a.title for a in _q(s, sort_by="top_keyword", sort_dir="desc")[0]]
    assert top[:3] == ["a3", "a1", "a2"]
    kc = [a.title for a in _q(s, sort_by="keyword_count", sort_dir="desc", keyword_id=None)[0]]
    assert kc != top, (
        "with no searched keyword resolved, keyword_count must fall through to the "
        "default order -- it cannot borrow the precomputed top-keyword answer"
    )
    assert sorted(kc) == sorted(top), "...while still returning the same corpus"


# --------------------------------------------------------------------------- #
#  the payload: three fields that only mean anything together
# --------------------------------------------------------------------------- #
def test_the_row_carries_the_term_the_count_and_the_tie_width(db):
    s, _ = db
    arts = s.query(Article).order_by(Article.title).all()
    tmap = _top_keyword_terms(s, arts)
    row = _article_row(arts[2], top_terms=tmap)   # a3, the tied one
    assert row["top_keyword"] == "levee"
    assert row["top_keyword_count"] == 40
    assert row["top_keyword_tied_n"] == 2, "a tie must be reported as a tie, not as a winner"


def test_a_pruned_keyword_reports_no_top_keyword_rather_than_a_bare_number(db):
    """The term is what makes the count checkable. If the keyword was pruned after this
    article was indexed the id no longer resolves, and a count with nothing to attach it
    to is a number a reader cannot verify -- so all three fields go null together."""
    s, ids = db
    s.query(Keyword).filter(Keyword.id == ids["levee"]).delete()
    s.commit()
    a3 = s.query(Article).filter_by(title="a3").one()
    tmap = _top_keyword_terms(s, [a3])
    row = _article_row(a3, top_terms=tmap)
    assert row["top_keyword"] is None
    assert row["top_keyword_count"] is None, "a count with no term is unverifiable"
    assert row["top_keyword_tied_n"] is None
    # ...and the stored column is untouched: this is a reporting rule, not a deletion.
    assert a3.top_keyword_count == 40


def test_a_never_indexed_article_reports_nulls_not_zero(db):
    """0 would read as "measured, and it mentions nothing" -- the opposite of the truth."""
    s, _ = db
    a4 = s.query(Article).filter_by(title="a4").one()
    row = _article_row(a4, top_terms=_top_keyword_terms(s, [a4]))
    assert row["top_keyword"] is None and row["top_keyword_count"] is None


def test_the_term_lookup_never_joins_articles_to_keywords(db):
    """The recorded SQLCipher codec trap: joining from a keyword table back to articles
    for one short string drags whole article rows (content is early in column order)
    through the codec. This resolves ids against `keywords` alone."""
    s, _ = db
    arts = s.query(Article).all()
    seen = []
    from sqlalchemy import event

    eng = s.get_bind()

    def rec(conn, cur, stmt, params, ctx, many):  # noqa: ANN001, PLR0913
        seen.append(stmt)

    event.listen(eng, "before_cursor_execute", rec)
    try:
        _top_keyword_terms(s, arts)
    finally:
        event.remove(eng, "before_cursor_execute", rec)
    joined = [q for q in seen if "articles" in q.lower()]
    assert not joined, f"the term lookup touched articles: {joined}"


def test_no_lookup_at_all_when_nothing_was_indexed(db):
    s, _ = db
    a4 = s.query(Article).filter_by(title="a4").one()
    assert _top_keyword_terms(s, [a4]) == {}
