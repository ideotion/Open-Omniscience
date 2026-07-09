"""Multi-word stopword PHRASES in the vendored scoped lists are now filtered (Item 8 KW).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The vendored stopwords-iso lists carry many MULTI-WORD stopword phrases (379 of 645 in
vi.txt), whose component syllables are not standalone entries — so the per-word n-gram
check let the whole filler phrase leak as a keyword. The extractor now also drops an
n-gram whose JOINED form is a stopword entry. This is a PARTIAL fix for syllable-segmented
languages (the single-syllable fragments still need a word segmenter) — the tests assert
exactly that boundary so the honesty is pinned, not over-claimed.
"""

from __future__ import annotations

from src.analytics import extract
from src.analytics.extract import BaselineExtractor


def test_joined_multiword_stopword_phrase_is_dropped(monkeypatch):
    """A bigram whose joined form is a stopword ENTRY is dropped; an adjacent content
    bigram (and the individual tokens) are untouched."""
    monkeypatch.setattr(extract, "_stopset", lambda language: frozenset({"bravo charlie"}))
    terms = {t.normalized for t in BaselineExtractor()._terms("alpha bravo charlie delta", "xx")}

    assert "bravo charlie" not in terms, "the multi-word stopword phrase must be filtered"
    assert "alpha bravo" in terms, "a non-stopword content bigram is untouched"
    # The single tokens still leak (no single-word stopword here) — the honest limitation:
    # activating multi-word entries does NOT segment syllable-fragmented junk.
    assert {"alpha", "bravo", "charlie", "delta"} <= terms


def test_real_vietnamese_multiword_stopword_no_longer_leaks():
    """End-to-end against the REAL vendored vi.txt: 'bao giờ' (when) is a multi-word entry
    whose syllables 'bao'/'giờ' are not standalone, so it used to leak as a keyword."""
    from src.services.stopwords import StopwordsManager

    vi = StopwordsManager().get_stopwords("vi")
    assert "bao giờ" in vi and "bao" not in vi and "giờ" not in vi, (
        "test premise: 'bao giờ' is a multi-word vi stopword with non-standalone syllables"
    )

    terms = {t.normalized for t in BaselineExtractor()._terms("chính bao giờ thương", "vi")}
    assert "bao giờ" not in terms, "the vi filler phrase must no longer be minted as a keyword"


def test_content_bigrams_are_not_over_filtered():
    """A guard against over-filtering: a real content phrase is never a stopword entry, so
    English extraction is unchanged."""
    terms = {t.normalized for t in BaselineExtractor()._terms("prime minister climate policy", "en")}
    assert "prime minister" in terms
    assert "climate policy" in terms
