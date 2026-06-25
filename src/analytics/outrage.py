"""Outrage / loaded-language intensity — a SECONDARY manipulation signal (§5C).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ninth manipulation-pattern measure (``docs/FUTURE_DEVELOPMENTS.md`` card list). Per the
ledger ruling it is SECONDARY — it ANNOTATES another card/surface, it is NEVER a standalone
Home Lead (a single article's emotive language is not, by itself, a manipulation event).

It names a STRUCTURE, never intent or truth: the DENSITY of loaded / intensifier language in
a text. A high density flags loaded FRAMING to read critically — it is not a verdict that the
article is false or manipulative (a measured opinion or editorial naturally uses intense
language — the innocent twin, stated in the caveat).

HONESTY (enforced in code, not just prose):
  * ENGLISH-ONLY, like the VADER sentiment baseline: a non-English / empty / unknown-language
    text returns a stated GAP (``measured: False``), NEVER a fabricated 0 — the lexicon is a
    curated English heuristic and we do not pretend to measure languages it cannot;
  * NO score / ranking / verdict — it returns the density plus its COMPONENTS (the matched
    markers, the '!' count, the ALL-CAPS-run count, the token count n), so a reader sees what
    drove it, never a blended "outrage score";
  * the lexicon is an explicit, modest HEURISTIC (not a lexicon of record), kept in code and
    tunable from the diagnostics logs like the keyword stoplists.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_CAPS_RUN = re.compile(r"\b[A-Z]{3,}\b")

# Curated English INTENSIFIERS (degree adverbs that amplify) — a heuristic, never exhaustive.
_INTENSIFIERS = frozenset({
    "very", "extremely", "incredibly", "utterly", "totally", "completely", "absolutely",
    "literally", "insanely", "unbelievably", "wildly", "massively", "hugely",
    "outrageously", "shockingly", "terribly", "horribly", "desperately", "furiously",
})
# Curated English LOADED / charged terms (emotive framing words common in outrage copy).
_LOADED = frozenset({
    "outrage", "outrageous", "slam", "slammed", "slams", "blast", "blasted", "blasts",
    "shocking", "shock", "shocked", "disgrace", "disgraceful", "scandal", "scandalous",
    "fury", "furious", "rage", "enraged", "explosive", "bombshell", "damning",
    "devastating", "catastrophic", "chaos", "meltdown", "backlash", "uproar", "firestorm",
    "crisis", "disaster", "horror", "betrayal", "traitor", "corrupt", "crooked", "evil",
    "monstrous", "destroy", "destroyed", "annihilate", "obliterate", "humiliate",
    "humiliated", "ripped", "torched", "eviscerate", "panic", "terror", "nightmare",
    "carnage", "savage", "brutal", "vicious",
})
_MARKERS = _INTENSIFIERS | _LOADED

OUTRAGE_CAVEAT = (
    "STRUCTURE, never intent or truth — a high density of loaded / intensifier language is a "
    "prompt to READ CRITICALLY, never a verdict that the article is false or manipulative. A "
    "measured opinion or editorial naturally uses intense language (the innocent twin). "
    "English-focused; other languages are not measured."
)
_METHOD = (
    "Share of curated English intensifier/loaded markers among the text's tokens, plus the "
    "'!' count and ALL-CAPS (>=3 letters) run count. A heuristic, English-only. No score."
)


def _gap(reason: str, language: str | None) -> dict:
    return {
        "measured": False,
        "reason": reason,
        "language": language or None,
        "method": _METHOD,
        "caveat": OUTRAGE_CAVEAT,
    }


def outrage_intensity(text: str | None, language: str | None = None) -> dict:
    """Measure loaded/intensifier-language density in ``text``. SECONDARY annotation only.

    English-only: a non-English, empty, or unknown-language text returns a GAP
    (``measured: False`` + a ``reason``), never a fabricated 0. For English it returns the
    density and its COMPONENTS (no score). PURE: stdlib only, deterministic, no DB/network.
    """
    lang = (language or "").strip().lower()
    body = (text or "").strip()
    if lang and lang != "en":
        return _gap("not English", lang)
    if not body:
        return _gap("empty", lang or None)
    if not lang:
        # We do not assume an untagged text is English (the lexicon would mis-measure it).
        return _gap("language unknown", None)

    tokens = [m.group(0).lower() for m in _WORD.finditer(body)]
    n = len(tokens)
    if n == 0:
        return _gap("no words", "en")
    matched = [w for w in tokens if w in _MARKERS]
    exclamations = body.count("!")
    shouting_caps = len(_CAPS_RUN.findall(text or ""))
    return {
        "measured": True,
        "language": "en",
        "n_tokens": n,
        "n_loaded": len(matched),
        "density": round(len(matched) / n, 4),
        "exclamations": exclamations,
        "shouting_caps": shouting_caps,
        "matched": sorted(set(matched))[:20],
        "method": _METHOD,
        "caveat": OUTRAGE_CAVEAT,
    }
