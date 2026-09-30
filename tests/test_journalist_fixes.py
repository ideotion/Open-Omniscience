"""The five fixes from the simulated-journalist walk (2026-09-30): driver and source guards.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour is driven as real code by ``tests/journalist_fixes_node_test.js`` (the
Observatory canvas, the Timescale undo, the commodity overlay, the Home signal value, the
map outline) and by the two suites that already own ``ooChart`` and ``honestTicks``. This
file runs that suite, and pins what a node run cannot see: the wiring in the shell, the CSS,
the allowlist and the twelve locales.

What each fix answers (the walk's own words, ``journalist-review-2026-09-30.md``):

* the map click showed its card below a 365 px table, off-screen, and nothing marked the
  country the reader had clicked;
* the main line charts zoom but nothing on the screen said so, and a 0-4 count axis was
  labelled 0, 1, 3, 4;
* "Timescale" only snapped date bounds and could not be undone, and the commodity overlay
  reset its own drop-down, flipped the chart to Indexed without saying so, and put its
  "no data" line far from the chart;
* the Observatory canvas froze at 320 px after a second theme change, and the Settings
  Theme select did nothing until Save while the swatches beside it applied at once;
* a raw float (0.4090909090909091) sat on a Home card.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, css_rule, function_body, read_static

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

# The keys this change added. One list, so a locale that misses one names it.
_NEW_KEYS = (
    "Scroll to zoom · drag to pan · double-click to reset",
    "Snap range to",
    "Switched to Indexed so the commodity price can share the axis with the counts. "
    "Choose Counts to go back.",
    "{symbol}: no price rows stored yet, so there is nothing to overlay.",
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_journalist_fixes_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "journalist_fixes_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checks passed" in proc.stdout


def test_every_new_string_is_keyed_in_all_twelve_locales() -> None:
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _NEW_KEYS:
            assert data.get(key), f"{path.name} is missing {key!r}"
        # A translated frame keeps its slot verbatim, or the symbol never reaches the reader.
        assert "{symbol}" in data[_NEW_KEYS[3]], f"{path.name}: the {{symbol}} slot was translated away"


def test_the_observatory_never_sizes_its_canvas_from_a_hidden_stage() -> None:
    js = read_static("app-observatory.js")
    body = function_body(js, "_obsPaintNow")
    assert "stage.clientWidth < 1) return" in body, (
        "a hidden tab measures zero wide; painting then froze a 320 px sky"
    )
    # Measured from the stage's INNER width: the border-box read made the canvas 2 px too wide.
    assert "getBoundingClientRect" not in body
    # ...and it repaints when the tab is shown again, which is not a window resize.
    assert "new ResizeObserver" in function_body(js, "_obsWire")
    # The observer remembers EVERY width it reports, hidden (0) included, so a tab shown again
    # at the width it had repaints: the paints made while it was hidden were skipped.
    assert "_obsStageResized(memo" in function_body(js, "_obsWire")
    resized = function_body(js, "_obsStageResized")
    assert "memo.w = w;" in resized and "return w > 0;" in resized
    assert "contain:inline-size" in css_rule(read_static("app.css"), "#sky-stage").replace(" ", ""), (
        "without inline-size containment a px-sized canvas holds its own stage wide, so the "
        "sky could never shrink again"
    )


def test_the_chart_says_how_to_zoom_and_the_timescale_says_what_it_does() -> None:
    js = app_js()
    # A LITERAL middle dot: the i18n scanner reads a `\\u00b7` escape as those six characters,
    # finds no such key in en.json and fails the untranslatable ratchet, though the page works.
    chart = function_body(js, "ooChart")
    assert 't9("Scroll to zoom \u00b7 drag to pan \u00b7 double-click to reset")' in chart
    assert "\\u00b7 drag to pan" not in chart
    # Brush mode brushes on a plain drag, so it never says "drag to pan"; and a finished
    # brush's readout is not wiped when the pointer leaves the canvas.
    assert "hintNow = () => (brushMode ? \"\" : idleHint)" in chart
    assert "bFrom == null && !brushMode) readout.textContent = idleHint" in chart
    scope = function_body(js, "ooTimeScope")
    assert 't("Snap range to")' in scope
    assert 't("Timescale")' not in scope, "the label went back to promising a re-binning it does not do"
    # The undo is a memory of the pre-snap bounds, dropped when the reader moves one.
    assert "unsnapped" in scope


def test_the_overlay_flips_to_indexed_only_for_a_commodity_that_has_prices() -> None:
    js = app_js()
    pick = function_body(js, "anTrendPick")
    assert 'prices || []).length' in pick and "autoIndexed = true" in pick
    draw = function_body(js, "drawAnTrend")
    # The choice is visible as a chip; the note sits beside the chart, not in a line far below.
    assert "chipSyms" in draw
    assert draw.index("noNotes") < draw.index("card-caveat"), (
        "the no-price note belongs directly under the chart, before the axis caveat"
    )


def test_the_theme_select_applies_on_change() -> None:
    shell = read_static("app-shell.js")
    wired = function_body(shell, "_wireThemeSelect")
    assert 'addEventListener("change"' in wired and "setTheme(" in wired
    assert "_lastSyncedThemeBucket" in wired, "it must not re-apply a bucket the theme already sits in"


def test_the_map_card_sits_under_the_map_and_the_click_outlines_the_country() -> None:
    js = read_static("app-map.js")
    detail = function_body(js, "_ooMapCountryDetail")
    signal = function_body(js, "_ooMapSignalDetail")
    assert "_ooMapDetailHost()" in detail and "_ooMapDetailHost()" in signal
    assert "_ooMapMarkSelected(isoKey)" in detail
    assert "_ooMapMarkSelected(null)" in signal, "a signal is not a country: no outline may stay"
    # The block that rewrites the map also wipes a docked card, and THREE paths redraw it
    # without going through _renderOoMapDim (the Regions toggle, the worldview select, another
    # map's worldview change), so ooMap itself calls the caller's afterRender from host._ooOpts.
    assert "afterRender: _ooMapRestoreDetail" in function_body(js, "_renderOoMapDim")
    assert 'typeof opts.afterRender === "function"' in function_body(js, "ooMap")
    assert "closeBtn" in detail and "ooMapCloseDetail()" in detail
    # Q302: a code is only ever written by the one cell, and nothing falls back to a raw code.
    assert "ooCountryCell(isoKey) ||" not in detail
    # The outline is one overlay path in the World map only (every ooMap draws an svg#oo-choro).
    sync = function_body(js, "_ooMapSyncOutline")
    assert '$("oo-coverage-map")' in sync and "document.querySelectorAll" not in sync
    assert "_ooMapSyncOutline();" in function_body(js, "_ooMapMarkSelected")
    assert "host._ooOnLod()" in function_body(js, "_ooLodAttach"), "a zoom redraw would leave the outline on the old d"
    rule = css_rule(read_static("app.css"), "#oo-choro .oomap-sel").replace(" ", "")
    assert "vector-effect:non-scaling-stroke" in rule and "pointer-events:none" in rule and "fill:none" in rule
    # Reduced motion is honoured, the way _exploreRevealAnalysis already does.
    assert "prefers-reduced-motion" in function_body(js, "_ooMapScrollBehavior")


def test_the_home_card_formats_its_signal_value_through_the_shared_formatter() -> None:
    js = read_static("app-home.js")
    assert "_sigValueText(sig.value)" in function_body(js, "cardHtml")
    assert "fmtNum(v)" in function_body(js, "_sigValueText")
