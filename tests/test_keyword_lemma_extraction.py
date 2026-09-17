"""Lemmatisation AT EXTRACTION — the invariants that bound it (Q416 = a, brief S04-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The change rewrites the STORED keyword key for every article ever indexed, so what is
pinned here is not "it lemmatises" but the three properties that bound the blast radius:

  * it may only ever MERGE (no input makes a previously-extracted term disappear),
  * it is IDEMPOTENT (re-indexing an already-lemmatised corpus is a no-op, which is
    exactly what the migration job will do, twice, on a paused-and-resumed run),
  * it is per-LANGUAGE (one language's morphology never rewrites another's word).

Plus the honest-degrade twin, which must still RUN where the lemmatiser is absent.
"""

from __future__ import annotations

import pytest

from src.analytics import lemma as lemma_mod
from src.analytics.extract import BaselineExtractor
from src.analytics.lemma import (
    LEMMA_LANGS,
    REASON_NO_LIBRARY,
    REASON_UNSEGMENTED,
    REASON_UNSUPPORTED,
    extraction_lemma,
    lemma_status,
    lemmatize,
    lemmatizer_available,
)

_needs_lemmatizer = pytest.mark.skipif(
    not lemmatizer_available(), reason="simplemma not importable here"
)

# Deliberately mixed: inflected forms that SHOULD merge, designations that must not be
# touched, a stopword-adjacent word, and an n-gram whose tokens are themselves inflected.
_EN = (
    "Researchers study climate policy. The study of studies shows that studies about "
    "climate studies matter. Election results and elections again, elections. "
    "The A-10 jet and COVID-19 and MP3 files were discussed alongside the economy."
)


def _terms(text: str, language: str, *, lemma: bool, monkeypatch) -> dict[str, tuple[str, int]]:
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1" if lemma else "0")
    out = BaselineExtractor().extract(text, language=language)
    return {t.normalized: (t.term, t.count) for t in out if t.kind == "term"}


@_needs_lemmatizer
def test_lemmatisation_only_ever_merges_and_never_loses_a_term(monkeypatch):
    """THE invariant. Every key the un-lemmatised extractor produced must still be
    REACHABLE — either unchanged, or folded into a key that is present — and the total
    occurrence count must be conserved exactly. A rule that could DROP a term would make
    this change unbounded over a corpus nobody can re-read."""
    off = _terms(_EN, "en", lemma=False, monkeypatch=monkeypatch)
    on = _terms(_EN, "en", lemma=True, monkeypatch=monkeypatch)

    # Anti-vacuity FIRST: if the two agree, this test proves nothing at all about merging.
    assert set(off) != set(on), "fixture does not exercise lemmatisation — nothing merged"

    assert sum(c for _, c in off.values()) == sum(c for _, c in on.values()), (
        "lemmatisation changed the total occurrence count; it may only regroup"
    )
    for key in off:
        folded = extraction_lemma(key, "en", kind="term")
        assert key in on or folded in on, f"term lost entirely: {key!r}"


@_needs_lemmatizer
def test_a_lemma_that_would_be_filtered_never_deletes_the_term(monkeypatch):
    """The guard inside `_key_for`, and the measurement that justifies it.

    Lemmatising a real CONTENT noun can land it on a stoplisted form: measured against
    this tree's own English stopset, `cars` -> `car`, `ways` -> `way`, `ends` -> `end`
    and `owns` -> `own` are ALL stoplisted, and `ads` -> `ad` falls below the 3-character
    term floor.

    WHAT THE UNGUARDED VERSION ACTUALLY DOES, measured by running it rather than reasoned
    about: it does not delete the row, it RENAMES it -- the mutant stored `car` with the
    four occurrences of `cars` under it, because the stoplist is checked against the
    SURFACE token before the key is chosen. That is worse than it looks and worse than
    deletion would be honest about: the index gains a key the stoplist exists to exclude,
    every stoplist-aware surface downstream then hides it, and the term is invisible with
    no row missing anywhere to show for it. `ads` goes the same way, under a key shorter
    than the floor that admitted it.

    So the rule is that a lemma is adopted only when it would itself have survived every
    filter the surface form just survived; otherwise the surface form stays its own key.
    A miss costs a merge; adopting costs the word."""
    from src.analytics.extract import _stopset, _term_floor

    stop = _stopset("en")
    # ANTI-VACUITY: this test means nothing unless the premise still holds. If a future
    # stoplist change removes `car`, this fails here rather than passing for free below.
    assert lemmatize("cars", "en") == "car" and "car" in stop
    assert lemmatize("ads", "en") == "ad" and len("ad") < _term_floor("ad", False)

    text = ("Electric cars dominate the market. Cars and more cars were counted, and the "
            "ads about cars ran everywhere; ads and ads again across the campaign.")
    on = _terms(text, "en", lemma=True, monkeypatch=monkeypatch)
    assert "cars" in on, "a content noun was deleted because its lemma is a stopword"
    assert "ads" in on, "a content noun was deleted because its lemma is below the floor"
    assert "car" not in on and "ad" not in on


@_needs_lemmatizer
def test_a_designation_is_never_rewritten(monkeypatch):
    """The negative space: hyphenated/digit-bearing designations and n-grams are outside
    the rule, so they must come through byte-identical. An over-eager lemmatiser reads as
    'conservative' while quietly rewriting `covid-19`."""
    on = _terms(_EN, "en", lemma=True, monkeypatch=monkeypatch)
    for designation in ("a-10", "covid-19", "mp3"):
        assert designation in on, f"designation rewritten or dropped: {designation}"
    assert "study climate policy" in on, "an n-gram must not be lemmatised"


@_needs_lemmatizer
def test_lemmatisation_is_idempotent(monkeypatch):
    """Re-running extraction over already-lemmatised keys must change nothing.

    This is the property the MIGRATION rests on: a resumable re-normalisation job that
    is paused and resumed re-reads articles it has already done, and a rule that is not
    idempotent would walk the key one step further on every pass. The recorded trap is a
    parser fed its own output — pinned here as an equality, not assumed."""
    for word in ("studies", "study", "elections", "election", "researchers", "researcher"):
        once = lemmatize(word, "en")
        assert lemmatize(once, "en") == once, f"not idempotent: {word!r} -> {once!r}"

    on1 = _terms(_EN, "en", lemma=True, monkeypatch=monkeypatch)
    # Feed the already-lemmatised KEYS back through as a document.
    on2 = _terms(" ".join(k for k in on1 if " " not in k), "en", lemma=True, monkeypatch=monkeypatch)
    for key in on2:
        assert lemmatize(key, "en") == key, f"a second pass moved the key again: {key!r}"


@_needs_lemmatizer
def test_the_lemma_is_computed_per_language_and_never_across_them():
    """`families.py`'s rule, enforced at the index. A German plural must not be resolved
    by English morphology and vice versa — measured on this library rather than assumed,
    because the failure is silent: the wrong language mostly DECLINES, so the damage is
    lost recall, and only an explicit assertion says which language did the work."""
    assert lemmatize("wahlen", "de") == "wahl"
    assert lemmatize("wahlen", "en") == "wahlen"  # English morphology declines
    assert lemmatize("studies", "en") == "study"
    assert lemmatize("studies", "fr") == "studies"  # French morphology declines
    assert lemmatize("réformes", "fr") == "réforme"
    assert lemmatize("réformes", "en") == "réformes"


@_needs_lemmatizer
def test_a_meaning_changing_lemma_is_refused():
    """`media` -> `medium` and `data` -> `datum` are correct English and wrong for a news
    corpus. The denylist is the refusal; without it the index would merge two topics."""
    for word in ("media", "data", "us"):
        assert lemmatize(word, "en") == word


@_needs_lemmatizer
def test_an_entity_is_never_lemmatised():
    """The entity path preserves case on purpose (`WHO` != `who`), and lemmatising would
    destroy exactly that. Guarded at the extraction seam, not left to the caller."""
    assert extraction_lemma("WHO", "en", kind="entity") == "WHO"
    assert extraction_lemma("studies", "en", kind="entity") == "studies"


@_needs_lemmatizer
def test_a_region_tagged_language_still_lemmatises():
    """`Article.language` is stored RAW, so most major outlets arrive as `en-US`. A gate
    that compares it to a bare `en` silently refuses to lemmatise them — the recorded
    framing-tone defect, one layer down. Normalisation happens inside `lemmatize`."""
    assert lemmatize("studies", "en-US") == "study"
    assert lemmatize("studies", "EN_gb") == "study"


def test_the_language_reasons_stay_four_distinct_facts(monkeypatch):
    """Runs WITHOUT the lemmatiser too — it is the degrade half.

    "Chinese is not lemmatised here" and "this install has no lemmatiser" are different
    facts and must not share a sentinel; the memoised classification must not cache the
    availability half, or a test that blanks the import reads a stale answer and passes
    while measuring nothing."""
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    if lemmatizer_available():
        assert lemma_status("zh") == REASON_UNSEGMENTED
        assert lemma_status("kl") == REASON_UNSUPPORTED
        assert lemma_status("en") not in (REASON_UNSEGMENTED, REASON_UNSUPPORTED)
    monkeypatch.setattr(lemma_mod, "_simplemma", None)  # the module whose code READS it
    assert lemma_status("en") == REASON_NO_LIBRARY
    assert lemmatize("studies", "en") == "studies", "no lemmatiser must be a no-op, never a crash"


def test_extraction_degrades_to_the_pre_lemma_behaviour_without_a_lemmatiser(monkeypatch):
    """Also runs without the optional package. With no lemmatiser the extractor must be
    byte-identical to the pre-2026-09-17 behaviour — which is what makes the opt-out and
    the degrade one mechanism instead of two."""
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    monkeypatch.setattr(lemma_mod, "_simplemma", None)
    degraded = _terms(_EN, "en", lemma=True, monkeypatch=monkeypatch)
    monkeypatch.setattr(lemma_mod, "_simplemma", None)
    off = _terms(_EN, "en", lemma=False, monkeypatch=monkeypatch)
    assert degraded == off


def test_the_dictionary_cache_has_room_for_every_language_we_ask_about():
    """MEASURED, not argued (`S04-07` PR 2): the cache was one slot under the working set.

    ``simplemma.lemmatize`` delegates to one process-wide lemmatiser whose dictionary
    factory keeps an LRU of **eight** loaded dictionaries. :data:`LEMMA_LANGS` holds
    **nine**, and ``_resolve_by_lemma`` asks for a term's lemma under every one of them in
    turn — so each call evicted the dictionary the next call needed and the hit rate was
    not poor but exactly ZERO. A per-form readout over a 120-form ring took **166 seconds
    on a three-article corpus**; the same call after this fix takes **8 milliseconds**.

    RUN AS AN A/B, against a factory built the way the library ships, because three
    plausible versions of this test measure nothing:

    * counting calls to ``_get_dictionary`` counts cache HITS — the decomposition
      strategies ask it a dozen times per lemma — so the number to read is the LRU's own
      ``misses``, which is by definition one per dictionary actually loaded;
    * ``Lemmatizer`` keeps a 65536-entry cache keyed on ``(token, lang)``, so a second
      pass over the SAME word loads nothing whatever the dictionary cache does — each
      pass therefore uses a DIFFERENT word;
    * a green result proves nothing unless the shipped default is shown to be red on the
      identical sequence, so the eight-slot factory is exercised right beside ours.
    """
    if not lemmatizer_available():
        pytest.skip("no simplemma in this install")
    try:
        from simplemma import Lemmatizer
        from simplemma.strategies import DefaultDictionaryFactory, DefaultStrategy
    except Exception:  # noqa: BLE001
        pytest.skip("this simplemma exposes a different strategy surface")

    langs = sorted(LEMMA_LANGS)

    def misses_over_two_passes(size: int) -> int:
        """Dictionaries LOADED on a second pass over the same languages, new words."""
        factory = DefaultDictionaryFactory(cache_max_size=size)
        lz = Lemmatizer(
            lemmatization_strategy=DefaultStrategy(dictionary_factory=factory)
        )
        for lg in langs:
            lz.lemmatize("zzqcoronavirus", lg)
        before = factory._get_dictionary.cache_info().misses
        for lg in langs:
            lz.lemmatize("zzqinfluenza", lg)
        return factory._get_dictionary.cache_info().misses - before

    shipped = misses_over_two_passes(8)
    assert shipped > 0, (
        "the eight-slot default did NOT thrash on this sequence, so this test no longer "
        "measures the defect it was written for -- check whether simplemma changed its "
        "default or its caching before trusting the green result below"
    )
    ours = misses_over_two_passes(max(8, len(LEMMA_LANGS) + 2))
    assert ours == 0, (
        f"our dictionary cache still evicts between two passes over the same {len(langs)} "
        f"languages ({ours} reloads), so every lemmatisation re-reads from disk"
    )
    # ... and the shipped lemmatiser this module actually uses is the fixed one.
    lz = lemma_mod._lemmatizer()
    strategy = getattr(lz, "_lemmatization_strategy", None)
    lookup = getattr(strategy, "_dictionary_lookup", None)
    factory = getattr(lookup, "_dictionary_factory", None)
    if factory is not None and hasattr(factory, "_get_dictionary"):
        assert factory._get_dictionary.cache_info().maxsize >= len(LEMMA_LANGS), (
            "the module's own lemmatiser has fewer dictionary slots than the languages "
            "it is asked about"
        )


def test_the_cache_is_sized_from_the_language_set_not_from_a_remembered_number():
    """The STRUCTURAL half: a tenth language must not silently re-open the cliff.

    The property is "at least as many slots as languages we ask for", so it is asserted
    against ``LEMMA_LANGS`` rather than against the number that satisfies it today. This
    is the guard that fails when someone adds a language, which is precisely when the
    behavioural test above would start failing in production and nowhere else.
    """
    src = (lemma_mod.__file__ or "").replace(".pyc", ".py")
    import pathlib

    text = pathlib.Path(src).read_text(encoding="utf-8")
    assert "cache_max_size=max(8, len(LEMMA_LANGS) + 2)" in text, (
        "the dictionary cache is sized to a literal; adding a language would put the "
        "working set back over the cache and re-introduce a 20,000x slowdown silently"
    )
