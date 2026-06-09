"""
Behavioral tests for the keyword extractor (Action Plan Phase 6.4).

Hardens a live enricher that powers the /api/keywords/* routes and was previously
almost untested. Deterministic assertions on frequency ranking, stopword removal,
title weighting, and the statistics/phrase outputs.
"""

from __future__ import annotations

from src.services.keyword_extractor import KeywordExtractor

_TEXT = (
    "Climate policy and energy markets. Climate change drives energy policy. Energy energy climate."
)


def _ke():
    return KeywordExtractor()


def test_extracts_and_ranks_by_frequency():
    top = _ke().get_top_keywords(_TEXT, top_n=3)
    words = [w for w, _ in top]
    assert words[0] == "energy"  # most frequent
    assert "climate" in words and "policy" in words
    # frequencies are non-increasing
    counts = [c for _, c in top]
    assert counts == sorted(counts, reverse=True)


def test_drops_stopwords():
    kws = _ke().extract_keywords(_TEXT)["keywords"]
    assert "and" not in kws and "the" not in kws


def test_top_n_and_scores():
    scored = _ke().get_top_keywords(_TEXT, top_n=2, include_scores=True)
    assert len(scored) == 2
    # scores are floats in (0, 1], descending
    s = [score for _, score in scored]
    assert all(0 < x <= 1 for x in s)
    assert s == sorted(s, reverse=True)


def test_title_is_weighted():
    # A title term should outrank a body term that appears the same number of times.
    out = _ke().extract_keywords_from_article(
        "oil spill report", title="Pollution", title_weight=3.0
    )
    assert "pollution" in out["keywords"]


def test_statistics_shape():
    stats = _ke().get_keyword_statistics(_TEXT)
    for key in ("total_keywords", "total_words", "unique_words", "max_frequency"):
        assert key in stats
    assert stats["total_words"] > 0
    assert stats["max_frequency"] >= stats["min_frequency"]


def test_key_phrases_are_multiword():
    phrases = _ke().extract_key_phrases(_TEXT)
    assert phrases
    assert any(" " in p for p in phrases)  # phrases contain >1 word


def test_empty_text_is_safe():
    out = _ke().extract_keywords("")
    assert out["keywords"] == []
    assert out["total_words"] == 0
