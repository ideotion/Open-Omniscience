"""Content-provenance S2 — the raw source_type CHANNEL facet on the browse surface.

Slice the corpus by the asserted ingestion channel (news/newsletter/wiki/statistics/
law/market/discovery) — a descriptive fact known by construction, never a quality
score. Distinct from the curated 5-class `provenance` derivation. ``src.api.main``
needs the crypto extra, so the SQL runs in CI; the pure facet helper runs anywhere.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Source

_ROOT = Path(__file__).resolve().parents[1]

try:
    from src.api.main import _article_row, _query_articles

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001 - crypto extra/native ext absent in the bare sandbox
    _HAVE_MAIN = False


def _score_like_keys(obj) -> list[str]:
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank":
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


@pytest.fixture()
def db():
    # StaticPool shares ONE in-memory connection across threads, so the async
    # /api/articles endpoint (which runs off the event loop) sees the seeded tables.
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    srcs = {
        "news": Source(name="BBC", domain="bbc.com", source_type="news"),
        "nl": Source(name="NL", domain="newsletters.import.local", source_type="newsletter"),
        "stat": Source(name="WB", domain="data.worldbank.org", source_type="statistics"),
        "law": Source(name="Law", domain="law.test", source_type="legal"),
    }
    s.add_all(srcs.values())
    s.commit()
    rows = [
        ("oil news story", "news"),
        ("oil newsletter note", "nl"),
        ("oil statistics figure", "stat"),
        ("oil legal filing", "law"),
        ("weather news brief", "news"),  # no "oil"
    ]
    for i, (title, sk) in enumerate(rows):
        body = f"{title} -- corpus content about {'oil markets' if 'oil' in title else 'weather'}"
        s.add(Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}",
            source_id=srcs[sk].id, title=title, content=body,
            hash=f"h{i}".ljust(64, "0"), language="en",
        ))
    s.commit()
    return s


# ---------------------------- the facet helper (anywhere) ---------------------- #

def test_source_type_facets_counts_by_channel(db):
    from src.analytics.queries import source_type_facets

    r = source_type_facets(db)
    by = {f["source_type"]: f["articles"] for f in r["facets"]}
    assert by == {"news": 2, "newsletter": 1, "statistics": 1, "legal": 1}
    assert r["total"] == 5
    assert _score_like_keys(r) == []
    assert "never a quality" in r["caveat"]


# ---------------------------- the browse/FTS filter (CI) ----------------------- #

def _titles(db, **kw):
    rows, total = _query_articles(
        db, query=kw.pop("query", None), source=None, start_date=None, end_date=None,
        language=None, tags=None, limit=100, offset=0, **kw,
    )
    return [a.title for a in rows], total


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_source_type_filter_partitions_the_browse_corpus(db):
    nl, _ = _titles(db, source_type="newsletter")
    stat, _ = _titles(db, source_type="statistics")
    law, _ = _titles(db, source_type="legal")
    news, _ = _titles(db, source_type="news")
    assert nl == ["oil newsletter note"]
    assert stat == ["oil statistics figure"]
    assert law == ["oil legal filing"]
    assert sorted(news) == ["oil news story", "weather news brief"]
    # An unknown channel narrows to nothing (honest empty), never a 400 or a guess.
    unknown, total = _titles(db, source_type="does-not-exist")
    assert unknown == [] and total == 0


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_source_type_filter_applies_on_the_fts_path(db):
    from sqlalchemy import text

    from src.database.fts import ensure_fts

    ensure_fts(db.get_bind())
    db.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    db.commit()
    all_oil, total = _titles(db, query="oil")
    assert total == 4
    stat_oil, tw = _titles(db, query="oil", source_type="statistics")
    assert stat_oil == ["oil statistics figure"] and tw == 1


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_article_row_exposes_raw_source_type(db):
    a = db.query(Article).filter_by(title="oil newsletter note").one()
    row = _article_row(a)
    assert row["source_type"] == "newsletter"
    assert row["provenance"] == "newsletter"  # both present, distinct concepts


# ------------------------------- wiring --------------------------------------- #

def test_endpoints_and_row_are_wired():
    main = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert '"source_type": src.source_type if src else None' in main
    assert "source_type: str | None = None" in main
    ins = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert '@router.get("/source-types")' in ins
    assert "q.source_type_facets(" in ins


# ------------------------------- the endpoints (CI) --------------------------- #

@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_endpoints(db):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    def _db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/articles?source_type=newsletter")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["total"] == 1
            assert data["results"][0]["source_type"] == "newsletter"

            f = client.get("/api/insights/source-types")
            assert f.status_code == 200, f.text
            fd = f.json()
            by = {x["source_type"]: x["articles"] for x in fd["facets"]}
            assert by["news"] == 2 and by["statistics"] == 1
            assert _score_like_keys(fd) == []
    finally:
        app.dependency_overrides.clear()
