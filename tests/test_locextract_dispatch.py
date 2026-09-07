"""The location extractor's dispatch must find exactly what the old scan found (PRH-05).

``extract_locations`` used to run every compiled pattern over the whole article. With the
bundled 21-city sample that is ~160 scans and invisible; with the gazetteer
``build_city_gazetteer.py`` generates it is thousands, measured at 2,173 ms for one
5,000-word body at 4,500 cities. The patterns are now split: the case-INSENSITIVE half
(span guards + the country table, a module constant) keeps its scan, and the
case-SENSITIVE half (the cities, the half that scales) is looked up by the leading word
run of each name and confirmed with the same compiled pattern.

That is a change to HOW candidates are found and must be no change at all to WHAT is
found. A 4,500-city differential over ~22,000 (text x source_country) pairs -- adversarial
nesting, casing, boundaries, punctuation, unicode, plus randomised prose -- reported zero
differences; these are the properties that would break silently if the dispatch drifted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

from src.timemap.locextract import _dispatch, _patterns, extract_locations


def _names(entries) -> list[str]:
    return [e["name"] for e in entries]


def test_the_dispatch_partitions_every_pattern_exactly_once():
    """THE SILENT-LOSS GUARD. A name that reaches neither half is simply never looked
    for, and nothing else in the extractor would say so -- the place just stops being
    found. Every pattern must land in exactly one half, and the two halves must
    reconstruct the whole list."""
    scan, index = _dispatch()
    scanned = [i for i, _rx, _n, _k in scan]
    indexed = [i for bucket in index.values() for i, _rx, _n, _k in bucket]
    assert not set(scanned) & set(indexed), "a pattern must not be in both halves"
    assert sorted(scanned + indexed) == list(range(len(_patterns()))), (
        "every pattern must be in exactly one half"
    )


def test_the_index_key_is_the_name_s_leading_word_run():
    """The lookup only works because a match at a word start implies the text's word run
    there EQUALS the name's leading word run -- the name either ends (so the trailing \\b
    forces a non-word character next) or continues with a non-word character of its own.
    A multi-word or hyphenated name is the case that would break a whole-name key."""
    _scan, index = _dispatch()
    for key, bucket in index.items():
        for _i, _rx, name, _kind in bucket:
            head = re.match(r"\w+", name)
            assert head is not None and head.start() == 0
            assert head.group(0) == key, f"{name!r} indexed under {key!r}"


def test_the_case_insensitive_half_is_never_indexed():
    """Deliberate, and the reason is a false-NEGATIVE hazard, not tidiness: re.IGNORECASE
    and str.lower() disagree on real input (``"İ".lower()`` is ``i`` + a combining dot,
    yet IGNORECASE matches ``İSTANBUL`` against ``istanbul``), so an exact token key over
    that half could miss a match the old scan found. It is also a fixed ~140 entries, so
    it does not scale with anything."""
    _scan, index = _dispatch()
    for bucket in index.values():
        for _i, rx, name, _kind in bucket:
            assert not (rx.flags & re.IGNORECASE), f"{name!r} is indexed but case-insensitive"
    assert re.compile("istanbul", re.IGNORECASE).match("İSTANBUL"), (
        "the premise: IGNORECASE matches where an exact lower() key would miss"
    )


def test_longest_match_still_claims_the_span():
    """The rule the candidate replay exists to preserve. Each of these was a real
    mis-resolution before the claim rule, and each is a WRONG country rather than a noisy
    one -- a reader cannot tell a fabricated attribution from a real one."""
    assert "Ireland" not in _names(extract_locations("A Northern Ireland statute."))
    assert "Sudan" not in _names(extract_locations("Aid reached South Sudan this week."))
    assert "China" not in _names(extract_locations("Vessels crossed the South China Sea."))
    # and the shorter name still resolves when it stands alone
    assert "Ireland" in _names(extract_locations("A statute of Ireland."))


def test_a_multi_word_name_is_confirmed_by_the_pattern_not_by_its_first_word():
    """THE CASE THAT MAKES THE VERIFICATION LOAD-BEARING. The index is keyed on a name's
    leading word run, so for a single-token city the key IS the whole name and the
    ``rx.match`` afterwards can only agree. For a multi-word one it cannot: without the
    confirmation, any word run equal to the first token proposes the whole name, and the
    extractor FABRICATES a place -- measured, "New arrivals were reported." yields New
    York and "The Mexico ministry said." yields Mexico City instead of Mexico. A wrong
    attribution is the one failure a reader cannot tell from a real one, which is why the
    candidate is confirmed against the compiled pattern rather than trusted."""
    assert _names(extract_locations("New arrivals were reported.")) == []
    assert _names(extract_locations("The Mexico ministry said.")) == ["Mexico"]


def test_a_shorter_name_starting_earlier_does_not_win_the_span():
    """THE CASE THAT DISTINGUISHES PATTERN ORDER FROM TEXT ORDER, and the one a
    leftmost-first replay gets wrong. Ordering candidates by position alone looks
    equivalent -- "Northern Ireland" starts before "Ireland", so leftmost also wins there
    -- but here the shorter name starts EARLIER: the guard "New Mexico" opens at 0 and
    the city "Mexico City" at 4. Pattern order (longest first) gives the city the span;
    position order gives it to the guard, which asserts nothing, and the city silently
    disappears. Measured: the correct replay yields Mexico City + Mexico, a position-only
    sort yields Mexico alone.

    Without this the pattern-order replay could be deleted and every other test here,
    including the whole longest-match suite, would still pass."""
    names = _names(extract_locations("New Mexico City and Mexico City and Mexico"))
    assert "Mexico City" in names, "the guard must not swallow a longer city name"


def test_a_name_without_word_boundaries_is_not_a_place():
    """NEGATIVE SPACE. The index proposes candidates by word run; the compiled pattern is
    what refuses them. A substring inside a longer word must stay a non-match."""
    for text in ("chinatown", "xIrelandy", "Mexicos", "unitedstates"):
        assert extract_locations(text) == [], f"{text!r} must yield no place"


def test_cities_stay_case_sensitive_and_countries_do_not():
    """The two halves differ in case sensitivity, and that difference is load-bearing:
    city names collide with common words, country names do not."""
    assert "Paris" in _names(extract_locations("Reported from Paris on Monday."))
    assert "Paris" not in _names(extract_locations("Reported from paris on Monday."))
    for spelling in ("France", "france", "FRANCE"):
        assert "France" in _names(extract_locations(f"Reported from {spelling} on Monday."))


def test_the_snippet_belongs_to_the_match_that_produced_it():
    """The candidate loop no longer holds a live match object, so the snippet is cut from
    the claimed span. An early draft read a leaked variable from the scan half and gave
    every indexed match some other pattern's snippet -- caught by the differential, not by
    any assertion over the names, because the names were right."""
    text = "Filed from Paris. " + ("filler words here. " * 20) + "Also from Berlin."
    for entry in extract_locations(text):
        assert entry["name"] in entry["snippet"], (
            f"{entry['name']!r} snippet {entry['snippet']!r} does not contain it"
        )
