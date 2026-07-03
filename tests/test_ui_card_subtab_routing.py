"""Home Leads route to the most useful analysis subtab for their type (item #39/#5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A Lead's "Open corpus" deep-link now carries a ?tab= for the subtab that best fits
the card type — rising -> Trend, coordination/near-dup/framing -> Related, reading-diet
/coverage -> Sources, space-time convergence -> When/Where/Who — reusing the existing
?tab= boot hydration (_anBootTab). Unknown types fall back to Overview. No new endpoint.
Pure string-assertion wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_card_subtab_map_exists_with_expected_routes():
    assert "function cardSubtab(" in _JS and "_CARD_SUBTAB" in _JS
    assert 'rising: "trend"' in _JS
    assert 'echo_chamber: "related"' in _JS
    assert 'diet_self_audit: "sources"' in _JS and 'coverage_advisor: "sources"' in _JS
    assert 'space_time_convergence: "www"' in _JS
    # unknown types fall back to Overview
    assert 'return (c && _CARD_SUBTAB[c.type]) || "overview"' in _JS


def test_openers_accept_and_pass_a_tab():
    assert "function openCardCorpus(ids, label, tab)" in _JS
    assert "function openAnalysisInNewTab(q, tab)" in _JS
    assert 'p.set("tab", tab)' in _JS
    # the omnibar Enter still works (tab optional): openCardCorpusQuery forwards it
    assert "function openCardCorpusQuery(q, tab) { openAnalysisInNewTab(q, tab); }" in _JS


def test_cardhtml_passes_the_routed_subtab():
    assert "const _tab = cardSubtab(c);" in _JS
    # both the id-set and query openers get the routed subtab
    assert "JSON.stringify(_tab)" in _JS


def test_reuses_the_existing_tab_deeplink_consumer():
    # the ?tab= is applied by the boot hydrator via _anBootTab — regression guard that the
    # consumer this feature relies on still exists.
    assert 'const tab = sp.get("tab")' in _JS
    assert '_anBootTab = tab' in _JS
    assert "_anSubtabs.select(_anBootTab)" in _JS
