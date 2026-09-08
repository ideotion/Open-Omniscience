"""
Behavioral tests for TextProcessor.process_text (Open Omniscience audit 10, P2-10).

Regression coverage for a naming bug: the n-gram result dict's keys were derived
from f"{'n' * n}grams", which produces "nngrams"/"nnngrams" for n=2/3 instead of
the documented "bigrams"/"trigrams" — a shape mismatch with the function's own
empty-text branch, and reachable verbatim through GET /api/keywords/process.
"""

from __future__ import annotations

from src.services.text_processor import text_processor

_TEXT = "the quick brown fox jumps over the lazy dog"

_EXPECTED_KEYS = {"unigrams", "bigrams", "trigrams", "all_ngrams", "words"}


def test_empty_text_key_names():
    result = text_processor.process_text("")
    assert set(result.keys()) == _EXPECTED_KEYS
    assert result["bigrams"] == []
    assert result["trigrams"] == []


def test_non_empty_text_key_names():
    result = text_processor.process_text(_TEXT)
    assert set(result.keys()) == _EXPECTED_KEYS
    # the historical bug produced these keys instead of bigrams/trigrams
    assert "nngrams" not in result
    assert "nnngrams" not in result


def test_bigrams_and_trigrams_contain_expected_ngrams():
    result = text_processor.process_text(_TEXT, remove_stopwords=False)
    words = result["words"]
    assert result["bigrams"] == [
        " ".join(words[i : i + 2]) for i in range(len(words) - 1)
    ]
    assert result["trigrams"] == [
        " ".join(words[i : i + 3]) for i in range(len(words) - 2)
    ]
    assert "quick brown" in result["bigrams"]
    assert "quick brown fox" in result["trigrams"]


def test_all_ngrams_unaffected_by_key_naming():
    result = text_processor.process_text(_TEXT, remove_stopwords=False)
    expected_all = result["unigrams"] + result["bigrams"] + result["trigrams"]
    assert result["all_ngrams"] == expected_all


def test_ngram_range_beyond_trigrams_uses_honest_fallback_name():
    result = text_processor.process_text("a b c d e", remove_stopwords=False, ngram_range=(1, 4))
    assert "4-grams" in result
    assert "nnnngrams" not in result
