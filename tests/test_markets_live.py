"""The Markets tab follows a language switch (row 367, app-markets.js).

The boards, the feed verdict list and its retry line, and the time-range control wrote translated text once into
ordinary nodes, so they stayed in the language that was active when they were drawn. The verdict list, the retry line
and the time-range control (its words, presets, scale options and attributes) are now held through ooLive/ooLiveHtml;
the two boards are drawn again from the cards they hold by ``repaintMarketBoards``, which app-boot's one
``oo:langchange`` listener calls, and only once a board has been drawn. The behaviour is driven as real code in
``markets_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_markets_tab_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "markets_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "markets_live_node_test.js: OK" in proc.stdout


def test_the_language_listener_redraws_the_boards():
    # The boards hold no ooLive node of their own and draw in the language in force, so their place in the listener
    # relative to ooLiveRepaint() does not matter; what matters is that the one listener calls them.
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    listener = boot.index('"oo:langchange"')
    assert boot.count("repaintMarketBoards()") == 1
    assert boot.index("repaintMarketBoards()") > listener
