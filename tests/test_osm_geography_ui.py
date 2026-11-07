"""The geography axis on the page (v0.6.0 B3c, S06-01 S4): wiring, language, and the renderers in node.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The renderers are driven in node (``tests/osm_geography_node_test.js``); here the wiring around them and the strings they and the
server say are pinned.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


def test_the_renderers_behave():
    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_geography_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_panel_is_in_the_world_map_tab_after_the_profile_and_hidden_until_read():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.partition('id="tab-timemap"')[2].partition('<div class="tab-page"')[0]
    assert '<section class="panel" id="osm-geography" hidden>' in tab and 'id="osm-geography-body"' in tab
    assert tab.index('id="osm-profile"') < tab.index('id="osm-geography"')
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmGeography")
    assert "sec.hidden = true" in load and "++_osmGeogSeq" in load
    assert "ensureOnline" not in load + function_source(js, "_osmGeogDraw"), "reading a local table asked for the network consent"
    assert "await loadOsmGeography" not in js, "the completeness figures must not wait on the map"


def test_the_count_poll_repaints_from_what_it_holds_and_an_empty_lane_clears_the_panel():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    load = function_source(js, "loadOsmCompleteness")
    assert "if (!(opts && opts.poll)) loadOsmGeography(done); else _osmGeogRepaint(done)" in load
    assert "loadOsmGeography([])" in load


def test_the_map_is_the_one_component_and_the_only_route_is_local():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    body = "".join(function_source(js, n) for n in ("loadOsmGeography", "_osmGeogFigures", "_osmGeogDraw", "_renderOsmGeography"))
    assert "fetch(" not in body and "http" not in body.replace("https://", "")
    assert "await ooMap(host, Object.assign({ values }, common))" in body and "await ooMap(host, Object.assign({ regionValues: values }, common))" in body
    assert '"/api/osm/geography"' in function_source(js, "loadOsmGeography")
    for forbidden in ("<svg", "viewBox", "project(", "d3.", "L.map("):
        assert forbidden not in body, f"the panel draws its own map ({forbidden}); the one component is ooMap"


def test_the_page_offers_exactly_the_measures_the_server_counts_and_regions_lack_only_the_change_window():
    from src.osm import geography as GEO

    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    measures = re.search(r"const OSM_GEOG_MEASURES = \[(.*?)\];", js, re.S)
    assert measures and re.findall(r'\["(\w+)"', measures.group(1)) == list(GEO.MEASURES)
    assert GEO.REGION_MEASURES == tuple(m for m in GEO.MEASURES if m != "changed")
    figures = function_source(js, "_osmGeogFigures")
    assert 'm === "changed"' in figures, "a change was attributed to a region"


def test_every_view_string_and_every_server_string_ships_in_twelve_languages():
    from src.osm import geography as GEO

    strings = [
        GEO.METHOD, GEO.CAVEAT,
        "OpenStreetMap places by country and region", "Map by", "Countries", "Regions of {country}", "Measure", "Number of places",
        "Share of the area's places", "Places with metadata", "Places carrying a brand tag", "Places carrying a check_date",
        "Places last edited within a year of the vintage", "Places with a tag changed in the window observed here", "{count} of {n} places ({share})",
        "A change row records the country a place was in, not its region, so this measure is drawn by country only.",
        "Counted before this measure existed: count the regions again to add it.", "Not drawn, because their cut did not finish: {names}.",
        "The colour is the number in the ranked table beside the map. Nothing is capped and nothing is scored.",
        "No places were counted here, so there is no share.",
    ]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)
            assert sorted(re.findall(r"\{\w+\}", s)) == sorted(re.findall(r"\{\w+\}", loc[s])), (path.name, "placeholders differ", s)


def test_the_region_sentences_are_shared_not_copied():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    assert js.count('"Per region: not counted yet. Counting reads every place once, on this machine."') == 1, "the admin-1 sentences were copied, not shared"
    assert "OSM_ADMIN1_SAY[a.status]" in function_source(js, "_osmCompAdmin1") and "OSM_ADMIN1_SAY[f.status]" in function_source(js, "_osmGeogDraw")
