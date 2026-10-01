"""The Home line that says a briefing refresh stopped early (R111 / diagnostics rank 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour is proven in ``tests/home_stop_line_node_test.js``, which extracts the real
``renderBriefing`` and ``_briefStamp`` from ``app-home.js`` and runs them in Node: where the
line sits, when it repaints, when it goes away, that a hostile reason is never reflected, and
that all 12 locales build it with no placeholder and no English left in. This wrapper only runs
that suite where Node exists.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_home_stop_line_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "home_stop_line_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "assertions passed" in proc.stdout
