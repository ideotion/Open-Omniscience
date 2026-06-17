"""Date-extraction diagnostics: what the extractor caught vs. what the text looks like.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer↔developer feedback channel (CLAUDE.md ruling 2026-06-10) applied to
date extraction: the corpus is private and local, so improving the extractor needs
an export the operator can *choose* to share. This module is the pure, testable
core behind ``GET /api/diagnostics/dates``.

The optimization question is "which mentioned dates does the extractor MISS?", so
this pairs the high-precision extractor (:mod:`src.timemap.dateextract`) with a
deliberately PERMISSIVE recall probe. The probe over-matches (bare years, CJK
年月日 dates, any d/m/y run, month/weekday/relative words) so that the difference
— date-like text the extractor did NOT turn into a tag — is exactly the material a
reviewer needs to spot a missing pattern. Probe hits are CANDIDATES, never
confirmed dates (a "2020" may be a quantity, a weekday may be generic): high
recall, low precision, by design and stated.

Pure: no I/O, no DB, fully unit-testable. The endpoint adds the corpus scan.
"""

from __future__ import annotations

import re
from datetime import date

from src.timemap.dateextract import _MONTHS, _REL_WORDS, _WEEKDAYS, extract_dates

# Languages whose month names the extractor's table covers. A date written in any
# OTHER language (ru/ar/zh/ja/hi/bn/id/…) can only be caught via ISO or numeric
# forms, so a low extracted-date rate for those languages is the clearest signal
# of a vocabulary gap — surfaced per-language rather than guessed at.
# Extended 2026-06-17 from the date-diagnostics log (ro/hu/tr/da/sk/pl/fi/sr/bg
# had real article volume but no vocabulary → near-zero coverage); sv/nb share
# the Nordic table now too.
MONTH_VOCAB_LANGS: frozenset[str] = frozenset(
    {"en", "fr", "de", "es", "it", "pt",
     "ro", "hu", "tr", "da", "sv", "nb", "fi", "pl", "sk", "sr", "bg",
     # RTL / Indic UI locales (Gregorian month names; zh/ja use 年月日 markers,
     # handled by the extractor's CJK path rather than a month-name table).
     "ar", "hi", "bn",
     # Remaining UI locales: Russian (Cyrillic, nom/gen/prep) + Indonesian.
     "ru", "id"}
)

# Probe kinds the extractor is *expected* to resolve (so a miss is actionable);
# ``bare_year`` is excluded — the extractor skips bare years BY DESIGN (too easily
# a quantity), so it is reported for context but never counted as a miss.
_ACTIONABLE_KINDS: frozenset[str] = frozenset(
    {"month_name", "cjk_date", "numeric", "weekday", "relative"}
)

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_NUMERIC_RE = re.compile(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b")
# East-Asian dates (年=year 月=month 日=day): extremely common in zh/ja text and
# entirely outside the extractor's Latin-month table — a high-value gap to surface.
_CJK_RE = re.compile(r"\d{1,4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|\d{1,2}\s*月\s*\d{1,2}\s*日")
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.I)
_WD_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I)
_REL_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_REL_WORDS, key=len, reverse=True)) + r")\b",
    re.I,
)

# Specificity order: a more-specific kind claims a span before a looser one can
# (so the "2026" inside "11/06/2026" is not also reported as a bare year).
_PROBES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cjk_date", _CJK_RE),
    ("numeric", _NUMERIC_RE),
    ("month_name", _MONTH_RE),
    ("weekday", _WD_RE),
    ("relative", _REL_RE),
    ("bare_year", _YEAR_RE),
)


def _snippet(text: str, start: int, end: int, pad: int = 36) -> str:
    s = text[max(0, start - pad) : min(len(text), end + pad)].strip()
    return re.sub(r"\s+", " ", s)


def recall_probe(text: str, *, limit: int = 40) -> list[dict]:
    """Permissive scan for date-LIKE strings — HIGH recall, LOW precision.

    Returns up to ``limit`` ``{kind, match, snippet}`` hits ordered by position.
    Deliberately over-matches so that comparing it against the high-precision
    extractor reveals what the extractor misses; a hit is a candidate, never a
    confirmed date.
    """
    if not text:
        return []
    kept: list[tuple[int, int, str, str]] = []  # (start, end, kind, match)
    for kind, rx in _PROBES:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            if any(s < ke and ks < e for ks, ke, _, _ in kept):  # overlaps a more specific hit
                continue
            kept.append((s, e, kind, m.group(0)))
    kept.sort(key=lambda h: h[0])
    out = [{"kind": k, "match": mt, "snippet": _snippet(text, s, e)} for s, e, k, mt in kept]
    return out[:limit]


def analyze_article(
    content: str | None,
    *,
    language: str | None = None,
    anchor: date | None = None,
    today: date | None = None,
    probe_limit: int = 40,
    extract_limit: int = 30,
) -> dict:
    """Pair the real extractor with the recall probe for ONE article's text.

    Returns the extractor's dates (exactly as ingest stores them — same anchor +
    language), the permissive probe hits, and counts including ``actionable_gap``
    = how many probe hits of an *expected* kind exceed the extracted dates (the
    sort key that floats the worst misses to the top of a sample). No score.
    """
    text = content or ""
    extracted = extract_dates(text, anchor=anchor, language=language, today=today, limit=extract_limit)
    probe = recall_probe(text, limit=probe_limit)
    by_kind: dict[str, int] = {}
    for h in probe:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
    actionable = sum(n for k, n in by_kind.items() if k in _ACTIONABLE_KINDS)
    return {
        "n_extracted": len(extracted),
        "n_date_like": len(probe),
        "probe_by_kind": by_kind,
        "actionable_gap": max(0, actionable - len(extracted)),
        "extracted": extracted,
        "date_like_in_text": probe,
    }


def base_language(language: str | None) -> str:
    """Normalise an article language to its base tag (``en-US`` -> ``en``)."""
    return (language or "?").split("-", 1)[0].strip().lower() or "?"
