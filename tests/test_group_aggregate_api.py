"""The group-aggregate endpoint, driven end to end over seeded figures (no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, rulings 43/44/47. The engine is unit-tested next door; what
this file exists for is the wiring, which is where the interesting mistakes live: whether
the roster and the figures describe the SAME year, whether the weight series reaches the
engine at all, and whether a real group with no membership data comes back as an honest
gap rather than as an error or an empty success.

The store keys areas by the producer's alpha-3 (FRA); the registry keys members by
alpha-2 (fr). That conversion is exactly the kind of seam that silently yields "no member
reported" — a plausible, wrong answer — so it is driven rather than assumed.
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


def _fig(area, series, year, value, extracted="2026-08-01"):
    return StatFigure(
        agency="worldbank", series_id=series, ref_area=area,
        time_period=str(year), value=value, unit="", extracted_at=extracted,
    )


@pytest.fixture
def client():
    """An ISOLATED engine routed in via dependency_overrides — never SessionLocal, whose
    rows would outlive this test and pollute every later one that reads the store."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # Three European economies, alpha-3 as the World Bank publishes them.
    rows = []
    for iso3, pop, gdp_pc in (("FRA", 68.0, 44_000.0), ("DEU", 84.0, 52_000.0), ("LUX", 0.66, 128_000.0)):
        rows += [
            _fig(iso3, "SP.POP.TOTL", 2023, pop),
            _fig(iso3, "NY.GDP.PCAP.CD", 2023, gdp_pc),
        ]
    s.add_all(rows)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        s.close()


def _agg(client, **params):
    r = client.get("/api/governments/group-aggregate", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #


def test_the_alpha3_store_reaches_the_alpha2_roster():
    """Pinned as its own claim: if this conversion breaks, every aggregate becomes an
    honest-looking 'no member reported' rather than an error."""
    from src.catalog.countries import to_iso2

    assert to_iso2("FRA") == "fr" and to_iso2("DEU") == "de"


def test_an_unpopulated_group_is_an_honest_gap_not_an_error(client):
    out = _agg(client, group="brics", indicator="SP.POP.TOTL")
    assert out["aggregate"] is None
    assert out["group"]["populated"] is False
    assert "guessing a date" in out["reason"]


def test_an_unknown_group_is_a_404(client):
    r = client.get("/api/governments/group-aggregate",
                   params={"group": "atlantis", "indicator": "SP.POP.TOTL"})
    assert r.status_code == 404


def test_an_unknown_indicator_is_a_404(client):
    r = client.get("/api/governments/group-aggregate",
                   params={"group": "europe", "indicator": "NOT.REAL"})
    assert r.status_code == 404


def test_europe_refuses_by_default_because_most_members_did_not_report(client):
    """Only three European countries are seeded, so the continent's coverage is far from
    complete — and the refusal names how many are missing rather than quietly averaging
    the three that happen to be there."""
    out = _agg(client, group="europe", indicator="SP.POP.TOTL", year="2023")
    agg = out["aggregate"]
    assert agg["coverage"]["reported"] == 3
    assert agg["coverage"]["members"] > 40
    assert agg["coverage"]["complete"] is False
    assert "value" not in agg["strategies"]["sum"]
    assert "did not report" in agg["strategies"]["sum"]["refused"]


def test_the_override_computes_and_carries_the_missing_members(client):
    out = _agg(client, group="europe", indicator="SP.POP.TOTL", year="2023",
               allow_incomplete=True)
    agg = out["aggregate"]
    assert agg["strategies"]["sum"]["value"] == pytest.approx(68.0 + 84.0 + 0.66)
    assert agg["strategies"]["sum"]["basis"] == "approximate"
    missing = agg["coverage"]["missing"]
    assert "gb" in missing and "fr" not in missing
    assert len(missing) == agg["coverage"]["members"] - 3


def test_the_weight_series_actually_reaches_the_engine(client):
    """The wiring claim: population must arrive as a WEIGHT, not merely as an indicator
    that happens to be in the store."""
    out = _agg(client, group="europe", indicator="NY.GDP.PCAP.CD", year="2023",
               allow_incomplete=True)
    w = out["aggregate"]["strategies"]["population_weighted"]
    expected = (44_000 * 68.0 + 52_000 * 84.0 + 128_000 * 0.66) / (68.0 + 84.0 + 0.66)
    assert w["value"] == pytest.approx(expected)
    # Exactness needs complete coverage too -- this run is partial, and says so.
    assert w["basis"] == "approximate"
    assert "PARTIAL" in w["method"]


def test_summing_a_per_capita_indicator_is_refused_through_the_endpoint(client):
    out = _agg(client, group="europe", indicator="NY.GDP.PCAP.CD", year="2023",
               allow_incomplete=True)
    s = out["aggregate"]["strategies"]["sum"]
    assert "value" not in s and "not a statistic at all" in s["refused"]


def test_the_roster_and_the_figures_describe_the_same_year(client):
    """With no year given the endpoint picks the indicator's latest period and re-resolves
    membership against it — otherwise a 2023 figure could be weighed against a roster
    resolved for 'now', which is the stale-roster defect wearing a different hat."""
    out = _agg(client, group="europe", indicator="SP.POP.TOTL", allow_incomplete=True)
    assert out["aggregate"]["period"] == "2023"
    assert out["aggregate"]["period_source"].startswith("latest")
    assert out["group"]["resolved_year"] == 2023


def test_every_response_states_the_registry_vintage(client):
    for group in ("europe", "brics"):
        out = _agg(client, group=group, indicator="SP.POP.TOTL")
        assert out["group"]["as_of"]


def test_the_groups_listing_shows_unpopulated_groups_with_their_reason(client):
    r = client.get("/api/governments/groups")
    assert r.status_code == 200
    body = r.json()
    by_key = {g["key"]: g for g in body["groups"]}
    assert by_key["africa"]["populated"] is True and by_key["africa"]["members"] > 50
    assert by_key["brics"]["populated"] is False and by_key["brics"]["reason"]
    # Populated from a live read on 2026-08-07, so no longer an example of a gap.
    assert by_key["wb-sub-saharan-africa"]["populated"] is True
    assert by_key["wb-sub-saharan-africa"]["members"] == 48
    # ...and the thirteen blocs still are, which is what keeps this test meaningful.
    assert sum(1 for g in body["groups"] if not g["populated"]) == 13
    assert body["as_of"]


# --------------------------------------------------------------------------- #
#  World Bank regions — populated 2026-08-07, so they aggregate end to end now
# --------------------------------------------------------------------------- #


@pytest.fixture
def sasia_client():
    """Three of South Asia's six members, plus the region's OWN published aggregate row.

    That last row is the point: the World Bank publishes `SAS` as an economy in the same
    series, and it must never be counted as a member of itself. `to_iso2("SAS")` is None
    so it cannot enter — this fixture proves that rather than assuming it.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    rows = []
    for iso3, pop, gdp_pc in (("IND", 1428.0, 2500.0), ("BGD", 173.0, 2700.0), ("LKA", 22.0, 3800.0)):
        rows += [_fig(iso3, "SP.POP.TOTL", 2023, pop), _fig(iso3, "NY.GDP.PCAP.CD", 2023, gdp_pc)]
    rows.append(_fig("SAS", "SP.POP.TOTL", 2023, 1900.0))       # the aggregate itself
    rows.append(_fig("SAS", "NY.GDP.PCAP.CD", 2023, 2600.0))
    s.add_all(rows)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        s.close()


def test_a_world_bank_region_aggregates_end_to_end(sasia_client):
    out = _agg(sasia_client, group="wb-south-asia", indicator="NY.GDP.PCAP.CD",
               year="2023", allow_incomplete=True)
    assert out["group"]["populated"] is True
    assert out["group"]["kind"] == "wb_region"
    assert len(out["group"]["members"]) == 6
    w = out["aggregate"]["strategies"]["population_weighted"]
    expected = (2500 * 1428.0 + 2700 * 173.0 + 3800 * 22.0) / (1428.0 + 173.0 + 22.0)
    assert w["value"] == pytest.approx(expected)


def test_the_regions_own_aggregate_row_is_never_counted_as_one_of_its_members(sasia_client):
    """`SAS` is published as an economy in the same series. If it leaked in, the region
    would contain itself and the weighted mean would double-count a whole region's worth
    of people -- a large, plausible, undetectable error."""
    out = _agg(sasia_client, group="wb-south-asia", indicator="SP.POP.TOTL",
               year="2023", allow_incomplete=True)
    agg = out["aggregate"]
    assert agg["coverage"]["reported"] == 3, "only the three real members reported"
    assert agg["strategies"]["sum"]["value"] == pytest.approx(1428.0 + 173.0 + 22.0)
    assert agg["spread"]["max"] == 1428.0, "1900 (the SAS aggregate) must not be in range"


def test_afghanistan_and_pakistan_aggregate_under_MENA_not_south_asia(sasia_client):
    """The reassignment reaching the surface it matters on. A tool still filing them under
    South Asia would compute both regions over the wrong populations."""
    sas = _agg(sasia_client, group="wb-south-asia", indicator="SP.POP.TOTL")["group"]["members"]
    mea = _agg(sasia_client, group="wb-middle-east-north-africa",
               indicator="SP.POP.TOTL")["group"]["members"]
    assert {"af", "pk"} & set(sas) == set()
    assert {"af", "pk"} <= set(mea)
