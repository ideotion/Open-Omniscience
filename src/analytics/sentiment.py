"""Per-article sentiment at ingest — language-aware, honest, LLM-less.

The maintainer's instinct was right: sentiment belongs at the scraping level. The
``Article.sentiment_score`` / ``sentiment_label`` columns existed but were NEVER
written — sentiment was only computed on-demand (VADER) in one subtab, so most of
the app showed nothing. This computes it ONCE per article through the
``index_article`` hook (so ingest, re-index and backfill all populate it) and stores
it, making sentiment available everywhere without recompute.

HONESTY BY CONSTRUCTION:
  * VADER is an ENGLISH lexicon (rule-based, no LLM, no network) — the English
    baseline. We score ONLY articles whose stored language is English.
  * Every other language (and unknown language / empty text) returns ``(None,
    None)`` — we NEVER fabricate a "neutral" for a language the lexicon cannot read
    (the same honest gap as the keyword zh/ja segmentation limit). Downstream shows
    "sentiment unavailable for <language>", never a fake score.
  * Extending beyond English (per-language lexicons / a local model) is a follow-up;
    the English baseline stays VADER.
"""

from __future__ import annotations

from functools import lru_cache

from src.analytics.managed import normalize_lang

# VADER thresholds (the library's documented convention).
_POS, _NEG = 0.05, -0.05


@lru_cache(maxsize=1)
def _analyzer():
    # Lazy + GRACEFUL: VADER ships in the optional [analysis] extra. A CORE install
    # (without it) must never crash ingest — we return None and simply score nothing.
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        return None
    return SentimentIntensityAnalyzer()


def _label(compound: float) -> str:
    if compound >= _POS:
        return "positive"
    if compound <= _NEG:
        return "negative"
    return "neutral"


def score_article(text: str | None, language: str | None) -> tuple[float | None, str | None]:
    """``(compound score in -1..1, label)`` for an ENGLISH article, else ``(None, None)``.

    Returns ``(None, None)`` for any non-English / unknown language or empty text —
    never a fabricated neutral. The score is the VADER compound, rounded; the label
    is positive / negative / neutral by the standard thresholds.

    English is matched on the NORMALISED code (2026-07-29): ``Article.language`` is
    stored raw from trafilatura's ``<html lang>`` read, so a major outlet arrives as
    ``en-US``/``en-GB`` and a bare ``!= "en"`` silently refused to score genuinely
    English coverage. Refusing to measure English is not the conservative direction of
    this gate — it destroys a real measurement as surely as scoring French would
    fabricate one. Kept deliberately IN STEP with ``src/awareness/framing.py``'s
    ``_scorable``: the two publish the same quantity (the framing table falls back from
    one to the other), so they must agree on what is measurable.
    """
    if normalize_lang(language) != "en":
        return None, None
    body = (text or "").strip()
    if not body:
        return None, None
    analyzer = _analyzer()
    if analyzer is None:  # the [analysis] extra is absent -> no sentiment, never a crash
        return None, None
    compound = float(analyzer.polarity_scores(body)["compound"])
    return round(compound, 4), _label(compound)
