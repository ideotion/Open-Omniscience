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
click-through 2026-09-26, rows N, O and T; re-walk 2026-09-27, row O-1).

Since O-1 the coach is a strip IN FLOW inside the sticky `.chrome`, under the top bar, so
it covers nothing by construction; that is pinned here from the markup and the CSS. The
ARROW is still placed by script, and ``net_coach_place_node_test.js`` drives it for real:
under the plane in LTR and RTL at 1440 and 375 px, never off the strip. This file also
pins that the arrow is RE-placed when the layout moves under it without a window resize
(a language switch mirrors the top bar; a tab relocates its subtab strip), and that the
coach stacks under the surfaces an operator opens on purpose -- at 375 px it once sat on
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


def test_the_coach_is_in_the_chrome_and_in_flow():
    """2026-09-27 re-walk O-1. As a position:fixed bubble below the whole chrome the coach
    sat exactly where every tab page begins: on Living sources' heading and on its
    visible-by-default caveat (92 of 372 sampled points of #living-caveat), and once the
    page was scrolled, on a form input (#sch-pages). A fixed box has no free rectangle to
    go to. In flow inside `.chrome`, right under the top bar, it pushes the page down
    instead of covering it -- which is a fact about the MARKUP and the CSS, so it is pinned
    here rather than in the geometry driver."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    chrome_at = html.index('<div class="chrome">')
    chrome_end = html.index("</div><!-- /.chrome -->", chrome_at)
    coach_at = html.index('<div id="net-coach"')
    assert chrome_at < coach_at < chrome_end, "#net-coach must live inside .chrome, in flow"
    assert html.index("</header>", chrome_at) < coach_at, (
        "#net-coach must sit UNDER the top bar, so its arrow points up at the plane"
    )
    rule = css_rule(_CSS.read_text(encoding="utf-8"), "#net-coach")
    assert "position: fixed" not in rule and "position:fixed" not in rule, (
        "#net-coach is floating again; a fixed box covers the page it hangs over"
    )
    assert "position: absolute" not in rule and "position:absolute" not in rule


def test_the_coach_stacks_under_what_the_operator_opens():
    """A passive invitation never outranks a surface opened on purpose: the palette and
    its results, the phone drawer, the enlarged mind map. Inside the sticky chrome the
    coach takes the chrome's stacking level, so the chrome's own z-index is the one that
    must stay under every one of them (and the coach carries none of its own to drift)."""
    css = _CSS.read_text(encoding="utf-8")
    assert "z-index" not in css_rule(css, "#net-coach"), (
        "#net-coach carries a z-index again -- it stacks with the chrome it sits in"
    )
    chrome = _z(css, ".chrome")
    for sel in (".overlay", ".palette", ".sidebar", ".mm-big"):
        assert chrome < _z(css, sel), f".chrome (z {chrome}), and the coach in it, stacks above {sel}"
