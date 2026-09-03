"""Offline, confidence-gated language detection (field §2.6, maintainer-approved 2026-06-23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Many articles arrive with NO language set (the source/extractor couldn't tag them) —
notably .eml newsletters. Those undetected articles then extract under the English
working-assumption stoplist, so a genuinely foreign one leaks its function words as
keywords (the "?"-language bucket). This deduces a SECONDARY/DEDUCED language for them
so the right stoplist applies, WITHOUT ever overwriting the authoritative
``Article.language`` (the two-class asserted-vs-deduced model — maintainer ruling Q3).

HONESTY by construction:
  * fully OFFLINE — ``py3langid`` ships a bundled model, makes ZERO network calls;
  * GATED like VADER — it lives in the ``[analysis]`` extra, so a core install simply
    gets ``None`` (the language stays unknown, exactly as today) — no hard dependency;
  * it NEVER guesses — ``None`` for short text (< ``min_chars``), low confidence
    (< ``min_prob``), or a language OUTSIDE the app's supported set (a Korean article is
    detected `ko`, which we cannot analyse, so it stays honestly unknown rather than
    being force-fit to the nearest supported language);
  * deterministic (no random seed), so a re-index reproduces the same result.
"""

from __future__ import annotations

import threading

from src.analytics.managed import MANAGED_LANGUAGES, UNSEGMENTED

# The languages the app meaningfully knows: managed (have a stoplist) + the unsegmented
# ones (zh/ja/th — labelled out of "?" even though segmentation is a separate gap). A
# detected language outside this set is rejected (honest unknown), never force-fit.
SUPPORTED: frozenset[str] = MANAGED_LANGUAGES | UNSEGMENTED

_MIN_CHARS = 200   # below this, detection is unreliable -> never guess
_MIN_PROB = 0.90   # confidence floor -> never guess
_MAX_CHARS = 5000  # bound the classify cost (the lead is plenty for detection)

_lock = threading.Lock()
_identifier = None
_unavailable = False


def _get_identifier():
    """Lazily build the (full-model, normalised-probability) identifier once.

    Sets ``_unavailable`` if the [analysis] lib is absent so we never retry-import on
    every call (the VADER ``_analyzer`` pattern)."""
    global _identifier, _unavailable
    if _identifier is not None or _unavailable:
        return _identifier
    with _lock:
        if _identifier is not None or _unavailable:
            return _identifier
        try:
            from py3langid.langid import MODEL_FILE, LanguageIdentifier

            # py3langid renamed this loader between 0.3 and 0.4 (from_pickled_model ->
            # from_model_file) and the dependency is pinned ">=0.3" with no ceiling, so
            # a fresh install got the new library and lost the old name. The failure was
            # SILENT and total: the except below set _unavailable, detector_available()
            # answered False, detect_language() answered None for every text, and every
            # article's detected_language stayed NULL — the honest-degrade path working
            # perfectly while the capability behind it was simply gone. Measured
            # 2026-09-02 on py3langid 0.4.0: from_pickled_model raises AttributeError,
            # from_model_file returns a working identifier (en at p=0.996).
            #
            # Both names are tried rather than pinning the dependency backwards: a
            # version constraint chosen for compatibility is also a security decision,
            # and supporting both APIs costs one getattr.
            _loader = getattr(LanguageIdentifier, "from_model_file", None) or getattr(
                LanguageIdentifier, "from_pickled_model", None
            )
            if _loader is None:
                raise AttributeError(
                    "py3langid exposes neither from_model_file nor from_pickled_model"
                )
            # norm_probs=True -> classify() returns (lang, probability in [0,1]); the
            # FULL model (no set_languages) so an unsupported language is detected AS
            # itself and then rejected below, instead of force-fit to a supported one.
            _identifier = _loader(MODEL_FILE, norm_probs=True)
        except Exception:  # noqa: BLE001 - lib/model absent -> honest unavailable
            _unavailable = True
        return _identifier


def detector_available() -> bool:
    """Is the offline model actually loadable here?

    ``detect_language`` answers ``None`` for four different reasons -- library absent,
    text too short, low confidence, unsupported language -- which is right for a
    caller that only wants the language. A caller that REPORTS the absence needs to
    tell "we could not check at all" from "we checked and could not tell", because
    they are different facts about different things: the first is about this install,
    the second is about the text. Costs one lazy load, then a flag.
    """
    return _get_identifier() is not None


def detect_language(
    text: str | None, *, min_chars: int = _MIN_CHARS, min_prob: float = _MIN_PROB
) -> str | None:
    """Deduce an article's language offline -> a supported ISO-2 code, or ``None``.

    ``None`` means "unknown" (lib absent, text too short, low confidence, or an
    unsupported language) -- it NEVER guesses. Restricted to ``SUPPORTED`` so it cannot
    return a language the engine can't use.
    """
    if not text:
        return None
    s = text.strip()
    if len(s) < min_chars:
        return None
    ident = _get_identifier()
    if ident is None:
        return None
    try:
        lang, prob = ident.classify(s[:_MAX_CHARS])
    except Exception:  # noqa: BLE001 - any classify failure -> honest unknown
        return None
    if lang in SUPPORTED and float(prob) >= min_prob:
        return lang
    return None
