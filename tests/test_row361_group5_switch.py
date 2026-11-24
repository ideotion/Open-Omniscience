"""Row 361 group 5: the enrich, discover, gold-builder and parts-bar lines follow a language switch.

The behaviour is driven in ``diag_group5_switch_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_group5_lines_follow_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "diag_group5_switch_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "diag_group5_switch_node_test.js: OK" in proc.stdout
