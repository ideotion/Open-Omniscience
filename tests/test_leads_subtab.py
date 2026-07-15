"""S12 — the Settings → Leads subtab wiring (conservative, ISOLATED, browser-unverified).

The subtab previews the /api/insights/leads-view (evidence chips + disclosed order + major floor
+ clusters). It is guarded source-side (node --check + these pins) because there is no headless
browser here. Load-bearing property: it NEVER touches the Home briefing render, so the flagship
feed stays byte-identical until a human click-through graduates a mode onto Home.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

_HTML = Path("src/static/index.html").read_text(encoding="utf-8")
_JS = Path("src/static/app.js").read_text(encoding="utf-8")


def test_leads_subtab_and_controls_present_in_settings():
    assert 'data-tab="leads"' in _HTML  # the ooSubtabs nav button
    assert 'id="set-leads"' in _HTML  # the panel
    for el in ("leads-prominence", "leads-min-n", "leads-min-sources", "leads-cluster",
               "leads-preview"):
        assert f'id="{el}"' in _HTML, el


def test_leads_js_calls_the_endpoint_and_renders_real_chips():
    assert 'if (cat === "leads") loadLeadsView()' in _JS  # wired into showSetCat
    assert "/api/insights/leads-view" in _JS
    assert "function loadLeadsView" in _JS and "function leadsViewHtml" in _JS
    # chips render REAL facts each with a #17 hover method — never a composite score
    for field in ("evidence_chips", "distinct_sources", "newest_age_days", "order_explain"):
        assert field in _JS, field


def test_leads_subtab_never_touches_the_home_briefing_render():
    # loadLeadsView is invoked ONLY from showSetCat (Settings), never from loadHome/renderBriefing.
    assert _JS.count("loadLeadsView()") >= 1
    # its OWN body (up to the next function) must not call/modify the Home briefing render.
    body = _JS[_JS.index("async function loadLeadsView"): _JS.index("function buildDrawer")]
    assert "renderBriefing" not in body and "loadHome" not in body, (
        "the leads preview must not touch the Home briefing render"
    )


def test_leads_render_shows_the_never_a_score_disclaimer():
    # The chips render the backend's disclosed facts (n · sources · age); the honesty note that
    # this is never a composite score is shown to the reader (the backend payload is no-score-
    # guarded in test_leads_view). A positive assertion, not a fragile word-ban.
    seg = _JS[_JS.index("function leadsChipHtml"): _JS.index("function buildDrawer")]
    assert "never a composite score" in seg
