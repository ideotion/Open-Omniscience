"""Governments tab API (field test 2026-06-22): per-country indicators + map + the
airplane-gated load-standard fetch. Reads run over seeded StatFigure rows (no network);
the fetch refusal is proven without a socket.

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
from src.database.models import Base, StatFigure
from src.database.session import get_db
from src.ingest import activate_kill_switch, clear_kill_switch


def _fig(area, series, year, value, extracted="2026-06-01"):
    return StatFigure(agency="worldbank", series_id=series, ref_area=area,
                      time_period=str(year), value=value, unit="", extracted_at=extracted)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all([
        _fig("FR", "NY.GDP.MKTP.CD", 2021, 2.9e12),
        _fig("FR", "NY.GDP.MKTP.CD", 2022, 3.0e12),
        _fig("FR", "SP.POP.TOTL", 2022, 67_900_000),
        _fig("FR", "GC.NLD.TOTL.GD.ZS", 2022, None),   # a published gap
        _fig("US", "NY.GDP.MKTP.CD", 2022, 25.0e12),
        _fig("US", "NY.GDP.MKTP.CD", 2021, 23.0e12),
    ])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()


def test_indicators_catalog(client):
    r = client.get("/api/governments/indicators").json()
    ids = {i["id"] for i in r["indicators"]}
    # the maintainer's named metrics are present
    assert {"NY.GDP.MKTP.CD", "SP.POP.TOTL", "SP.DYN.LE00.IN", "SL.UEM.TOTL.ZS",
            "GC.NLD.TOTL.GD.ZS"} <= ids
    assert r["agency"] == "worldbank" and r["catalog_revised"]
    # No fabricated score FIELD on any indicator (the caveat prose may SAY "never a
    # credibility score" — that's the disclosure, not a score field).
    for i in r["indicators"]:
        assert not any("score" in k.lower() for k in i)


def test_map_latest_per_country(client):
    r = client.get("/api/governments/map", params={"indicator": "NY.GDP.MKTP.CD"}).json()
    by = {c["country"]: c for c in r["by_country"]}
    # the LATEST period per country (2022 for both), not an older year
    assert by["FR"]["year"] == "2022" and by["FR"]["value"] == 3.0e12
    assert by["US"]["year"] == "2022" and by["US"]["value"] == 25.0e12
    assert r["years"] == ["2021", "2022"]   # the slider's history range
    assert r["indicator"]["label"].startswith("GDP")


def test_map_specific_year(client):
    r = client.get("/api/governments/map",
                   params={"indicator": "NY.GDP.MKTP.CD", "year": "2021"}).json()
    by = {c["country"]: c for c in r["by_country"]}
    assert by["FR"]["value"] == 2.9e12 and by["US"]["value"] == 23.0e12


def test_map_unknown_indicator_404(client):
    assert client.get("/api/governments/map", params={"indicator": "NOPE"}).status_code == 404


def test_country_data_all_indicators_with_gap(client):
    r = client.get("/api/governments/country/FR").json()
    assert r["country"] == "FR"
    by = {i["id"]: i for i in r["indicators"]}
    # every curated indicator is listed, even with no data (a gap, never zero)
    assert "SP.DYN.LE00.IN" in by and by["SP.DYN.LE00.IN"]["latest"] is None
    # GDP has a latest from the most recent year + a 2-point history
    assert by["NY.GDP.MKTP.CD"]["latest"] == {"year": "2022", "value": 3.0e12}
    assert len(by["NY.GDP.MKTP.CD"]["series"]) == 2
    # a published-gap value (None) does not become a fabricated latest
    assert by["GC.NLD.TOTL.GD.ZS"]["latest"] is None


def test_load_standard_refused_under_airplane(client):
    activate_kill_switch()
    try:
        r = client.post("/api/governments/load-standard", json={})
        assert r.status_code == 409 and "airplane" in r.json()["detail"].lower()
    finally:
        clear_kill_switch()
