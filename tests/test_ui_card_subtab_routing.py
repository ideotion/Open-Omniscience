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
from tests.js_source_helper import app_js

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_JS = app_js()


def test_card_subtab_map_exists_with_expected_routes():
    assert "function cardSubtab(" in _JS and "_CARD_SUBTAB" in _JS
    assert 'rising: "trend"' in _JS
    assert 'echo_chamber: "related"' in _JS
    assert 'diet_self_audit: "sources"' in _JS and 'coverage_advisor: "sources"' in _JS
    assert 'space_time_convergence: "www"' in _JS
    # unknown types fall back to Overview
    assert 'return (c && _CARD_SUBTAB[c.type]) || "overview"' in _JS


def test_openers_accept_and_pass_a_tab():
    """The routed subtab must survive every hop from the card to the window.

    Asserted on the PARAMETER NAMES rather than on a verbatim signature: ruling 16 gave
    these openers a further argument (the Lead's provenance), and a literal-signature
    anchor fails on a change that adds to the chain without breaking anything in it --
    the recorded stale-anchor trap. What still fails, correctly, is `tab` disappearing
    from any hop.
    """
    import re

    def _params(name: str) -> list[str]:
        m = re.search(r"function\s+" + name + r"\s*\(([^)]*)\)", _JS)
        assert m, f"{name} not found in app.js -- was it renamed?"
        return [p.strip().split("=")[0].strip() for p in m.group(1).split(",") if p.strip()]

    assert _params("openCardCorpus")[:3] == ["ids", "label", "tab"]
    assert _params("openAnalysisInNewTab")[:2] == ["q", "tab"]
    assert _params("openCardCorpusQuery")[:2] == ["q", "tab"]
    assert 'p.set("tab", tab)' in _JS
    # the omnibar Enter still works (tab optional): openCardCorpusQuery forwards it
    from tests.js_source_helper import function_body

    assert "openAnalysisInNewTab(q, tab" in function_body(_JS, "openCardCorpusQuery")


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
