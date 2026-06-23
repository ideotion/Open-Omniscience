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

            # norm_probs=True -> classify() returns (lang, probability in [0,1]); the
            # FULL model (no set_languages) so an unsupported language is detected AS
            # itself and then rejected below, instead of force-fit to a supported one.
            _identifier = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
        except Exception:  # noqa: BLE001 - lib/model absent -> honest unavailable
            _unavailable = True
        return _identifier


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
