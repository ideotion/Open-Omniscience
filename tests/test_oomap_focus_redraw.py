"""The ooMap focus slider redraws the signals, not the world.

The docket's REMAINING note read "full SVG rebuild on slide -- could update only the
signals layer". The measurement behind it: `focusT` feeds the signal markers and their
year label and NOTHING else, yet every animation frame of a drag re-projected and
re-serialised all 175 countries (285 rings, 10,521 coordinate pairs) into fresh path `d`
strings, replaced the host's entire innerHTML and re-attached every listener -- to move a
handful of circles.

This file guards the WIRING. The behaviour -- that the cheap path draws exactly what the
full render would, leaves the other layers alone, refuses rather than half-updating, and
keeps the click-resolution list in step -- is executed in
`tests/oomap_focus_redraw_node_test.js` and run from here, because those are the
properties a source grep cannot tell apart from their opposites.
"""

from __future__ import annotations

import json
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


def _map_js() -> str:
    return read_static("app-map.js")


def test_the_signals_layer_is_its_own_function_and_its_own_svg_group():
    """Both halves are needed: a shared renderer so the two paths cannot draw different
    markers, and an addressable `<g>` so the cheap path has something to replace."""
    js = _map_js()
    assert "function _ooSignalLayer(" in js
    assert "data-oomap-siglayer" in js, "the layer needs a stable hook to swap"
    assert "data-oomap-sigkinds" in js, "the legend chips change with the window"
    assert "data-oomap-focuslabel" in js, "the year label changes with the window"


def test_the_projection_is_module_level_which_is_what_makes_the_cheap_path_safe():
    """`lon2x`/`lat2y` must stay pure module-level constants with zoom on the viewBox. If
    the projection ever depended on the current view, redrawing one layer against a stale
    projection would misplace every marker -- so this is the precondition, not a detail."""
    js = _map_js()
    assert "const lon2x = lon =>" in js and "const lat2y = lat =>" in js
    layer = strip_comments(function_source(js, "_ooSignalLayer"))
    assert_absent(layer, "MAP_VB", why="the layer must not read the live viewBox")
    assert_absent(layer, "getBoundingClientRect", why="no view-dependent measurement")


def test_the_drag_handler_takes_the_cheap_path_and_can_fall_back():
    js = _map_js()
    # The handler is an object property, not a declaration, so slice the option literal.
    start = js.index("onFocus: v => {")
    handler = strip_comments(js[start : js.index("onSignal:", start)])
    assert_present(handler, "_ooMapFocusRedraw(", why="the drag must take the cheap path")
    assert_present(handler, "requestAnimationFrame", why="still coalesced to one per frame")
    assert_present(handler, "_renderOoMapDim()", why="a refusal must fall back to the full render")
    assert "if (!_ooMapFocusRedraw(host, base)) _renderOoMapDim();" in handler, (
        "the fallback must be conditional on the refusal, not unconditional -- an "
        "unconditional full render beside the cheap one is strictly worse than before"
    )


def test_the_cheap_path_refuses_rather_than_half_updating():
    body = strip_comments(function_source(_map_js(), "_ooMapFocusRedraw"))
    assert_present(body, "if (!layer) return false", why="no rendered layer -> refuse")
    assert_present(body, "data-oomap-sig", why="replaced markers need their listeners back")
    assert_present(body, "host._ooSigVisible =", why="the click list must not go stale")
    assert_absent(body, "innerHTML = `<div", why="it must never rebuild the host")
    assert_absent(body, "_renderOoMapDim", why="the cheap path must not call the expensive one")


def test_the_measurement_in_the_comment_matches_the_shipped_geometry():
    """The code comment states a number. A comment may state reasoning, but a number in
    one is a claim, and a claim nobody re-checks is how a stale figure outlives its
    fact -- so the geometry file is counted here."""
    geo = json.loads((_ROOT / "src" / "static" / "world_countries.json").read_text("utf-8"))
    countries = geo["countries"]
    rings = sum(len(v.get("rings", [])) for v in countries.values())
    pairs = sum(len(r) for v in countries.values() for r in v.get("rings", []))
    js = _map_js()
    assert f"{len(countries)} countries" in js, f"the comment's country count is not {len(countries)}"
    assert f"{rings} rings" in js, f"the comment's ring count is not {rings}"
    assert f"{pairs:,} coordinate pairs" in js, f"the comment's pair count is not {pairs:,}"


def test_the_node_suite_executes_the_real_functions():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oomap_focus_redraw_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "12 passed" in proc.stdout, proc.stdout
    assert "0 failed" in proc.stdout, proc.stdout
