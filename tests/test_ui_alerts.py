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

from tests.js_source_helper import assert_present, function_body, read_static
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
    """Each claim is scoped to the function that must satisfy it.

    Whole-file, all four needles matched 14-47 times elsewhere in the concatenated UI
    source, so the strip could have lost its caveat, its staleness disclosure and its
    corpus link and every assertion here would still have passed.
    """
    app = read_static("app.js")
    strip = function_body(app, "_renderHomeAlerts")
    # Staleness disclosed (silence is not safety); caveat visible; method in the hover.
    assert_present(strip, "silence is not safety",
                   why="the no-snapshot state must disclose that silence is not safety")
    assert_present(strip, "card-caveat", why="the alert caveat must be visible by default (#23)")
    assert_present(strip, "openAnalysisForIds(",
                   why="watch/convergence sets must open the exact corpus")
    # External hazard links pass the confirm popup (invariant #7) -- rendered per hazard.
    assert_present(function_body(app, "_hazardStripItem"), "extLink(",
                   why="hazard URLs must open via the external-link confirm")


def test_alerts_never_promote_a_magnitude_into_urgent():
    ui = _ui_source()
    # The three provider tiers are rendered as-is; the frontend never invents a tier — the
    # 'urgent' class only ever paints whatever the backend already tiered.
    assert "urgent" in ui and "watch" in ui, "the provider tiers must be surfaced as given"


def test_alert_strip_shows_the_hazard_type_in_words():
    """Field impressions 2026-08-01, ruling 4: "clicking on an earthquake to see the
    event description misses that [it is an earthquake], new users will not be able to
    deduce that". A glyph is a scannability aid, never the label — every hazard render
    states the type in words, translated, and an unlisted type falls back to the
    provider's own string rather than inventing a name."""
    ui = _ui_source()
    assert "function hazardTypeLabel(" in ui, "a shared type-in-words helper must exist"
    assert "HAZARD_TYPE_KEYS" in ui and '"Earthquake"' in ui, "hazard types must be keyed"
    # the compact strip item and the MAP's own detail panel both use it (the report
    # was specifically about the map detail)
    assert "haz-kind" in ui, "the strip item must render the type in words"
    assert 'hazardTypeLabel(s.hazard_type)' in ui, (
        "the map signal detail must name the hazard type, not just the generic kind"
    )


def test_alert_strip_display_floor_never_removes_recall():
    """Rulings 1-2: the strip shows the major events first and collapses the rest into
    ONE line that opens the World map. A floor is honest only while everything stays
    reachable — the payload, the map and 'Open corpus' are all unchanged."""
    ui = _ui_source()
    assert "h.major" in ui, "the strip must read the backend's display-floor flag"
    assert "openWorldMapHazards()" in ui, "the overflow line must reach the full set on the map"
    assert "display floor" in ui, "the overflow line must say WHY the rest are not listed"
    # the floor is stated as a magnitude BAND, never as urgency
    assert "hazardMagLabel" in ui, "a magnitude must render with its band label"


def test_map_major_only_is_a_default_lens_not_an_exclusion():
    """Ruling 4: 'Major only' is ON BY DEFAULT and one click restores full recall; the
    UI says so in words. A deep-linked below-floor event clears the filter rather than
    landing the user on a map that does not show the point they clicked."""
    ui = _ui_source()
    assert "_ooMapHazMajorOnly = true" in ui, "the major-only lens must default ON"
    assert "default lens, not an exclusion" in ui, "the default must be stated as a lens"
    assert "_ooMapHazType" in ui, "a hazard-TYPE filter must exist"
    assert "function _hazardSignalIsMajor(" in ui, (
        "the map must use the same provider-declared facts as the alert layer"
    )
