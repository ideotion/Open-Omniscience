"""ooSubtabs' left and right arrow keys follow the strip's writing direction (row 192; invariant #18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour is driven through the shipped component by ``subtabs_rtl_arrows_node_test.js`` in both
directions; this file runs it and pins that the direction is read where the key is pressed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import function_source, read_static


def test_arrow_keys_mirror_in_a_right_to_left_strip():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "subtabs_rtl_arrows_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_direction_is_read_inside_the_keydown_handler():
    src = read_static("app-markets.js")
    oo = function_source(src, "ooSubtabs")
    # read per key press, never once at wiring time: a language switch flips the direction live
    assert re.search(r'addEventListener\("keydown"[\s\S]*const rtl = isRtl\(\);', oo), (
        "the direction is read inside the keydown handler")
