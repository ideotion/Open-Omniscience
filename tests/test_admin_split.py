"""The world + per-country detail split of the OSM boundary artifacts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What may not regress (browser walk 2026-09-30: reading both whole files took about 20 s and
the first map paint 26 to 36 s at full-build size, and 97% of what was parsed was discarded):

- the world file draws every country and region, at about the published budget;
- a detail file is the input's OWN rings, never a redrawing, and it exists only where the world
  file simplified something;
- nothing is invented, dropped or left stale: same input, same bytes; a rebuild deletes the
  detail files it no longer produces; a region no country claims stays whole in the world file;
- the budget the split uses IS the budget the map draws (the two constants are held equal).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from src.maintenance import registry as R
from src.timemap import admin_split as S
from tests.js_source_helper import read_static

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"


def _jag(cx: float, cy: float, r: float, n: int) -> list[list[float]]:
    """A closed-open ring of ``n`` vertices with a coast-like wobble (so DP has work to do)."""
    return [[round(cx + (r + 0.05 * math.sin(k * 0.9)) * math.cos(2 * math.pi * k / n), 4),
             round(cy + (r + 0.05 * math.sin(k * 0.9)) * math.sin(2 * math.pi * k / n), 4)] for k in range(n)]


def _docs(n_countries: int = 6, per_country: int = 2000, regions_each: int = 3, per_region: int = 400):
    countries, regions = {}, {}
    a3s = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"][:n_countries]
    for i, a3 in enumerate(a3s):
        cx, cy = -150 + i * 40, (i % 3) * 10
        countries[a3] = {"a2": a3[:2], "name": a3, "names": {}, "osm": i, "rings": [_jag(cx, cy, 8, per_country)]}
        for j in range(regions_each):
            regions[f"{a3[:2]}-{j}"] = {"country": a3, "a2": a3[:2], "placed_by": "iso3166-2-prefix", "name": f"{a3}{j}",
                                        "names": {}, "osm": 100 * i + j, "key": "iso3166-2",
                                        "rings": [_jag(cx + j, cy, 2, per_region)]}
    regions["r999"] = {"country": None, "a2": None, "placed_by": None, "name": "orphan", "names": {}, "osm": 999,
                       "key": "osm-relation", "rings": [_jag(0, 60, 1, 500)]}
    meta = {"schema": 1, "vintage": "2026-09-01", "attribution": "© OpenStreetMap contributors, ODbL 1.0", "source": "t"}
    return ({**meta, "kind": "admin0", "countries": countries, "contested": [{"id": "r1", "rings": [_jag(5, 5, 1, 300)]}]},
            {**meta, "kind": "admin1", "regions": regions})


def _v(feats):
    return sum(len(r) for f in feats.values() for r in f["rings"])


def test_the_world_file_is_the_budget_and_every_feature_is_in_it():
    a0, a1 = _docs()
    res = S.split_artifacts(a0, a1, budget=6000)
    for doc, layer in ((res["admin0"], "countries"), (res["admin1"], "regions")):
        assert set(doc[layer]) == set((a0 if layer == "countries" else a1)[layer]), "no country or region vanishes"
        assert all(f["rings"] and len(f["rings"][0]) >= 3 for f in doc[layer].values())
    # AT the budget or under it, never over: one vertex over and the map strides every outline by 2.
    assert _v(res["admin0"]["countries"]) <= 6000, "a layer totals at most the budget"
    assert _v(res["admin0"]["countries"]) >= 6000 * 0.85, "and not far under it (detail thrown away)"
    assert _v(res["admin1"]["regions"]) < _v(a1["regions"]), "the region layer was simplified too"
    assert _v(res["admin1"]["regions"]) <= 6000, "including the region no country claims, which stays whole"
    assert res["stats"]["admin0"]["full"] == _v(a0["countries"])
    # The contested areas travel whole: few, and each is capped by the build already.
    assert res["admin0"]["contested"] == a0["contested"]


def test_a_detail_file_is_the_inputs_own_rings():
    a0, a1 = _docs()
    res = S.split_artifacts(a0, a1, budget=6000)
    assert res["details"], "something was simplified, so there is detail to fetch"
    for a3, d in res["details"].items():
        assert re.fullmatch(r"[A-Z]{3}", a3)
        assert d["vintage"] == "2026-09-01" and d["a3"] == a3
        if d["country"]:
            assert d["country"]["rings"] == a0["countries"][a3]["rings"], "byte for byte the input"
        for k, r in d["regions"].items():
            assert r["rings"] == a1["regions"][k]["rings"] and a1["regions"][k]["country"] == a3
    # Every simplified feature has its detail; every feature says how big its detail is.
    for a3, c in res["admin0"]["countries"].items():
        assert c["full_vertices"] == len(a0["countries"][a3]["rings"][0])
        if len(c["rings"][0]) < c["full_vertices"]:
            assert res["details"][a3]["country"]["rings"]
    assert res["admin0"]["split"]["detail"] == "osm_borders/detail/{a3}.json"
    assert res["admin0"]["split"]["world_budget"] == 6000


def test_a_layer_that_fits_the_budget_is_not_split():
    a0, a1 = _docs(n_countries=2, per_country=50, regions_each=1, per_region=20)
    res = S.split_artifacts(a0, a1, budget=S.WORLD_VERTEX_BUDGET)
    assert res["details"] == {} and res["admin0"]["split"]["detail"] is None
    assert res["admin0"]["countries"]["AAA"]["rings"] == a0["countries"]["AAA"]["rings"]
    assert res["admin0"]["countries"]["AAA"]["full_vertices"] == 50, "one reader code path: the size is always present"


def test_a_region_no_country_claims_stays_whole_in_the_world_file():
    a0, a1 = _docs()
    res = S.split_artifacts(a0, a1, budget=6000)
    assert res["admin1"]["regions"]["r999"]["rings"] == a1["regions"]["r999"]["rings"]
    assert all("r999" not in d["regions"] for d in res["details"].values())


def test_a_filename_is_only_ever_three_capitals():
    a0, a1 = _docs()
    a0["countries"]["../x"] = {"a2": "xx", "name": "bad", "names": {}, "osm": 7, "rings": [_jag(0, 0, 5, 3000)]}
    res = S.split_artifacts(a0, a1, budget=6000)
    assert "../x" not in res["details"] and all(re.fullmatch(r"[A-Z]{3}", k) for k in res["details"])
    assert res["admin0"]["countries"]["../x"]["rings"] == a0["countries"]["../x"]["rings"], "unnameable: kept whole"


def test_two_files_from_different_dates_are_refused_and_a_tiny_budget_too():
    a0, a1 = _docs()
    with pytest.raises(ValueError, match="different data dates"):
        S.split_artifacts(a0, {**a1, "vintage": "2026-08-01"})
    with pytest.raises(ValueError, match="budget"):
        S.split_artifacts(a0, a1, budget=3)


def test_the_split_is_deterministic_and_does_not_touch_its_input():
    a0, a1 = _docs()
    before = json.dumps([a0, a1], sort_keys=True)
    one = S.split_artifacts(a0, a1, budget=6000)
    two = S.split_artifacts(a0, a1, budget=6000)
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
    assert json.dumps([a0, a1], sort_keys=True) == before


def test_the_script_writes_the_tree_and_a_rebuild_leaves_no_stale_country(tmp_path):
    from scripts.split_admin_boundaries import write_split

    a0, a1 = _docs()
    rep = write_split(a0, a1, tmp_path, budget=6000, precision=2)
    root = tmp_path / "osm_borders"
    assert (root / "admin0.world.json").is_file() and (root / "admin1.world.json").is_file()
    names = {p.stem for p in (root / "detail").glob("*.json")}
    assert names and rep["detail_bytes"] > 0 and rep["world_bytes"] < rep["detail_bytes"] + rep["world_bytes"]
    (root / "detail" / "ZZZ.json").write_text("{}", encoding="utf-8")        # a country of an older build
    write_split(a0, a1, tmp_path, budget=6000, precision=2)
    assert not (root / "detail" / "ZZZ.json").exists(), "a rebuild deletes what it no longer produces"
    doc = json.loads((root / "admin0.world.json").read_text(encoding="utf-8"))
    assert doc["split"]["detail"] and doc["vintage"] == "2026-09-01"
    dry = write_split(a0, a1, tmp_path / "elsewhere", budget=6000, precision=2, dry_run=True)
    assert not (tmp_path / "elsewhere").exists() and dry["detail_files"] == rep["detail_files"]


def test_the_world_budget_is_the_budget_the_map_draws():
    m = re.search(r"const OOMAP_ADMIN1_VERTEX_CAP = ([\d_]+);", read_static("app-map.js"))
    assert m and int(m.group(1).replace("_", "")) == S.WORLD_VERTEX_BUDGET


def test_the_split_files_carry_the_same_vintage_as_the_whole_ones_when_both_exist():
    """A stale split would draw an old border under a new "as of". Vacuous until a build exists."""
    whole = _STATIC / "osm_admin0.json"
    world = _STATIC / S.WORLD_FILES["admin0"]
    if not (whole.is_file() and world.is_file()):
        pytest.skip("borders not built on this checkout")
    assert json.loads(world.read_text(encoding="utf-8"))["vintage"] == json.loads(whole.read_text(encoding="utf-8"))["vintage"]


def test_the_registry_watches_the_split_beside_the_whole_files():
    ids = {e["id"] for e in R.load_registry()}
    assert "osm-borders-split" in ids


def test_a_simplified_feature_carries_the_box_of_its_full_rings_so_a_lost_island_stays_reachable():
    """The world outline can lose an island (the smallest rings go first); the map decides what is in
    sight from this box, so an island the world file dropped is still found by a view over it."""
    a0, a1 = _docs(n_countries=2, per_country=3000)
    far = [[60.0, 60.0], [60.4, 60.0], [60.4, 60.4], [60.0, 60.4]]
    a0["countries"]["AAA"]["rings"].append(far)          # a small far island of the first country
    res = S.split_artifacts(a0, a1, budget=2500)
    c = res["admin0"]["countries"]["AAA"]
    assert len(c["rings"][0]) < 3000, "it was simplified"
    assert c["full_bbox"] == S.bbox(a0["countries"]["AAA"]["rings"]), "the box is the INPUT's, island included"
    assert c["full_bbox"][2] >= 60.4
    for doc, layer, canon in ((res["admin0"], "countries", a0), (res["admin1"], "regions", a1)):
        for k, f in doc[layer].items():
            if "full_bbox" not in f:
                assert f["rings"] == canon[layer][k]["rings"], "no box is written where nothing was simplified"


def test_floors_and_unplaced_features_do_not_push_a_layer_over_the_budget():
    """Each feature is floored at MIN_FEATURE_VERTICES and a region no country claims stays whole, and
    both cost budget the proportional split would otherwise spend twice."""
    a0, a1 = _docs(n_countries=8, per_country=200, regions_each=8, per_region=15)
    for j in range(40):                                            # a crowd of tiny regions the floor binds
        a1["regions"][f"TT-{j}"] = {**a1["regions"]["AA-0"], "country": "AAA", "rings": [_jag(0, -50 + j, 0.2, 14)]}
    a0["countries"]["AAA"]["rings"] = [_jag(0, 0, 8, 9000)]
    budget = 2000
    res = S.split_artifacts(a0, a1, budget=budget)
    assert _v(res["admin1"]["regions"]) <= budget, _v(res["admin1"]["regions"])
    assert _v(res["admin0"]["countries"]) <= budget
    caps = S._caps({"big": 9000, "s1": 14, "s2": 14}, reserved=500, budget=1000)
    assert caps["s1"] == caps["s2"] == S.MIN_FEATURE_VERTICES and caps["big"] <= 1000 - 500


def test_the_detail_template_is_the_one_path_the_map_accepts():
    m = re.search(r'const OOMAP_DETAIL_TEMPLATE = "([^"]+)";', read_static("app-map.js"))
    assert m and m.group(1) == S.DETAIL_TEMPLATE


def test_a_build_that_dies_half_way_leaves_the_previous_files_whole(tmp_path, monkeypatch):
    from scripts import split_admin_boundaries as SB

    a0, a1 = _docs()
    SB.write_split(a0, a1, tmp_path, budget=6000, precision=2)
    root = tmp_path / "osm_borders"
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.json")}
    real = Path.write_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(OSError):
        SB.write_split(a0, a1, tmp_path, budget=6000, precision=2)
    monkeypatch.setattr(Path, "write_text", real)
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.json")}
    assert after == before, "the live directory is replaced in one rename or not at all"
    assert not (tmp_path / ".osm_borders.new").exists() and not (tmp_path / ".osm_borders.old").exists()
    SB.write_split(a0, a1, tmp_path, budget=6000, precision=2)     # and a rerun after the failure works
    assert not (tmp_path / ".osm_borders.new").exists()


def test_skipping_the_split_removes_the_previous_one_it_would_otherwise_outrank(tmp_path):
    from scripts import split_admin_boundaries as SB

    a0, a1 = _docs()
    SB.write_split(a0, a1, tmp_path, budget=6000, precision=2)
    assert SB.remove_split(tmp_path) is True and not (tmp_path / "osm_borders").exists()
    assert SB.remove_split(tmp_path) is False
    body = (_ROOT / "scripts" / "build_admin_boundaries.py").read_text(encoding="utf-8")
    assert "remove_split(out)" in body, "--no-split must not leave a world file that outranks the new whole ones"
