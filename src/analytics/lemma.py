"""The ONE lemmatisation seam — shared by extraction and by display-time grouping.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

**Q416 = a (2026-09-15, gate row M):** *"Add ``simplemma`` to the core dependencies;
lemmatise at extraction; a migration re-normalises existing keywords under a job."*

Until now lemmatisation lived entirely inside :mod:`src.analytics.families`, as a
DISPLAY-time collapse over rows the store had already written, and ``simplemma`` sat
in the ``[analysis]`` extra so a core install silently did nothing. Q416 moves it to
the index: a term is lemmatised as it is EXTRACTED, so ``studies`` and ``study`` are
one keyword in the database rather than two rows a later layer has to reunite.

**WHY ONE MODULE AND NOT TWO COPIES.** The rules that make lemmatisation safe here —
which languages, which norms must never be lemmatised, single tokens only, never
across languages — are the load-bearing part, and the ledger's standing lesson is
that *a lesson recorded against one assertion does not propagate itself to the one
beside it*. Two copies of ``_LEMMA_LANGS`` would drift the first time either is
tuned, and the two layers would then disagree about what "the same keyword" means,
which is precisely the bucket-key disagreement the language-equilibrium lever paid
for. ``families.py`` imports from here; so does ``extract.py``.

**THE GUARDS ARE THE FEATURE** (all of them inherited verbatim from the reviewed
display-time rules, which the maintainer vetted over the live ~500k-article corpus in
2026-07-18 — top 500 keywords → 35 candidate groups / 71 keywords, found clean):

* **Single-token TERMS only.** A multi-word phrase is never lemmatised (a phrase's
  head is not always its last token and we have no parser), and an ENTITY name is
  never lemmatised at all — ``WHO`` is not a plural.
* **Never across languages.** The lemma is computed per-language and the caller keys
  on ``(language, lemma)``, so an English ``mangas`` can never reach a Spanish one.
  A language outside :data:`LEMMA_LANGS` is a no-op, not a guess.
* **zh/ja are excluded, and that is disclosed rather than silently true.** They are
  unsegmented here (their segmenters are the ``[segmentation]`` extra / ``S04-07``);
  lemmatising a sentence-long pseudo-token would be nonsense. :func:`lemma_status`
  names the reason so a surface can say it.
* **A meaning-changing norm is denylisted.** ``media``→``medium``, ``data``→``datum``,
  ``us``→``we`` are wrong for a news corpus. Evidence-grown, not guessed.
* **Any lemmatiser error falls back to the input.** A wrong lemma is worse than none.

**WHAT IS DELIBERATELY NOT DONE HERE.** This does not lemmatise n-grams, and it does
not lemmatise the languages ``simplemma`` covers poorly. Both are refusals, both are
reported by :func:`lemma_status`, and neither is a to-do: widening either one changes
what the stored index means, and that is a ruling, not a tuning knob.
"""

from __future__ import annotations

import os
from functools import lru_cache

from src.analytics.managed import normalize_lang

try:  # core since Q416 = a; the guard stays so an odd install degrades, never crashes
    import simplemma as _simplemma
except Exception:  # noqa: BLE001 - a broken/absent install must not break extraction
    _simplemma = None  # type: ignore[assignment]

#: The ``simplemma`` release whose bundled dictionaries this corpus was normalised
#: against. It is a DATED-DATA pin, not a version convenience: the dictionaries are
#: the artifact, and a different release can lemmatise the same word differently,
#: which silently re-partitions the stored keyword index. Registered in
#: ``configs/external_artifacts.yml`` (id ``simplemma-dictionaries``) — the protocol
#: guard in ``tests/test_external_freshness.py`` fails if it is not.
SIMPLEMMA_AS_OF = "2026-09-17"

#: The languages we lemmatise — the UI/corpus languages ``simplemma`` handles well.
#: Unsegmented scripts (zh/ja) and languages it covers poorly are deliberately absent
#: so they no-op rather than produce a wrong lemma.
LEMMA_LANGS: frozenset[str] = frozenset({"en", "fr", "de", "es", "it", "pt", "nl", "ru", "id"})

#: Norms whose lemma CHANGES the meaning for a news corpus. Evidence-grown and
#: log-tunable, exactly like the plural denylist beside it in ``families.py``. Spelled
#: without the leading underscore now that it is public, but the app's own diagnostic
#: copy still calls it ``_MISLEMMA_DENYLIST`` (an i18n key in twelve locale files,
#: which re-keying for one underscore would un-translate) - so a grep for either name
#: must land here. Same for ``_LEMMA_LANGS`` -> :data:`LEMMA_LANGS`.
MISLEMMA_DENYLIST: frozenset[str] = frozenset(
    {"media", "data", "us", "good", "better", "was", "be", "left", "right"}
)

#: Why a language is not lemmatised, when it is not. Kept as reasons rather than a
#: bare boolean because "we do not lemmatise Chinese" and "we do not lemmatise
#: Klingon" are different facts and a surface that states the first must not say the
#: second (the standing two-absences-one-sentinel rule).
REASON_OK = "lemmatised"
REASON_NO_LIBRARY = "no-lemmatiser"
REASON_UNSEGMENTED = "unsegmented-script"
REASON_UNSUPPORTED = "language-not-covered"
REASON_DISABLED = "disabled"

_UNSEGMENTED_EXCLUDED: frozenset[str] = frozenset({"zh", "ja"})


def lemmatizer_available() -> bool:
    """Is a lemmatiser importable in THIS install?

    The source of truth a test must skip on — never an assumed environment. (The
    recorded segmenter/referee lesson: assert against the availability probe, and
    write the second test that still RUNS without the optional thing and asserts the
    honest degrade.)"""
    return _simplemma is not None


def extraction_lemma_enabled() -> bool:
    """Lemmatisation AT EXTRACTION is on by default (Q416 = a) — this is the opt-out.

    Separate from ``OO_FAMILY_LEMMA`` on purpose: that one governs the DISPLAY-time
    collapse, which is reversible because it never touches the stored index, while
    this one decides what is WRITTEN. Folding the two onto one variable would let an
    operator who wanted a display change quietly alter their corpus."""
    return _simplemma is not None and os.getenv("OO_EXTRACT_LEMMA", "1") == "1"


#: Our OWN lemmatiser, and the reason it exists rather than the module-level
#: ``simplemma.lemmatize`` this used to call.
#:
#: **MEASURED, 2026-09-17 (`S04-07` PR 2), after a per-form readout over a 120-form ring
#: took 49 seconds on a THREE-ARTICLE corpus.** ``simplemma.lemmatize`` delegates to one
#: process-wide legacy lemmatiser whose ``DefaultDictionaryFactory`` caches loaded
#: dictionaries in an LRU of **eight**. :data:`LEMMA_LANGS` has **nine** entries, and
#: :func:`src.analytics.queries._resolve_by_lemma` asks for a term's lemma under EVERY one
#: of them in turn — so each call evicts the dictionary the next call is about to need.
#: The hit rate is not merely poor, it is exactly ZERO, and every single lemmatisation
#: re-reads a dictionary from disk. One language fewer and the cost vanishes; one more and
#: nothing changes. That is the shape of the defect: not a slow library, a cache
#: dimensioned one slot under the working set, which is invisible at any smaller language
#: count and does not degrade gracefully — it falls off a cliff.
#:
#: So the factory is sized from ``LEMMA_LANGS`` ITSELF rather than to a number someone has
#: to remember to raise: adding a tenth language must not silently re-introduce this.
#: The headroom is deliberate but not load-bearing — the property is "at least as many
#: slots as languages we ask for", and the test asserts that, not the constant.
#:
#: Lazy, because building it loads nothing until a lemma is actually wanted, and a
#: module-level construction would put dictionary I/O in the import path of everything
#: that touches extraction. Falls back to the module function if this ``simplemma``
#: exposes a different surface: a slow lemma is worth having, a crash is not.
_LEMMATIZER: object | None = None


def _lemmatizer():  # noqa: ANN202 - a simplemma Lemmatizer, or the module itself
    """The shared lemmatiser, built once, with room for every language we ask about."""
    global _LEMMATIZER
    if _LEMMATIZER is None:
        try:
            from simplemma import Lemmatizer
            from simplemma.strategies import DefaultDictionaryFactory, DefaultStrategy

            _LEMMATIZER = Lemmatizer(
                lemmatization_strategy=DefaultStrategy(
                    dictionary_factory=DefaultDictionaryFactory(
                        cache_max_size=max(8, len(LEMMA_LANGS) + 2),
                    ),
                ),
            )
        except Exception:  # noqa: BLE001 - an odd simplemma must degrade, never crash
            _LEMMATIZER = _simplemma
    return _LEMMATIZER


@lru_cache(maxsize=256)
def _language_reason(language: str | None) -> str:
    """The part of :func:`lemma_status` that is a pure function of frozen sets.

    THE CACHE STOPS HERE ON PURPOSE. Whether a lemmatiser is IMPORTABLE is a fact
    about the process, not about the language, and memoising it is the recorded
    "a degrade probe that caches its own answer" trap: a test that blanks the import
    to exercise the degrade would get a cached pre-patch answer back and pass while
    measuring nothing. So the availability check lives in the uncached caller."""
    lg = normalize_lang(language)
    if lg in _UNSEGMENTED_EXCLUDED:
        return REASON_UNSEGMENTED
    if lg not in LEMMA_LANGS:
        return REASON_UNSUPPORTED
    return REASON_OK


def lemma_status(language: str | None) -> str:
    """One of the ``REASON_*`` constants for ``language`` — what a surface may say.

    The four reasons are kept apart because they are four different facts and a
    surface that says "Chinese is not lemmatised here" must not also be the sentence
    that means "this install has no lemmatiser at all"."""
    if _simplemma is None:
        return REASON_NO_LIBRARY
    if not extraction_lemma_enabled():
        return REASON_DISABLED
    return _language_reason(language)


def lemmatize(norm: str, language: str | None) -> str:
    """The lemma of a SINGLE-token normalised term, or ``norm`` unchanged.

    Conservative by construction: a multi-token form, an unsupported/unknown
    language, a denylisted norm, a missing ``simplemma``, or any lemmatiser error all
    fall back to ``norm``. The ``language`` is normalised HERE (``en-US`` → ``en``)
    rather than at every call site, because ``Article.language`` is stored raw and a
    gate that compares it to a bare code silently refuses to measure most major
    outlets — the recorded framing-tone defect, one layer down.
    """
    if not norm or " " in norm:
        return norm
    if norm in MISLEMMA_DENYLIST:
        return norm
    lg = normalize_lang(language)
    if _simplemma is None or lg not in LEMMA_LANGS or lg in _UNSEGMENTED_EXCLUDED:
        return norm
    try:
        return (_lemmatizer().lemmatize(norm, lg) or norm).casefold()
    except Exception:  # noqa: BLE001 - never let a lemmatiser hiccup break extraction
        return norm


def extraction_lemma(norm: str, language: str | None, *, kind: str = "term") -> str:
    """:func:`lemmatize` with the EXTRACTION-time guards: terms only, opt-out honoured.

    ``kind`` is the extractor's own classification. An entity keeps its surface form —
    an acronym is not an inflected word, and the entity path deliberately preserves
    case (``WHO`` ≠ ``who``), which lemmatisation would destroy.
    """
    if kind != "term" or not extraction_lemma_enabled():
        return norm
    return lemmatize(norm, language)
