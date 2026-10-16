"""Runs the clean stop's UI test under node (``tests/memstop_row_node_test.js``) and pins the contracts between the files it reads."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_row_the_phase_and_the_toast_run_as_real_code_under_node():
    proc = subprocess.run(["node", str(_ROOT / "tests" / "memstop_row_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_phase_the_stop_sets_is_the_one_the_page_words():
    from src.scheduler import memstop

    assert memstop.PHASE == "memory-stop"
    assert 'phase === "memory-stop"' in (_ROOT / "src/static/app-core.js").read_text(encoding="utf-8")


def test_the_toast_is_called_from_the_boot_health_read():
    assert "memoryStopNoticeOnce()" in (_ROOT / "src/static/app-settings.js").read_text(encoding="utf-8")
