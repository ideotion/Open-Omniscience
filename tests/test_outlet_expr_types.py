"""``outlet_expr`` counts the same outlets as before without building a string per row (row J, R146 cost note).

The expression used to be ``coalesce(domain, 'source-' || cast(source_id as text))``. It is now ``coalesce(domain, source_id)``:
an INTEGER where the source row is gone, the text domain where it is there. SQLite's ``DISTINCT`` keeps storage classes apart, so
nothing may merge that was apart before. What these pin: every count equals the old spelling's on a store holding each awkward
case (an orphan id equal to a domain written in digits, several orphans, sibling feeds of one outlet, a one-feed outlet), and the
cheaper shape stays (no cast, no concatenation), because the string work was half of the measured cost of the outlet join.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String, cast, create_engine, func, literal
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.database.outlet import outlet_expr


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


def _distinct_outlets(s, expr):
    return (s.query(func.count(func.distinct(expr(Article.source_id, Source.domain))))
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
    new, old = _distinct_outlets(s, outlet_expr), _distinct_outlets(s, _old_spelling)
    assert new == old == 6        # "123" (domain), bbc.com, dw.com, orphan 123, orphan 777, orphan 778


def test_the_expression_builds_no_string(s):
    """Red without the change: the old spelling compiled to a cast and a concatenation for every row."""
    sql = str(outlet_expr(Article.source_id, Source.domain).compile(compile_kwargs={"literal_binds": True})).upper()
    assert "CAST" not in sql and "||" not in sql, sql
    assert sql.startswith("COALESCE(")


def test_a_mention_view_style_scan_agrees_with_the_old_spelling(s):
    """The same equality on the shape the four gates use: GROUP BY with the distinct count inside HAVING."""
    a = Source(name="A", domain="a.example", rss_url="https://a.example/f")
    b = Source(name="B1", domain="b.example", rss_url="https://b.example/1")
    c = Source(name="B2", domain="b.example", rss_url="https://b.example/2")
    s.add_all([a, b, c])
    s.commit()
    _articles(s, [a.id, b.id, c.id, 9001, 9002, a.id])

    def grouped(expr):
        n = func.count(func.distinct(expr(Article.source_id, Source.domain)))
        return s.query(Article.language, n).outerjoin(Source, Source.id == Article.source_id).group_by(Article.language).having(n >= 2).all()

    assert grouped(outlet_expr) == grouped(_old_spelling) == [("en", 4)]
