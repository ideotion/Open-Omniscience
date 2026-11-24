"""Settings > Backup lines that follow a language switch (row 366, the app-backup.js part of the row 352 list).

The renderers run as real code in ``backup_live_text_node_test.js``: the volume status line and the differences panel are drawn
through ``ooLive``/``ooLiveHtml`` and redrawn in French by ``ooLiveRepaint`` alone, with no new request.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_backup_lines_follow_a_language_switch_in_node():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "backup_live_text_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "backup_live_text_node_test.js: OK" in proc.stdout
