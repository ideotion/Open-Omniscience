"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

The airplane coachmark (#net-coach): where it sits, and when it moves (delegated
click-through 2026-09-26, rows N, O and T).

The GEOMETRY is driven for real in ``net_coach_place_node_test.js``: never on the top
bar or the subtab strip under it, never on the sidebar, in LTR and RTL at 1440 and 375
px, still pointing at the plane. This file pins the three things a geometry test
cannot see: that the coach is RE-placed when the layout moves under it without a window
resize (a language switch mirrors the top bar; a tab relocates its subtab strip), and
that it stacks under the surfaces an operator opens on purpose -- at 375 px it sat on
the command palette's results.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.js_source_helper import (
    app_js,
    css_rule,
    event_listener_bodies,
    function_body,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_BOOT = _ROOT / "src" / "static" / "app-boot.js"
_CSS = _ROOT / "src" / "static" / "app.css"


@pytest.mark.skipif(
    subprocess.run(["which", "node"], capture_output=True).returncode != 0,
    reason="node is not installed",
)
def test_the_node_driver_places_the_real_coach():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "net_coach_place_node_test.js")],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_a_language_switch_re_places_the_coach():
    """Arabic mirrors the top bar without resizing the window, so the coach stayed at its
    LTR pixel spot, 1,019 px from the plane and over the sidebar's Insights item."""
    bodies = event_listener_bodies(_BOOT.read_text(encoding="utf-8"), "oo:langchange")
    assert bodies, "no oo:langchange listener in app-boot.js"
    assert any("_placeCoach()" in strip_comments(b) for b in bodies), (
        "no oo:langchange handler re-places the coach; a direction flip leaves it behind"
    )


def test_a_chrome_that_changes_height_re_places_the_coach():
    """A tab with facet subtabs relocates its strip under the top bar: the chrome grows
    with no window resize, and the coach placed on Home ended up on Settings' subtabs."""
    body = strip_comments(function_body(app_js(), "maybeShowNetCoach"))
    assert "ResizeObserver" in body and 'closest(".chrome")' in body, (
        "the coach no longer follows the chrome's height"
    )
    assert "_coachRO.observe(" in body
    assert "_coachRO.disconnect()" in strip_comments(function_body(app_js(), "dismissNetCoach")), (
        "a dismissed coach keeps observing the chrome"
    )


def _z(css: str, selector: str) -> int:
    m = re.search(r"z-index:\s*(\d+)", css_rule(css, selector))
    assert m, f"{selector} lost its z-index -- re-anchor this test"
    return int(m.group(1))


def test_the_coach_stacks_under_what_the_operator_opens():
    """A passive invitation never outranks a surface opened on purpose: the palette and
    its results, the phone drawer, the enlarged mind map. It still sits above the sticky
    chrome, so it is never drawn under the page it hangs over."""
    css = _CSS.read_text(encoding="utf-8")
    coach = _z(css, "#net-coach")
    for sel in (".overlay", ".palette", ".sidebar", ".mm-big"):
        assert coach < _z(css, sel), f"#net-coach (z {coach}) stacks above {sel}"
    assert coach > _z(css, ".chrome"), "#net-coach must stack above the sticky chrome"
