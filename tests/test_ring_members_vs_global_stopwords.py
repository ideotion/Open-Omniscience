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

**RESOLVED 2026-09-30 (R102, D24, the maintainer's «4 = yes»): the ratchet below reached ZERO.**
`analytics.extract` now EXEMPTS a ring member from the language-agnostic union when it is a
single word that only ANOTHER language's list holds: `global_stopwords()` (the query-time
layer) drops it, and `_stopset(language)` (extraction) lifts it only in the language whose
ring names it. A member its OWN language stoplists (the vendored list or that language's
curated `stopwords_extra` file: French "tout", English "work") stays hidden, which is the
"different, defensible case" the helper below always excluded. The tests at the end pin the
list, the per-language behaviour and the two refusals.

WHAT THIS FILE DID BEFORE THAT, AND WHAT IT DELIBERATELY DID NOT. It does not fix the
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

from functools import lru_cache

import pytest

from src.analytics.equivalence import shipped_rings
from src.analytics.extract import (
    BaselineExtractor,
    _global_stopwords_raw,
    _load_extra_stopwords_by_language,
    _stopset,
    global_stopwords,
    ring_member_exemptions,
)
from src.services.stopwords import stopwords_manager

# Zero slack, per the house ratchet rule: a ratchet with room is a ratchet that does
# nothing. It was 38 until R102 exempted the ring members; NEVER raise it to make room.
_CROSS_LANGUAGE_RING_KILLS = 0


def _cross_language_kills() -> list[tuple[str, str, str]]:
    """Ring members that are content in THEIR OWN language and grammar in another.

    Read through the real loader (`shipped_rings`), never a hand-parse of the YAML: the
    guard must measure what the app resolves, including the curated file's overrides.
    Multi-word members are excluded because the stoplist is a UNIGRAM filter -- it
    cannot remove "contenu CO2" by holding "contenu". A member its OWN language also
    stoplists (`pt:tempo` in Portuguese) is a different, defensible case and is not
    counted here.
    """
    every = global_stopwords()
    extra = _load_extra_stopwords_by_language()
    out: list[tuple[str, str, str]] = []
    for ring in shipped_rings():
        for lang, term in ring.members:
            if not term or " " in term:
                continue
            own = stopwords_manager.get_stopwords(lang) | extra.get(lang, frozenset())
            if term in every and term not in own:
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
    ring = next((r for r in shipped_rings() if r.id == "advertising"), None)
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
        for r in shipped_rings()
        for lang, term in r.members
        if lang == "fr" and "contenu" in term.split()
    ]
    assert hits, "expected fr:contenu CO2 in the carbon-footprint ring"
    assert all(" " in term for _, term in hits), (
        "A single-word fr:contenu ring member now exists, so stoplisting 'contenu' "
        "would break it too -- re-read the refusal above with this new evidence."
    )


def test_the_podcast_ring_is_shown_in_its_own_languages_and_stays_furniture_elsewhere():
    """'podcast' is deliberate platform furniture (PLATFORM_STOPWORDS) and ALSO the German,
    French and Portuguese member of the `podcast` ring. Before R102 the furniture rule ate
    the ring's own members. Now extraction lifts it exactly in the languages whose ring names
    it; English (its own list) and every language with no such member still hide it."""
    assert "podcast" in _global_stopwords_raw(), "podcast is deliberate platform furniture"
    ring = next((r for r in shipped_rings() if r.id == "podcast"), None)
    assert ring is not None
    for lang in ("de", "fr", "pt"):
        assert (lang, "podcast") in {(lg, t.lower()) for lg, t in ring.members}
        assert "podcast" not in _stopset(lang), lang
    for lang in ("en", "es", "it", "nl"):
        assert "podcast" in _stopset(lang), lang


# The 30 ring members R102 shows again, by language. Explicit on purpose: it is the list the
# maintainer was promised in the pull request, and a ring or stoplist change that moves it
# should be read, not absorbed. It was 34 until the maintainer's answer 12 = a kept four of the
# fourteen proposed words hidden: German "all", Spanish "are", English "bio" and "uno".
_EXEMPT = {
    "ar": {"o"},
    "bn": {"u"},
    "de": {"bio", "os", "podcast", "re", "un", "uno"},
    "en": {"os", "u", "un", "war"},
    "es": {"az", "so"},
    "fr": {"dette", "jo", "os", "photo", "podcast"},
    "id": {"so", "u"},
    "ja": {"o", "os"},
    "pt": {"al", "am", "lei", "podcast", "so", "solo", "u"},
}


def test_the_exempted_ring_members_are_exactly_the_promised_list():
    got = {lang: set(words) for lang, words in ring_member_exemptions().items()}
    assert got == _EXEMPT
    assert sum(len(w) for w in got.values()) == 30


def test_a_word_its_own_language_stoplists_stays_hidden():
    """The refusal that keeps the exemption honest: French 'tout' and English 'work' are in
    ring members of `universe` and `occupation`, but their OWN language's curated list holds
    them, so they were never a cross-language kill and stay hidden."""
    assert "tout" in _stopset("fr") and "tout" in global_stopwords()
    assert "work" in _stopset("en") and "work" in global_stopwords()


def test_the_four_words_the_maintainer_kept_hidden_stay_hidden():
    """Answer 12 = a: German "all", Spanish "are", English "bio" and "uno" are hidden, by
    putting each in its OWN language's curated list (which the exemption rule already
    respects). German "bio"/"uno" are German content and stay shown."""
    for lang, word in (("de", "all"), ("es", "are"), ("en", "bio"), ("en", "uno")):
        assert word in _stopset(lang), (lang, word)
        assert word not in ring_member_exemptions().get(lang, ()), (lang, word)
    # The query layer has no language: "bio"/"uno" stay out of it because German still shows
    # them (a keyword only reaches the store through extraction, which hides them in English).
    assert "all" in global_stopwords() and "are" in global_stopwords()
    assert "bio" not in _stopset("de") and "uno" not in _stopset("de")


def test_the_same_spelling_is_content_in_one_language_and_grammar_in_another():
    """The whole point, on real text through the real extractor: French 'dette' (debt) is
    kept, while the Danish grammar word that hid it still is Danish grammar."""
    assert "dette" not in _stopset("fr") and "dette" in _stopset("da")
    b = BaselineExtractor()
    fr = {t.term for t in b._terms("La dette publique augmente", "fr")}
    da = {t.term for t in b._terms("dette er en dette", "da")}
    assert "dette" in fr
    assert "dette" not in da
    en = {t.term for t in b._terms("the war and the bio", "en")}
    # English 'war' was hidden by the German grammar word 'war'; 'bio' is one of the four
    # kept hidden on purpose (12 = a).
    assert "war" in en and "bio" not in en
    de = {t.term for t in b._terms("Er war da", "de")}
    assert "war" not in de  # German keeps its own grammar word out


def test_the_query_time_union_lets_a_stored_member_through_but_extraction_stays_per_language():
    """global_stopwords() has no language, and a keyword only reaches the store through
    extraction, so the query layer drops every exempted member; a language WITHOUT the member
    (Spanish 'podcast') is still filtered at extraction and never stored."""
    every = global_stopwords()
    for words in _EXEMPT.values():
        assert not (set(words) & every)
    assert "podcast" in _stopset("es")


def test_a_ring_reload_refreshes_the_exemptions(monkeypatch):
    """Review finding: the exemption set is memoised on top of the rings, so a restore or a
    Wikidata ring load (both call invalidate_ring_caches) must refresh it, or a removed ring
    keeps exempting and a new one stays hidden until restart."""
    from src.analytics import equivalence, extract

    assert "dette" in ring_member_exemptions().get("fr", frozenset())
    real = equivalence.shipped_rings
    monkeypatch.setattr(equivalence, "shipped_rings", lru_cache(maxsize=1)(lambda: ()))
    try:
        equivalence.invalidate_ring_caches()
        assert ring_member_exemptions() == {}
        assert "dette" in _stopset("fr")
    finally:
        monkeypatch.setattr(equivalence, "shipped_rings", real)
        equivalence.invalidate_ring_caches()
    assert "dette" in ring_member_exemptions().get("fr", frozenset())
    assert "dette" not in extract._stopset("fr")


def test_the_ring_grouping_switch_does_not_change_what_extraction_keeps(monkeypatch):
    """OO_KEYWORD_EQUIV turns off ring GROUPING; it is not in the engine identity's switches, so
    the stoplist exemptions must not depend on it (two installs, one stamp, one set of rows)."""
    from src.analytics import equivalence

    with_rings = {lang: set(w) for lang, w in ring_member_exemptions().items()}
    monkeypatch.setenv("OO_KEYWORD_EQUIV", "0")
    equivalence.invalidate_ring_caches()
    try:
        assert {lang: set(w) for lang, w in ring_member_exemptions().items()} == with_rings
    finally:
        monkeypatch.undo()
        equivalence.invalidate_ring_caches()
