"""Help's scrolling code blocks are keyboard-reachable, on BOTH render paths.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``.prose pre`` carries ``overflow-x:auto``, so a wide code sample in a Help document
scrolls sideways with a mouse and, with no ``tabindex``, not at all with a keyboard —
the reader simply never sees the right-hand side of the line. That is axe-core's
``scrollable-region-focusable`` (WCAG 2.1.1), measured n=3 on the Help surface and left
open in the docket as "out of this pass's scope".

The BEHAVIOUR — which blocks are marked, which are deliberately not, and that the mark
is removed when a block stops overflowing — is executed in
``tests/prose_scrollable_node_test.js``, because it turns on real measured geometry that
no source assertion can see.

What is pinned HERE is the wiring the node suite cannot see: that the pass runs on BOTH
paths that write into ``#doc-prose``. ``openDoc`` renders it and ``filterDoc`` re-renders
it from the find box, so a fix applied to only one is silently undone the first time a
reader types — the one-of-two-render-paths shape this round has met repeatedly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import assert_absent, assert_present, function_source, read_static

_SETTINGS = read_static("app-settings.js")
_CSS = (Path(__file__).resolve().parents[1] / "src" / "static" / "app.css").read_text(
    encoding="utf-8"
)


def test_the_behaviour_is_executed():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "prose_scrollable_node_test.js")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_both_render_paths_run_the_pass():
    """The whole point: one helper, both writers into #doc-prose."""
    for fn in ("openDoc", "filterDoc"):
        assert_present(
            function_source(_SETTINGS, fn), "markScrollableProse",
            why=f"{fn} writes #doc-prose, so it must re-mark the scrollable blocks; "
                "fixing only one path means the find box silently undoes the fix",
        )


def test_the_rule_this_answers_still_exists_in_the_css():
    """If `.prose pre` ever stops scrolling, this pass is dead code, not a fix.

    Pinned so the fix and the condition it answers cannot drift apart silently.
    """
    assert "overflow-x:auto" in _CSS, (
        "the horizontally scrollable code block is what makes the tab stop necessary"
    )


def test_no_role_is_added_alongside_the_tabindex():
    src = function_source(_SETTINGS, "markScrollableProse")
    assert_absent(
        src, 'role',
        why="role=region would demand an accessible name; inventing one per code block "
            "is screen-reader noise, and tabindex alone satisfies the rule",
    )
    assert_present(src, 'setAttribute("tabindex", "0")')
