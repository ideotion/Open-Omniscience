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
    assert out["admin1"]["status"] == "no-admin1-file", "no outline file here, and none is guessed"
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
    assert "Q823" in lane["exports"] and "held" not in lane["exports"]
    assert "OpenStreetMap contributors" in lane["credit"] and "ODbL" in lane["credit"]
    r = c.get("/api/osm/countries/ZZ/completeness")
    assert r.status_code == 200 and r.json()["n"] == 4
    assert c.get("/api/osm/countries/XQ/completeness").status_code == 400


# --------------------------------------------------------------------------- #
#  Per admin-1 region (S5), over a hand-made outline file in row E's format    #
# --------------------------------------------------------------------------- #
# Fixture Land is the square 0.1..0.2. WEST is lon 0.10-0.14 (the pharmacy, 0.18/0.12); EAST
# is lon 0.14-0.20 but only lat 0.10-0.14 (the bakery, 0.12/0.18) -- so the cafe (0.15/0.15)
# is in NO region, the site relation has NO point, and EMPTY holds nothing.


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _outlines(tmp_path, vintage="2025-01-06"):
    import json

    doc = {
        "kind": "admin1", "vintage": vintage, "source": "fixture",
        "regions": {
            "ZZ-W": {"country": "ZZZ", "name": "West", "names": {"fr": "Ouest"}, "rings": [_box(0.10, 0.10, 0.14, 0.20)]},
            "ZZ-E": {"country": "ZZZ", "name": "East", "names": {}, "rings": [_box(0.14, 0.10, 0.20, 0.14)]},
            "ZZ-X": {"country": "ZZZ", "name": "Empty", "names": {}, "rings": [_box(0.5, 0.5, 0.6, 0.6)]},
            "QQ-1": {"country": "QQQ", "name": "Elsewhere", "names": {}, "rings": [_box(1, 1, 2, 2)]},
        },
    }
    p = tmp_path / "osm_admin1.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _regions(out):
    return {r["key"]: r for r in out["regions"]}


def test_each_place_is_counted_in_the_region_whose_outline_holds_it(osm_lane_dir, tmp_path):
    from src.osm.completeness import count_admin1

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    out = count_admin1("ZZZ", path=_outlines(tmp_path))
    assert out["status"] == "complete"
    regs = _regions(out)
    assert set(regs) == {"ZZ-W", "ZZ-E", "ZZ-X"}, "another country's region was counted here"
    assert regs["ZZ-W"]["n"] == 1 and regs["ZZ-E"]["n"] == 1
    west = {k["key"]: k["present"] for k in regs["ZZ-W"]["keys"]}
    east = {k["key"]: k["present"] for k in regs["ZZ-E"]["keys"]}
    assert west == {"opening_hours": 0, "website": 0, "email": 0, "phone": 0}, "the pharmacy's empty hours counted"
    assert east == {"opening_hours": 0, "website": 0, "email": 1, "phone": 1}, "the bakery's contact:email twin"


def test_the_three_uncounted_populations_are_counted_never_dropped(osm_lane_dir, tmp_path):
    from src.osm.completeness import count_admin1

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    out = count_admin1("ZZZ", path=_outlines(tmp_path))
    assert out["outside"] == 1, "the cafe, in no region's outline"
    assert out["no_point"] == 1, "the site relation, with no point of its own"
    empty = _regions(out)["ZZ-X"]
    assert empty["n"] == 0 and all(k["share"] is None for k in empty["keys"]), "an empty region read as 0 %"
    total = sum(r["n"] for r in out["regions"]) + out["outside"] + out["no_point"]
    assert total == tag_completeness("ZZZ")["n"], "the split does not add up to the country"


def test_a_split_reads_stale_when_the_outlines_or_the_ingest_change(osm_lane_dir, tmp_path):
    from src.osm.completeness import admin1_state, count_admin1

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    assert admin1_state("ZZZ", path=path)["status"] == "complete"
    assert admin1_state("ZZZ", path=_outlines(tmp_path, vintage="2026-01-01"))["status"] == "stale"
    path = _outlines(tmp_path)
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert admin1_state("ZZZ", path=path)["status"] == "stale", "a re-ingest left the old split reading as current"


def test_without_the_outline_file_or_a_region_the_refusal_is_named(osm_lane_dir, tmp_path):
    from src.osm.completeness import Admin1Error, admin1_state, count_admin1, start_count

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    missing = tmp_path / "absent.json"
    assert admin1_state("ZZZ", path=missing)["status"] == "no-admin1-file"
    with pytest.raises(Admin1Error, match="no-admin1-file"):
        start_count("ZZZ", path=missing)
    assert admin1_state("FRA", path=_outlines(tmp_path))["status"] == "no-regions"
    with pytest.raises(Admin1Error, match="no-regions"):
        count_admin1("FRA", path=_outlines(tmp_path))
    assert admin1_state("ZZZ", path=_outlines(tmp_path))["status"] == "not-counted"


def test_a_count_left_running_by_a_restart_reads_interrupted(osm_lane_dir, tmp_path):
    from src.osm.completeness import admin1_state
    from src.osm.lane_models import OsmAdmin1Split

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        s.add(OsmAdmin1Split(alpha3="ZZZ", status="counting"))
    assert admin1_state("ZZZ", path=_outlines(tmp_path))["status"] == "interrupted"


def test_the_count_route_refuses_by_name_and_counts_on_a_thread(osm_lane_dir, tmp_path, monkeypatch):
    import time

    from src.api.main import app
    from src.osm import completeness

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    c = TestClient(app)
    monkeypatch.setattr(completeness, "ADMIN1_FILE", tmp_path / "absent.json")
    r = c.post("/api/osm/countries/ZZ/admin1")
    assert r.status_code == 409 and r.json()["detail"] == "no-admin1-file"
    monkeypatch.setattr(completeness, "ADMIN1_FILE", _outlines(tmp_path))
    assert c.post("/api/osm/countries/ZZ/admin1").json()["started"] is True
    for _ in range(100):
        got = c.get("/api/osm/countries/ZZ/completeness").json()["admin1"]
        if got["status"] == "complete":
            break
        time.sleep(0.05)
    assert got["status"] == "complete" and _regions(got)["ZZ-W"]["n"] == 1
