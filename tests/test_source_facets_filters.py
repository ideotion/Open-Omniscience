"""Sources multi-select facets + filtering (field test 2026-06-22, #23).

A facets endpoint feeds the dropdowns with the REAL distinct catalog values + counts;
list_sources filters in SQL BEFORE pagination with explicit OR-within / AND-across
semantics + a tag any|all toggle. Counts only, no score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.database.models import Base, Source
from src.database.session import get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    rows = [
        ("BBC", "bbc.com", "en", "GB", "news", "news,world", True),
        ("Le Monde", "lemonde.fr", "fr", "FR", "news", "news,politics", True),
        ("Guardian", "theguardian.com", "en", "GB", "news", "news,science", True),
        ("Reuters Fin", "reuters.com", "en", "GB", "agency", "finance,markets", True),
        ("Disabled DE", "dw.de", "de", "DE", "news", "news", False),
    ]
    for name, dom, lang, country, stype, tags, enabled in rows:
        s.add(Source(name=name, domain=dom, language=lang, country=country,
                     source_type=stype, tags=tags, enabled=enabled))
    s.commit()

    def _db():
        yield s

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _keys(facet):
    return {x["key"]: x["n"] for x in facet}


def test_facets_distinct_values_and_counts(client):
    r = client.get("/api/sources/facets").json()
    assert _keys(r["languages"]) == {"en": 3, "fr": 1, "de": 1}  # all (incl. disabled)
    assert _keys(r["countries"]) == {"GB": 3, "FR": 1, "DE": 1}
    assert _keys(r["types"]) == {"news": 4, "agency": 1}
    tags = _keys(r["tags"])
    assert tags["news"] == 4 and tags["science"] == 1 and tags["markets"] == 1
    # enabled_only restricts the active set (the disabled de source drops out)
    r2 = client.get("/api/sources/facets?enabled_only=true").json()
    assert "de" not in _keys(r2["languages"])


def test_languages_or_within_and_across_filters(client):
    # WITHIN languages = OR: en OR fr -> 3 enabled-or-not... default has no enabled filter
    r = client.get("/api/sources/?languages=en,fr").json()
    assert {x["domain"] for x in r} == {"bbc.com", "lemonde.fr", "theguardian.com", "reuters.com"}
    # ACROSS filters = AND: (en OR fr) AND type=news -> reuters (agency) drops out
    r = client.get("/api/sources/?languages=en,fr&types=news").json()
    assert {x["domain"] for x in r} == {"bbc.com", "lemonde.fr", "theguardian.com"}


def test_tag_mode_any_vs_all(client):
    # any (default): news OR science
    r = client.get("/api/sources/?tags=news,science").json()
    assert {x["domain"] for x in r} == {"bbc.com", "lemonde.fr", "theguardian.com", "dw.de"}
    # all: must carry BOTH news AND science -> only the Guardian
    r = client.get("/api/sources/?tags=news,science&tag_mode=all").json()
    assert {x["domain"] for x in r} == {"theguardian.com"}


def test_free_text_q_and_country_filter(client):
    r = client.get("/api/sources/?q=guard").json()
    assert {x["domain"] for x in r} == {"theguardian.com"}
    r = client.get("/api/sources/?countries=GB&enabled=true").json()
    assert {x["domain"] for x in r} == {"bbc.com", "theguardian.com", "reuters.com"}


def test_filter_then_paginate(client):
    # The filter must apply across the catalogue, then paginate (not paginate-then-filter).
    r = client.get("/api/sources/?types=news&limit=2").json()
    assert len(r) == 2  # 4 news sources exist; a page of 2 is returned
    r_all = client.get("/api/sources/?types=news&limit=100").json()
    assert len(r_all) == 4
