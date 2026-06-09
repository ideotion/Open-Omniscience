"""Extract explicit dates *mentioned in article text* (for the temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A story's *publication* date is not the date it is *about*: a 2024 piece may report
on a 1945 event or a 2026 election. This module finds the explicit calendar dates a
text mentions so the temporal map can place coverage at the moment it discusses.

**High precision by design** (the project's ethos — better to miss a date than invent
one). We match only unambiguous forms:

  * ISO ``YYYY-MM-DD``
  * ``11 September 2001`` / ``11 Sept 2001`` (day)
  * ``September 11, 2001`` (day)
  * ``September 2001`` / ``Sept 2001`` (month)

We deliberately do **not** extract bare years (``in 1945`` — too easily a quantity,
a page number, a model year) or relative expressions (``last Tuesday`` — needs a
reference and guesses), and every result is a *candidate* carrying the matched snippet
as provenance, never a confirmed fact. Pure: no I/O, fully unit-tested.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))   # longest first so 'sept' beats 'sep'

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I)
_MDY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_MY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I)

# Plausible window for a *mentioned* date: deep history up to a little ahead of "now".
_MIN_YEAR, _MAX_AHEAD = 1000, 5


def _valid(year: int, month: int, day: int, today: date) -> date | None:
    if not (_MIN_YEAR <= year <= today.year + _MAX_AHEAD):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _snippet(text: str, start: int, end: int, pad: int = 24) -> str:
    s = text[max(0, start - pad):min(len(text), end + pad)].strip()
    return re.sub(r"\s+", " ", s)


def extract_dates(text: str, *, today: date | None = None, limit: int = 8) -> list[dict]:
    """Explicit calendar dates mentioned in ``text``, as candidates with provenance.

    Returns up to ``limit`` de-duplicated ``{date, precision, text}`` dicts, ordered by
    first appearance. ``precision`` is ``"day"`` or ``"month"``. Overlapping matches are
    resolved most-specific-first (a day match suppresses the month match inside it).
    """
    if not text:
        return []
    today = today or date.today()
    consumed: list[tuple[int, int]] = []      # spans claimed by more specific matches
    found: dict[tuple[str, str], dict] = {}

    def claim(start: int, end: int) -> bool:
        for cs, ce in consumed:
            if start < ce and cs < end:        # overlaps an already-claimed span
                return False
        consumed.append((start, end))
        return True

    def add(d: date, precision: str, m: re.Match) -> None:
        key = (d.isoformat(), precision)
        if key not in found:
            found[key] = {"date": d.isoformat(), "precision": precision,
                          "text": _snippet(text, m.start(), m.end()), "pos": m.start()}

    for m in _ISO_RE.finditer(text):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _DMY_RE.finditer(text):
        d = _valid(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _MDY_RE.finditer(text):
        d = _valid(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _MY_RE.finditer(text):          # month precision — only where no day match claimed it
        d = _valid(int(m.group(2)), _MONTHS[m.group(1).lower()], 1, today)
        if d and claim(*m.span()):
            add(d, "month", m)

    out = sorted(found.values(), key=lambda c: c["pos"])
    for c in out:
        c.pop("pos", None)
    return out[:limit]
