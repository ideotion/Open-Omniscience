"""
Tests for the outrage / loaded-language intensity SECONDARY signal (src/analytics/outrage.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

PURE (stdlib only) so it runs in the bare sandbox AND CI. Asserts the honesty rules live in
the SHAPE of the output: English-only (a non-English / empty / unknown-language text is a
stated GAP, never a fabricated 0), the density carries its COMPONENTS (matched markers, '!',
ALL-CAPS runs, n), and there is NO score / ranking key anywhere.
"""

from __future__ import annotations

from src.analytics.outrage import outrage_intensity


def _no_score(d: dict) -> None:
    # The honesty invariant is about FIELD NAMES (keys), not values — the method/caveat may
    # legitimately say "no score". Walk keys recursively and assert none is a score/ranking.
    def walk(o: object) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                kl = str(k).lower()
                assert "score" not in kl and "ranking" not in kl, f"banned field name: {k}"
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(d)


def test_english_loaded_text_is_measured_with_components():
    text = "SHOCKING betrayal! The corrupt official utterly destroyed the deal — absolute chaos!!"
    out = outrage_intensity(text, "en")
    assert out["measured"] is True
    assert out["language"] == "en"
    assert out["n_tokens"] > 0
    assert out["n_loaded"] >= 4  # shocking, betrayal, corrupt, destroyed, chaos, utterly, absolute…
    assert out["density"] > 0
    assert out["exclamations"] == 3
    assert out["shouting_caps"] == 1  # "SHOCKING"
    # The matched markers are surfaced (so the reader sees what drove it).
    assert "betrayal" in out["matched"] and "corrupt" in out["matched"]
    _no_score(out)


def test_calm_english_is_measured_but_low():
    out = outrage_intensity("The committee reviewed the quarterly budget and approved it.", "en")
    assert out["measured"] is True
    assert out["n_loaded"] == 0
    assert out["density"] == 0.0
    assert out["matched"] == []


def test_non_english_is_an_honest_gap_never_a_zero():
    out = outrage_intensity("Le gouvernement a approuvé le budget.", "fr")
    assert out["measured"] is False
    assert out["reason"] == "not English"
    assert "density" not in out  # never a fabricated 0 for a language we don't measure
    _no_score(out)


def test_unknown_language_is_not_assumed_english():
    # An untagged text could be any language — we do not mis-measure it as English.
    out = outrage_intensity("SHOCKING betrayal! Total chaos!", None)
    assert out["measured"] is False
    assert out["reason"] == "language unknown"


def test_empty_text_is_a_gap():
    assert outrage_intensity("", "en")["measured"] is False
    assert outrage_intensity("   ", "en")["reason"] == "empty"


def test_caveat_states_structure_not_intent():
    out = outrage_intensity("outrage and fury", "en")
    assert "never intent or truth" in out["caveat"].lower() or "structure" in out["caveat"].lower()
    assert "innocent twin" in out["caveat"].lower()
