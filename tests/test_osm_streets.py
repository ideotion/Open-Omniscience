"""The street layer: self-rendered roads at high zoom from the ingested OSM roads (S07-02 S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q821 = b: the streets are drawn by this app from ``osm.db``, never fetched from a tile server.
Q822: the published caps hold; over one, whole road classes are left out in a FIXED order that
comes from the stored ``highway`` value alone, and the answer names each class left out.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.osm import ingest
from src.osm import view as V
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE
from tests.js_source_helper import function_source

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
BOX = (0.1, 0.1, 0.2, 0.2)


def _add_roads(roads) -> None:
    """Add road ways to the ingested fixture country and rebuild its view index.

    ``roads`` is a list of ``(highway value, [(lat, lon), ...], name or None)``.
    """
    import sqlalchemy as sa

    from src.osm.geometry import encode_coords
    from src.osm.lane_models import osm_objects_table
    from src.osm.tags import column_name
    from src.versioned import store

    name = column_name("name")
    with store.lane_session("osm") as s:
        for i, (value, coords, label) in enumerate(roads):
            s.execute(sa.insert(osm_objects_table).values(
                osm_type="w", osm_id=900000 + i, country_alpha3="ZZZ", kind="road", notable=False,
                primary_key="highway", primary_value=value, geom=encode_coords(coords),
                node_count=len(coords), **{name: label},
            ))
    V.build_view_index("ZZZ")


def _line(i: int, n: int = 2) -> list[tuple[float, float]]:
    lat = 0.11 + 0.0001 * i
    return [(lat, 0.11 + 0.08 * k / (n - 1)) for k in range(n)]


def test_the_drop_order_is_pinned_and_comes_from_the_highway_value_only():
    # The planner's point (1): reordering this tuple is a change a reviewer sees here.
    assert [c for c, _ in V.STREET_CLASSES] == [
        "motorway", "trunk", "primary", "secondary", "tertiary", "minor", "service", "path", "other",
    ]
    assert V.street_class("motorway_link") == 0 and V.street_class("residential") == 5
    assert V.street_class("footway") == 7
    assert V.street_class("raceway") == V.street_class(None) == len(V.STREET_CLASSES) - 1
    seen = [v for _, vs in V.STREET_CLASSES for v in vs]
    assert len(seen) == len(set(seen)), "a highway value belongs to one class"
    # street_class reads its argument and nothing else: no tag, name, size or count reaches it.
    import inspect
    assert list(inspect.signature(V.street_class).parameters) == ["value"]


def test_the_fixture_road_is_drawn_with_its_class_and_name(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    d = V.streets(*BOX)
    assert d["status"] == "streets" and d["layer"] == "streets"
    assert d["total"] == 1 and d["drawn"] == 1 and d["dropped"] == []
    (road,) = d["roads"]
    assert road["o"] == "w/12" and road["v"] == "residential" and road["k"] == 5
    assert road["name"] == "Fixture Road" and len(road["c"]) == 2
    assert d["counts"]["minor"] == 1 and d["caps"]["street_view_max_deg"] == V.STREET_VIEW_MAX_DEG


def test_only_roads_are_sent(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    d = V.streets(*BOX)
    assert {r["o"] for r in d["roads"]} == {"w/12"}, "the building, the border, the cafe stay in the object layer"


def test_an_area_with_no_roads_says_so(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    d = V.streets(10, 10, 10.1, 10.1)
    assert d["status"] == "no-roads" and d["total"] == 0 and d["roads"] == [] and d["vintage"] == []


def test_the_vintage_is_the_extract_date_and_the_last_applied_diff(osm_lane_dir):
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        c.extract_vintage = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
        c.diff_timestamp = datetime(2026, 11, 3, 21, 0, tzinfo=UTC)
        c.diff_sequence = 4321
    (v,) = V.streets(*BOX)["vintage"]
    assert v == {"alpha3": "ZZZ", "extract_date": "2026-10-01T21:00:00+00:00",
                 "last_diff": "2026-11-03T21:00:00+00:00", "diff_sequence": 4321}


def test_over_the_count_cap_the_lowest_classes_go_first_and_are_named(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _add_roads([("primary", _line(0), "Main"), ("footway", _line(1), None), ("footway", _line(2), None),
                ("service", _line(3), None), ("raceway", _line(4), None)])
    monkeypatch.setattr(V, "POINTS_PER_VIEW", 3)
    d = V.streets(*BOX)
    # primary (1) + minor (the fixture's residential, 1) = 2; service would make 3, path 5.
    assert d["status"] == "streets" and d["total"] == 6
    assert d["drawn"] == 3 and d["dropped"] == ["path", "other"]
    assert {r["v"] for r in d["roads"]} == {"primary", "residential", "service"}


def test_drawn_counts_only_what_is_drawn_and_the_rest_is_accounted_for(osm_lane_dir):
    """A road under a pixel, or with no stored shape, is counted in the view and NOT in "Drawn"."""
    import sqlalchemy as sa

    from src.osm.lane_models import osm_objects_table
    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _add_roads([("primary", _line(0), "Main"),
                ("service", [(0.15, 0.15), (0.15, 0.15000001)], None),   # about a millimetre long
                ("service", _line(2), None)])
    with store.lane_session("osm") as s:   # a stored road whose shape is gone: the R*Tree still holds its box
        s.execute(sa.update(osm_objects_table).where(osm_objects_table.c.osm_id == 900002).values(geom=None))
    d = V.streets(*BOX)
    assert d["status"] == "streets" and d["total"] == 4
    assert d["drawn"] == len(d["roads"]) == 2, "Drawn is what is on the canvas"
    assert d["subpixel"] == 1 and d["no_shape"] == 1
    assert d["drawn"] + d["subpixel"] + d["no_shape"] == d["total"]


def test_a_view_taller_than_twice_the_street_width_is_refused(osm_lane_dir):
    with pytest.raises(V.ViewError):
        V.streets(0, -90, 0.1, 90)


def test_over_the_vertex_cap_whole_classes_go_too(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _add_roads([("motorway", _line(0), None), ("tertiary", _line(1, 40), None)])
    monkeypatch.setattr(V, "VERTICES_PER_VIEW", 10)
    monkeypatch.setattr(V, "SIMPLIFY_PX", 10**6)   # keep every vertex
    d = V.streets(*BOX)
    assert d["status"] == "streets" and d["dropped"] == ["tertiary", "minor"]
    assert [r["v"] for r in d["roads"]] == ["motorway"] and d["vertices"] == 2


def test_when_the_top_class_alone_is_over_a_cap_the_object_layer_draws(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _add_roads([("motorway", _line(i), None) for i in range(4)])
    monkeypatch.setattr(V, "POINTS_PER_VIEW", 3)
    d = V.streets(*BOX)
    assert d["status"] == "too-many" and d["roads"] == []
    assert d["dropped"] == ["motorway", "minor"]
    assert d["fallback"]["status"] == "clusters"


def test_a_view_wider_than_the_street_layer_is_refused(osm_lane_dir):
    with pytest.raises(V.ViewError):
        V.streets(0, 0, V.STREET_VIEW_MAX_DEG * 2, 0.1)


def test_no_lane_is_a_state(osm_lane_dir):
    assert V.streets(*BOX)["status"] == "no-lane"


def test_the_route_serves_streets_and_opens_no_socket(osm_lane_dir, monkeypatch):
    from src.api.main import app

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")

    def refuse(*a, **k):
        raise AssertionError("a street view opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    c = TestClient(app)
    q = {"w": 0.1, "s": 0.1, "e": 0.2, "n": 0.2}
    assert c.get("/api/osm/view", params={**q, "layer": "streets"}).json()["status"] == "streets"
    assert c.get("/api/osm/view", params=q).json()["status"] == "objects", "the default layer is unchanged"
    assert c.get("/api/osm/view", params={**q, "layer": "tiles"}).status_code == 422
    assert c.get("/api/osm/view", params={"w": 0, "s": 0, "e": 1, "n": 1, "layer": "streets"}).status_code == 400


def test_the_client_draws_streets_itself_and_keeps_the_credit():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    layer = function_source(js, "_ooOsmLaneLayer")
    assert 'layer: "streets"' in layer or "layer=streets" in layer
    assert "ensureOnline" not in layer
    # Q821 = b: no tile server, no external host, no WebGL anywhere in the street path.
    for bad in ("tile.openstreetmap", "{z}/{x}/{y}", "webgl", "http://", "https://"):
        assert bad not in layer.lower(), bad
    # The frame budget at the caps: a gesture MOVES the drawn bitmap, and the raster redraw
    # waits for the view to be still (measured: a redraw per wheel event cost 70-115 ms tasks).
    assert "cv.style.transform = `translate(" in layer and "setTimeout(draw, 120)" in layer
    assert 'overflow:hidden' in layer, "a moved bitmap must stay inside the map"
    m = re.search(r"const OO_OSM_STREET_MAX_DEG = ([0-9.]+);", js)
    assert m and float(m.group(1)) == V.STREET_VIEW_MAX_DEG, "client and server agree on the street zoom"
    legend = function_source(js, "_ooOsmLaneLegend")
    vintage = function_source(js, "_ooOsmLaneVintage")   # one helper for every layer since row 259
    # The planner's point (3): the vintage reads as extract date and last applied diff, never "current".
    assert "_ooOsmLaneVintage(d)" in legend
    assert "extract date" in vintage.lower() and "last applied" in vintage.lower()
    assert "current" not in vintage.lower(), "the drawing is never called current"
    assert "current" not in legend.replace("OOI18N.current", "").lower(), "the drawing is never called current"
    # Point (2): the OSM credit is printed by ooMap beside the lane's legend, whatever the layer.
    oomap = function_source(js, "ooMap")
    assert "openstreetmap.org/copyright" in oomap and "ODbL 1.0" in oomap


STRINGS = [
    V.STREETS_METHOD,
    "No roads ingested for this area.",
    "OpenStreetMap streets in view: {n}. Drawn: {d}.",
    "Left out to stay within the caps: {classes}.",
    "Too many roads for one view, even of the most important class: drawn as clusters.",
    "Extract date {a}: {d}.",
    "Last applied diff {a}: {d}.",
    "No daily diff applied since the extract.", "not stated in the extract",
    "Too small to see at this zoom: {n}.", "With no stored shape: {n}.",
    "motorways", "trunk roads", "primary roads", "secondary roads", "tertiary roads",
    "minor streets", "service roads", "paths", "other roads",
]


def test_every_street_string_ships_in_twelve_languages():
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in STRINGS:
            assert s in loc, (path.name, s)


def test_the_drawing_runs_as_real_code():
    """tests/osm_streets_node_test.js: one path per class, labels placed and capped."""
    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_streets_node_test.js")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "3 passed" in proc.stdout
