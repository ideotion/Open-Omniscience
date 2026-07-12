"""
Subjectivity / loaded-language engine — the rule-based pivot (sentiment ruling, S5.2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The multilingual sentiment ruling BANS the model path (no torch/onnx/transformers in
pyproject), so the honest direction is a RULE-BASED loaded-language / subjectivity engine
feeding the manipulation surfaces. This module generalises the English-only in-code
``outrage.py`` heuristic to a per-language, lexicon-FILE-driven engine:

  * a per-language lexicon loader (``configs/subjectivity/<lang>.txt`` — the vendored
    stopwords-iso pattern: dated via ``SUBJECTIVITY_AS_OF`` + a registry entry, one
    lowercased term per line, ``#`` comments allowed);
  * a scorer that emits DESCRIPTIVE COMPONENTS — the matched term list WITH SPANS (char
    offsets, so a reader surface can highlight exactly what was flagged), the loaded-term
    count, the token count n, and the density share — NEVER a composite score, NEVER a
    fabricated neutral;
  * an HONEST per-language GAP: a language with no lexicon (or an empty/unknown-language
    text) returns ``{available: False, reason}`` — exactly like VADER's English-only gap,
    so a language we cannot measure is declared, never guessed at 0.

It NAMES A STRUCTURE (the density of loaded/subjective framing), never intent or truth: a
measured opinion or editorial naturally uses charged language (the innocent twin, stated in
the caveat). It ANNOTATES a card/surface — it is never a standalone Home Lead (the §5C
ruling that governs ``outrage.py``).

VADER-SEED INVESTIGATION (the brief asked, answered honestly): VADER's bundled lexicon is
VALENCE-annotated (a −4…+4 positive/negative sentiment intensity per word). Subjectivity /
loaded-framing is a DIFFERENT axis — "allegedly" / "so-called" / "reportedly" are subjective
but valence-neutral, and "excellent" is high-valence but not loaded framing. So VADER
valence does NOT map to subjectivity; it is NOT reused here (forcing it would mislabel the
axis). The English seed comes from the loaded/intensifier vocabulary the outrage heuristic
already curates, plus a small set of subjectivity/hedging markers.

The shipped ``configs/subjectivity/*.txt`` are MODEST SEED lexicons proving the mechanism
across three scripts (Latin/Cyrillic/Arabic), flagged for native review — a real
license-clean lexicon of record is a networked sourcing/vetting step (the operator list),
not fabricated here.
"""

from __future__ import annotations

import pathlib
import re
from functools import lru_cache

# Registered in configs/external_artifacts.yml (the *_AS_OF protocol guard). Bump when the
# seed lexicons are refreshed / replaced with the vetted operator-sourced lists.
SUBJECTIVITY_AS_OF = "2026-07"

# Unicode letter-run tokenizer (Latin, Cyrillic, Arabic, …) with offsets. Excludes digits +
# underscore. Space-segmented scripts tokenize cleanly; an unsegmented script (zh/ja/th)
# yields ideograph RUNS that will not match multi-char lexicon entries — an honest limit
# (those languages simply match little until a segmenter + a segmented lexicon exist).
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

_BASE = pathlib.Path(__file__).resolve().parents[2] / "configs" / "subjectivity"

_METHOD = (
    "Share of curated loaded/subjective markers among the text's tokens, with the matched "
    "terms and their character spans. A per-language lexicon heuristic, not a lexicon of "
    "record. No score."
)
_CAVEAT = (
    "STRUCTURE, never intent or truth — a high density of loaded / subjective language is a "
    "prompt to READ CRITICALLY, never a verdict that the article is false or manipulative. "
    "A measured opinion or editorial naturally uses charged language (the innocent twin). "
    "The lexicon is a modest per-language seed (flagged for native review); a language with "
    "no lexicon is DECLARED unmeasured, never scored at 0."
)


@lru_cache(maxsize=None)
def load_lexicon(language: str | None) -> frozenset[str] | None:
    """The loaded/subjective lexicon for a language, or ``None`` when there is no lexicon.

    Network-free. ``configs/subjectivity/<lang>.txt`` — one lowercased term per line, ``#``
    comment lines and blanks ignored. An absent file OR an empty file → ``None`` (the honest
    "no lexicon" gap; never an empty match set masquerading as "measured, found nothing").
    """
    lang = (language or "").strip().lower()
    if not lang:
        return None
    f = _BASE / f"{lang}.txt"
    if not f.is_file():
        return None
    words = frozenset(
        line.strip().lower()
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return words or None


def available_languages() -> set[str]:
    """The languages with a non-empty lexicon (what the engine can actually measure)."""
    if not _BASE.is_dir():
        return set()
    out: set[str] = set()
    for f in _BASE.glob("*.txt"):
        if load_lexicon(f.stem):
            out.add(f.stem.lower())
    return out


def _gap(reason: str, language: str | None) -> dict:
    return {
        "available": False,
        "reason": reason,
        "language": language or None,
        "method": _METHOD,
        "caveat": _CAVEAT,
    }


def subjectivity(text: str | None, language: str | None = None) -> dict:
    """Measure loaded/subjective-language density in ``text`` for ``language``.

    Returns DESCRIPTIVE components (n_tokens, n_loaded, density, the matched ``terms``, and
    ``spans`` = char offsets for a highlight surface) — never a composite score. Honest gaps:
    an unknown language (we never assume English), a language with no lexicon, or an empty /
    word-less text return ``{available: False, reason}`` — never a fabricated 0. PURE: stdlib
    only, deterministic, no DB / network.

    A clean, factual text in a SUPPORTED language returns ``available: True`` with
    ``n_loaded: 0`` / ``density: 0.0`` — a real measurement ("no loaded terms found"), which
    is DIFFERENT from the unmeasured gap of an unsupported language.
    """
    lang = (language or "").strip().lower()
    if not lang:
        return _gap("language unknown", None)  # never assume a text is English
    lex = load_lexicon(lang)
    if lex is None:
        return _gap("no lexicon for this language", lang)
    body = text or ""
    if not body.strip():
        return _gap("empty", lang)
    spans: list[dict] = []
    n_tokens = 0
    for m in _WORD.finditer(body):
        n_tokens += 1
        if m.group(0).lower() in lex:
            spans.append({"term": m.group(0), "start": m.start(), "end": m.end()})
    if n_tokens == 0:
        return _gap("no words", lang)
    return {
        "available": True,
        "language": lang,
        "n_tokens": n_tokens,
        "n_loaded": len(spans),
        "density": round(len(spans) / n_tokens, 4),
        "terms": sorted({s["term"].lower() for s in spans})[:30],
        "spans": spans[:200],
        "method": _METHOD,
        "caveat": _CAVEAT,
    }
