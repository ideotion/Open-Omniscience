"""Row 361 group 7: the advanced-search notes and filter caveats follow a language switch.

The behaviour is driven in ``analysis_group7_switch_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_group7_notes_follow_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "analysis_group7_switch_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "analysis_group7_switch_node_test.js: OK" in proc.stdout
