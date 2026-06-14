"""
Tests for analytics queries + the Insights API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Builds a small indexed corpus, then pins trend buckets, top/associations (PMI
sign), context snippets, map aggregation, and the API status/reindex flow.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _mk(db, h, text, when, country="fr"):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=1,
        title="T",
        content=text,
        hash=h,
        country=country,
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country=country, city="Paris")
    return a


def test_trend_and_top(db):
    _mk(
        db,
        "a1",
        "Inflation rose. Inflation worries grew as inflation spread across markets here.",
        "2024-01-03",
    )
    _mk(
        db,
        "a2",
        "Inflation again dominated headlines while inflation pressures intensified sharply.",
        "2024-01-10",
    )
    tr = q.trend(db, "inflation", bucket="week")
    assert tr["resolved"]["normalized"] == "inflation"
    assert tr["total"] >= 4 and len(tr["points"]) >= 1
    top = q.top_terms(db, limit=10)
    assert any(t["normalized"] == "inflation" for t in top["terms"])


def test_associations_pmi_positive_for_cooccurring(db):
    # "sanctions" and "nickel" always co-occur -> positive PMI.
    for i, when in enumerate(["2024-02-01", "2024-02-02", "2024-02-03"]):
        _mk(
            db,
            f"c{i}",
            "New sanctions hit supply. Sanctions affected nickel and nickel exports broadly.",
            when,
        )
    _mk(
        db,
        "d0",
        "Unrelated weather report about rainfall and rainfall patterns over the coast today.",
        "2024-02-04",
    )
    assoc = q.associations(db, "sanctions", min_cooccur=2)
    pairs = {p["normalized"]: p for p in assoc["pairs"]}
    assert "nickel" in pairs and pairs["nickel"]["pmi"] > 0
    assert assoc["method"].startswith("pointwise mutual information")


def test_context_snippet_contains_term(db):
    _mk(
        db,
        "x1",
        "The committee discussed wildfire response and wildfire funding for the affected region.",
        "2024-03-01",
    )
    ctx = q.context(db, "wildfire", limit=5)
    assert ctx["count"] >= 1
    assert "wildfire" in ctx["mentions"][0]["snippet"].lower()
    assert ctx["mentions"][0]["country"] == "fr" and ctx["mentions"][0]["city"] == "Paris"


def test_map_data_groups_by_area(db):
    _mk(
        db,
        "m1",
        "Election campaigns and election rallies filled the capital this election season now.",
        "2024-03-05",
        country="fr",
    )
    _mk(
        db,
        "m2",
        "Drought worsened. Drought and drought relief efforts dominated the regional agenda.",
        "2024-03-06",
        country="ke",
    )
    data = q.map_data(db, days=3650)
    codes = {c["code"] for c in data["countries"]}
    assert {"fr", "ke"} <= codes
    assert any(c["name"] == "Paris" for c in data["cities"])


def test_insights_api_status_and_reindex(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ins.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        s.add(
            Article(
                url="https://x.test/p",
                canonical_url="https://x.test/p",
                source_id=1,
                title="T",
                content="Diplomacy and diplomacy talks shaped the summit agenda this week here.",
                hash="hh",
                country="fr",
                language="en",
                published_at=datetime(2024, 4, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            st = client.get("/api/insights/status").json()
            assert st["total_articles"] == 1 and st["remaining"] == 1
            re = client.post("/api/insights/reindex?limit=50").json()
            assert re["indexed"] == 1 and re["remaining"] == 0
            top = client.get("/api/insights/top?limit=5").json()
            assert any(t["normalized"] == "diplomacy" for t in top["terms"])
    finally:
        app.dependency_overrides.clear()


def test_corpus_keywords_scopes_to_article_set(db):
    """corpus_keywords aggregates over a GIVEN article set, not the whole corpus."""
    a1 = _mk(db, "ck1", "tariff tariff steel industry policy", "2026-01-01")
    a2 = _mk(db, "ck2", "tariff steel industry", "2026-01-02")
    _mk(db, "ck3", "weather sunshine beaches holiday", "2026-01-03")  # excluded set
    res = q.corpus_keywords(db, article_ids=[a1.id, a2.id], limit=20)
    assert res["n_articles"] == 2
    assert res["count"] > 0
    norms = {t["normalized"] for t in res["terms"]}
    # terms come only from the two selected articles, never the third
    assert "weather" not in norms and "sunshine" not in norms and "beaches" not in norms
    # the shared subject surfaces
    assert any(("tariff" in n) or ("steel" in n) or ("industry" in n) for n in norms), norms
    # empty set is handled
    assert q.corpus_keywords(db, article_ids=[], limit=10)["count"] == 0
