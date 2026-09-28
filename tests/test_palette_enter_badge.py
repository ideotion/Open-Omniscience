"""The palette's Enter always opens the analysis window on the typed query (Q608 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HISTORY. ``renderPalette`` used to build ``_palFiltered = [...statics, ...live]`` with
``_palSel`` starting at 0, so Enter ran the first STATIC match whenever the typed text
matched a page or a command ("search", "collect", "open", "data", "help", "settings" all
do). The Analysis row carried ``↵ ↗`` unconditionally, so on exactly those queries the
palette advertised a key that would run a different row; the badge was then made
conditional, and WHICH row Enter should run was left to the maintainer
(``docs/ledger/OPEN_QUEUE.md``).

RULED (Q608 = a, 2026-09-15): "Enter always opens the analysis window on the typed query;
static commands need an explicit selection." So the order is now ``[...live, ...statics]``
behind ``_palOrder``, the Analysis row is live's FIRST row, and its ↵ is unconditionally
true. The behaviour is driven in node (``palette_enter_node_test.js``); this file pins the
source shape the node test cannot see.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import assert_absent, assert_present, function_source, read_static

_ROOT = Path(__file__).resolve().parents[1]
_SHELL = read_static("app-shell.js")
_RENDER = function_source(_SHELL, "renderPalette")


def test_the_analysis_row_is_first_and_its_badge_is_unconditional():
    assert_present(_RENDER, "_palFiltered = _palOrder(statics, live, raw)",
                   why="the order is the one pure function the node test drives")
    assert_present(_RENDER, 'sub: "↵ ↗"',
                   why="Enter now always runs the Analysis row, so the badge is always true")
    assert_absent(_RENDER, 'statics.length ? "↗" : "↵ ↗"',
                  why="the conditional badge hedged a question Q608 has answered")


def test_the_analysis_row_is_the_last_one_unshifted():
    """The Analysis row must be unshifted AFTER the Boolean-search row, or the Boolean row
    would sit at index 0 and Enter would run it instead."""
    analysis = _RENDER.index('ooLabelText(t("Analysis")')
    boolean = _RENDER.index('t("Run the full Boolean search for")')
    assert boolean < analysis, "the Analysis row is unshifted after (so above) the Boolean row"


def test_the_selection_starts_at_the_first_row_and_survives_live_redraws():
    assert_present(_RENDER, "_palSel = 0")
    # An explicit arrow-key choice is kept when the live results land and redraw the
    # list; otherwise "I arrowed to Settings" became an analysis on the next Enter.
    assert_present(_RENDER, "_palLastRaw === raw && _palSel > 0")


def test_the_static_commands_that_collide_are_real():
    """Not a hypothetical: the shipped command labels collide with ordinary queries,
    which is why the order had to be ruled rather than left to chance."""
    cmds = function_source(_SHELL, "palCommands")
    labels = [m.group(1) for m in re.finditer(r'label:\s*"([^"]+)"', cmds)]
    assert len(labels) >= 5, "the static command list should not have quietly emptied"
    for probe in ("search", "collect", "open"):
        assert any(probe in lab.lower() for lab in labels)


def test_palette_enter_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "palette_enter_node_test.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
