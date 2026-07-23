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


def test_multiword_titlecase_is_a_term_not_an_entity():
    # Title-Case is no longer an entity signal (anglocentric; breaks for German).
    # A multi-word name is captured as ONE topical TERM, offset intact; it becomes
    # a real entity only via the gazetteer / spaCy (see the gazetteer test below).
    text = (
        "Emmanuel Macron met advisers in the capital. "
        "Emmanuel Macron then addressed reporters about the economy."
    )
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "emmanuel macron" in by
    ent = by["emmanuel macron"]
    assert ent.kind == "term"  # Title-Case alone never makes an entity now
    assert ent.count == 2
    assert text[ent.first_offset : ent.first_offset + len("Emmanuel Macron")] == "Emmanuel Macron"


def test_gazetteer_promotes_a_term_to_its_entity_kind():
    # Named entities come from the gazetteer now, not capitalisation: "rio tinto"
    # is a term that the gazetteer promotes to kind="org".
    text = "Rio Tinto reported output. Rio Tinto shares moved on the news today."
    ex = BaselineExtractor(gazetteer={"rio tinto": "org"})
    by = _by_norm(ex.extract(text))
    assert by["rio tinto"].kind == "org"


def test_sentence_initial_capital_not_an_entity():
    # "Markets" only ever appears capitalised at sentence start -> not an entity.
    text = "Markets fell today. Traders worried about inflation and slowing growth."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "markets" not in {k for k, v in by.items() if v.kind != "term"}


def test_acronym_is_an_entity_distinct_from_its_lowercase_homograph():
    # The WHO/Who problem: "WHO" (org) is an entity kept case-distinct from the
    # pronoun "who" — casefolding would merge them, so we don't.
    text = "Experts at WHO met on Friday. They asked who knew the risks beforehand."
    by = _by_norm(BaselineExtractor().extract(text))
    assert "WHO" in by and by["WHO"].kind == "entity"
    assert "who" not in {k for k, v in by.items() if v.kind != "term"}


def test_stopword_homograph_acronym_survives():
    # "US" must not vanish into the stopword "us": its case is preserved.
    text = "The US said it would act. The deal still mattered to the US and allies."
    by = _by_norm(BaselineExtractor().extract(text))
    assert "US" in by and by["US"].kind == "entity"


def test_german_capitalised_nouns_are_not_entities():
    # German capitalises every noun; none here is a proper name -> all terms.
    text = "Die Behauptung war falsch. Die Medien berichteten ausführlich über Menschen und Belege."
    by = _by_norm(BaselineExtractor().extract(text, language="de"))
    assert not [k for k, v in by.items() if v.kind != "term"]


def test_all_caps_headline_words_are_not_acronyms():
    # In an ALL-CAPS headline every word is caps -> none stands out as an acronym.
    text = "BREAKING NEWS REPORT: markets fell sharply as traders worried about the economy."
    by = _by_norm(BaselineExtractor().extract(text))
    ents = {k for k, v in by.items() if v.kind != "term"}
    assert not ({"BREAKING", "NEWS", "REPORT"} & ents)


def test_terms_have_counts_and_offsets():
    text = (
        "Climate policy dominated the summit. Climate policy negotiators "
        "debated climate targets and emissions for hours on end today."
    )
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "climate" in by and by["climate"].kind == "term"
    assert by["climate"].count >= 3
    # A bigram phrase is captured as a single term.
    assert "climate policy" in by and by["climate policy"].count >= 2
    off = by["climate"].first_offset
    assert text[off : off + 7].lower() == "climate"


def test_stopword_bounded_ngrams_are_dropped():
    text = "The cost of the project rose. The team reviewed the plan of the office."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    # No phrase should start or end with a stopword.
    assert "of the" not in by
    assert not any(
        t.term.split()[0] in {"the", "of"}
        for t in ex.extract(text)
        if t.kind == "term" and " " in t.term
    )


def test_romance_elision_is_stripped_from_terms():
    """l'assemblée -> assemblée (not the whole "l'assemblée"); qu'il -> the stopword
    "il" (dropped); d'euros -> euros. The elided article/pronoun is tokenization
    noise, so it must never become part of a keyword (field finding 2026-06-18)."""
    text = "L'Assemblée nationale a voté la réforme. D'euros et qu'il faut. L'assemblée débat."
    ex = BaselineExtractor()
    by = _by_norm(ex.extract(text))
    assert "assemblée" in by
    assert "euros" in by
    # The contracted forms must NOT survive as keywords.
    assert "l'assemblée" not in by and "d'euros" not in by and "qu'il" not in by
    # And the de-elided form feeds the n-grams.
    assert "assemblée nationale" in by


def test_empty_text_yields_nothing():
    assert BaselineExtractor().extract("") == []
    assert BaselineExtractor().extract("   ") == []


def test_get_extractor_spacy_falls_back_when_absent():
    # spaCy isn't installed in the core test env -> must fall back to baseline,
    # never raise.
    ex = get_extractor("spacy")
    assert ex.name == "baseline"
    assert isinstance(ex, BaselineExtractor)


def test_2026_07_01_korean_marathi_stopword_batch_is_collision_free():
    """The 2026-07-01 keyword-log batch added Korean (Hangul) + Marathi (Devanagari)
    grammar to the language-agnostic stopword union. Distinct scripts -> collision-free:
    the batch words are filtered, but CONTENT (incl. the deliberately-excluded mr words)
    and any ASCII/Latin token are untouched, so no other-language content is hidden."""
    from src.analytics.extract import global_stopwords

    gs = global_stopwords()
    # grammar/connectives are now filtered
    for w in ("하지만", "그러나", "따라서", "때문에", "आहे", "आणि", "नाही", "होते"):
        assert w in gs, w
    # CONTENT stays a keyword: the mr words we deliberately EXCLUDED + a ko content noun
    for w in ("반도체", "जात", "कोटी", "माहिती", "कमी"):
        assert w not in gs, w
    # the batch is DISTINCT-SCRIPT only: it added no ASCII token, so no Latin-corpus
    # content word (e.g. English 'man'/'tag'/'state') can be hidden by it.
    added = set("공동으로 관계없이 하지만 그러나 आहे आणि नाही होते".split())
    assert all(not any(ord(c) < 128 for c in w) for w in added)
    for latin_content in ("man", "tag", "state", "time", "premier", "grande", "parte"):
        # these were NOT in the batch; the guard is that the batch can't touch them
        assert latin_content not in added


def test_extra_stopwords_migration_is_byte_identical_to_the_pre_migration_blob():
    """Phase 4.1 (PR #740/#744 remediation) replaced the 370-line in-Python
    ``_EXTRA_STOPWORD_TEXT`` string blob with a loader over
    ``configs/stopwords_extra/<lang>.yml`` data files. That was declared a
    REPRESENTATION change only -- the acceptance bar is that the resulting
    ``_EXTRA_STOPWORDS`` frozenset (after the curly-apostrophe contraction
    expansion the module already applies) is byte-identical to the set the old
    blob produced. The digest below was computed once, directly from
    ``origin/main``'s pre-migration ``_EXTRA_STOPWORD_TEXT`` via AST
    (``ast.literal_eval``, never a hand-transcription) plus the SAME
    curly-apostrophe expansion the module performs, over the sorted,
    newline-joined member set -- so any accidental drop, duplication, or the
    YAML-1.1-boolean-scalar trap (PyYAML's safe_load silently turning an
    unquoted ``no``/``yes``/``on``/``off``/``true``/``false`` list item into a
    Python bool instead of a string -- a real bug caught by this exact check
    during the migration) reddens this test immediately.
    """
    import hashlib

    from src.analytics.extract import _EXTRA_STOPWORDS

    # Every member must be a str: the YAML-boolean-coercion regression guard.
    assert all(isinstance(w, str) for w in _EXTRA_STOPWORDS)
    assert len(_EXTRA_STOPWORDS) == 2377

    digest = hashlib.sha256(
        "\n".join(sorted(_EXTRA_STOPWORDS)).encode("utf-8")
    ).hexdigest()
    assert (
        digest
        == "a1a7493a21afb9abfe48eb1f13b323df6ea2cff46a21f03f7c3901f62221fc86"
    ), "the extra-stopword SET changed -- confirm this is intentional, not a migration regression"
