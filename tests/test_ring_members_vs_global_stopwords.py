"""One language's grammar must not silently delete another language's CONCEPT.

WHY THIS FILE EXISTS. `docs/ledger/OPEN_QUEUE.md`'s KEYWORD STOPLIST entry carries a
REMAINING item (3): French publishing furniture ("publicité"/"contenu") leaks into
extracted keywords, and the note says a French batch "would globalise
(collision-check needed); low-df, deferred". THE COLLISION CHECK WAS RUN (2026-09-09)
AND IT SAYS NO -- `fr:publicité` and `fr:publicités` are the French MEMBERS of the
Wikidata-verified `advertising` ring (Q37038). Adding them to the only channel
French can reach would have deleted the French side of a concept the English side
keeps, which is precisely the blind-by-language filter the maintainer REJECTED on
2026-06-19 ("we shouldn't blind a user from foreign language keyword trends").

Running the check turned up something the docket did not know: THE SAME THING IS
ALREADY HAPPENING, in the other direction, unmeasured. `StopwordsManager` tests
`language_stopwords` first and holds exactly `en` and `fr`, and
`analytics.extract.global_stopwords()` unions EVERY per-language list into one
language-agnostic set -- so a word that is grammar in Danish silences it as content
everywhere. `fr:dette` (the French member of the `debt` ring) is invisible because
"dette" means "this" in Danish/Norwegian. `pt:lei` (statute) falls to Italian "lei".
`pt:solo` (soil) falls to Spanish/Italian "solo". And `de:Podcast`/`fr:podcast`/
`pt:podcast` are removed from the `podcast` ring by the deliberate global
`PLATFORM_STOPWORDS` entry for "podcast" -- the furniture rule eating its own ring.

WHAT THIS FILE DOES, AND WHAT IT DELIBERATELY DOES NOT. It does not fix the
architecture: making the scoped channel reachable for `en`/`fr` is a stoplist
ARCHITECTURE change (`get_stopwords`'s branch order is load-bearing and its docstring
says so), it interacts with the month-occupancy work, and choosing it needs corpus
measurement this sandbox has no corpus for. So this is a RATCHET: the number of
cross-language kills is pinned at what it is today and may not grow, and the twin
test keeps the ceiling honest.

WHICH TEST CATCHES WHAT, stated because the two are not interchangeable and the
difference is easy to assume away. The RATCHET catches an addition to `en` (or any
list) that kills a ring member in a DIFFERENT language -- verified against a mutant
putting "publicité" in `PLATFORM_STOPWORDS`, which took the count 38 -> 40. It does
NOT catch the French batch this file is named for: a word added to `LANGUAGE_STOPWORDS
["fr"]` is stoplisted by fr's own list too, so by this file's own definition it stops
being a CROSS-language kill and the count does not move. The NAMED COUNTEREXAMPLE
test below is what fails there, and it is the one that quotes the ring.
"""

from __future__ import annotations

import pytest

from src.analytics.equivalence import load_rings
from src.analytics.extract import global_stopwords
from src.services.stopwords import stopwords_manager

# Zero slack, per the house ratchet rule: a ratchet with room is a ratchet that does
# nothing. Lower it when a kill is genuinely resolved; NEVER raise it to make room.
_CROSS_LANGUAGE_RING_KILLS = 38


def _cross_language_kills() -> list[tuple[str, str, str]]:
    """Ring members that are content in THEIR OWN language and grammar in another.

    Read through the real loader (`load_rings`), never a hand-parse of the YAML: the
    guard must measure what the app resolves, including the curated file's overrides.
    Multi-word members are excluded because the stoplist is a UNIGRAM filter -- it
    cannot remove "contenu CO2" by holding "contenu". A member its OWN language also
    stoplists (`pt:tempo` in Portuguese) is a different, defensible case and is not
    counted here.
    """
    every = global_stopwords()
    out: list[tuple[str, str, str]] = []
    for ring in load_rings():
        for lang, term in ring.members:
            if not term or " " in term:
                continue
            if term in every and term not in stopwords_manager.get_stopwords(lang):
                out.append((ring.id, lang, term))
    return sorted(out)


def test_cross_language_ring_kills_do_not_grow():
    kills = _cross_language_kills()
    assert len(kills) <= _CROSS_LANGUAGE_RING_KILLS, (
        "A stopword addition made one more concept invisible in a language that "
        "spells it as content. New kills:\n  "
        + "\n  ".join(f"{r}: {lang}:{t}" for r, lang, t in kills[_CROSS_LANGUAGE_RING_KILLS:])
        + "\n\nA word added to LANGUAGE_STOPWORDS['en'|'fr'] becomes GLOBAL "
        "(analytics.extract.global_stopwords unions every list). If the word is a "
        "ring member in some language, that language loses the concept while the "
        "others keep it -- the blind-by-language filter ruled out on 2026-06-19."
    )


def test_the_ratchet_equals_the_real_count():
    """The twin. A ceiling left above the real number is slack, and slack is how a
    ratchet quietly stops ratcheting."""
    assert len(_cross_language_kills()) == _CROSS_LANGUAGE_RING_KILLS


@pytest.mark.parametrize("term", ["publicité", "publicités"])
def test_the_french_advertising_batch_is_refused_and_here_is_the_ring_it_would_break(term):
    """The named counterexample for the exact edit the docket contemplated.

    Kept as its own test rather than left in prose because the next stoplist pass will
    reach for precisely this change -- the docket even pre-authorises it pending "a
    collision check". This IS the collision check, and it fails."""
    ring = next((r for r in load_rings() if r.id == "advertising"), None)
    assert ring is not None, "the advertising ring is the evidence; it must exist"
    assert ("fr", term) in ring.members, f"fr:{term} is a member of the advertising ring"
    assert term not in global_stopwords(), (
        f"{term!r} was added to the global stopword channel. French can only reach that "
        "channel, so this hides the French side of the advertising ring while English "
        "'advertising' stays visible. That is the rejected blind-by-language filter."
    )


def test_contenu_is_only_ever_a_multi_word_ring_member_so_the_unigram_case_differs():
    """Honesty about the OTHER half of the docket's pair: 'contenu' appears in the
    rings only inside `fr:contenu CO2` (carbon-footprint), which a unigram stoplist
    cannot remove. So the refusal above rests on publicité, not on contenu -- and
    this test records that difference instead of letting one word's evidence be
    quietly borrowed for the other."""
    hits = [
        (r.id, term)
        for r in load_rings()
        for lang, term in r.members
        if lang == "fr" and "contenu" in term.split()
    ]
    assert hits, "expected fr:contenu CO2 in the carbon-footprint ring"
    assert all(" " in term for _, term in hits), (
        "A single-word fr:contenu ring member now exists, so stoplisting 'contenu' "
        "would break it too -- re-read the refusal above with this new evidence."
    )


def test_the_podcast_ring_shows_the_mechanism_eating_its_own_furniture_rule():
    """The self-demonstrating case, pinned so the irony cannot be lost in a refactor:
    'podcast' is a DELIBERATE global furniture stopword, and the `podcast` ring's own
    non-English members are exactly what that removes."""
    every = global_stopwords()
    assert "podcast" in every, "podcast is deliberate platform furniture (PLATFORM_STOPWORDS)"
    ring = next((r for r in load_rings() if r.id == "podcast"), None)
    assert ring is not None
    killed = [f"{lang}:{t}" for lang, t in ring.members if t in every]
    assert killed, "the podcast ring should still show the collision this test describes"
