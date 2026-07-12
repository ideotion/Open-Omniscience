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
from collections import Counter

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


def _char_script(cp: int) -> str:
    """The writing system of a codepoint, coarse but enough to tell a lexicon apart from a
    mismatched text (Latin vs Cyrillic vs Arabic vs other)."""
    if 0x0400 <= cp <= 0x04FF or 0x0500 <= cp <= 0x052F:
        return "cyrillic"
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF:
        return "arabic"
    if (0x41 <= cp <= 0x5A) or (0x61 <= cp <= 0x7A) or (0xC0 <= cp <= 0x24F):
        return "latin"
    return "other"  # CJK / Hangul / Thai / Devanagari / etc.


def _dominant_script(text: str) -> str | None:
    """The majority writing system among the LETTERS of ``text``, or None if it has none."""
    c: Counter = Counter()
    for ch in text:
        if ch.isalpha():
            c[_char_script(ord(ch))] += 1
    return c.most_common(1)[0][0] if c else None


# mtime-aware lexicon cache: lang -> (mtime, frozenset, script). Keyed on the file's mtime so
# a long-running process (the app boots once) picks up a REPLACED lexicon — the vetted
# operator-sourced list the registry names — WITHOUT a restart, instead of serving a stale set.
_CACHE: dict[str, tuple[float, frozenset[str], str]] = {}


def _load(language: str | None) -> tuple[float, frozenset[str], str] | None:
    lang = (language or "").strip().lower()
    if not lang:
        return None
    f = _BASE / f"{lang}.txt"
    try:
        mtime = f.stat().st_mtime
    except OSError:  # absent file
        _CACHE.pop(lang, None)
        return None
    cached = _CACHE.get(lang)
    if cached is not None and cached[0] == mtime:
        return cached
    words = frozenset(
        line.strip().lower()
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not words:  # an empty file is "no lexicon", never a masquerading empty match set
        _CACHE.pop(lang, None)
        return None
    script = _dominant_script(" ".join(words)) or "other"
    entry = (mtime, words, script)
    _CACHE[lang] = entry
    return entry


def load_lexicon(language: str | None) -> frozenset[str] | None:
    """The loaded/subjective lexicon for a language, or ``None`` when there is no lexicon.

    Network-free. ``configs/subjectivity/<lang>.txt`` — one SINGLE-TOKEN lowercased term per
    line (a multi-word/hyphenated entry cannot match the tokenizer), ``#`` comments + blanks
    ignored. Absent / empty file → ``None`` (the honest "no lexicon" gap). mtime-cached, so a
    replaced lexicon is picked up without a restart."""
    e = _load(language)
    return e[1] if e else None


def available_languages() -> set[str]:
    """The languages with a non-empty lexicon (what the engine can actually measure)."""
    if not _BASE.is_dir():
        return set()
    return {f.stem.lower() for f in _BASE.glob("*.txt") if _load(f.stem)}


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
    entry = _load(lang)
    if entry is None:
        return _gap("no lexicon for this language", lang)
    _mtime, lex, lex_script = entry
    body = text or ""
    if not body.strip():
        return _gap("empty", lang)
    # SCRIPT GUARD (skeptic #1/#3): a text whose dominant script does not match the lexicon's
    # is NOT measurable by that lexicon (a mislabelled language, or unsegmented CJK scanned
    # against a Latin list). Return an honest GAP, never a fabricated density:0.0 that reads as
    # "measured, clean". `language` is the SOURCE-ASSERTED value, which the project treats as
    # unreliable — so this is a real production path, not a corner case.
    text_script = _dominant_script(body)
    if text_script and text_script != lex_script:
        return _gap(
            f"text script ({text_script}) does not match the {lang} lexicon ({lex_script}) "
            f"— likely a mislabelled language; not measured",
            lang,
        )
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
