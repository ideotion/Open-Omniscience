"""Home's trends poll backs off after a deadline refusal (the node suite drives the real schedule)."""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_home_trends_backoff_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "home_trends_backoff_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok -" in proc.stdout
