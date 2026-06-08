"""
Tests for emotion-category measurement (§4) — lexicon-based, honest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.awareness.emotion import emotion_counts, emotion_profile, load_lexicon


def test_emotion_counts_detect_category_words():
    counts = emotion_counts("This is an outrage and a betrayal; people are furious and angry.")
    assert counts["anger"] >= 3
    assert counts["joy"] == 0


def test_emotion_profile_dominant_and_caveat():
    snippets = ["panic and dread spread as the threat grew",
                "fear and terror gripped the region", "a small note of hope remained"]
    prof = emotion_profile(snippets)
    assert prof["dominant"] == "fear"
    assert prof["n_snippets"] == 3
    assert prof["total_hits"] >= 4
    assert "sample" in prof["lexicon_source"]
    assert "never" in prof["caveat"].lower() or "not" in prof["caveat"].lower()


def test_empty_snippets_no_hits():
    prof = emotion_profile([])
    assert prof["total_hits"] == 0 and prof["dominant"] is None


def test_custom_lexicon_override(monkeypatch, tmp_path):
    load_lexicon.cache_clear()
    lex = tmp_path / "lex.json"
    lex.write_text(json.dumps({"calm": ["serene", "peaceful", "tranquil"]}), "utf-8")
    monkeypatch.setenv("OO_EMOTION_LEXICON", str(lex))
    try:
        loaded, source = load_lexicon()
        assert "calm" in loaded and "custom" in source
        assert emotion_counts("a serene and peaceful and tranquil scene")["calm"] == 3
    finally:
        load_lexicon.cache_clear()


def test_bad_lexicon_degrades_to_sample(monkeypatch, tmp_path):
    load_lexicon.cache_clear()
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", "utf-8")
    monkeypatch.setenv("OO_EMOTION_LEXICON", str(bad))
    try:
        _, source = load_lexicon()
        assert source == "sample"            # loud fallback, never silent nothing
    finally:
        load_lexicon.cache_clear()
