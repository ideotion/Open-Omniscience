"""Honest gaps in the ONE chart toolkit (invariant #16).

The behaviour is proven by tests/series_gaps_node_test.js, which extracts the real
``_seriesRuns`` from src/static/app.js. What lives HERE is the wiring: that both
renderers actually call it, that the trap which made the naive fix wrong stays
closed, and that the string explaining a break exists in every locale.

THE DEFECT: both renderers drew straight through a hole. ``dashChartSvg`` emitted a
single ``<polyline>`` over every point, and ``ooChart`` coerced ``+p.v`` (so a null
became a plotted ZERO, because ``+null`` is 0 and ``isFinite(0)`` is true) and then
lineTo'd unconditionally. On a real time axis that paints a measurement nobody took,
which the project's own committed chart framework rejects outright ("Render gaps as
gaps; mark 'no data' distinctly", docs/research/dataviz/chart_decision_framework.md).

Every assertion below is scoped to the ONE function body it claims to guard, sliced
from that function's own ``function`` line -- never a whole-file substring search,
which is only as meaningful as that string's uniqueness (the recorded house lesson,
learned when a test named for one surface turned out to be asserting about another).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
_LOCALES = _ROOT / "src" / "static" / "locales"

_GAP_NOTE = "The line breaks where nothing was recorded — a gap is not a zero."


def _body(name: str) -> str:
    """The source of ONE top-level function, brace-matched from its BODY brace.

    Matching starts only after the parentheses balance: a signature can carry a
    ``{}`` in a default parameter, and starting at the first brace would truncate
    the body to nothing and make every assertion over it pass vacuously.
    """
    at = _APP.index(f"function {name}(")
    depth, i = 0, -1
    for j in range(_APP.index("(", at), len(_APP)):
        if _APP[j] == "(":
            depth += 1
        elif _APP[j] == ")":
            depth -= 1
            if depth == 0:
                i = _APP.index("{", j)
                break
    assert i != -1, f"could not find the body of {name}"
    depth = 0
    for j in range(i, len(_APP)):
        if _APP[j] == "{":
            depth += 1
        elif _APP[j] == "}":
            depth -= 1
            if depth == 0:
                return _APP[at:j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_series_gaps_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "series_gaps_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_both_renderers_split_a_series_into_runs() -> None:
    """Neither renderer may go back to drawing one unbroken line over everything."""
    dash = _body("dashChartSvg")
    assert "_seriesRuns(" in dash, "dashChartSvg must split its series into runs"
    assert "run.map(i =>" in dash, "dashChartSvg must build each polyline from a RUN"
    # The exact removed expression, and nothing broader: the first draft of this
    # guard searched for `points.map((p, i) =>` and failed against CORRECT code,
    # because the BAR branch legitimately maps every point (bars cannot bridge a
    # gap -- each one stands alone). A "must be gone" assertion is only as strong
    # as the uniqueness of what it searches for.
    assert "Xp(p, i).toFixed(1)},${Y(p.price).toFixed(1)}" not in dash, (
        "dashChartSvg must emit one polyline PER RUN, never one over every point"
    )

    chart = _body("ooChart")
    assert "_seriesRuns(" in chart, "ooChart must split its visible points into runs"
    assert "s.vis.forEach((p, i) =>" not in chart, (
        "ooChart must not lineTo unconditionally across every visible point"
    )


def test_a_missing_value_can_never_become_a_plotted_zero() -> None:
    """``+null`` is 0 and ``isFinite(0)`` is true, so the NAIVE check keeps a
    published gap as a real measurement of nothing -- the failure mode that is worse
    than the bridged line this whole fix is about."""
    chart = _body("ooChart")
    assert "_missing(p.v)" in chart, "ooChart must test for missing BEFORE coercing"
    # The precise shape that used to coerce a null to zero.
    assert "v: +p.v})" not in chart, "the bare `+p.v` coercion must not come back"

    runs = _body("_seriesRuns")
    assert "_missing(" in runs, "_seriesRuns must use the missing-aware predicate"
    assert "isFinite(opts.value" not in runs, (
        "a bare isFinite() readmits null as a finite zero"
    )


def test_a_gap_is_only_ever_claimed_on_a_real_time_axis() -> None:
    """A fabricated gap invents an outage that never happened, so the split is
    opt-in per call site: index spacing claims observation order, not elapsed time."""
    runs = _body("_seriesRuns")
    assert "opts.timed" in runs, "the time-gap rule must be gated on a real time axis"
    assert "deltas.length >= 3" in runs, (
        "a cadence guessed from fewer than three intervals must not split anything"
    )
    dash = _body("dashChartSvg")
    assert "timed: shared" in dash, (
        "dashChartSvg may only apply the time-gap rule in its shared-time-axis mode"
    )


def test_the_break_is_explained_in_every_locale() -> None:
    """A break the reader cannot interpret is just a broken chart. The note ships in
    all twelve locales -- and it is NOT caught by the i18n gate, which scans
    index.html only and never opens app.js, so this is the check that covers it."""
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert _GAP_NOTE in data, f"{path.name} is missing the gap note"
        assert data[_GAP_NOTE].strip(), f"{path.name} has an empty gap note"
