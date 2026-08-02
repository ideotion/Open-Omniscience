"""The ingest-rhythm heatmap (field impressions 2026-08-01, ruling 10) is proven by a
Node test (tests/ingest_rhythm_node_test.js) that extracts the real aggregator from
src/static/app.js.

The maintainer asked to diversify the app's visualization vocabulary. The honesty
problem this first activation had to solve is that an empty cell is ambiguous: the
backend emits an hourly bucket only for hours that HAVE articles, so a missing hour
inside the observed span is a true zero, while a weekday/hour slot that has not come
round yet is unobserved. Blending the two would paint quiet periods that never happened.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_ingest_rhythm_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ingest_rhythm_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ingest-rhythm checks passed" in proc.stdout
