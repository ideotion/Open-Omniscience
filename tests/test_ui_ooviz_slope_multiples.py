"""Two more honest ooViz chart types wired to real payloads (batch F item 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Beyond the shipped dumbbell, a Tufte SLOPE chart and a shared-scale SMALL-MULTIPLES
grid are built on new pure ooViz primitives (slopeGeometry / gridLayout) and wired
to the existing /api/insights/trending-windows payload. Both obey invariant #16:
shared scales so panels/lines are comparable, a GAP is never zero-filled, a line
when dense / bars when sparse (n shown), never an interpolated curve, counts only /
no score, caveats visible. Pure string-assertion wiring guard (browser-unverified
per fork-3).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_repo_invariants import _ui_source
from tests.js_source_helper import function_body as _slice

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_OOVIZ = (_STATIC / "ooviz.js").read_text(encoding="utf-8")


def _fn_body(name: str) -> str:
    """One function's body, brace-matched. Shared slicer."""
    return _slice(_JS, name)


def test_ooviz_exposes_the_two_new_pure_primitives():
    assert "function slopeGeometry(" in _OOVIZ
    assert "function gridLayout(" in _OOVIZ
    # both exported in the public API object
    assert "slopeGeometry: slopeGeometry," in _OOVIZ
    assert "gridLayout: gridLayout," in _OOVIZ


def test_slope_geometry_shares_one_scale_and_breaks_at_gaps():
    # ONE shared value scale over every finite value (comparable slopes)
    assert "linearScale(v0, v1, height - pad.b, pad.t)" in _OOVIZ
    # a missing value is a GAP (y:null + missing:true), never zero-filled
    assert "missing: miss, y: miss ? null : sy(v)" in _OOVIZ


def test_slope_renderer_uses_primitive_and_never_bridges_a_gap():
    assert "function slopeChartSvg(" in _JS
    assert "ooViz.slopeGeometry" in _JS
    # segments only between ADJACENT measured points — break at a gap, never bridge
    assert "if (a.missing || b.missing) continue;" in _JS
    # colour encodes DIRECTION (rising/falling), not a fabricated score
    assert 'last > first ? "var(--ok)" : last < first ? "var(--err)"' in _JS
    assert "slopeScore" not in _JS and "slope_score" not in _JS
    # truncation disclosed, never silent (like the dumbbell)
    assert "_SLOPE_MAX" in _JS and 't("+ {n} more (not shown)")' in _JS


def test_small_multiples_shares_one_scale_and_is_honest_16():
    assert "function smallMultiplesSvg(" in _JS
    body = _fn_body("smallMultiplesSvg")
    assert "ooViz.gridLayout" in body
    # ONE shared vertical scale across every panel (the small-multiples honesty win)
    assert "// SHARED 0..maxV" in body
    # invariant #16: line when dense, bars when sparse — never an interpolated curve.
    # Scoped to THIS body: the identical expression lives in dashChartSvg, and a
    # whole-file search silently accepted that one instead.
    assert "_SPARSE_BAR_MAX" in body
    # ...and the threshold counts REAL observations, not array slots — "n=30" over a
    # series with 25 gaps claims evidence that was never collected.
    assert "nReal >= _SPARSE_BAR_MAX" in body
    # n is shown per panel, and it is the real count
    assert "n=${nReal}" in body


def test_slope_from_trending_windows_uses_rate_not_raw_counts():
    # per-day RATE (count / window length) so the nested windows are comparable
    assert "_slopeFromTrendWindows" in _JS
    assert '{"24h": 1, "7d": 7, "30d": 30}' in _JS
    assert "(x.recent || 0) / DAYS[w.label]" in _JS


def test_panels_and_slope_deeplink_to_analysis_window():
    # a term panel / slope endpoint opens its own analysis window (redundant by design)
    assert "openAnalysisFor(" in _JS  # already present app-wide; ensure the new code uses it
    assert "renderTrendSlope" in _JS and "renderTrendMultiples" in _JS


def test_trends_lens_toggle_is_wired_additively():
    ui = _ui_source()
    assert 'data-trdlens="slope"' in ui and 'data-trdlens="multiples"' in ui
    assert 'id="trd-slope"' in ui and 'id="trd-multiples"' in ui
    assert "function setTrendLens(" in _JS
    # default lens stays "windows" (no regression to the shipped view)
    assert '_trdLens = "windows"' in _JS


def test_the_node_suite_for_small_multiples_actually_runs():
    """A test that never executes is not a test.

    tests/small_multiples_gaps_node_test.js had no pytest wrapper, so its twelve
    assertions ran only when someone invoked node by hand -- while the sibling
    suite whose doctrine it cites (tests/test_chart_gaps.py) has had one all along.
    """
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest

        pytest.skip("node not available")
    js = Path(__file__).resolve().parents[1] / "tests" / "small_multiples_gaps_node_test.js"
    proc = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
