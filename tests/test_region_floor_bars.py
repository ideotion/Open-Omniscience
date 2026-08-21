"""
Guard: the regional-balance surface shows a chart BESIDE its table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

GUI audit 2026-07-28, finding V-2: of 941 top-level functions in app.js, 87
call a renderer and 35 emit a table and never a chart. ``renderCoverage
Regions`` was one of them -- yet the question it answers ("which regions sit
BELOW their floor?") is a length comparison against a target, which the
project's own committed chart-decision framework puts squarely in bar
territory.

The bars are added BESIDE the table, never replacing it (invariant #8 + the
Desk lesson): the table stays the precise, sortable, screen-readable record;
the chart is the glance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from tests.js_source_helper import app_js, function_body

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"

_NEW_STRINGS = (
    "floor",
    "Sources per region against each region's floor.",
    "Bar = sources collected; the vertical mark is that region's floor. "
    "Counts only, no score.",
)


def _body(fn_name: str) -> str:
    """One function's own body, brace-matched (tests.js_source_helper)."""
    return function_body(app_js(), fn_name)


def test_the_bars_are_added_beside_the_table_not_instead_of_it():
    body = _body("renderCoverageRegions")
    assert "_regionFloorBars(" in body, "the chart is not wired into the surface"
    assert "<table>" in body and "<th>Region</th>" in body, (
        "the table disappeared -- the chart must be ADDED beside it, never "
        "replace it (invariant #8: never silently lose a tool)"
    )


def test_bars_carry_no_score_and_state_their_method():
    body = _body("_regionFloorBars")
    assert "no score" in body, "the counts-only caveat must be visible"
    assert "r.sources" in body, "bars must plot the REAL source count"
    for banned in ("score", "rating", "rank"):
        assert f"{banned}:" not in body, f"a {banned!r} field leaked into the chart"


def test_a_missing_floor_is_omitted_never_fabricated():
    """A region with no configured floor must plot without a marker."""
    body = _body("_regionFloorBars")
    assert "r.min_sources != null" in body, (
        "the floor marker must be conditional on a floor actually existing -- "
        "drawing one anyway would fabricate a target"
    )


def test_the_scale_keeps_an_unmet_floor_on_canvas():
    """Scaling to max(value, floor), not max(value).

    A floor far above every bar must stay visible; scaling to the bars alone
    would push it off the right edge, where a badly-missed target would read
    as "no floor configured" -- the opposite of the truth.
    """
    body = _body("_regionFloorBars")
    assert "Math.max(r.sources || 0, r.min_sources || 0)" in body, (
        "the scale must span value AND floor"
    )


def test_bars_never_truncate_regions():
    """Anti-capping: every region with data is plotted."""
    body = _body("_regionFloorBars")
    assert ".slice(" not in body, "the chart truncates regions"
    assert "rows.map(" in body, "every filtered region must be rendered"


def test_new_strings_are_keyed_in_every_locale():
    codes = sorted(p.stem for p in _LOCALES.glob("*.json"))
    for code in codes:
        data = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        missing = [s for s in _NEW_STRINGS if s not in data]
        assert not missing, f"{code}: unkeyed chart strings {missing}"
        if code != "en":
            echoed = [s for s in _NEW_STRINGS if data[s] == s]
            assert not echoed, f"{code}: English echoed back for {echoed}"


def test_the_renderer_prefers_the_shared_ooviz_scale():
    """V-1: ooviz primitives were built and tested with zero call sites.

    This is one of the first activations; it must use the shared scale (with
    a local fallback) rather than growing a private one.
    """
    body = _body("_regionFloorBars")
    assert "ooViz.linearScale" in body, "use the shared primitive"
    assert "window.ooViz &&" in body, (
        "guard the shared primitive so the surface still renders if ooviz.js "
        "fails to load"
    )


def test_single_region_renders_nothing():
    """One bar compares nothing -- rendering it would imply a comparison."""
    body = _body("_regionFloorBars")
    assert re.search(r"rows\.length < 2", body), (
        "a single region must not render a comparison chart"
    )
