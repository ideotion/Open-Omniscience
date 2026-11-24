"""Every map states the date of its OpenStreetMap data, and draws contested areas contested
(0.6 gate, section 1's exit text; row 259).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gate's claim is about EVERY map, so most of what is pinned here is the reason "every" holds:
  * there is ONE world-map renderer, ``ooMap`` in app-map.js. No other script loads the world
    geometry, the contested areas or the OSM border files, and the files that call ``ooMap`` are
    pinned, so a new map surface is a visible change here;
  * ooMap draws its border-source legend UNCONDITIONALLY (no option turns it off), and the
    contested layer is chosen by the worldview alone, never by a caller's option;
  * the three OSM layers ooMap can draw over the borders each state their data's date: the
    lane's object and cluster views (they drew undated until this row; only the street view
    said its date) and the downloaded-region preview (whose countries replaced Natural Earth's
    while the legend still credited Natural Earth, with no date).
What the legend SAYS for each input is run as real code in tests/map_vintage_r259_node_test.js.
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from src.osm import ingest
from src.osm import view as V
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE
from tests.js_source_helper import function_body, function_source, strip_comments

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
MAP_JS = (STATIC / "app-map.js").read_text(encoding="utf-8")

# The files whose scripts draw a world map, each through ooMap. A new caller is a new map surface:
# add it here only after checking it is drawn through ooMap and inherits the legend.
OOMAP_CALLERS = {"app-gov-law.js", "app-insights.js", "app-living.js", "app-map.js", "app-sources.js"}


def _scripts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(STATIC.rglob("*.js")) if "vendor" not in p.parts}


# --------------------------------------------------------------- one renderer, one legend


def test_the_files_that_draw_a_world_map_are_pinned_and_each_draws_it_through_ooMap():
    callers = {name for name, src in _scripts().items() if re.search(r"(?<![\w.])ooMap\(", src.replace("function ooMap(", ""))}
    assert callers == OOMAP_CALLERS, f"a world map was added or removed: {sorted(callers ^ OOMAP_CALLERS)}"


def test_no_script_but_the_shared_renderer_loads_the_world_geometry_or_the_border_files():
    from src.api.geo import BORDER_FILES

    names = ["world_countries.json", "world_disputed.json", *BORDER_FILES, "osm_borders/detail/"]
    for script, src in _scripts().items():
        if script == "app-map.js":
            continue
        code = strip_comments(src)
        for name in names:
            assert name not in code, f"{script} reads {name}: a second map renderer would draw without the dated legend"


def test_ooMap_draws_the_border_source_legend_whatever_the_caller_asks():
    body = function_body(MAP_JS, "ooMap")
    span = '<span class="muted" data-oomap-borders data-i18n-dyn title="${esc(_bsrc.title)}">${esc(_bsrc.label)}</span>'
    assert body.count(span) == 1
    # Not inside a `${cond ? ... : ""}` of its own: the nearest unclosed interpolation before it is
    # the template that holds the whole map, never a caller's option.
    before = body[: body.index(span)]
    line = before[before.rindex("\n") + 1 :]
    assert "?" not in line and "opts." not in line, "the dated legend must never depend on a caller's option"
    assert "const _bsrc = _ooBoundarySource(" in body


def test_the_contested_layer_follows_the_worldview_alone_and_is_drawn_above_the_fills():
    body = function_body(MAP_JS, "ooMap")
    assert "const wv = _ooEffectiveWorldview(_ooMapWorldview, osmConv);" in body
    assert "${paths}${_adm1.markup}${_disp.markup}" in body
    m = re.search(r"const _disp = (.+?);\n", body, re.S)
    assert m and "opts." not in m.group(1), "no caller can switch the contested layer off"


# --------------------------------------------------------------- the OSM lane's views


def test_every_layer_of_the_lane_names_the_date_of_the_data_in_view(osm_lane_dir, monkeypatch):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    one = V.view(0.0, 0.0, 0.3, 0.3)
    assert one["status"] == "objects"
    assert [v["alpha3"] for v in one["vintage"]] == ["ZZZ"]
    # The fixture stamps no replication time: its date is absent, and said so, never today's.
    assert one["vintage"][0]["extract_date"] is None and one["vintage"][0]["last_diff"] is None
    monkeypatch.setattr(V, "POINTS_PER_VIEW", 3)
    live = V.view(0.13, 0.13, 0.17, 0.17)
    wide = V.view(-40, -40, 40, 40)
    assert live["status"] == wide["status"] == "clusters"
    assert [v["alpha3"] for v in live["vintage"]] == [v["alpha3"] for v in wide["vintage"]] == ["ZZZ"]


def test_a_country_whose_border_is_out_of_view_is_not_named(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert V.view(10, 10, 11, 11)["vintage"] == []


def test_a_stamped_extract_dates_the_view(osm_lane_dir, tmp_path):
    g = _osm_lane_helpers.generator()
    stamped = tmp_path / "stamped.osm.pbf"
    stamped.write_bytes(g.build((1_790_000_000, 4242)))
    ingest.ingest_country(stamped, "ZZ", reader="python")
    (v,) = V.view(0.0, 0.0, 0.3, 0.3)["vintage"]
    assert v["extract_date"].startswith("2026-09-21"), v


def test_the_lane_legend_states_the_date_on_every_layer_it_draws():
    legend = function_source(MAP_JS, "_ooOsmLaneLegend")
    assert legend.count("_ooOsmLaneVintage(d)") == 2, "the street view AND the object/cluster views"
    # Row 372(b): the line is drawn through ooLive, so the render returns it and a language switch redraws it.
    assert "return line + (vint ? \" \" + vint : \"\");" in legend
    assert "ooLive(el, () => {" in legend


# --------------------------------------------------------------- the downloaded-region preview


@pytest.fixture()
def geo_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.geo import osm_downloads as mod
    from src.geo.osm_downloads import OsmDownloadManager

    mgr = OsmDownloadManager(base_dir=tmp_path)
    monkeypatch.setattr(mod, "_manager", mgr, raising=False)
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    with TestClient(app) as c:
        yield c, tmp_path


def _code() -> str:
    from src.geo.osm_regions import list_regions

    return next(r.code for r in list_regions() if r.code != "planet")


def _preview_date(geo_client, data: bytes) -> str:
    from src.geo.osm_downloads import osm_filename

    c, tmp_path = geo_client
    code = _code()
    (tmp_path / osm_filename(code)).write_bytes(data)
    r = c.get(f"/api/geo/regions/{code}/preview", params={"max_bytes": 4096})
    assert r.status_code == 200
    return r.headers["X-OO-Region-Extract-Date"]


def test_the_preview_carries_the_extract_date_from_the_file_header(geo_client):
    g = _osm_lane_helpers.generator()
    assert _preview_date(geo_client, g.build((1_790_000_000, 4242))) == "2026-09-21"


def test_an_unstamped_or_unreadable_extract_is_dated_unknown_never_today(geo_client):
    assert _preview_date(geo_client, FIXTURE.read_bytes()) == "unknown"
    assert _preview_date(geo_client, struct.pack(">i", 7) + b"garbage" * 100) == "unknown"


def test_the_preview_overlay_keeps_the_date_and_hands_it_to_the_legend():
    toggle = function_source(MAP_JS, "_ooMapToggleOsm")
    assert 'res.headers.get("X-OO-Region-Extract-Date")' in toggle
    assert "extractDate, points: geo.nodes" in toggle
    body = function_body(MAP_JS, "ooMap")
    assert "{ n: osmUsed, date: opts.osmGeo && opts.osmGeo.extractDate }" in body
    assert "_ooOsmPreviewDated(osm.extractDate)" in body


# --------------------------------------------------------------- the legend, run


def test_the_legend_strings_run_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "map_vintage_r259_node_test.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
