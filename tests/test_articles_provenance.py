"""Articles subtab: content-provenance filter + per-article keyword count.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A descriptive ingestion-channel filter (wikipedia/web/newsletter/statistics) plus the
searched keyword's per-article mention count -- counts only, never a quality score, and
never the keyword_mentions->articles decrypt join. ``src.api.main`` needs the crypto
extra, so these run in CI (the pure derivation is in tests/test_provenance_class.py and
the SQL is exercised by a standalone repro).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from src.api.main import (  # noqa: E402
        _article_row,
        _keyword_counts,
        _query_articles,
        _resolve_count_keyword,
    )

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001  # pragma: no cover - crypto extra/native ext absent in the bare sandbox
    _HAVE_MAIN = False

from src.analytics.queries import _normalize  # noqa: E402
from src.database.models import Article, Base, Keyword, KeywordMention, Source  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)"
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    srcs = {
        "wiki": Source(name="Wikipedia (en)", domain="en.wikipedia.org"),
        "news": Source(name="Newsletters", domain="newsletters.import.local"),
        "stat": Source(name="World Bank", domain="data.worldbank.org", source_type="statistics"),
        "web": Source(name="BBC", domain="bbc.com", source_type="news"),
    }
    s.add_all(srcs.values())
    s.commit()
    # (title, source-key, "oil" frequency or None)
    rows = [
        ("wiki oil report", "wiki", 9),
        ("newsletter oil note", "news", 2),
        ("stat oil figure", "stat", 5),
        ("bbc oil story", "web", 3),
        ("bbc weather", "web", None),  # web article that never mentions oil
    ]
    arts = {}
    for i, (title, sk, _c) in enumerate(rows):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}",
            source_id=srcs[sk].id, title=title,
            content=f"{title} -- shared oil corpus content", hash=f"h{i}".ljust(64, "0"),
            language="en",
        )
        s.add(a)
        s.flush()
        arts[title] = a
    kw = Keyword(term="oil", normalized_term=_normalize("oil"), language="en")
    s.add(kw)
    s.flush()
    for (title, _sk, c) in rows:
        if c is not None:
            s.add(KeywordMention(keyword_id=kw.id, article_id=arts[title].id, count=c))
    s.commit()
    s._kw_id = kw.id  # type: ignore[attr-defined]
    return s


def _titles(db, **kw):
    rows, total = _query_articles(
        db, query=kw.pop("query", None), source=None, start_date=None, end_date=None,
        language=None, tags=None, limit=100, offset=0, **kw,
    )
    return [a.title for a in rows], total


def test_resolve_count_keyword_exact_only(db):
    kid, term = _resolve_count_keyword(db, "oil")
    assert kid == db._kw_id and term == "oil"
    # A term that is not a stored keyword -> nothing (never a loose match).
    assert _resolve_count_keyword(db, "petroleum-derivatives-xyz") == (None, None)
    assert _resolve_count_keyword(db, None) == (None, None)


def test_keyword_counts_are_real_per_article_frequencies(db):
    ids = [a.id for a in db.query(Article)]
    cmap = _keyword_counts(db, db._kw_id, ids)
    by_title = {a.title: cmap.get(a.id) for a in db.query(Article)}
    assert by_title["wiki oil report"] == 9
    assert by_title["stat oil figure"] == 5
    assert by_title["bbc weather"] is None  # never mentioned -> absent, not zero
    # No keyword id -> empty map (no fabricated counts).
    assert _keyword_counts(db, None, ids) == {}


def test_provenance_filter_partitions_the_browse_corpus(db):
    wiki, _ = _titles(db, provenance="wikipedia")
    news, _ = _titles(db, provenance="newsletter")
    stat, _ = _titles(db, provenance="statistics")
    web, _ = _titles(db, provenance="web")
    assert wiki == ["wiki oil report"]
    assert news == ["newsletter oil note"]
    assert stat == ["stat oil figure"]
    assert sorted(web) == ["bbc oil story", "bbc weather"]
    # The four buckets recover exactly the whole corpus.
    assert sorted(wiki + news + stat + web) == sorted(a.title for a in db.query(Article))


def test_provenance_filter_applies_on_the_fts_path(db):
    from sqlalchemy import text

    from src.database.fts import ensure_fts

    ensure_fts(db.get_bind())
    db.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    db.commit()
    # "oil" matches 4 articles; the wikipedia filter narrows to one.
    all_oil, total = _titles(db, query="oil")
    assert total == 4
    wiki_oil, total_w = _titles(db, query="oil", provenance="wikipedia")
    assert wiki_oil == ["wiki oil report"] and total_w == 1


def test_keyword_count_sort_orders_by_frequency(db):
    from sqlalchemy import text

    from src.database.fts import ensure_fts

    ensure_fts(db.get_bind())
    db.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    db.commit()
    titles, _ = _titles(
        db, query="oil", keyword_id=db._kw_id, sort_by="keyword_count", sort_dir="desc"
    )
    # 9 > 5 > 3 > 2 (the no-mention article is not an FTS hit for "oil").
    assert titles == ["wiki oil report", "stat oil figure", "bbc oil story", "newsletter oil note"]


def test_article_row_carries_provenance_and_count(db):
    a = db.query(Article).filter(Article.title == "wiki oil report").one()
    row = _article_row(a, keyword_count=9)
    assert row["provenance"] == "wikipedia"
    assert row["keyword_count"] == 9
    web = db.query(Article).filter(Article.title == "bbc weather").one()
    assert _article_row(web)["provenance"] == "web"
    assert _article_row(web)["keyword_count"] is None
