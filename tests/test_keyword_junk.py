"""
Slice 4b — keyword extraction junk (FIX_SESSION_2026-07-14). Three sub-fixes at extraction:
tracker-URL residue never becomes a keyword; a repeated-token n-gram is dropped; an accented-Latin
shout / a CTA button word is a term, not an acronym ENTITY.

NEGATIVE-SPACE lens (the mandatory skeptic for an honesty-critical extractor change): the fixes must
NOT over-reach — a Greek/Cyrillic acronym is Latin-accent-free so it STAYS an entity; a real
non-repeated bigram survives; URL-free prose is unchanged; a real ASCII acronym stays an entity.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.analytics.extract import BaselineExtractor

_EX = BaselineExtractor()


def _terms(text: str, lang: str = "en") -> set[str]:
    return {e.normalized for e in _EX.extract(text, language=lang)}


def _entities(text: str, lang: str = "en") -> set[str]:
    return {e.normalized for e in _EX.extract(text, language=lang) if e.kind == "entity"}


# --- (i) URL residue ------------------------------------------------------------------------

def test_tracker_url_residue_is_never_a_keyword():
    r = _terms("Read it at https://example.com/p?utm_source=nl&mc_eid=abc123def about the election economy.")
    assert not ({"utm_source", "mc_eid", "abc123def", "https", "www"} & r)
    assert "election" in r and "economy" in r  # the prose around the link is untouched


def test_url_free_prose_is_unchanged():
    # NEGATIVE SPACE: no URL -> the strip is a no-op, ordinary words survive
    r = _terms("The government announced a new budget policy for the coming year.")
    assert "government" in r and "budget" in r and "policy" in r


# --- (ii) repeated-token n-grams -------------------------------------------------------------

def test_repeated_token_ngram_is_dropped_but_the_unigram_survives():
    r = _terms("Please share share share this important election coverage widely.")
    assert "share share" not in r and "share share share" not in r
    assert "share" in r  # the unigram is legitimate content, kept


def test_a_real_non_repeated_bigram_survives():
    # NEGATIVE SPACE: only IDENTICAL-token n-grams are dropped, never a real phrase
    r = _terms("The prime minister addressed the climate summit at length today.")
    assert "prime minister" in r and "climate summit" in r


# --- (iii) accented / CTA all-caps are terms, not entities -----------------------------------

def test_accented_latin_and_cta_caps_are_not_entities():
    e = _entities("DÉCOUVREZ our story. PARTAGEZ it now. SUBSCRIBE below.")
    assert not ({"DÉCOUVREZ", "PARTAGEZ", "SUBSCRIBE"} & e)


def test_a_real_ascii_acronym_still_is_an_entity():
    assert "NASA" in _entities("The NASA mission and the WHO panel met in France.")
    assert "WHO" in _entities("Experts at WHO reviewed the data carefully.")


def test_greek_and_cyrillic_acronyms_are_not_dropped_by_the_latin_accent_guard():
    # NEGATIVE SPACE: the guard is LATIN-accent-only, so a Greek (ΕΕ) / Cyrillic (СССР) acronym —
    # which is NOT a Latin-accented word — must still be eligible as an entity (over-reach guard).
    assert "ΕΕ" in _entities("Η ΕΕ ανακοίνωσε νέα μέτρα.", lang="el")
    assert "СССР" in _entities("Историки обсуждали как СССР менялся во времени.", lang="ru")
