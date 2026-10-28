"""The markets Load / Refresh / Retry verdict box says how many feeds a Stop left unfetched (R377).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour is proven in ``tests/markets_skipped_offline_node_test.js``, which extracts the real ``_renderFeedVerdicts`` from ``app-markets.js`` and runs it in
Node (the import-all route ends a batch at a Stop and reports the feeds not fetched as ``skipped_offline``, so without this line a partial load read as complete).
This wrapper only runs that suite where Node exists.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_markets_skipped_offline_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "markets_skipped_offline_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "assertions passed" in proc.stdout
