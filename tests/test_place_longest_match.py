"""Longest-match place resolution (field feedback 2026-08-07, item 3 / brief slice B5).

The reader export of the UK *Data Protection Act 2018* listed ``Ireland (ie)`` among its
places. Every pattern was run independently over the whole text, so ``\\bireland\\b``
matched inside "Northern Ireland" — a UK Act filed under a different sovereign state.

That is a WRONG COUNTRY, not a noisy one, and a reader cannot tell a fabricated
attribution from a real one. The same mechanism produced ``Sudan`` from "South Sudan"
(separate states since 2011) and ``China`` from "South China Sea".

Both directions are tested throughout: the fix must not delete a place that really is
there. An over-eager span guard would look conservative while quietly dropping data.
"""

from __future__ import annotations

import pytest

from src.timemap.locextract import extract_locations


def _places(text: str) -> list[tuple[str, str | None]]:
    return [(e["name"], e.get("country")) for e in extract_locations(text)]


def _countries(text: str) -> set[str | None]:
    return {e.get("country") for e in extract_locations(text) if e["kind"] == "country"}


# --------------------------------------------------------------------------- #
# The field specimen
# --------------------------------------------------------------------------- #


def test_northern_ireland_is_the_united_kingdom_not_ireland():
    """The reported bug, in the shape it was reported."""
    text = "This Part extends to England, Wales and Northern Ireland."
    assert "ie" not in _countries(text), "a UK Act must not be attributed to Ireland"
    assert "gb" in _countries(text)


def test_the_republic_is_still_ireland():
    """The twin. Suppressing the wrong answer must not suppress the right one."""
    assert "ie" in _countries("An agreement with the Republic of Ireland was signed.")
    assert "ie" in _countries("The delegation travelled to Ireland.")


@pytest.mark.parametrize(
    "text,wrong,right",
    [
        ("Aid reached South Sudan this week.", "sd", "ss"),
        ("The Republic of the Congo held elections.", "cd", "cg"),
        ("Fighting continued in the Democratic Republic of the Congo.", "cg", "cd"),
    ],
)
def test_a_longer_country_name_beats_the_shorter_one_nested_in_it(text, wrong, right):
    got = _countries(text)
    assert wrong not in got, f"{text!r} must not resolve to {wrong}"
    assert right in got


@pytest.mark.parametrize(
    "text,code",
    [
        ("Flooding across Sudan displaced thousands.", "sd"),
        ("A summit in Congo was announced.", "cd"),
    ],
)
def test_the_bare_names_still_resolve(text, code):
    """The negative-space twin for the pair above."""
    assert code in _countries(text)


# --------------------------------------------------------------------------- #
# Span guards: a claimed span that asserts nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,must_not",
    [
        ("Tensions rose in the South China Sea last month.", "cn"),
        ("A vessel crossed the East China Sea.", "cn"),
        ("Currents in the Sea of Japan were measured.", "jp"),
        ("An oil spill in the Gulf of Mexico spread north.", "mx"),
        ("The New Mexico legislature met on Tuesday.", "mx"),
        ("A restaurant in Little Italy closed.", "it"),
    ],
)
def test_a_feature_named_after_a_country_is_not_that_country(text, must_not):
    """Attributing a contested sea to one claimant is a loaded fabrication, not noise."""
    assert must_not not in _countries(text)


@pytest.mark.parametrize(
    "text,code",
    [
        ("Exports from China rose.", "cn"),
        ("The delegation flew to Japan.", "jp"),
        ("Mexico signed the accord.", "mx"),
        ("A vote in Italy was delayed.", "it"),
    ],
)
def test_the_guarded_countries_still_resolve_on_their_own(text, code):
    """The mandatory twin: a guard must claim its phrase, not the country's name."""
    assert code in _countries(text)


def test_a_guard_does_not_swallow_a_country_elsewhere_in_the_sentence():
    """The guard claims only its own characters."""
    got = _countries("Talks on the South China Sea were hosted by France.")
    assert "fr" in got
    assert "cn" not in got


# --------------------------------------------------------------------------- #
# Canonicalisation: one country, one entry
# --------------------------------------------------------------------------- #


def test_surface_forms_of_one_country_collapse_into_one_place():
    """The same export showed Uk / United Kingdom / Britain as three separate places."""
    out = extract_locations("The UK, Britain and the United Kingdom are named here.")
    gb = [e for e in out if e.get("country") == "gb"]
    assert len(gb) == 1, f"one country, one entry — got {[e['name'] for e in gb]}"
    assert gb[0]["mentions"] == 3, "the mentions of every surface form must sum"
    assert gb[0]["name"] == "United Kingdom", "render the canonical name, not what matched"


def test_two_different_countries_stay_two_places():
    """The twin: canonicalising must merge surface forms, never distinct countries."""
    out = extract_locations("Both France and Germany objected.")
    assert {e.get("country") for e in out} == {"fr", "de"}


# --------------------------------------------------------------------------- #
# Nothing else regressed
# --------------------------------------------------------------------------- #


def test_multiple_places_are_still_found_and_ordered_by_mentions():
    text = "France said France would act. Germany disagreed."
    out = [e for e in extract_locations(text) if e["kind"] == "country"]
    assert out[0]["country"] == "fr" and out[0]["mentions"] == 2
    assert {e["country"] for e in out} == {"fr", "de"}


def test_empty_and_placeless_text_yield_nothing():
    assert extract_locations("") == []
    assert extract_locations("The committee met to discuss the quarterly budget.") == []


def test_every_result_still_carries_its_deduced_note():
    """The honesty contract of this extractor: a name match, never a confirmed site."""
    for entry in extract_locations("A hearing in France and Northern Ireland."):
        assert "deduced" in entry["note"]
