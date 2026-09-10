"""The palette's ↵ badge only appears on the row Enter will actually run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``renderPalette`` builds ``_palFiltered = [...statics, ...live]`` and ``_palSel`` starts
at 0, so Enter runs the first STATIC match whenever the typed text matches a page or a
command. The Analysis row carried ``sub: "↵ ↗"`` unconditionally -- so on exactly those
queries the palette advertised a key that would run a different row. Measured against
the nine static commands plus the nav pages, the collision is not exotic: "search",
"collect", "open", "data", "help" and "settings" all match at least one.

A row that says ↵ and does not answer to it is the palette misdescribing itself. The ↗
(opens in a new browser tab) is true either way and stays.

WHICH row Enter *should* run is a product question -- the recorded ruling says Enter
defaults to the analysis window, and hoisting it above a matching command would mean
typing "Settings" and getting an analysis OF the word "Settings". That is recorded in
``docs/ledger/OPEN_QUEUE.md`` for the maintainer, not decided here.
"""

from __future__ import annotations

import re

from tests.js_source_helper import assert_absent, assert_present, function_source, read_static

_SHELL = read_static("app-shell.js")
_RENDER = function_source(_SHELL, "renderPalette")


def test_the_enter_badge_is_conditional_on_there_being_no_static_match():
    assert_present(
        _RENDER, 'sub: statics.length ? "↗" : "↵ ↗"',
        why="Enter runs the first STATIC match when one exists, so the badge cannot "
            "claim Enter unconditionally",
    )
    assert_absent(
        _RENDER, 'sub: "↵ ↗"',
        why="the unconditional badge is the claim this replaced",
    )


def test_the_new_tab_arrow_is_kept_either_way():
    """↗ describes where the row opens, which does not depend on the selection."""
    assert _RENDER.count("↗") >= 2, "both branches of the badge keep the new-tab arrow"


def test_the_selection_still_starts_at_the_first_row():
    """The badge tracks the real rule; it must not drift from it.

    If ``_palSel`` ever stops starting at 0, the condition above stops describing which
    row Enter runs and this file is wrong rather than merely stale.
    """
    assert_present(_RENDER, "_palSel = 0")
    assert_present(_RENDER, "_palFiltered = [...statics, ...live]")


def test_the_static_commands_that_collide_are_real():
    """Not a hypothetical: the shipped command labels collide with ordinary queries."""
    cmds = function_source(_SHELL, "palCommands")
    labels = [m.group(1) for m in re.finditer(r'label:\s*"([^"]+)"', cmds)]
    assert len(labels) >= 5, "the static command list should not have quietly emptied"
    for probe in ("search", "collect", "open"):
        assert any(probe in lab.lower() for lab in labels), (
            f"typing {probe!r} matches a static command, which is why the badge had to "
            "become conditional"
        )
