"""The honest-chart primitive module (src/static/ooviz.js) is proven by a Node test
(tests/ooviz_node_test.js): the ported research primitives (isMissing/linearScale/
sqrtAreaScale/niceTicks/mulberry32/pathWithGaps/binCounts1D/fiveNumberSummary) PLUS
statSeriesPaths — the Phase B2 consumer of the src/stats/series.py to_chart_series
output (one subpath per comparability segment, a unit/base-year/SA-NSA break NEVER
joined, each broken at its own gaps).

The math is the genuinely VERIFIABLE core of the honest-chart toolkit; the live ooChart
wiring (drawing these paths) is the browser-deferred follow-on, flagged browser-unverified.
This wrapper runs the Node test inside CI (skips cleanly where node is absent).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_ooviz_primitives_and_stat_series_paths():
    test_js = _ROOT / "tests" / "ooviz_node_test.js"
    assert test_js.exists(), "the node test script must exist"
    r = subprocess.run(
        ["node", str(test_js)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_ROOT),
    )
    assert r.returncode == 0, f"ooviz node test failed:\n{r.stdout}\n{r.stderr}"
    assert "OOVIZ OK" in r.stdout


def test_ooviz_module_is_self_contained_and_network_free():
    """ooViz must be dependency-free, node/browser dual (attaches to the global AND
    exports for the node test), make no network call (the math needs no DOM/network),
    and carry the honesty-by-shape primitives. No charting library, no fabricated data."""
    src = (_ROOT / "src" / "static" / "ooviz.js").read_text(encoding="utf-8")
    assert "root.ooViz = API" in src, "must attach to the global as ooViz"
    assert "module.exports = API" in src, "must export for the node test"
    assert "function statSeriesPaths" in src, "must carry the to_chart_series consumer"
    assert "function pathWithGaps" in src, "must carry the gap-breaking path primitive"
    # The §5B "normalized-only" map data layer (comparability gate + levels->symbols).
    assert "function choroplethData" in src, "must carry the choropleth comparability gate"
    assert "function symbolRadii" in src, "must carry the area-honest proportional symbols"
    # No network surface (the math reads values the caller already has).
    for forbidden in ("fetch(", "XMLHttpRequest", "import(", "require("):
        assert forbidden not in src, f"ooViz must be network/dependency-free: found {forbidden!r}"
