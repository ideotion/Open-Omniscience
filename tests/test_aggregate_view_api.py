"""The published-aggregate view (field feedback 2026-08-07, rulings 1b and 32).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruling 1(b) resolved the World Bank aggregates leaking into country surfaces as "keep
them, tag them, exclude them from country surfaces, give them their own view". The
storage and the classifier shipped; this is the view's API.

The load-bearing property is the SEPARATION, and it has two directions that fail
differently, so both are asserted here rather than only the one that motivated the
ruling. An aggregate appearing among countries is the reported defect: `XD` rendered as
a nation with a $77T GDP. A country appearing among aggregates is the mirror, and is
worse in kind — it would assert that the World Bank publishes "France" as an aggregate,
which is not a labelling slip but a false claim about what the producer publishes.
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
from src.ingest import clear_kill_switch


def _fig(area, series, year, value, extracted="2026-08-01"):
    return StatFigure(agency="worldbank", series_id=series, ref_area=area,
                      time_period=str(year), value=value, unit="", extracted_at=extracted)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all([
        # Two real countries and two real aggregates, so both directions are testable.
        _fig("FRA", "NY.GDP.MKTP.CD", 2022, 3.0e12),
        _fig("DEU", "NY.GDP.MKTP.CD", 2022, 4.1e12),
        _fig("WLD", "NY.GDP.MKTP.CD", 2022, 100.0e12),   # World
        _fig("WLD", "NY.GDP.MKTP.CD", 2021, 96.0e12),
        _fig("HIC", "NY.GDP.MKTP.CD", 2022, 77.0e12),    # High income — the "XD" of the report
    ])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()


# --------------------------------------------------------------------------- #
# The listing: a shortlist by default, the full set in the same payload
# --------------------------------------------------------------------------- #


def test_the_listing_carries_a_shortlist_and_the_full_set_together(client):
    d = client.get("/api/governments/aggregates").json()
    rows = d["aggregates"]

    short = [a for a in rows if a["shortlist"]]
    assert len(short) >= 10, "the curated default view must not be empty"
    assert len(rows) > len(short), (
        "ruling 32 wants the full set BEHIND a control, which means shipped in the same "
        "payload — a second fetch would make 'show all' able to fail on its own"
    )
    names = {a["name"] for a in short}
    assert {"World", "Sub-Saharan Africa"} <= names
    assert d["as_of"], "the registry vintage travels with the list"


def test_the_listing_offers_no_country(client):
    """The mirror direction, and the one that would assert something false."""
    from src.catalog.countries import classify_ref_area

    rows = client.get("/api/governments/aggregates").json()["aggregates"]
    assert rows, "guard against an empty listing satisfying this for free"
    bad = [a for a in rows if classify_ref_area(a["code"]) != "aggregate"]
    assert bad == [], f"a country reached the aggregate listing: {bad}"


def test_a_non_place_bucket_is_not_offered_as_somewhere(client):
    """'Not classified' is a real code and not a place; beside World it reads as one."""
    codes = {a["code"] for a in client.get("/api/governments/aggregates").json()["aggregates"]}
    assert "INX" not in codes


def test_has_data_separates_a_producer_gap_from_an_unfetched_install(client):
    rows = {a["code"]: a for a in client.get("/api/governments/aggregates").json()["aggregates"]}
    assert rows["WLD"]["has_data"] is True
    # Real aggregate, nothing fetched for it in this store — must read as "not held here",
    # never as "the producer publishes nothing".
    assert rows["ECS"]["has_data"] is False


# --------------------------------------------------------------------------- #
# One aggregate's figures
# --------------------------------------------------------------------------- #


def test_an_aggregate_serves_its_own_published_series(client):
    d = client.get("/api/governments/aggregate/WLD").json()
    assert d["code"] == "WLD" and d["name"] == "World" and d["kind"] == "aggregate"
    gdp = next(i for i in d["indicators"] if i["id"] == "NY.GDP.MKTP.CD")
    assert gdp["latest"] == {"year": "2022", "value": 100.0e12}
    assert [p["year"] for p in gdp["series"]] == ["2021", "2022"]
    assert "not figures this app computed" in d["caveat"], (
        "the reader must be told this is the producer's own aggregate, not ours"
    )


def test_an_aggregate_is_reachable_by_its_alpha_2_form_too(client):
    """`1W` and `WLD` are the same World; a picker may hold either."""
    assert client.get("/api/governments/aggregate/1W").json()["code"] == "WLD"


def test_a_country_is_refused_by_the_aggregate_route(client):
    r = client.get("/api/governments/aggregate/FRA")
    assert r.status_code == 404
    assert "not a published aggregate" in r.json()["detail"]


def test_an_unknown_code_is_refused_rather_than_invented(client):
    r = client.get("/api/governments/aggregate/ZZZ")
    assert r.status_code == 404
    assert "unknown aggregate" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# The country surfaces stay clean — the defect that started the ruling
# --------------------------------------------------------------------------- #


def test_the_choropleth_carries_no_aggregate(client):
    """`XD` on the map as a nation with a $77T GDP is the reported field defect."""
    rows = client.get("/api/governments/map?indicator=NY.GDP.MKTP.CD").json()["by_country"]
    assert rows, "an empty map would satisfy this for free"
    assert {r["iso3"] for r in rows} == {"FRA", "DEU"}
    assert all(r["iso3"] not in {"WLD", "HIC"} for r in rows)


def test_the_country_route_serves_an_aggregate_but_never_calls_it_a_country(client):
    """Not a 404 — the figures are real and a bookmark should keep working — but the
    payload says what it is, so no surface can render it as a nation by accident."""
    d = client.get("/api/governments/country/WLD").json()
    assert d["kind"] == "aggregate"
    assert d["iso2"] is None
    assert client.get("/api/governments/country/FRA").json()["kind"] == "country"
