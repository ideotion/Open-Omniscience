"""The stopword review panel's wiring (R98, D11): a source-level guard over the static assets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Browser-unverified until the Chromium walk (fork-3): this pins what cannot regress silently,
mostly negative space. The caveat is visible and never behind a toggle (informed consent); the
language picker is a real <select> (and the walk opens it); there is no inline handler (the CSP
has no 'unsafe-inline', #1199); no control sets a keyword's kind (R107); and nothing egresses,
so nothing is ensureOnline-gated (invariant #14 covers egress only).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import app_js, function_body

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = app_js()


def _panel() -> str:
    start = _HTML.index('id="swr-panel"')
    return _HTML[start : _HTML.index("</section>", start)]


def test_the_panel_lives_in_advanced_keywords_with_a_select_not_a_text_input():
    adv = _HTML.index('data-adv="keywords"')
    nxt = _HTML.index('data-adv="calendars"')
    assert adv < _HTML.index('id="swr-panel"') < nxt
    panel = _panel()
    assert re.search(r'<select id="swr-lang"', panel)
    assert 'input id="swr-lang"' not in panel


def test_the_caveat_is_visible_not_behind_a_toggle():
    panel = _panel()
    assert 'class="card-caveat"' in panel
    assert "<details" not in panel and "hidden" not in panel.split('id="swr-summary"')[0]


def test_no_inline_handlers_and_no_kind_control_in_the_panel_or_its_script():
    panel = _panel()
    assert not re.search(r"\son(click|change|input)=", panel)
    assert "data-on-click" not in panel
    body = "".join(
        function_body(_JS, n)
        for n in ("_swrWire", "loadStopwordReview", "loadStopwordReviewList", "swrDecide", "swrExport")
    )
    for forbidden in ("entity_type", "set_kind", "kind_override", "onclick="):
        assert forbidden not in body, forbidden
    # the only decisions the screen can send
    assert '"accept"' in body and '"reject"' in body
    # the prose may say "kind" (it states that nothing sets one); no CONTROL may carry it
    names = re.findall(r'(?:id|name|data-[a-z-]+)="([^"]*)"', panel)
    assert not [n for n in names if "kind" in n.lower()]
    assert len(re.findall(r"<select", panel)) == 1 and "<input" not in panel


def test_loopback_only_so_no_consent_gate():
    body = function_body(_JS, "loadStopwordReview") + function_body(_JS, "swrExport")
    assert "ensureOnline" not in body
    assert "/api/keywords/stopword-review" in body


def test_the_panel_loads_when_the_keywords_section_opens():
    shell = (_STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert 'typeof loadStopwordReview === "function"' in shell
