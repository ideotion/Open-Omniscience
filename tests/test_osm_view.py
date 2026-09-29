"""The map's view of the OSM lane under published caps (S05-04 S6, Q822 = a).

The fixture (``scripts/make_osm_fixture.py``) puts Fixture Land's eight drawable objects between
0.1 and 0.2 degrees; two relations have neither a shape nor a point and are counted, not drawn.
"""

from __future__ import annotations

import json
import socket
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
BOX = (0.0, 0.0, 0.3, 0.3)


def test_the_ingest_builds_the_rtree_and_counts_what_it_cannot_draw(osm_lane_dir):
    rep = ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert rep.view_index == {"alpha3": "ZZZ", "rows": 8, "no_box": 2}
    assert V.refresh_view_indexes() == {}, "a fresh index is not rebuilt"


def test_a_view_under_the_cap_sends_every_object_one_by_one(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    d = V.view(*BOX)
    assert d["status"] == "objects" and d["total"] == 8 and d["shapes"] == "shapes"
    by = {f["o"]: f for f in d["objects"]}
    assert by["w/12"]["k"] == "road" and len(by["w/12"]["c"]) == 2
    assert by["w/13"]["c"][0] == by["w/13"]["c"][-1], "a building is a closed ring"
    assert by["n/5"]["p"] == [0.15, 0.15] and "c" not in by["n/5"]
    assert d["caps"]["points_per_view"] == V.POINTS_PER_VIEW


def test_a_view_elsewhere_is_empty_not_an_error(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert V.view(10, 10, 11, 11)["total"] == 0


def test_above_the_cap_every_object_is_counted_in_a_cluster(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    monkeypatch.setattr(V, "POINTS_PER_VIEW", 3)
    # A view narrower than the finest pyramid level clusters live from the R*Tree.
    live = V.view(0.13, 0.13, 0.17, 0.17)
    assert live["status"] == "clusters" and live["level"] is None
    # Six boxes meet this view: the cafe, the village, both border ways, the road, the building.
    assert live["total"] == 6 and sum(c["n"] for c in live["clusters"]) == 6
    assert "objects" not in live, "no object is sent past the cap"
    # A wide view reads the pyramid, and still counts all eight.
    wide = V.view(-40, -40, 40, 40)
    assert wide["status"] == "clusters" and wide["level"] is not None
    assert wide["total"] == 8
    assert all(0.1 <= c["lat"] <= 0.2 and 0.1 <= c["lon"] <= 0.2 for c in wide["clusters"]), (
        "a cluster sits at the mean of what it counts, never at a cell's centre"
    )


def test_the_pyramid_levels_add_up_at_every_level(osm_lane_dir):
    from sqlalchemy import text

    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        sums = dict(s.execute(text("SELECT level, sum(n) FROM osm_view_cells GROUP BY level")).all())
    assert set(sums) == set(V.PYRAMID_LEVELS) and set(sums.values()) == {8}


def test_above_the_vertex_budget_shapes_are_sent_as_points(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    monkeypatch.setattr(V, "VERTICES_PER_VIEW", 3)
    d = V.view(*BOX)
    assert d["shapes"] == "points" and d["vertices"] > 3
    assert all("c" not in f and "p" in f for f in d["objects"])


def test_thinning_keeps_the_ends_and_drops_what_is_under_a_pixel():
    line = [(0.0, 0.0), (0.0, 0.0001), (0.0, 0.0002), (0.0, 1.0)]
    assert V.thin(line, 0.01) == [(0.0, 0.0), (0.0, 1.0)]
    assert V.thin(line, 0.00005) == line


def test_a_re_ingest_is_noticed_and_rebuilt(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert V.view(*BOX)["total"] == 8, "the old ids are gone, the new ones drawn once"


@pytest.mark.parametrize("box", [(1, 0, 0, 1), (0, 1, 1, 0), (float("nan"), 0, 1, 1)])
def test_a_box_that_is_not_ordered_is_refused(box):
    with pytest.raises(V.ViewError):
        V.parse_bbox(*box)


def test_no_lane_is_a_state_not_an_error(osm_lane_dir):
    assert V.view(*BOX)["status"] == "no-lane"


def test_the_route_serves_it_and_opens_no_socket(osm_lane_dir, monkeypatch):
    from src.api.main import app

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")

    def refuse(*a, **k):
        raise AssertionError("a map view opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    c = TestClient(app)
    body = c.get("/api/osm/view", params={"w": 0, "s": 0, "e": 0.3, "n": 0.3}).json()
    assert body["status"] == "objects" and body["total"] == 8
    assert c.get("/api/osm/view", params={"w": 1, "s": 0, "e": 0, "n": 1}).status_code == 400


def test_the_layer_draws_on_a_canvas_and_states_the_caps():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    layer = function_source(js, "_ooOsmLaneLayer")
    assert 'createElement("canvas")' in layer and "/api/osm/view" in layer
    assert "ensureOnline" not in layer, "a local read asked for the network"
    assert "my !== seq" in layer, "a late answer must not paint over a newer view"
    legend = function_source(js, "_ooOsmLaneLegend")
    assert "c.method" in legend and "Read in {read} ms, drawn in {draw} ms on this machine." in legend
    wire = function_source(js, "_wireOoMap")
    assert "lane.view(vb)" in wire and "OO_OSM_LANE_MIN_ZOOM" in wire
    # Q823 = a: the OSM credit and the licence line travel with the layer.
    assert "openstreetmap.org/copyright" in function_source(js, "ooMap") and "ODbL 1.0" in function_source(js, "ooMap")


def test_every_layer_string_ships_in_twelve_languages():
    strings = [V.CAPS_METHOD, V.CLUSTER_EDGE, "OpenStreetMap contributors",
               "OpenStreetMap: reading the view…", "OpenStreetMap: the view could not be read.",
               "OpenStreetMap: no country's map data is ready here yet.",
               "OpenStreetMap, objects in view: {n}. Drawn as clusters: {c}.",
               "OpenStreetMap, objects in view: {n}. Shapes drawn as points.",
               "OpenStreetMap, objects in view: {n}. Drawn one by one.",
               "Read in {read} ms, drawn in {draw} ms on this machine."]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)
