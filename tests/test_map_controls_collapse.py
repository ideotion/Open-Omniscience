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


def test_the_css_hides_the_panel_only_below_600px_and_leaves_desktop_alone():
    assert re.search(r"\.oomap-panel\s*\{\s*display:contents;", CSS), (
        "above 600 px the panel must be invisible plumbing (display:contents)"
    )
    assert ".oomap-wrap > .oomap-ctl-toggle { display:none;" in CSS
    media = CSS.split("@media (max-width: 600px) {", 1)[1]
    assert ".oomap-wrap:not(.oomap-ctl-open) .oomap-panel { display:none; }" in media
    # opened, the panel stacks BELOW the map (static), never over it
    opened = media.split(".oomap-wrap.oomap-ctl-open .oomap-panel {", 1)[1].split("}", 1)[0]
    assert "position:absolute" not in opened
    assert "position:static !important" in media


def test_a_choice_closes_the_panel_and_a_repaint_keeps_the_state():
    assert "host._ooCtlOpen" in JS
    assert 'panel.addEventListener("click"' in JS and 'panel.addEventListener("change"' in JS
    # no inline handler (the CSP forbids 'unsafe-inline')
    assert "onclick" not in JS.split("data-oomap-ctl", 1)[1][:400]
