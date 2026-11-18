"""The map's layer buttons and its time slider share one bottom stack (row 162).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The time slider (shown while the Signals layer is on) sat at a fixed 36 px above the map's edge, on
the same layer as the buttons beneath it. Once the buttons wrapped to a second row (more layers, a
longer language) the slider lay over that row, and the Signals button that turns the slider off could
not be clicked: measured in Chromium at 1280 px, the point at the button's centre belonged to the
slider. The encrypted walk on the full seed corpus hit it as a 30 s click timeout. Both groups now
live in one column that grows upward, so the slider always sits above however many rows the buttons
take, and the empty part of the column lets clicks and drags reach the map.
"""

from __future__ import annotations

import re

from tests.js_source_helper import function_body, read_static

_MAP_JS = read_static("app-map.js")


def _style_of(html: str, marker: str) -> str:
    m = re.search(re.escape(marker) + r'[^>]*?style="([^"]*)"', html, re.S)
    assert m, marker
    return m.group(1).replace(" ", "")


def test_the_slider_and_the_buttons_stack_instead_of_overlapping():
    body = function_body(_MAP_JS, "ooMap")
    gran = _style_of(body, 'class="oomap-gran"')
    slider = _style_of(body, 'class="oomap-time"')
    for style in (gran, slider):
        assert "position:absolute" not in style and "bottom:" not in style, "no fixed offset of its own"
        assert "pointer-events:auto" in style, "the controls themselves take clicks"
    stack = _style_of(body, 'class="oomap-bottom"')
    assert "position:absolute" in stack and "bottom:8px" in stack
    assert "flex-direction:column-reverse" in stack, "the buttons at the edge, the slider above them"
    assert "pointer-events:none" in stack, "the stack's empty part never blocks the map"
    assert "${granHtml}${sliderHtml}</div>" in body, "both groups inside the one stack"
    assert "bottom:36px" not in body
