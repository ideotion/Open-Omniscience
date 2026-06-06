"""
Tests for keyword/entity extraction (baseline).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the honesty-relevant behaviour: multi-word entities are one unit, a
gazetteer assigns person/org/location kinds (else the generic "entity"),
sentence-initial capitalisation isn't mistaken for an entity, topical n-gram
terms carry counts + first offsets, and offsets actually point at the term.
"""

from __future__ import annotations

from src.analytics.extract import BaselineExtractor, ExtractedTerm, get_extractor


def _by_norm(terms: list[ExtractedTerm]) -> dict[str, ExtractedTerm]:
    return {t.normalized: t for t in terms}


def test_multiword_entity_is_one_unit_with_offset():
    text = ("Emmanuel Macron met advisers in the capital. "
            "Emmanuel Macron then addressed reporters about the economy.")
    ex = BaselineExtractor()
    terms = ex.extract(text)
    by = _by_norm(terms)
    assert "emmanuel macron" in by
    ent = by["emmanuel macron"]
    assert ent.kind == "entity"          # no gazetteer -> honest generic kind
    assert ent.count == 2
    # The offset points exactly at the entity in the source text.
    assert text[ent.first_offset:ent.first_offset + len("Emmanuel Macron")] == "Emmanuel Macron"


def test_gazetteer_assigns_entity_kind():
    text = "Rio Tinto reported output. Rio Tinto shares moved on the news today."
    gaz = {"rio tinto": "org"}
    ex = BaselineExtractor(gazetteer=gaz)
    by = _by_norm(ex.extract(text))
    assert by["rio tinto"].kind == "org"


def test_sentence_initial_capital_not_an_entity():
    # "Markets" only ever appears capitalised at sentence start -> not an entity.
    text = "Markets fell today. Traders worried about inflation and slowing growth."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "markets" not in {k for k, v in by.items() if v.kind != "term"}


def test_terms_have_counts_and_offsets():
    text = ("Climate policy dominated the summit. Climate policy negotiators "
            "debated climate targets and emissions for hours on end today.")
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "climate" in by and by["climate"].kind == "term"
    assert by["climate"].count >= 3
    # A bigram phrase is captured as a single term.
    assert "climate policy" in by and by["climate policy"].count >= 2
    off = by["climate"].first_offset
    assert text[off:off + 7].lower() == "climate"


def test_stopword_bounded_ngrams_are_dropped():
    text = "The cost of the project rose. The team reviewed the plan of the office."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    # No phrase should start or end with a stopword.
    assert "of the" not in by
    assert not any(t.term.split()[0] in {"the", "of"} for t in ex.extract(text) if t.kind == "term" and " " in t.term)


def test_empty_text_yields_nothing():
    assert BaselineExtractor().extract("") == []
    assert BaselineExtractor().extract("   ") == []


def test_get_extractor_spacy_falls_back_when_absent():
    # spaCy isn't installed in the core test env -> must fall back to baseline,
    # never raise.
    ex = get_extractor("spacy")
    assert ex.name == "baseline"
    assert isinstance(ex, BaselineExtractor)
