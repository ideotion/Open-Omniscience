"""PF10 = a (2026-09-30): below 600 px the ooMap control groups collapse into ONE in-map button.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured 2026-09-16 at 390 px: the in-map groups covered 79% of the world map, 112% with the
worldview picker. Chromium-verified on this change (390 px and 1280 px, the world-map tab):
the closed state covers 6% (the button alone), the opened panel stacks the groups BELOW the
map rather than over it, and 1280 px is byte-for-byte the old layout. These pin the wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import arrow_const_source, function_body

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "src" / "static" / "app-map.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")


def test_the_four_control_groups_all_live_inside_one_panel():
    panel = JS.split('<div class="oomap-panel">', 1)[1].split('<ul class="sr-only">', 1)[0]
    for group in ("oomap-controls", "${pickerHtml}", "${granHtml}", "${sliderHtml}"):
        assert group in panel, f"{group} must sit inside .oomap-panel or it will not collapse"


def test_the_toggle_is_a_labelled_button_that_reports_its_state():
    m = re.search(r'<button type="button"[^>]*data-oomap-ctl[^>]*>[^<]*<', JS, re.S)
    assert m, "the in-map toggle button is missing"
    tag = m.group(0)
    assert 'aria-expanded="false"' in tag
    assert 't("Show or hide the map\'s controls")' in tag
    assert 't("Map controls")' in JS, "the button must carry visible text, never an icon alone"
    assert 'setAttribute("aria-expanded"' in JS, "the state must be kept in step"


def _media_blocks(css: str, header: str) -> list[str]:
    """The bodies of every `header { ... }` block, found by brace matching (not by slicing)."""
    out, start = [], 0
    while (i := css.find(header, start)) != -1:
        j = css.index("{", i)
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        out.append(css[j + 1 : k - 1])
        start = k
    return out


def test_the_css_hides_the_panel_only_below_600px_and_leaves_desktop_alone():
    assert re.search(r"\.oomap-panel\s*\{\s*display:contents;", CSS), (
        "above 600 px the panel must be invisible plumbing (display:contents)"
    )
    assert ".oomap-wrap > .oomap-ctl-toggle { display:none;" in CSS
    blocks = _media_blocks(CSS, "@media (max-width: 600px)")
    assert blocks, "the phone-width block is missing"
    mine = [b for b in blocks if ".oomap-panel" in b]
    assert len(mine) == 1
    media = mine[0]
    assert ".oomap-wrap:not(.oomap-ctl-open) .oomap-panel { display:none; }" in media
    # opened, the panel stacks BELOW the map (static), never over it
    opened = media.split(".oomap-wrap.oomap-ctl-open .oomap-panel {", 1)[1].split("}", 1)[0]
    assert "position:absolute" not in opened
    assert "position:static !important" in media
    # nothing that hides the panel may sit OUTSIDE the phone-width block
    outside = CSS
    for b in blocks:
        outside = outside.replace(b, "")
    assert ".oomap-panel { display:none" not in outside
    assert "oomap-panel { display:none" not in outside.replace(
        ".oomap-wrap:not(.oomap-ctl-open) .oomap-panel { display:none; }", ""
    )


def test_only_the_button_writes_the_open_state_and_a_repaint_reads_it():
    """No choice closes the panel: that hid the focused control and raced the repaint (review finding)."""
    assert "host._ooCtlOpen" in JS
    # The whole _wireOoMap body, cut by the shared slicer (not a hand-rolled split): the toggle's
    # wiring lives in it, and nothing else in it may listen on the panel.
    wiring = function_body(JS, "_wireOoMap")
    assert "host._ooCtlOpen = !!on" in arrow_const_source(JS, "setOpen")
    assert 'tog.addEventListener("click"' in wiring
    assert "panel.addEventListener" not in wiring, (
        "a listener on the panel would reset the state against a panel a repaint has replaced"
    )
    assert wiring.count("setOpen(") == 2, "one initial paint from the stored state, one toggle"
    # no inline handler (the CSP forbids 'unsafe-inline')
    assert "onclick" not in JS.split("data-oomap-ctl", 1)[1][:400]
