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

from src.timemap.dateextract import (
    _CJK_REL_RE,
    _CJK_WD_RE,
    _EN_AGO_RE,
    _FA_DMY_RE,
    _FA_MY_RE,
    _KO_REL_RE,
    _KO_WD_RE,
    _MONTHS,
    _REL_LANG_GATES,
    _REL_WORDS,
    _WD_COLLOC_RE,
    _WD_COMING_RE,
    _WD_LANG_GATES,
    _WD_LAST_RE,
    _WEEKDAYS,
    extract_dates,
)

# Languages whose month names the extractor's table covers. A date written in any
# OTHER language (ru/ar/zh/ja/hi/bn/id/…) can only be caught via ISO or numeric
# forms, so a low extracted-date rate for those languages is the clearest signal
# of a vocabulary gap — surfaced per-language rather than guessed at.
# Extended 2026-06-17 from the date-diagnostics log (ro/hu/tr/da/sk/pl/fi/sr/bg
# had real article volume but no vocabulary → near-zero coverage); sv/nb share
# the Nordic table now too.
MONTH_VOCAB_LANGS: frozenset[str] = frozenset(
    {"en", "fr", "de", "es", "it", "pt", "nl",
     "ro", "hu", "tr", "da", "sv", "nb", "fi", "pl", "sk", "sr", "bg",
     # RTL / Indic UI locales (Gregorian month names; zh/ja/ko use the 年月日 /
     # 년월일 markers, handled by the extractor's CJK/Korean patterns rather
     # than a month-name table — as are Vietnamese and Thai).
     "ar", "hi", "bn",
     # Remaining UI locales: Russian (Cyrillic, nom/gen/prep) + Indonesian.
     "ru", "id",
     # Vocabulary that had landed but was never reflected here (the flag lied
     # "no vocab" for these): Greek, Ukrainian, Estonian, Urdu, Slovenian.
     "el", "uk", "et", "ur", "sl",
     # Slice-B additions (2026-07-02): Croatian, Czech, Malay, Filipino, Swahili.
     "hr", "cs", "ms", "tl", "sw",
     # Backend batch A (2026-07-03): Catalan, Persian, Malayalam, Telugu. Persian now
     # resolves BOTH Gregorian transliterations AND Solar-Hijri (Jalali) names by exact
     # conversion (wave 8, 2026-07-08; fa-gated); "May" (مه/می) stays withheld as a
     # fabrication vector.
     "ca", "fa", "ml", "te"}
)

# Probe kinds the extractor is *expected* to resolve (so a miss is actionable);
# ``bare_year`` is excluded — the extractor skips bare years BY DESIGN (too easily
# a quantity), so it is reported for context but never counted as a miss.
_ACTIONABLE_KINDS: frozenset[str] = frozenset(
    {"month_name", "cjk_date", "numeric", "weekday", "relative"}
)

# Digit-safe boundaries instead of \b (mirrors the extractor, slice B):
# ideographs are \w in Python re, so \b never fired on glued CJK prose
# ("报道于2024-06-11发布") — the probe was blind to the same dates the extractor
# missed, so the field coverage numbers UNDERCOUNTED the CJK gap. Digits of ANY
# script still block (a date is never carved out of a longer numeral).
_YEAR_RE = re.compile(r"(?<!\d)(?<![A-Za-z_])(1[0-9]{3}|20[0-9]{2})(?!\d)(?![A-Za-z_])")
_NUMERIC_RE = re.compile(r"(?<!\d)(?<![A-Za-z_])\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?!\d)(?![A-Za-z_])")
# East-Asian dates: 年月日 (zh/ja, with the 号/號 colloquial day markers),
# era-name years (令和6年…, 民國113年…), and Korean 년월일.
_CJK_RE = re.compile(
    r"(?:令和|平成|昭和|大正|明治|民國|民国)\s*(?:\d{1,3}|元)\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号號])?"
    r"|\d{1,4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号號])?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*[日号號]"
    r"|\d{1,4}\s*년\s*\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
)
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.I)
_WD_RE = re.compile(
    r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I
)
_REL_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_REL_WORDS, key=len, reverse=True)) + r")\b",
    re.I,
)

# Specificity order: a more-specific kind claims a span before a looser one can
# (so the "2026" inside "11/06/2026" is not also reported as a bare year).
# The CJK/Korean relative + weekday probes reuse the extractor's own regexes
# (boundary-free, slice-C) so the probe sees exactly what the extractor sees;
# each carries the extractor's OWN language gate (third field; None = ungated)
# so a gated family outside its language never counts as a phantom gap.
_PROBES: tuple[tuple[str, re.Pattern[str], frozenset[str] | None], ...] = (
    ("cjk_date", _CJK_RE, None),
    ("numeric", _NUMERIC_RE, None),
    ("month_name", _MONTH_RE, None),
    # Persian Solar-Hijri (Jalali) named dates — the extractor's OWN patterns
    # (exact lockstep), fa-GATED because the month names are ordinary Persian
    # words elsewhere: a Jalali name outside fa is deliberately skipped by the
    # extractor, so probing it there would report a phantom, permanent gap.
    ("month_name", _FA_DMY_RE, frozenset({"fa"})),
    ("month_name", _FA_MY_RE, frozenset({"fa"})),
    ("weekday", _WD_RE, None),
    # The phrase forms reuse the extractor's OWN compiled patterns (exact
    # lockstep, including the "hari minggu ini" exclusion), so an extractor
    # gain never shows as extracted-without-probed.
    ("weekday", _WD_LAST_RE, None),
    ("weekday", _WD_COMING_RE, None),
    ("weekday", _WD_COLLOC_RE, None),
    ("weekday", _CJK_WD_RE, frozenset({"zh", "ja"})),
    ("weekday", _KO_WD_RE, frozenset({"ko"})),
    ("relative", _REL_RE, None),
    ("relative", _CJK_REL_RE, frozenset({"zh", "ja"})),
    ("relative", _KO_REL_RE, frozenset({"ko"})),
    ("relative", _EN_AGO_RE, frozenset({"en"})),
    ("bare_year", _YEAR_RE, None),
)

# LOCKSTEP with the extractor's per-token language gates (slice C): a gated
# token outside its language is one the extractor DELIBERATELY skips (da
# "mandag morgen" = Monday MORNING, tr "senin" = "your"), so counting it as
# date-like would report a phantom, permanent per-language gap. With no
# language hint the extractor also skips — so does the probe.
_GATED_TOKENS: dict[str, set[str]] = {**_REL_LANG_GATES, **_WD_LANG_GATES}

# Soft separators + at most ONE day/year number token — what may sit between a
# weekday probe hit and the date it is an appositive of (see recall_probe).
_APPOS_BRIDGE = re.compile(
    r"[ \t,、，()（）\[\]]*(?:\d{1,4}(?:st|nd|rd|th|er|\.|-го|-е)?[ \t,、，()（）\[\]]*)?"
)


def _gate_allows(matched: str, language: str | None) -> bool:
    gate = _GATED_TOKENS.get(matched.lower())
    if gate is None:
        return True
    return (language or "")[:2].lower() in gate


def _snippet(text: str, start: int, end: int, pad: int = 36) -> str:
    s = text[max(0, start - pad) : min(len(text), end + pad)].strip()
    return re.sub(r"\s+", " ", s)


def recall_probe(text: str, *, limit: int = 40, language: str | None = None) -> list[dict]:
    """Permissive scan for date-LIKE strings — HIGH recall, LOW precision.

    Returns up to ``limit`` ``{kind, match, snippet}`` hits ordered by position.
    Deliberately over-matches so that comparing it against the high-precision
    extractor reveals what the extractor misses; a hit is a candidate, never a
    confirmed date. ``language`` mirrors the extractor's per-token language
    gates: a gated weekday/relative homograph outside its language (da
    "morgen" = morning) is not date-like there and is not counted.
    """
    if not text:
        return []
    base = (language or "")[:2].lower()
    kept: list[tuple[int, int, str, str]] = []  # (start, end, kind, match)
    _date_kinds = {"cjk_date", "numeric", "month_name"}

    def _adjacent_to_a_date(s: int, e: int) -> bool:
        # Mirrors the extractor's appositive suppression ("Tuesday, June 16,
        # 2026" — the weekday NAMES the explicit date): a date-adjacent weekday
        # hit would otherwise report a phantom gap on every standard dateline.
        # The month probe matches only the month TOKEN, so the bridge admits
        # one number token between them ("mardi 16 juin", "wtorek, 11 czerwca
        # 2024" — the extractor's claimed span covers the day/year digits).
        return any(
            k in _date_kinds
            and ((ke <= s and _APPOS_BRIDGE.fullmatch(text, ke, s))
                 or (e <= ks and _APPOS_BRIDGE.fullmatch(text, e, ks)))
            for ks, ke, k, _ in kept
        )

    for kind, rx, langs in _PROBES:
        if langs is not None and base not in langs:
            continue  # a language-gated family the extractor would skip here
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            if kind in ("weekday", "relative") and not _gate_allows(m.group(0), language):
                continue
            if kind == "weekday" and _adjacent_to_a_date(s, e):
                continue
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

    Known asymmetry, stated: the probe counts every OCCURRENCE while the
    extractor dedups by (date, precision), so an article repeating one date N
    times shows an inflated gap of N-1 with zero real misses — read the gap as
    a triage signal, never an exact miss count.
    """
    text = content or ""
    extracted = extract_dates(text, anchor=anchor, language=language, today=today, limit=extract_limit)
    probe = recall_probe(text, limit=probe_limit, language=language)
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
