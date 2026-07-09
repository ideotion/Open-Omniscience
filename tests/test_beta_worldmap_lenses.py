"""BETA wave — B1: World-map ooSubtabs lens strip + story lenses (field-test Item 6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

String-assertion guards (browser-unverified per fork-3) that the World-map tab gained
the invariant-#18 ooSubtabs lens grammar organizing the map's lenses (Coverage · Stories
· Places · Server IPs) plus the corpus-derived story-type filter, WITHOUT regressing the
ooMap honesty invariants (deduced-never-a-verdict, no score, counts only). Pure
file-reads + locale JSON — no app import (runs in the core sandbox).
"""

from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_LOCALES = _STATIC / "locales"
_LANGS = ["en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]


def test_lens_nav_exists_with_four_lenses():
    """The World-map panel has an ooSubtabs lens nav with the four lenses."""
    assert 'id="oomap-lenses"' in _HTML
    for tab in ("coverage", "stories", "places", "servers"):
        assert f'data-tab="{tab}"' in _HTML, f"lens '{tab}' must be a subtab button"
    # It is the invariant-#18 subtab grammar (a <nav class="tabs"> of data-tab buttons).
    assert 'class="tabs" id="oomap-lenses"' in _HTML


def test_lens_nav_relocates_to_the_top_subtab_strip():
    """Like every other tab's facets, the lens nav registers for #subtab-strip relocation."""
    assert 'timemap: "oomap-lenses"' in _APP


def test_lens_strip_is_wired_via_ooSubtabs():
    """The lens strip is driven by the shared ooSubtabs helper, not bespoke handlers."""
    assert 'ooSubtabs($("oomap-lenses"), selectOoMapLens' in _APP
    assert "async function selectOoMapLens(" in _APP


def test_lens_presets_layer_state_and_reuses_existing_endpoints():
    """Each lens presets the existing in-map layer flags and reuses the SAME endpoints the
    in-map toggles already use — no new fetch surface."""
    assert '_ooMapSignalsOn = (key === "stories")' in _APP
    assert '_ooMapPlacesOn = (key === "places")' in _APP
    assert '_ooMapServerOn = (key === "servers")' in _APP
    # reuses the live endpoints (already consumed by the in-map toggles)
    assert '/api/timemap?limit=4000' in _APP
    assert '/api/insights/where?limit=400' in _APP
    assert '/api/insights/server-locations' in _APP


def test_story_type_filter_exists_and_is_client_side():
    """The Stories lens filters plotted signals by story KIND client-side (no new endpoint)."""
    assert "_ooMapStoryKind" in _APP
    assert 'sig = sig.filter(s => (s.kind || "article") === _ooMapStoryKind)' in _APP
    assert "function _renderOoMapLensBar(" in _APP
    assert "data-story-kind" in _APP


def test_story_types_are_translated_and_honest():
    """Story-type labels route through kindLabel (translated), and the story-type panel
    carries a VISIBLE deduced/never-a-verdict caveat — counts only, no score/ranking."""
    assert "function kindLabel(" in _APP
    assert "kindLabel(k)" in _APP  # used to label the story chips
    # visible honesty caveat (not toggle-gated)
    assert "Story types are deduced from your corpus by event kind" in _APP
    assert "never a verdict or ranking" in _APP
    # no score/ranking value on a chip: only fmtNum counts are rendered
    assert "counts only, never a verdict or ranking" in _APP


def test_no_fabricated_data_when_a_lens_is_empty():
    """An empty Stories lens shows an honest empty state, never a blank or a fabricated point."""
    assert "No located events in your corpus yet" in _APP
    # a failed lens fetch degrades to an empty layer, never a crash
    assert "_ooMapWhere = { places: [] }" in _APP


def test_coverage_is_the_safe_default_lens():
    """Coverage (always-available, no extra fetch) is the default active lens; Stories is a
    first-class lens one click away (making Stories the DEFAULT awaits corpus story
    aggregation — a backend gap, deferred, noted in the PR)."""
    assert 'let _ooMapLens = "coverage"' in _APP


def test_b1_locale_keys_present_in_all_twelve_locales():
    """Every B1 user-facing string is keyed ×12 (non-en AI-drafted, flagged for native review)."""
    keys = [
        "Coverage", "Stories", "Server IPs", "Map lens", "All stories", "Story types",
        "Conflict", "Climate", "Disaster", "Civic",
        "— explore your corpus by place",
        "No located events in your corpus yet — collect more, or explore the Coverage lens.",
        "Story types are deduced from your corpus by event kind — counts only, never a verdict or ranking.",
    ]
    for lang in _LANGS:
        data = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert k in data, f"{lang}.json missing B1 key {k!r}"
            assert str(data[k]).strip(), f"{lang}.json has empty value for {k!r}"


def test_ooMap_honesty_invariants_preserved():
    """The lens work must not regress the ooMap no-data-hatch / deduced-place caveats."""
    assert "url(#oomap-nodata)" in _APP  # no-data hatch, never a guessed colour
    assert "Mentioned places: deduced from text, never confirmed." in _APP
