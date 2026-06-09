"""
Emotion-category measurement around a keyword — lexicon-based, degrades loudly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tone (VADER, in :mod:`src.awareness.framing`) gives *valence* — positive/negative. Richer
**emotions** (anger, fear, joy, sadness, trust, …) need an **emotion lexicon**, which is a
*new* dependency, not thin. Honest constraints (FUTURE_DEVELOPMENTS §4 tone & emotion):

  * **Degrade loudly.** If no usable lexicon is available the API says so — it never
    fabricates an emotion score.
  * **Not a verdict.** A high "fear" count means fear-associated *words* co-occur with the
    keyword; it does not label a source "fearmongering" or judge the coverage. It is a
    measured word-pattern to read, with its ``n`` and method.
  * **English-only here.** The bundled lexicon is English; other languages need their own.

A small, original **sample** lexicon ships so the feature is demonstrable offline, clearly
labelled as minimal. Point ``OO_EMOTION_LEXICON`` at a fuller JSON lexicon
(``{category: [words...]}``) for real work.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

_LOG = logging.getLogger(__name__)
_WORD_RE = re.compile(r"[a-z]+")

# A minimal, ORIGINAL demonstration lexicon (clearly not authoritative). Each list is a
# handful of unambiguous emotion-associated words. Replace via OO_EMOTION_LEXICON.
_SAMPLE_LEXICON: dict[str, list[str]] = {
    "anger": [
        "anger",
        "angry",
        "outrage",
        "outraged",
        "fury",
        "furious",
        "rage",
        "hostile",
        "betrayal",
    ],
    "fear": [
        "fear",
        "afraid",
        "terror",
        "terrified",
        "panic",
        "dread",
        "threat",
        "alarming",
        "danger",
    ],
    "joy": [
        "joy",
        "joyful",
        "delight",
        "delighted",
        "celebrate",
        "triumph",
        "elated",
        "cheerful",
        "hopeful",
    ],
    "sadness": [
        "sad",
        "sadness",
        "grief",
        "mourning",
        "sorrow",
        "despair",
        "tragic",
        "loss",
        "heartbroken",
    ],
    "trust": [
        "trust",
        "trusted",
        "reliable",
        "credible",
        "honest",
        "assurance",
        "confidence",
        "dependable",
    ],
    "disgust": [
        "disgust",
        "disgusting",
        "revulsion",
        "repulsive",
        "appalling",
        "sickening",
        "vile",
    ],
    "surprise": [
        "surprise",
        "surprised",
        "shock",
        "shocking",
        "astonishing",
        "unexpected",
        "sudden",
    ],
    "anticipation": [
        "anticipation",
        "await",
        "expectation",
        "upcoming",
        "imminent",
        "forthcoming",
        "soon",
    ],
}

LEXICON_CAVEAT = (
    "Emotion counts are word-association measures: how many emotion-lexicon words co-occur "
    "with the keyword's context, by category. They do NOT judge the coverage or label a "
    "source. The bundled lexicon is a minimal English SAMPLE — provide OO_EMOTION_LEXICON "
    "for serious use, and note it is English-only."
)


@lru_cache(maxsize=1)
def load_lexicon() -> tuple[dict[str, frozenset[str]], str]:
    """Load the emotion lexicon. Returns (``{category: words}``, source-label).

    Precedence: ``OO_EMOTION_LEXICON`` JSON file → the bundled sample. A bad custom file
    degrades loudly to the sample (with a warning), never silently to nothing.
    """
    path = os.getenv("OO_EMOTION_LEXICON")
    if path:
        try:
            raw = json.loads(Path(path).expanduser().read_text("utf-8"))
            lex = {k: frozenset(w.lower() for w in v) for k, v in raw.items() if v}
            if lex:
                return lex, f"custom:{path}"
            _LOG.warning("OO_EMOTION_LEXICON at %s is empty; using the sample lexicon", path)
        except Exception:  # noqa: BLE001 - a bad lexicon must not crash; fall back loudly
            _LOG.warning(
                "OO_EMOTION_LEXICON at %s unreadable; using the sample lexicon", path, exc_info=True
            )
    return {k: frozenset(v) for k, v in _SAMPLE_LEXICON.items()}, "sample"


def emotion_counts(text: str) -> dict[str, int]:
    """Count emotion-lexicon word hits per category in ``text`` (case-insensitive)."""
    lex, _ = load_lexicon()
    words = _WORD_RE.findall(text.lower())
    if not words:
        return dict.fromkeys(lex, 0)
    bag = words  # multiset: repeated emotion words count repeatedly
    counts: dict[str, int] = {}
    for category, vocab in lex.items():
        counts[category] = sum(1 for w in bag if w in vocab)
    return counts


def emotion_profile(snippets: list[str]) -> dict:
    """Aggregate emotion counts across context snippets around a keyword.

    Returns per-category totals, the dominant category, the total emotional-word hits,
    and the number of snippets — every figure a real count, with method + caveat.
    """
    lex, source = load_lexicon()
    totals: dict[str, int] = dict.fromkeys(lex, 0)
    for s in snippets:
        for k, v in emotion_counts(s).items():
            totals[k] += v
    total_hits = sum(totals.values())
    dominant = max(totals, key=lambda k: totals[k]) if total_hits else None
    return {
        "categories": totals,
        "dominant": dominant,
        "total_hits": total_hits,
        "n_snippets": len(snippets),
        "lexicon_source": source,
        "method": "count of emotion-lexicon words per category across the keyword's context windows",
        "caveat": LEXICON_CAVEAT,
    }
