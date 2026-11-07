"""The geography axis: counts by country and by admin-1 region (v0.6.0 B3c, S06-01 S4, Q816 = a).

Expected values are written out by hand from the rows seeded below, never computed by the code under test. Every refusal has a test that
fails when the refusal is removed.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from src.osm import geography as GEO
from src.osm import ingest
from src.osm.completeness import admin1_state, count_admin1
from src.osm.lane_models import OsmCountry, OsmDiffRun, OsmTagChange, osm_objects_table
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import _extract
from tests.test_osm_profile import _seed as _profile_seed

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]
T = osm_objects_table


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


def _seed():
    """B3b's five places, plus three edge cases for the edited-in-a-year count: the relation (no point) edited exactly one year back from the
    vintage (2024-01-10: the boundary is NOT within the year, as in B3b's age buckets), the inserted node 900 edited AFTER the vintage
    (never counted as recent), and that same node carrying only brand:wikidata (a brand by B3b's recorded key set)."""
    _profile_seed()
    with store.lane_session("osm") as s:
        s.execute(T.update().where(T.c.osm_type == "r", T.c.osm_id == 101).values(timestamp=_dt(2024, 1, 10)))
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 900).values(timestamp=_dt(2025, 2, 1), t_brand_wikidata="Q9"))


def _area(view, alpha3="ZZZ"):
    (a,) = [a for a in view["areas"] if a["alpha3"] == alpha3]
    return a


def _changes():
    """Window of two days. Place n5 changed two keys and n6 one (two places); n900 was CREATED (an object event, not a tag change); a row
    of another country must not count, nor a change to an object that is not a place."""
    with store.lane_session("osm") as s:
        for seq, day in ((1, _dt(2025, 1, 11)), (2, _dt(2025, 1, 12))):
            s.add(OsmDiffRun(alpha3="ZZZ", sequence=seq, diff_timestamp=day))
        rows = [("n", 5, "website", "added", None, 1, "ZZZ"), ("n", 5, "phone", "removed", None, 1, "ZZZ"), ("n", 6, "brand", "modified", None, 2, "ZZZ"),
                ("n", 900, "name", "added", "created", 1, "ZZZ"), ("n", 77, "name", "added", None, 1, "QQQ")]
        # a change row is written for every kept class: a road or a building edited is not a place edited
        other = s.execute(sa.select(T.c.osm_type, T.c.osm_id).where(T.c.country_alpha3 == "ZZZ", T.c.kind != "poi")).first()
        assert other is not None, "the fixture must hold an object that is not a place"
        rows.append((other[0], other[1], "name", "modified", None, 1, "ZZZ"))
        for osm_type, osm_id, key, change, event, day, country in rows:
            s.add(OsmTagChange(osm_type=osm_type, osm_id=osm_id, key=key, change=change, object_event=event, country_alpha3=country,
                               diff_timestamp=_dt(2025, 1, 10 + day), object_version=2))


# --------------------------------------------------------------------------- #
#  Country level                                                              #
# --------------------------------------------------------------------------- #


def test_a_lane_that_never_ran_is_named_and_not_created(osm_lane_dir):
    assert GEO.countries_view() == {"status": "lane-never-run"}
    assert not store.lane_exists("osm"), "reading the geography must not create the lane file"


def test_an_unreadable_lane_is_named_without_the_errors_words(cut, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /home/someone/x")

    monkeypatch.setattr(store, "lane_session", boom)
    got = GEO.countries_view()
    assert got["status"] == "unreadable" and "secret" not in repr(got) and "/home" not in repr(got)


def test_each_measure_is_a_count_of_places_exactly_these(cut):
    _seed()
    a = _area(GEO.countries_view())
    # places n5, n6, n7, r101 and the inserted n900; the brand on a PLACE (node 8) is not a place with metadata.
    assert a["n"] == 5 and a["values"]["places"] == 5
    assert a["values"]["brand"] == 4, "n5, n6 (brand), n7 (brand 'acme') and n900 (brand:wikidata only); r101 carries none"
    assert a["values"]["checked"] == 4, "n5, n6, n7 ('soon' is still a check_date a mapper wrote) and r101; n900's is empty"
    # extract vintage 2025-01-10, one year back 2024-01-10: only n5 (2024-12-01); n6 and n7 are older, r101 is exactly one year back (not
    # within), n900 is dated after the vintage (not recent).
    assert a["values"]["edited_1y"] == 1
    assert a["alpha2"] == "ZZ" and a["name"]


def test_the_vintage_is_the_extract_and_the_last_change_file_applied(cut):
    _seed()
    a = _area(GEO.countries_view())
    assert a["vintage"] == {"extract": "2025-01-10T00:00:00+00:00", "last_diff": None, "reference": "2025-01-10T00:00:00+00:00"}
    with store.lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        c.diff_timestamp, c.diff_sequence = _dt(2025, 1, 12), 2
    a = _area(GEO.countries_view())
    assert a["vintage"] == {"extract": "2025-01-10T00:00:00+00:00", "last_diff": "2025-01-12T00:00:00+00:00", "reference": "2025-01-12T00:00:00+00:00"}
    # the ages move with the reference: 2024-01-12 now, still only n5
    assert a["values"]["edited_1y"] == 1


def test_changed_is_absent_with_its_reason_until_a_change_file_is_observed_and_never_zero(cut):
    _seed()
    a = _area(GEO.countries_view())
    assert a["values"]["changed"] is None and a["reasons"]["changed"] == "no-daily-files"
    assert a["observed_since"] is None


def test_changed_counts_places_with_an_ordinary_tag_change_once_each(cut):
    _seed()
    _changes()
    a = _area(GEO.countries_view())
    assert a["values"]["changed"] == 2, "n5 (two keys) and n6; the created n900 and another country's row are not tag changes here"
    assert a["observed_since"] == "2025-01-11T00:00:00+00:00"
    assert "changed" not in a["reasons"]


def test_a_country_without_any_date_has_no_edited_figure_not_a_zero(cut):
    _seed()
    with store.lane_session("osm") as s:
        s.query(OsmCountry).filter_by(alpha3="ZZZ").one().extract_vintage = None
    a = _area(GEO.countries_view())
    assert a["values"]["edited_1y"] is None and a["reasons"]["edited_1y"] == "no-reference"
    assert a["vintage"]["reference"] is None
    assert a["values"]["places"] == 5, "the other measures do not need a date"


def test_a_country_that_did_not_finish_is_listed_apart_and_not_mapped(cut):
    _seed()
    with store.lane_session("osm") as s:
        s.add(OsmCountry(alpha2="QQ", alpha3="QQQ", name="Elsewhere", status="ingesting"))
    got = GEO.countries_view()
    assert [a["alpha3"] for a in got["areas"]] == ["ZZZ"] and got["not_cut"] == ["QQQ"]


def test_no_score_no_blend_and_the_method_and_caveat_travel(cut):
    _seed()
    got = GEO.countries_view()
    assert got["measures"] == ["places", "brand", "checked", "edited_1y", "changed"]
    assert not any("score" in k for k in got) and not any("score" in k for k in _area(got))
    assert got["method"] and got["caveat"]
    assert "share of the area's own places" in GEO.CAVEAT, "the caveat does not say why the share is offered"


def test_the_route_reads_the_lane_and_makes_no_request(cut):
    from src.api.main import app

    _seed()
    got = TestClient(app).get("/api/osm/geography").json()
    assert got["status"] == "ok" and _area(got)["values"]["places"] == 5


def test_the_route_on_a_lane_that_never_ran_creates_nothing(osm_lane_dir):
    from src.api.main import app

    assert TestClient(app).get("/api/osm/geography").json() == {"status": "lane-never-run"}
    assert not store.lane_exists("osm")


# --------------------------------------------------------------------------- #
#  Region level                                                               #
# --------------------------------------------------------------------------- #


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _outlines(tmp_path):
    doc = {
        "kind": "admin1", "vintage": "2025-01-06", "source": "fixture",
        "regions": {
            "ZZ-W": {"country": "ZZZ", "name": "West", "names": {}, "rings": [_box(0.10, 0.10, 0.14, 0.20)]},
            "ZZ-E": {"country": "ZZZ", "name": "East", "names": {}, "rings": [_box(0.14, 0.10, 0.20, 0.14)]},
            "ZZ-X": {"country": "ZZZ", "name": "Empty", "names": {}, "rings": [_box(0.5, 0.5, 0.6, 0.6)]},
        },
    }
    p = tmp_path / "osm_admin1.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _place(osm_type, osm_id, lat, lon):
    with store.lane_session("osm") as s:
        s.execute(T.update().where(T.c.osm_type == osm_type, T.c.osm_id == osm_id).values(lat=lat, lon=lon))


def _seed_points():
    """n5 and n6 in West, n7 in East, the relation 101 with no point, n900 in no outline."""
    _place("n", 5, 0.15, 0.12)
    _place("n", 6, 0.11, 0.12)
    _place("n", 7, 0.12, 0.17)
    _place("r", 101, None, None)
    _place("n", 900, 0.30, 0.30)


def _regions(state):
    return {r["key"]: r for r in state["regions"]}


def test_each_region_carries_the_same_counts_the_country_does_by_the_same_rules(cut, tmp_path):
    _seed()
    _seed_points()
    with store.lane_session("osm") as s:   # West must differ between brand (2) and check_date (1): symmetric figures hide a swapped column
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 6).values(t_check_date=None))
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    regs = _regions(admin1_state("ZZZ", path=path))
    assert regs["ZZ-W"]["n"] == 2 and regs["ZZ-W"]["measures"] == {"brand": 2, "checked": 1, "edited_1y": 1}, "n5 and n6 are West (n6 has no check_date); only n5 is a year fresh"
    assert regs["ZZ-E"]["n"] == 1 and regs["ZZ-E"]["measures"] == {"brand": 1, "checked": 1, "edited_1y": 0}, "n7 is East: brand 'acme', check_date 'soon', edited in 2019"
    assert regs["ZZ-X"]["n"] == 0 and regs["ZZ-X"]["measures"] == {"brand": 0, "checked": 0, "edited_1y": 0}
    st = admin1_state("ZZZ", path=path)
    assert st["outside"] == 1 and st["no_point"] == 1, "n900 in no outline and the relation with no point: counted, not dropped"
    country = _area(GEO.countries_view())["values"]
    placed = {m: sum(r["measures"][m] for r in regs.values()) for m in ("brand", "checked", "edited_1y")}
    # the regions plus the two unplaced places equal the country: n900 (in no outline) carries a brand:wikidata and r101 (no point) a check_date
    assert country["checked"] == 3
    assert placed["brand"] + 1 == country["brand"] and placed["checked"] + 1 == country["checked"] and placed["edited_1y"] == country["edited_1y"]


def test_a_split_counted_before_these_measures_existed_has_none_and_not_zeros(cut, tmp_path):
    from src.osm.lane_models import OsmAdmin1Split

    _seed()
    _seed_points()
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    with store.lane_session("osm") as s:
        row = s.query(OsmAdmin1Split).filter_by(alpha3="ZZZ").one()
        stored = json.loads(row.regions_json)
        for v in stored.values():
            v.pop("measures")
        row.regions_json = json.dumps(stored)
    regs = _regions(admin1_state("ZZZ", path=path))
    assert all(r["measures"] is None for r in regs.values()), "an old split read as counted zeros"
    assert regs["ZZ-W"]["n"] == 2, "the old figures still read"


def test_a_country_with_no_date_stores_no_edited_figure_for_its_regions(cut, tmp_path):
    _seed()
    _seed_points()
    with store.lane_session("osm") as s:
        s.query(OsmCountry).filter_by(alpha3="ZZZ").one().extract_vintage = None
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    regs = _regions(admin1_state("ZZZ", path=path))
    assert regs["ZZ-W"]["measures"] == {"brand": 2, "checked": 2}, "an edited count of 0 would say nothing was edited"


# --------------------------------------------------------------------------- #
#  Source-level guards                                                         #
# --------------------------------------------------------------------------- #


def test_the_module_makes_no_request_and_imports_no_socket_library():
    src = (ROOT / "src" / "osm" / "geography.py").read_text(encoding="utf-8")
    for needle in ("requests", "httpx", "urllib", "socket", "http.client"):
        assert needle not in src, needle
