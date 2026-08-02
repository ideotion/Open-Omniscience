"""The axis-honesty pass (field impressions 2026-08-01, ruling 10) is proven by a Node
test (tests/axis_honesty_node_test.js) that EXTRACTS the real helpers from src/static/app.js.

The maintainer's report: a "law documents tracked" tile whose y-axis read 23 and 23.5,
whose two x-ticks both read "2026-07", and whose "n=2" could not be distinguished from
the plotted value. One expression caused the numeric half in each renderer --
`span = (max - min) || 1` -- which fabricated a span for a FLAT series (gridlines
[23, 23.5, 23] in dashChartSvg, [23, 23.33, 23.67, 24] in ooChart) and, with no integer
snapping anywhere, let a COUNT axis print a fractional count.

Running it here keeps the guarantee in CI; it skips cleanly where node is absent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_axis_honesty_node_suite() -> None:
    """Flat series, integer axes, adaptive+de-duplicated time labels, and the
    source-level guards that keep the fabrication vectors gone."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "axis_honesty_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "axis-honesty checks passed" in proc.stdout
