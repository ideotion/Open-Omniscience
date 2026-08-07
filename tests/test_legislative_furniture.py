"""Legislative structural headings are not organisations (2026-08-07, brief slice B4).

The reader export of the UK *Data Protection Act 2018* carried ``PART`` twenty-four
times as an ORGANIZATION. Statute text is full of shouted structural headings, so every
tracked legal document manufactures the same false entity — and the law vertical is
about to grow from ~23 documents to whole national corpora.

The twin matters more than usual here: these words are ordinary English. The rule must
demote only the shouted ALL-CAPS heading and leave the lowercase content word — a
"part" of a whole, an "article" of clothing — untouched in the index.
"""

from __future__ import annotations

import pytest

from src.analytics.extract import BaselineExtractor


def _extract(text: str):
    return BaselineExtractor().extract(text, language="en")


def _kinds(text: str, term: str) -> set[str]:
    return {t.kind for t in _extract(text) if t.normalized.lower() == term}


def _terms(text: str) -> set[str]:
    return {t.normalized.lower() for t in _extract(text)}


LEGISLATIVE = ["PART", "SCHEDULE", "CHAPTER", "SECTION", "ANNEX", "APPENDIX", "ARTICLE"]


@pytest.mark.parametrize("word", LEGISLATIVE)
def test_a_shouted_structural_heading_is_never_an_entity(word):
    text = (
        f"{word} 3 sets out the general processing rules. "
        f"{word} 4 concerns law enforcement processing, and {word} 5 the intelligence "
        f"services. The Commissioner must publish guidance under {word} 6."
    )
    assert "entity" not in _kinds(text, word.lower()), (
        f"{word} is a heading in a statute, not an organisation"
    )


def test_the_field_specimen_shape():
    """PART repeated the way the Act repeats it."""
    text = " ".join(f"PART {i} of this Act applies to processing." for i in range(1, 25))
    assert "entity" not in _kinds(text, "part")


# --------------------------------------------------------------------------- #
# The twin: the lowercase content words are untouched
# --------------------------------------------------------------------------- #


def test_the_lowercase_content_words_survive_as_terms():
    """These are ordinary English. Removing them from the index would be the worse bug.

    Only the five that are not ALREADY global stopwords are asserted here. "article" and
    "part" were stoplisted long before this change, for reasons of their own — asserting
    them would be claiming credit for a behaviour this fix neither created nor touched,
    and the assertion would fail against clean `src`. The membership test below is what
    actually pins that this list did not reach the lowercase path.
    """
    text = (
        "The report described a difficult section of the route. Each half of the "
        "chapter was revised, and the appendix listed every schedule of works. "
        "The annex covered the remaining items."
    )
    terms = _terms(text)
    for word in ("section", "chapter", "appendix", "schedule", "annex"):
        assert word in terms, f"the lowercase content word {word!r} must stay indexed"


def test_the_rule_reads_the_shouted_surface_only():
    """The mechanism, not a sample of it: the check is on the ALL-CAPS token.

    A future refactor that moved this list into the term pipeline would delete five
    ordinary English words from every corpus, and the sample above would not
    necessarily catch it.
    """
    import inspect

    from src.analytics.extract import BaselineExtractor as _BE

    body = inspect.getsource(_BE._entities)
    assert "_LEGISLATIVE_FURNITURE_STOP" in body, (
        "the legislative list belongs to the ENTITY (acronym) path; if it moves to the "
        "term path it silently removes 'section'/'chapter'/'schedule' from the index"
    )
    assert "_LEGISLATIVE_FURNITURE_STOP" not in inspect.getsource(_BE._terms)


def test_a_real_all_caps_acronym_is_still_an_entity():
    """The stoplist must not have widened into the acronym detector generally."""
    text = (
        "The WHO published new guidance this week. The WHO statement followed a UNESCO "
        "report, and the WHO confirmed the finding."
    )
    assert "entity" in _kinds(text, "who")


def test_the_two_furniture_lists_stay_disjoint_and_lowercase():
    """A duplicate across the two lists would hide which evidence added a word.

    Both are matched with `.casefold()`, so an uppercase entry would silently never fire.
    """
    from src.analytics.extract import _CAPS_FURNITURE_STOP, _LEGISLATIVE_FURNITURE_STOP

    assert not (_CAPS_FURNITURE_STOP & _LEGISLATIVE_FURNITURE_STOP)
    for word in _LEGISLATIVE_FURNITURE_STOP:
        assert word == word.casefold(), f"{word!r} would never match"


def test_no_legislative_word_is_also_a_roman_numeral_needing_the_allowlist():
    """Guards against a future addition (e.g. "DIVISION"? no — but "MIX"/"CIV" shapes)
    silently colliding with the strict Roman-numeral exclusion below it in the module."""
    from src.analytics.extract import _LEGISLATIVE_FURNITURE_STOP, _is_strict_roman_numeral

    for word in _LEGISLATIVE_FURNITURE_STOP:
        assert not _is_strict_roman_numeral(word.upper()), word
