"""De-duplicate events that arrive from multiple subscribed calendars/feeds.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The same real-world event often comes from several calendars (World Press Freedom Day is
in both ``civic`` and ``un_days``; an election from a national feed *and* an aggregator).
We collapse them into one display row — an "event family" — keeping every source, and we
**surface** any date disagreement rather than silently picking one (a moved/contested
date is information, like the law tracker's diff). Pure functions, no I/O.
"""

from __future__ import annotations

import re


def _norm_title(title: str) -> str:
    """Lowercase, drop parenthetical source-suffixes ('(UN)'), keep alphanumerics."""
    t = re.sub(r"\([^)]*\)", " ", title or "")
    return re.sub(r"[^0-9a-z]+", " ", t.lower()).strip()


def _when_key(e: dict) -> str:
    """The COARSE 'when' for the fingerprint: month (or cadence), NOT the exact day.

    Grouping on the month — not the day — is deliberate: it lets two feeds that give the
    *same* event slightly *different* dates still group, so the disagreement can be
    surfaced (see ``date_variants``) instead of producing two silent rows.
    """
    if e.get("next_occurrence"):
        return e["next_occurrence"][5:7]  # MM
    if e.get("month"):
        return f"{int(e['month']):02d}"
    return e.get("cadence") or ""


def _when_display(e: dict) -> str:
    return e.get("next_occurrence") or _when_key(e) or "—"


def fingerprint(e: dict) -> tuple[str, str, str]:
    """Identity key: normalised title + when + country (catches cross-feed duplicates)."""
    return (_norm_title(e.get("title", "")), _when_key(e), (e.get("country") or "").upper())


def dedup(events: list[dict], cal_names: dict[str, str] | None = None) -> list[dict]:
    """Collapse duplicate events into one row each, preserving sources + flagging
    date disagreements. Input order is preserved (first occurrence wins as canonical).
    """
    cal_names = cal_names or {}
    order: list[tuple] = []
    groups: dict[tuple, list[dict]] = {}
    for e in events:
        fp = fingerprint(e)
        if fp not in groups:
            order.append(fp)
            groups[fp] = []
        groups[fp].append(e)

    out: list[dict] = []
    for fp in order:
        members = groups[fp]
        canon = members[0]
        sources, displays = [], []
        for m in members:
            if m.get("calendar") and m["calendar"] not in sources:
                sources.append(m["calendar"])
            d = _when_display(m)
            if d not in displays:
                displays.append(d)
        merged = {
            **canon,
            "sources": sources,
            "also_in": [cal_names.get(s, s) for s in sources if s != canon.get("calendar")],
            "duplicate_count": len(members),
        }
        if len(displays) > 1:  # the feeds disagree on the date — surface, don't hide
            merged["date_variants"] = displays
        out.append(merged)
    return out
