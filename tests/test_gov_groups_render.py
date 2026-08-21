"""Driver for tests/gov_groups_node_test.js (field feedback 2026-08-07, rulings 43/44/45/47).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The group-aggregation ENGINE refuses honestly and is well covered by
tests/test_stats_aggregation.py. This drives the other end: the one renderer those
refusals pass through on their way to a reader. That boundary is where an honest payload
has twice stopped being honest in this project — a "not asked" printed as "failed", a
caveat computed and dropped — so the refusals, the coverage, the spread and the
membership vintage are asserted against rendered HTML rather than against the payload.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gov_groups_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "gov_groups_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
