"""
Tests for the city gazetteer + Insights map coordinate enrichment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.cities import build_index, load_cities, lookup, parse_cities_sparql
from src.database.models import Article, Base, Source


def test_sample_gazetteer_loads_and_looks_up():
    cities = load_cities()
    assert len(cities) >= 15
    idx = build_index(cities)
    paris = lookup(idx, "Paris", "fr")
    assert paris and abs(paris.lat - 48.86) < 0.1 and abs(paris.lon - 2.35) < 0.1
    # Name-only fallback still resolves.
    assert lookup(idx, "Tokyo") is not None
    assert lookup(idx, "Nowhereville") is None


def test_parse_cities_sparql():
    payload = {
        "results": {
            "bindings": [
                {
                    "cityLabel": {"value": "Lyon"},
                    "coord": {"value": "Point(4.8357 45.7640)"},
                    "cc": {"value": "FR"},
                    "population": {"value": "513000"},
                },
                {"cityLabel": {"value": "NoCoord"}},  # dropped
            ]
        }
    }
    cities = parse_cities_sparql(payload)
    assert len(cities) == 1
    assert cities[0].name == "Lyon" and cities[0].country == "fr"
    assert abs(cities[0].lat - 45.76) < 0.01 and abs(cities[0].lon - 4.84) < 0.01


def test_map_endpoint_attaches_coordinates(tmp_path):
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'map.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        a = Article(
            url="https://x.test/p",
            canonical_url="https://x.test/p",
            source_id=1,
            title="T",
            content="Election rallies and election debates filled the capital this week here.",
            hash="h1",
            country="fr",
            language="en",
            published_at=datetime(2024, 5, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr", city="Paris")

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            data = client.get("/api/insights/map?days=3650").json()
            paris = next((c for c in data["cities"] if c["name"] == "Paris"), None)
            assert paris is not None
            assert "lat" in paris and "lon" in paris  # coordinates attached
            assert data["cities_placed"] >= 1
    finally:
        app.dependency_overrides.clear()
