"""The ONE projection seam, and the proof that every map surface shares it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling Q801 (2026-09-15): Equal Earth on all five map surfaces through one
``project(lon, lat)``, no toggle, named in the legend.

THIS FILE GUARDS THE WIRING; the BEHAVIOUR -- that the projection is equal-area, that
the Newton inverse inverts it, that it ignores the viewBox -- is executed in
``tests/map_projection_node_test.js`` and run from here, because those are properties a
source grep cannot tell apart from their opposites.

The guard that matters most here is the NEGATIVE one: that no residual plate-carree
arithmetic survives anywhere outside the seam. A second projection would not crash or
fail a test; it would quietly draw one layer in the wrong place, which is exactly the
class of defect a reader of the diff cannot see.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_source,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

# Every module that could plausibly place a coordinate on a map surface.
_MAP_MODULES = (
    "app-map.js", "app-boot.js", "app-gov-law.js", "app-insights.js", "app-library.js",
    "app-markets.js", "app-shell.js", "app-sources.js", "app-corpus.js",
    "app-observatory.js", "osmpbf.js",
)


def _map_js() -> str:
    return read_static("app-map.js")


def _is_definition(line_no: int) -> bool:
    """True when that 1-indexed line of app-map.js declares ooMap rather than calls it."""
    line = _map_js().split("\n")[line_no - 1]
    return "function ooMap(" in line


def test_the_seam_exists_and_is_the_only_projection():
    js = _map_js()
    assert "function project(lon, lat)" in js, "the one projection seam must be present"
    assert "function unproject(px, py)" in js, "the inverse the pointer readouts need"
    assert js.count("function project(") == 1, "exactly one seam, never two"


def test_no_residual_plate_carree_arithmetic_survives_anywhere():
    """The retired projection was `lon2x`/`lat2y`. Neither the names nor the arithmetic
    may survive in ANY static module -- a surviving copy draws a second projection that
    nothing would report, because both look like a map."""
    for name in _MAP_MODULES:
        path = _STATIC / name
        if not path.exists():
            continue
        src = strip_comments(path.read_text(encoding="utf-8"))
        assert "lon2x" not in src, f"{name}: the retired lon2x survived"
        assert "lat2y" not in src, f"{name}: the retired lat2y survived"
        # The arithmetic itself, under any name: (lon + 180) / 360 and (90 - lat) / 180.
        assert not re.search(r"\+\s*180\s*\)\s*/\s*360", src), f"{name}: plate-carree x arithmetic"
        assert not re.search(r"90\s*-\s*[A-Za-z_.$()\[\]]+\s*\)\s*/\s*180", src), (
            f"{name}: plate-carree y arithmetic"
        )


def test_every_ooMap_surface_shares_the_one_seam():
    """The five surfaces are the five `ooMap(host, ...)` call sites. They share the seam
    by CONSTRUCTION -- there is one `ooMap`, and it projects through `project()` -- so
    what is proved here is that the call sites still exist and that none of them has
    grown a projection of its own."""
    sites = []
    for name in _MAP_MODULES:
        path = _STATIC / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\booMap\(\s*\w", src):
            sites.append((name, src[: m.start()].count("\n") + 1))
    # `async function ooMap(` matches the regex too, so the definition is excluded by
    # name rather than by position -- a positional filter would go quietly wrong the day
    # the definition moves.
    defn = [s for s in sites if s[0] == "app-map.js" and _is_definition(s[1])]
    callers = [s for s in sites if s not in defn]
    assert len(callers) >= 5, f"expected at least five ooMap call sites, found {callers}"
    modules = {s[0] for s in callers}
    assert {"app-map.js", "app-gov-law.js", "app-insights.js", "app-sources.js"} <= modules, (
        f"a known map surface stopped calling ooMap: {sorted(modules)}"
    )
    body = strip_comments(function_source(_map_js(), "ooMap"))
    assert_present(body, "project(", why="ooMap must place coordinates through the seam")


def test_the_graticule_is_built_once_and_curved():
    """Two surfaces draw a graticule. Invariant #16's rule -- the rules must not be
    re-derived per surface -- applies to geometry as much as to charts, and in Equal
    Earth a straight meridian would be a fabricated shape."""
    js = _map_js()
    assert "function _mapGraticule(" in js
    body = strip_comments(function_source(js, "_mapGraticule"))
    assert_present(body, "polyline", why="meridians curve, so they are polylines")
    assert_present(body, "project(", why="the graticule rides the seam like everything else")
    # Both callers use the shared builder rather than emitting their own lines.
    assert js.count("_mapGraticule(") >= 3, "the builder plus its two callers"


def test_the_box_is_derived_from_the_projection_not_written_down():
    js = strip_comments(_map_js())
    assert "const MAP_H = MAP_W * EE_Y_MAX / EE_X_MAX" in js, (
        "MAP_H must FOLLOW the projection; a written-down 350.44 can drift away from it"
    )
    assert not re.search(r"MAP_W\s*=\s*720\s*,\s*MAP_H\s*=\s*360", js), "the plate-carree box survived"


def test_the_legend_names_the_projection_and_offers_no_toggle():
    """Q801: named in the legend, no toggle. The absence is the load-bearing half."""
    js = _map_js()
    assert_present(js, 't("Equal Earth · equal-area")', why="Q801 names it in the legend")
    stripped = strip_comments(js)
    for needle in ("data-oomap-projection", "setProjection", "projectionToggle"):
        assert_absent(stripped, needle, why="Q801 rules out a projection toggle")


def test_the_node_suite_executes_the_real_seam():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "map_projection_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "14 passed" in proc.stdout, proc.stdout
    assert "0 failed" in proc.stdout, proc.stdout
