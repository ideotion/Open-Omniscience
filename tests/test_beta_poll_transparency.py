"""BETA wave — B3: poll-transparency structured per-field form (field-test F2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Tier-2 poll-transparency checklist backend (POST /api/insights/poll-transparency)
accepts named fields but the UI was a paste-raw-JSON box. B3 replaces it with per-field
labelled inputs (keeping a collapsed raw-JSON power-user fallback — never lose a tool) and
renders the checklist with the disclosure-floor honesty framing (STATED vs not, never a
score; non-disclosure of a core item outranks any disclosed imperfection). Pure file-reads
+ locale JSON; no app import.
"""

from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_APP = (_STATIC / "app.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_LOCALES = _STATIC / "locales"
_LANGS = ["en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]

# The exact backend field vocabulary (PollFieldsBody) the form must cover.
_CORE = ["pollster", "sponsor", "fielding_dates", "sample_size", "population", "question_wording"]
_SUPP = ["sampling_method", "margin_of_error", "mode", "weighting", "response_rate"]


def test_every_backend_field_has_a_labelled_input():
    """All 11 CORE + SUPPLEMENTARY disclosure fields are per-field inputs (id pf_<key>)."""
    for key in _CORE + _SUPP:
        assert f'id="pf_{key}"' in _HTML, f"missing labelled input for disclosure field {key!r}"


def test_raw_json_fallback_is_kept_collapsed():
    """The raw-JSON box survives as a collapsed <details> power-user fallback (Desk lesson)."""
    assert "<details" in _HTML
    assert 'id="poll-fields"' in _HTML
    assert "Advanced: paste disclosed fields as JSON" in _HTML
    # the raw JSON OVERRIDES/EXTENDS the structured form (not the only path, not lost)
    assert "Object.assign(fields, extra)" in _APP


def test_check_builds_fields_from_the_form_and_posts_the_live_endpoint():
    assert "async function pollTransparencyCheck(" in _APP
    assert 'document.getElementById("pf_" + f.key)' in _APP
    assert "/api/insights/poll-transparency" in _APP
    assert 'method: "POST"' in _APP
    # the field vocabulary in JS matches the backend contract
    for key in _CORE + _SUPP:
        assert f'key: "{key}"' in _APP, f"POLL_FIELDS missing {key!r}"


def test_result_is_rendered_as_a_checklist_not_raw_json():
    """The old renderer dumped JSON.stringify; B3 renders a structured checklist."""
    assert "function _renderPollTransparency(" in _APP
    assert "JSON.stringify(d, null, 2)" not in _APP  # the raw-JSON dump is gone
    # stated / not-stated neutral marks + the ordered checklist
    assert 't("stated")' in _APP
    assert 't("not stated")' in _APP
    assert "d.checklist" in _APP


def test_disclosure_floor_honesty_no_score():
    """The tally is a plain count explicitly 'never a score'; missing CORE disclosures are
    highlighted as the interpretation floor; the backend caveat is rendered VISIBLE."""
    assert "a tally, never a score" in _APP
    assert "Missing core disclosures — needed to interpret this poll at all:" in _APP
    assert "d.core_gaps" in _APP
    # the verbatim question is echoed as structure; notes + backend caveat shown
    assert "The exact question, shown verbatim as structure:" in _APP
    assert "d.caveat" in _APP
    # no percentage / composite-score rendering: the tally uses a slash count, not a %.
    assert "standard disclosures stated" in _APP


def test_clear_helper_resets_the_form():
    assert "function pollTransparencyClear(" in _APP
    assert "Clear the form" in _HTML


def test_b3_locale_keys_present_in_all_twelve_locales():
    keys = [
        "Who conducted the poll", "Sample size (n)", "The exact question asked",
        "Check poll transparency", "Clear the form", "stated", "not stated",
        "a tally, never a score", "Supplementary disclosures",
        "Core disclosures — the floor to interpret a poll",
        "Advanced: paste disclosed fields as JSON",
        "Missing core disclosures — needed to interpret this poll at all:",
    ]
    for lang in _LANGS:
        data = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert k in data, f"{lang}.json missing B3 key {k!r}"
            assert str(data[k]).strip(), f"{lang}.json empty value for {k!r}"
