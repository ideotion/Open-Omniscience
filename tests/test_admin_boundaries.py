"""The OSM-derived admin-0 / admin-1 boundary artifacts (0.5 row E, brief S05-05 S1 + S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins what the build may never do: key a region silently, overwrite one code with
another, pick a claim, exceed a published vertex cap, or write a border with no date.
The geometry fixture (``tests/fixtures/osm/admin_boundaries.osm.pbf``, from the readable
``admin_boundaries.osm`` beside it) holds one country
with two admin-1 regions (one tagged ISO 3166-2, one untagged), one contested area
with two claims and one claim naming a single party.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from src.maintenance import registry as R
from src.timemap import admin_geo as G
from tests.js_source_helper import function_body, function_source

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "osm" / "admin_boundaries.osm.pbf"
_STATIC = _ROOT / "src" / "static"
_MAP_JS = (_STATIC / "app-map.js").read_text(encoding="utf-8")


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _rec(osm_id, box, **tags):
    return G.BoundaryRecord(osm_id=osm_id, tags=dict(tags), outers=[_box(*box)])


def _records():
    return [
        _rec(1, (0, 40, 10, 50), boundary="administrative", admin_level="2",
             **{"ISO3166-1:alpha2": "FR", "name": "France", "name:ar": "فرنسا"}),
        _rec(2, (1, 41, 4, 44), boundary="administrative", admin_level="4",
             **{"ISO3166-2": "FR-IDF", "name": "Île-de-France", "name:en": "Ile-de-France"}),
        _rec(3, (5, 41, 9, 44), boundary="administrative", admin_level="4", name="Région sans code"),
        _rec(4, (11, 41, 13, 43), boundary="disputed", claimed_by="FR;DE", name="Zone"),
        _rec(5, (14, 41, 15, 42), boundary="claim", claimed_by="FR", name="Lone"),
        _rec(6, (2, 42, 3, 43), boundary="administrative", admin_level="8", name="commune"),
    ]


def _build(records=None, **kw):
    return G.build_artifacts(records or _records(), vintage="2026-09-01", source="fixture.osm", **kw)


# ------------------------------------------------------------------ keys (Q314)


def test_admin0_is_keyed_alpha3_from_its_own_alpha2_tag():
    a0, _ = _build()
    assert list(a0["countries"]) == ["FRA"]
    fra = a0["countries"]["FRA"]
    assert fra["a2"] == "fr" and fra["osm"] == 1 and fra["names"] == {"ar": "فرنسا"}


def test_admin1_keyed_iso3166_2_with_relation_id_fallback_and_both_counted():
    _, a1 = _build()
    regs = a1["regions"]
    assert set(regs) == {"FR-IDF", "r3"}
    assert regs["FR-IDF"]["key"] == "iso3166-2" and regs["FR-IDF"]["placed_by"] == "iso3166-2-prefix"
    assert regs["r3"]["key"] == "osm-relation"
    # the untagged region is PLACED by a point inside it, never left countryless silently
    assert regs["r3"]["country"] == "FRA" and regs["r3"]["placed_by"] == "inside-admin0"
    c = a1["counts"]
    assert (c["tagged"], c["fallback"], c["unplaced"]) == (1, 1, 0)


def test_a_duplicate_code_never_overwrites_the_first_region():
    recs = _records() + [_rec(7, (6, 45, 8, 47), boundary="administrative", admin_level="4",
                              **{"ISO3166-2": "FR-IDF", "name": "Impostor"})]
    _, a1 = _build(recs)
    assert a1["regions"]["FR-IDF"]["osm"] == 2
    assert a1["regions"]["r7"]["key"] == "osm-relation"
    assert a1["counts"]["duplicate_codes"] == 1


def test_a_malformed_code_falls_back_rather_than_being_trusted():
    key, how = G.admin1_key({"ISO3166-2": "France-Nord"}, 99)
    assert (key, how) == ("r99", "osm-relation")


def test_an_unkeyed_country_is_counted_and_named_never_dropped_silently():
    recs = _records() + [_rec(8, (20, 40, 22, 42), boundary="administrative", admin_level="2", name="Nowhere")]
    a0, _ = _build(recs)
    assert a0["counts"]["unkeyed"] == 1 and a0["unkeyed"][0]["osm"] == 8


def test_an_unplaceable_region_is_counted():
    recs = _records() + [_rec(9, (30, 10, 31, 11), boundary="administrative", admin_level="4", name="Adrift")]
    _, a1 = _build(recs)
    assert a1["regions"]["r9"]["country"] is None
    assert a1["counts"]["unplaced"] == 1


# ------------------------------------------------------------ contested (Q826)


def test_contested_area_carries_both_claims_and_a_single_claim_is_marked_incomplete():
    a0, _ = _build()
    by_id = {c["id"]: c for c in a0["contested"]}
    zone = by_id["r4"]
    assert [p["a3"] for p in zone["claims"]] == ["FRA", "DEU"] and zone["complete"] is True
    lone = by_id["r5"]
    assert len(lone["claims"]) == 1 and lone["complete"] is False
    assert a0["counts"]["contested_incomplete"] == 1


def test_disputed_by_is_read_and_an_unknown_code_is_kept():
    who = G.parties({"claimed_by": "IN", "disputed_by": "PK;CN;ZZ"})
    assert [p["code"] for p in who] == ["IN", "PK", "CN", "ZZ"]
    assert who[-1]["a3"] is None          # still a party the data names


# ------------------------------------------------------ vertex caps (Q822) + holes


def _circle(n, cx=0.0, cy=0.0, r=5.0):
    return [[cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)] for k in range(n)]


def test_no_polygon_exceeds_its_published_cap():
    islands = [_circle(40, 30 + k, 30, 0.3) for k in range(60)]
    big = G.BoundaryRecord(osm_id=50, tags={"boundary": "administrative", "admin_level": "4", "ISO3166-2": "FR-ARA"},
                           outers=[_circle(5000, 5, 45, 3)] + islands, inners=[_circle(900, 5, 45, 1)])
    _, a1 = _build(_records() + [big], admin1_cap=G.ADMIN1_VERTEX_CAP)
    for key, r in a1["regions"].items():
        assert sum(len(x) for x in r["rings"]) <= G.ADMIN1_VERTEX_CAP, key
    assert a1["regions"]["FR-ARA"]["rings"], "the largest ring is never dropped"
    assert a1["counts"]["simplified"] >= 1


def test_holes_are_kept_when_they_fit():
    rec = G.BoundaryRecord(osm_id=60, tags={"boundary": "administrative", "admin_level": "2",
                                            "ISO3166-1:alpha2": "IT"},
                           outers=[_box(0, 0, 10, 10)], inners=[_box(4, 4, 5, 5)])
    a0, _ = _build([rec])
    assert len(a0["countries"]["ITA"]["rings"]) == 2
    assert not G.point_in_rings((4.5, 4.5), a0["countries"]["ITA"]["rings"])   # the enclave is outside
    assert G.point_in_rings((2, 2), a0["countries"]["ITA"]["rings"])


# ---------------------------------------------------------------- vintage + shape


@pytest.mark.parametrize("bad", [None, "", "2026-09", "2026-13-01", "yesterday"])
def test_no_vintage_no_artifact(bad):
    with pytest.raises(ValueError):
        G.build_artifacts(_records(), vintage=bad, source="x")


def test_the_build_is_deterministic_and_states_its_vintage_and_attribution():
    a, b = _build(), _build(list(reversed(_records())))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    for doc in a:
        assert doc["vintage"] == "2026-09-01" and "OpenStreetMap" in doc["attribution"]
        assert doc["caps"]["admin0"] == G.ADMIN0_VERTEX_CAP


# --------------------------------------------------- the reader (pyosmium, [geo])


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bab", _ROOT / "scripts" / "build_admin_boundaries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("reader", ["python", "pyosmium"])
def test_the_script_reads_the_fixture_through_the_lanes_one_reader(reader):
    """ONE reader for the OSM lane: the build goes through ``src.osm.reader.open_extract``
    and the lane's own ``stitch``, and both backends must produce the same artifacts."""
    if reader == "pyosmium":
        pytest.importorskip("osmium")
    mod = _script()
    assert mod.header_vintage(str(_FIXTURE)) == "2026-09-01"     # read from the file's own header
    recs, unclosed = mod.read_boundaries(str(_FIXTURE), reader=reader)
    assert unclosed == 0
    assert sorted(r.osm_id for r in recs) == [1001, 1002, 1003, 1004, 1005]   # admin_level=8 skipped
    a0, a1 = G.build_artifacts(recs, vintage="2026-09-01", source=_FIXTURE.name)
    assert set(a1["regions"]) == {"FR-IDF", "r1003"}
    assert {c["id"] for c in a0["contested"]} == {"r1004", "r1005"}
    assert a1["regions"]["FR-IDF"]["rings"] == [[[1.0, 41.0], [4.0, 41.0], [4.0, 44.0], [1.0, 44.0]]]


def test_the_build_script_opens_no_osm_reader_of_its_own():
    src = (_ROOT / "scripts" / "build_admin_boundaries.py").read_text(encoding="utf-8")
    assert "from src.osm.reader import open_extract" in src and "from src.osm.geometry import stitch" in src
    assert "import osmium" not in src and "SimpleHandler" not in src


# ------------------------------------------------------- registry + freshness


def test_registry_entries_exist_and_absent_artifacts_read_not_built():
    ids = {a["id"]: a for a in R.load_registry()}
    for rid, fname in (("osm-admin0-boundaries", "osm_admin0.json"), ("osm-admin1-boundaries", "osm_admin1.json")):
        pin = ids[rid]["pin"]
        assert pin["path"] == f"src/static/{fname}" and pin["vintage_key"] == "vintage"
        assert "ODbL" in ids[rid]["license"]
    rows = {r["id"]: r for r in R.evaluate()}
    for rid, fname in (("osm-admin0-boundaries", "osm_admin0.json"), ("osm-admin1-boundaries", "osm_admin1.json")):
        if not (_STATIC / fname).exists():
            assert rows[rid]["status"] == "info" and "not built yet" in rows[rid]["detail"]
        else:
            assert rows[rid]["status"] in ("ok", "info")


def test_a_built_artifact_answers_to_its_window(tmp_path, monkeypatch):
    art = tmp_path / "a.json"
    art.write_text(json.dumps({"vintage": "2020-01-01"}), encoding="utf-8")
    entry = {"id": "t", "pin": {"path": "a.json", "sha256": "", "vintage_key": "vintage", "optional": True},
             "freshness": {"max_age_months": 24}, "refresh": "rebuild"}
    monkeypatch.setattr(R, "_ROOT", tmp_path)
    monkeypatch.setattr(R, "load_registry", lambda path=None: [entry])
    assert R.evaluate(today=date(2026, 9, 29))[0]["status"] == "stale"
    art.write_text(json.dumps({"vintage": "2026-06-01"}), encoding="utf-8")
    assert R.evaluate(today=date(2026, 9, 29))[0]["status"] == "info"
    art.unlink()
    assert R.evaluate(today=date(2026, 9, 29))[0]["status"] == "info"
    entry["pin"]["optional"] = False
    assert R.evaluate(today=date(2026, 9, 29))[0]["status"] == "stale"


@pytest.mark.parametrize("fname,feature,cap", [
    ("osm_admin0.json", "countries", G.ADMIN0_VERTEX_CAP),
    ("osm_admin1.json", "regions", G.ADMIN1_VERTEX_CAP),
])
def test_a_shipped_artifact_keeps_its_published_caps(fname, feature, cap):
    p = _STATIC / fname
    if not p.exists():
        pytest.skip(f"{fname} not built yet (operator step)")
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert G.valid_vintage(doc["vintage"])
    limit = doc["caps"][feature.replace("countries", "admin0").replace("regions", "admin1")]
    assert limit <= cap
    for key, f in doc[feature].items():
        assert sum(len(r) for r in f["rings"]) <= limit, key


# --------------------------------------------------------- the maps (S2 wiring)


def test_every_ooMap_surface_loads_the_osm_artifacts_with_natural_earth_as_fallback():
    assert '"osm_admin0.json"' in _MAP_JS and '"osm_admin1.json"' in _MAP_JS
    assert "/static/world_countries.json" in _MAP_JS          # the fallback stays
    body = function_body(_MAP_JS, "ooMap")
    assert body.index("await _ooMapOsmAdminLoad()") < body.index('host.innerHTML = `<div class="oomap-wrap"')


def test_the_legend_states_which_source_drew_the_borders_and_its_vintage():
    assert "data-oomap-borders" in _MAP_JS
    assert '"Borders: OpenStreetMap, as of {date}"' in _MAP_JS
    assert '"Borders: Natural Earth 50m"' in _MAP_JS
    assert "© OpenStreetMap contributors (ODbL 1.0)" in _MAP_JS


def test_regions_draw_between_the_fills_and_the_contested_hatch_and_keep_the_country_click():
    assert "${paths}${_adm1.markup}${_disp.markup}" in _MAP_JS
    layer = function_source(_MAP_JS, "_ooAdmin1Layer")
    assert "data-iso=" in layer and "data-oomap-region" in layer
    assert 'title="${esc(ti)}"' in layer                       # the #oo-tip carrier (#17)


def test_the_region_display_cap_is_published_and_degrades_by_striding():
    m = re.search(r"const OOMAP_ADMIN1_VERTEX_CAP = (\d+);", _MAP_JS)
    assert m and int(m.group(1)) > 0
    assert "strided" in _MAP_JS


def test_new_map_strings_ship_in_all_twelve_locales():
    keys = ["Borders: OpenStreetMap, as of {date}", "Borders: Natural Earth 50m",
            "{n} regions: {tagged} keyed by their ISO 3166-2 code, {fallback} by their OpenStreetMap "
            "relation id because OpenStreetMap carries no code for them."]
    for loc in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k), (loc.name, k)
            assert "{date}" in d[k] if "{date}" in k else True


# ------------------------------------------- the ranked table and region choropleth (S3, Q816)


def test_ranked_table_and_region_choropleth_node_suite():
    """The table is never capped and an unmeasured region is a gap: run as real code in node."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oomap_ranked_table_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_borders_follow_the_view_node_suite():
    """Zooming sharpens the borders up to the file's own detail, and only what is in sight
    counts against the vertex budget (browser walk 2026-09-30): run as real code in node."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oomap_lod_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_country_outlines_are_budgeted_too_and_the_view_redraws_them():
    """The admin-0 outlines had no budget at all (1.3M vertices at a realistic size) and every
    coordinate was rounded to ~5 km whatever the zoom."""
    body = function_body(_MAP_JS, "ooMap")
    assert "_ooStrideRings(c.rings, a0Step)" in body
    assert "_ooLodAttach(host, svg)" in function_body(_MAP_JS, "_wireOoMap")
    assert "lod.view(vb)" in function_body(_MAP_JS, "_wireOoMap")


def test_the_map_reads_the_small_world_file_first_and_a_country_s_detail_on_demand():
    """Reading both whole files took about 20 s and the first paint 26 to 36 s at full-build size
    (walked 2026-09-30); the split gets the first paint to about 2 s and the detail comes as the
    view narrows. A build without the split is still read whole."""
    load = function_body(_MAP_JS, "_ooMapOsmAdminLoad")
    assert '"osm_borders/admin0.world.json", "osm_admin0.json"' in load
    assert '"osm_borders/admin1.world.json", "osm_admin1.json"' in load
    assert "(await get(world)) || get(whole)" in load, "the whole file is the fallback, per layer"
    loader = function_body(_MAP_JS, "_ooLodDetailLoader")
    assert "template !== OOMAP_DETAIL_TEMPLATE" in loader, "only the one path the split writes is fetched"
    assert 'const OOMAP_DETAIL_TEMPLATE = "osm_borders/detail/{a3}.json";' in _MAP_JS
    assert "doc.vintage === vintage" in loader, "a detail file of another build is refused"
    assert "admin0.vintage !== admin1.vintage" in load, "two layers of different builds are never mixed"
    assert "^[A-Z]{3}$" in loader, "only three capitals ever name a file"
    assert "navigator.deviceMemory" in loader, "the detail cache is sized from the machine"


def test_the_legend_owns_its_hover_so_the_translator_cannot_put_the_old_one_back():
    """i18n.js caches the FIRST title an element shows and restores it on later passes, so a
    hover rewritten as the view changes was put back to its first value (measured: the
    "drawn thinner than the file" sentence stayed after every outline was at full detail).
    An element that renders itself through t() opts out (data-i18n-dyn); maps repaint on a switch."""
    assert 'data-oomap-borders data-i18n-dyn title=' in _MAP_JS


def test_every_map_zooms_as_far_as_the_lane_does_because_a_deep_zoom_is_now_cheap():
    """The tightest zoom was 1,600 km wide without the lane, where a 0.1 km border is a fraction of a
    pixel. The redraw draws only what is in sight, within the vertex budget, so a deep zoom
    costs no more than a wide one (measured: no long task while panning at the deepest zoom)."""
    assert "const minW = W * OO_OSM_LANE_MIN_ZOOM;" in _MAP_JS
    assert "W * 0.04" not in _MAP_JS


def test_every_choropleth_renders_the_ranked_table_beside_it():
    body = function_body(_MAP_JS, "ooMap")
    assert "const rankHtml = _ooRankedTable(rankRows, rankGap, opts);" in body
    assert "${rankHtml}" in body
    # Rows come from the caller, the regions or the countries -- never a sliced list.
    table = function_source(_MAP_JS, "_ooRankedTable")
    assert ".slice(0," not in table and "slice(0, " not in table
    # The World map's continent view lists each continent once.
    world = function_body(_MAP_JS, "_renderOoMapDim")
    assert "tableRows" in world and "contAgg[c].value" in world


def test_region_mode_scales_by_the_regions_and_leaves_countries_unvalued():
    body = function_body(_MAP_JS, "ooMap")
    assert "Object.values(regionVals || values)" in body
    assert "v = regionVals ? undefined : values[code]" in body
    assert "regionVals, fillFor, vlabel)" in body
    # The Regions toggle is not offered where the regions ARE the data.
    assert "hasAdmin1 && !regionVals ?" in body
    assert '"This measure is by region, but the region boundaries are not built on this install yet: ' in body


def test_s3_strings_ship_in_all_twelve_locales():
    keys = ["1 area with no data: hatched on the map, never counted as zero.",
            "{n} areas with no data: hatched on the map, never counted as zero.",
            "Ranked table · 1 area with data", "Ranked table · {n} areas with data",
            "The full data behind the map: every area with a value, ranked, none left out. "
            "The colours are a picture of this table.",
            "This measure is by region, but the region boundaries are not built on this install yet: "
            "the table below holds every value.",
            "Rank", "Area", "Value", "no data"]
    for loc in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k), (loc.name, k)
            assert ("{n}" in d[k]) == ("{n}" in k), (loc.name, k)


# ------------------------------------------------ OSM's convention (row L, Q803)


def test_each_contested_area_records_which_osm_borders_hold_it():
    recs = [
        _rec(1, (0, 40, 10, 50), boundary="administrative", admin_level="2", **{"ISO3166-1:alpha2": "FR"}),
        _rec(2, (5, 45, 15, 55), boundary="administrative", admin_level="2", **{"ISO3166-1:alpha2": "DE"}),
        _rec(3, (1, 41, 2, 42), boundary="disputed", claimed_by="FR;DE"),
        _rec(4, (6, 46, 7, 47), boundary="disputed", claimed_by="FR;DE"),
        _rec(5, (20, 20, 21, 21), boundary="claim", claimed_by="FR"),
    ]
    admin0, _ = G.build_artifacts(recs, vintage="2026-09-01", source="t")
    held = {c["id"]: [h["a3"] for h in c["held_by"]] for c in admin0["contested"]}
    assert held == {"r3": ["FRA"], "r4": ["DEU", "FRA"], "r5": []}
    # None and several are KEPT as they are -- never narrowed to one here or on the map.
    assert admin0["counts"]["contested_held"] == {"by_one": 1, "by_none": 1, "by_several": 1}
    assert "held_by" in admin0["method"]


def test_osm_convention_node_suite():
    """The default opens on OSM's convention only with the file; nothing is picked."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oomap_osm_convention_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_row_l_strings_ship_in_all_twelve_locales():
    keys = ["OpenStreetMap's convention, as of {date}",
            "inside several countries' borders in OpenStreetMap, attributed to none",
            "inside no country's border in OpenStreetMap, attributed to none",
            "OpenStreetMap names only one party", "no party named",
            "Natural Earth's layer lists {n} disputed areas, drawn under the other worldviews."]
    for loc in sorted((_STATIC / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k), (loc.name, k)
            for ph in ("{date}", "{n}"):
                assert (ph in d[k]) == (ph in k), (loc.name, k)
