"""``outlet_expr`` counts the same outlets as before and builds no string and reads no text per row (row J, R146 cost note, R177).

The expression was ``coalesce(domain, 'source-' || cast(source_id as text))``, then ``coalesce(domain, source_id)``; it is now
``coalesce(sources.outlet_id, source_id)``, an INTEGER on both sides: the lowest id of the domain's sources, or the bare source id
where the source row is gone. An outlet id is the id of a row that exists, so it never equals an orphan's own id. What these pin:
every count equals the old (text) spelling's on a store holding each awkward case (an orphan id equal to a domain written in
digits, several orphans, sibling feeds of one outlet, a one-feed outlet), and the cheaper shape stays (no cast, no
concatenation, no domain column), because the string work was the measured cost of the outlet join.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String, cast, create_engine, func, literal
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.database.outlet import outlet_expr, outlets_unhealed


@pytest.fixture()
def s(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _old_spelling(source_id_col, domain_col):
    return func.coalesce(domain_col, literal("source-").op("||")(cast(source_id_col, String)))


def _articles(s, per_source):
    """One article for every (source_id, n) pair: ``per_source`` is a list of source ids, repeats allowed."""
    for i, sid in enumerate(per_source):
        s.add(Article(url=f"https://x.example/{i}", canonical_url=f"https://x.example/{i}", source_id=sid, title="t", content="c",
                      hash=f"h{i}", language="en"))
    s.commit()


def _distinct_outlets(s, expr, col):
    return (s.query(func.count(func.distinct(expr(Article.source_id, col))))
            .select_from(Article).outerjoin(Source, Source.id == Article.source_id).scalar())


def test_an_orphan_id_and_a_domain_in_digits_stay_two_outlets_and_every_count_is_unchanged(s):
    digits = Source(name="Digits", domain="123", rss_url="https://123/feed")
    bbc_en = Source(name="BBC News", domain="bbc.com", rss_url="https://bbc.com/en")
    bbc_ar = Source(name="BBC Arabic", domain="bbc.com", rss_url="https://bbc.com/ar")
    dw = Source(name="DW", domain="dw.com", rss_url="https://dw.com/rss")
    s.add_all([digits, bbc_en, bbc_ar, dw])
    s.commit()
    # articles of: the digits-domain source, both BBC feeds, DW, an orphan whose id is 123 (the digits domain's spelling), two more
    # orphans, one of them twice
    _articles(s, [digits.id, bbc_en.id, bbc_ar.id, dw.id, 123, 777, 778, 778])
    new, old = _distinct_outlets(s, outlet_expr, Source.outlet_id), _distinct_outlets(s, _old_spelling, Source.domain)
    assert new == old == 6        # "123" (domain), bbc.com, dw.com, orphan 123, orphan 777, orphan 778


def test_the_expression_builds_no_string(s):
    """Red without the change: the old spelling compiled to a cast and a concatenation for every row."""
    sql = str(outlet_expr(Article.source_id, Source.outlet_id).compile(compile_kwargs={"literal_binds": True})).upper()
    assert "CAST" not in sql and "||" not in sql and "DOMAIN" not in sql, sql
    assert sql.startswith("COALESCE(")


def test_a_mention_view_style_scan_agrees_with_the_old_spelling(s):
    """The same equality on the shape the four gates use: GROUP BY with the distinct count inside HAVING."""
    a = Source(name="A", domain="a.example", rss_url="https://a.example/f")
    b = Source(name="B1", domain="b.example", rss_url="https://b.example/1")
    c = Source(name="B2", domain="b.example", rss_url="https://b.example/2")
    s.add_all([a, b, c])
    s.commit()
    _articles(s, [a.id, b.id, c.id, 9001, 9002, a.id])

    def grouped(expr, col):
        n = func.count(func.distinct(expr(Article.source_id, col)))
        return s.query(Article.language, n).outerjoin(Source, Source.id == Article.source_id).group_by(Article.language).having(n >= 2).all()

    assert grouped(outlet_expr, Source.outlet_id) == grouped(_old_spelling, Source.domain) == [("en", 4)]


def _store_with_sibling_feeds(s):
    a = Source(name="A", domain="a.example", rss_url="https://a.example/f")
    b1 = Source(name="B1", domain="b.example", rss_url="https://b.example/1")
    b2 = Source(name="B2", domain="b.example", rss_url="https://b.example/2")
    c = Source(name="C", domain="c.example", rss_url="https://c.example/f")
    s.add_all([a, b1, b2, c])
    s.commit()
    _articles(s, [a.id, b1.id, b2.id, c.id, 9001])  # four live feeds of three outlets, and an orphan
    return a, b1, b2, c


def test_the_default_shape_is_one_coalesce_of_the_two_columns(s):
    """The healed store reads the cheap form: no subquery, nothing correlated (the +29 % form is the opt-in below)."""
    sql = str(outlet_expr(Article.source_id, Source.outlet_id).compile(compile_kwargs={"literal_binds": True})).upper()
    assert sql == "COALESCE(SOURCES.OUTLET_ID, ARTICLES.SOURCE_ID)", sql


def test_the_unhealed_shape_has_one_correlated_subquery_and_no_string_work(s):
    sql = str(outlet_expr(Article.source_id, Source.outlet_id, unhealed=True).compile(compile_kwargs={"literal_binds": True})).upper()
    assert sql.count("SELECT") == 1 and "MIN(" in sql and "CAST" not in sql and "||" not in sql, sql


def test_a_row_the_boot_step_has_not_reached_is_counted_exactly_only_when_the_gate_asks(s):
    """R146: the plain form reads a NULL row as its own outlet, which OVERCOUNTS (the unsafe direction); ``unhealed=True`` does
    not, and ``outlets_unhealed`` is what tells a gate which form it needs."""
    _store_with_sibling_feeds(s)
    assert outlets_unhealed(s) is False
    healed = _distinct_outlets(s, outlet_expr, Source.outlet_id)
    assert healed == 4  # a, b, c and the orphan
    s.execute(Source.__table__.update().values(outlet_id=None))  # an UPDATE of outlet_id alone fires no trigger
    s.commit()
    assert outlets_unhealed(s) is True
    plain = _distinct_outlets(s, outlet_expr, Source.outlet_id)
    exact = (s.query(func.count(func.distinct(outlet_expr(Article.source_id, Source.outlet_id, unhealed=True))))
             .select_from(Article).outerjoin(Source, Source.id == Article.source_id).scalar())
    assert plain == 5, "b's two feeds count twice while the column is NULL: the stated overcount"
    assert exact == healed == 4


def test_a_mixed_store_counts_exactly_with_the_unhealed_form(s):
    """Some rows healed, some NULL (a heal that stopped half way): the exact form agrees with the healed count."""
    a, b1, b2, c = _store_with_sibling_feeds(s)
    s.execute(Source.__table__.update().where(Source.id.in_([b1.id, b2.id, c.id])).values(outlet_id=None))
    s.commit()
    exact = (s.query(func.count(func.distinct(outlet_expr(Article.source_id, Source.outlet_id, unhealed=True))))
             .select_from(Article).outerjoin(Source, Source.id == Article.source_id).scalar())
    assert exact == 4
