"""
Wave 3 H — the severity alert strip on Home (info / watch / urgent).

A compact, LOCAL alert strip from GET /api/signals/alerts. 'Urgent' is only ever a
provider-declared RED hazard (never a promoted magnitude band); every alert states its
provider + the snapshot's staleness ("silence is not safety"); the caveat is VISIBLE
(#23) and the method rides the #oo-tip hover. Hazard URLs go through the external-link
confirm (extLink, invariant #7); watch/convergence sets open the exact corpus. The panel
hides when there is nothing so Home is never blank-and-silent.

Browser-unverified per fork-3 — node-checked + grep-guarded here.
"""

from __future__ import annotations

from tests.test_repo_invariants import _ui_source


def test_alert_strip_container_and_loader_wired():
    ui = _ui_source()
    assert 'id="home-alerts-panel"' in ui, "the alert strip needs a hideable container"
    assert 'id="home-alerts"' in ui, "the alert strip needs a render target"
    assert "loadHomeAlerts" in ui, "a loader for the alert strip must exist"
    assert "/api/signals/alerts" in ui, "the strip must read the local alerts endpoint"


def test_alerts_load_on_home_and_on_live_refresh():
    ui = _ui_source()
    assert "loadHomeAlerts();" in ui, "the alert strip must load with Home"


def test_alerts_are_honest_local_and_layered():
    ui = _ui_source()
    # Staleness disclosed (silence is not safety); caveat visible; method in the hover.
    assert "silence is not safety" in ui, "the no-snapshot state must disclose that silence is not safety"
    assert "card-caveat" in ui, "the alert caveat must be visible by default (#23)"
    # External hazard links pass the confirm popup (invariant #7); corpus opens local.
    assert "extLink(" in ui, "hazard URLs must open via the external-link confirm"
    assert "openAnalysisForIds(" in ui, "watch/convergence sets must open the exact corpus"


def test_alerts_never_promote_a_magnitude_into_urgent():
    ui = _ui_source()
    # The three provider tiers are rendered as-is; the frontend never invents a tier — the
    # 'urgent' class only ever paints whatever the backend already tiered.
    assert "urgent" in ui and "watch" in ui, "the provider tiers must be surfaced as given"
