"""Analytic 1, tag completeness (Q815 · 1): counts, n, method, caveat, never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Expected figures are derived by hand from the fixture's literals: four places with metadata
(the cafe, the bakery, the pharmacy, the site relation); the cafe has all four tags; the bakery
has a phone and its e-mail in ``contact:email``; the pharmacy's ``opening_hours`` is EMPTY.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.osm import ingest
from src.osm.completeness import tag_completeness
from src.versioned import store
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE

osm_lane_dir = _osm_lane_helpers.osm_lane_dir


def test_the_four_keys_are_counted_separately_with_the_contact_twin_and_empty_as_absent(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    out = tag_completeness("ZZZ")
    assert out["status"] == "complete"
    assert out["n"] == 4
    got = {k["key"]: k["present"] for k in out["keys"]}
    assert got == {"opening_hours": 1, "website": 1, "email": 2, "phone": 2}
    assert [k["key"] for k in out["keys"]] == ["opening_hours", "website", "email", "phone"]
    assert out["keys"][2]["share"] == pytest.approx(0.5)
    assert out["method"] and out["caveat"]
    assert out["admin1"] == {"status": "waiting", "reason": "admin1-keys-row-e"}
    assert not any("score" in k for k in out), "a blended figure crept in"


def test_a_lane_that_does_not_exist_is_absent_and_carries_no_figures(osm_lane_dir):
    out = tag_completeness("ZZZ")
    assert out["status"] == "lane-absent"
    assert out["n"] is None and out["keys"] == []
    assert not store.lane_exists("osm"), "asking created the lane"


def test_a_country_not_ingested_is_said_so(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert tag_completeness("FRA")["status"] == "not-ingested"


def test_an_unfinished_country_is_REFUSED_not_counted_as_a_small_one(osm_lane_dir):
    from src.osm.lane_models import OsmCountry

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        s.query(OsmCountry).filter_by(alpha3="ZZZ").one().status = "ingesting"
    out = tag_completeness("ZZZ")
    assert out["status"] == "ingesting"
    assert out["n"] is None and out["keys"] == []


def test_zero_places_gives_no_share_never_zero_percent(osm_lane_dir):
    from src.osm.lane_models import OsmObject

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        s.query(OsmObject).filter_by(kind="poi").delete()
    out = tag_completeness("ZZZ")
    assert out["n"] == 0
    assert all(k["share"] is None for k in out["keys"])


def test_the_api_reads_the_lane_and_refuses_a_bad_code(osm_lane_dir):
    from src.api.main import app

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    c = TestClient(app)
    lane = c.get("/api/osm/lane").json()
    assert lane["countries"][0]["alpha3"] == "ZZZ"
    assert lane["lane_bytes"] and lane["lane_bytes"] > 0
    assert "Q823" in lane["exports"]
    r = c.get("/api/osm/countries/ZZ/completeness")
    assert r.status_code == 200 and r.json()["n"] == 4
    assert c.get("/api/osm/countries/XQ/completeness").status_code == 400
