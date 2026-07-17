"""Loader for the curated world-events catalog (configs/world_events.yml).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Offline, dependency-light. Events are grouped into subscribable *calendars* and carry
*tags* (the facet/cross-link backbone), so a large catalog stays selectable/groupable/
filterable. ``next_occurrence`` is computed ONLY for fixed-date entries (month + day
known) — never invents a date for a summit whose exact date moves each year. Honest by
construction.
"""

from __future__ import annotations

import calendar as _calendar
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "world_events.yml"

_CATEGORIES = ("civic", "political", "economic", "technology")


@lru_cache(maxsize=1)
def _raw() -> dict:
    if not CATALOG_PATH.exists():
        return {}
    return yaml.safe_load(CATALOG_PATH.read_text("utf-8")) or {}


@lru_cache(maxsize=1)
def load_calendars() -> list[dict]:
    """The declared calendars (subscribable collections)."""
    out = []
    for c in _raw().get("calendars", []):
        if isinstance(c, dict) and c.get("key"):
            out.append(
                {
                    "key": str(c["key"]),
                    "name": str(c.get("name", c["key"])),
                    "category": str(c.get("category", "other")),
                    "description": c.get("description"),
                }
            )
    return out


def _coerce_year(v: object) -> int | None:
    """A 4-digit-ish year as int, or None. Defensive against bad YAML."""
    try:
        y = int(v)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return y if 1 <= y <= 9999 else None


@lru_cache(maxsize=1)
def load_events() -> list[dict]:
    """Read and validate event definitions from the YAML catalog.

    Beyond the simple fixed-date (month/day) annual entry, two ADDITIVE recurrence
    fields are honoured (both optional, both never invented):
      * ``origin_year`` / ``until_year`` -- the ACTIVE range of years for a recurring
        event (e.g. a day "since 1950", or a one-cycle observance that has ended). An
        occurrence outside this range is suppressed; ``origin_year`` is surfaced so a
        surface can show "since YYYY" provenance.
      * ``end_month`` / ``end_day`` -- a MONTH-SPAN (e.g. "Dry January", a multi-day
        summit). When present the occurrence is a date RANGE, not a single day; a span
        may wrap the year end (Dec -> Jan). Honest by construction: a span is only built
        from explicitly stated start+end, never guessed.
    """
    out = []
    for e in _raw().get("events", []):
        if not (isinstance(e, dict) and e.get("title") and e.get("official_url")):
            continue
        tags = [str(t) for t in (e.get("tags") or []) if t]
        out.append(
            {
                "title": str(e["title"]),
                "calendar": str(e.get("calendar", "other")),
                "category": str(e.get("category", "other")),
                "country": e.get("country"),
                "region": e.get("region"),
                "cadence": str(e.get("cadence", "annual")),
                "month": e.get("month"),
                "day": e.get("day"),
                # Floating recurrence: month + weekday + week (e.g. 3rd Tuesday of
                # March; week -1 = last). Present only for movable-by-rule events.
                "weekday": _coerce_weekday(e.get("weekday")),
                "week": e.get("week"),
                "end_month": e.get("end_month"),
                "end_day": e.get("end_day"),
                "origin_year": _coerce_year(e.get("origin_year")),
                "until_year": _coerce_year(e.get("until_year")),
                "confirmed": bool(e.get("confirmed", False)),
                "official_url": str(e["official_url"]),
                "tags": tags,
                "note": e.get("note"),
            }
        )
    return out


def _in_active_range(year: int, origin_year: int | None, until_year: int | None) -> bool:
    """Is ``year`` within the event's active [origin_year, until_year] range (inclusive)?

    Either bound may be None (open). An event that began in 2027 has no 2026 instance;
    an observance that ran only 2010-2015 has none after.
    """
    if origin_year is not None and year < origin_year:
        return False
    if until_year is not None and year > until_year:
        return False
    return True


def _span_end_date(start: date, end_month: int | None, end_day: int | None) -> date | None:
    """The end date of a span starting at ``start``, or None if no valid span end.

    A span whose (end_month, end_day) is calendar-earlier than the start is taken to
    WRAP into the next year (Dec 20 -> Jan 5). Returns None when end is absent/invalid.
    """
    if not end_month or not end_day:
        return None
    try:
        end_same = date(start.year, int(end_month), int(end_day))
    except ValueError:
        return None
    if end_same >= start:
        return end_same
    try:  # wraps the year end
        return date(start.year + 1, int(end_month), int(end_day))
    except ValueError:
        return None


# Floating (non-fixed) recurrence: "the third Tuesday of March", "last Monday of
# May" (maintainer 2026-06-18 — many real recurring events are defined this way).
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def _coerce_weekday(v) -> int | None:
    """A YAML ``weekday`` -> 0=Mon..6=Sun, from a name ('tuesday'/'tue') or an int."""
    if v is None:
        return None
    if isinstance(v, int):
        return v if 0 <= v <= 6 else None
    return _WEEKDAYS.get(str(v).strip().lower())


def nth_weekday(year: int, month: int, weekday: int, week: int) -> date | None:
    """The date of the Nth ``weekday`` (0=Mon..6=Sun) of ``month``/``year``.

    ``week`` >= 1 counts from the start (1 = first); ``week`` == -1 is the LAST one.
    Returns None when that occurrence does not exist (e.g. a 5th Friday in a month
    with only four) — the caller skips to the next year, never inventing a date.
    """
    ndays = _calendar.monthrange(year, month)[1]
    if week == -1:  # the last `weekday` of the month
        last = date(year, month, ndays)
        return date(year, month, ndays - ((last.weekday() - weekday) % 7))
    if week is None or week < 1:
        return None
    first = date(year, month, 1)
    day = 1 + ((weekday - first.weekday()) % 7) + (week - 1) * 7
    return date(year, month, day) if day <= ndays else None


def _next_occurrence(
    month: int | None,
    day: int | None,
    today: date,
    *,
    origin_year: int | None = None,
    until_year: int | None = None,
    weekday: int | None = None,
    week: int | None = None,
) -> str | None:
    """The next calendar date this entry falls on within the active year range.

    Handles BOTH a FIXED date (``month`` + ``day``) and a FLOATING one (``month`` +
    ``weekday`` + ``week``, e.g. the 3rd Tuesday of March). None if neither is fully
    specified, or if no occurrence falls in [origin_year, until_year]. Scans a few
    years forward so a future ``origin_year`` is honoured.
    """
    floating = weekday is not None and week is not None
    if not month or (not floating and not day):
        return None
    # Scan up to ~the gap to a future origin plus this/next year; bounded + cheap.
    last = today.year + 1
    if origin_year is not None and origin_year > last:
        last = origin_year
    for year in range(today.year, last + 1):
        if not _in_active_range(year, origin_year, until_year):
            continue
        try:
            d = nth_weekday(year, int(month), weekday, week) if floating else date(year, int(month), int(day))
        except (ValueError, TypeError):
            # Audit finding 2026-07-17: a fixed-date event whose day doesn't exist in
            # THIS particular year (e.g. a Feb 29 "leap day" entry, in a non-leap
            # year) used to abandon the WHOLE scan here instead of trying the next
            # candidate year — so a genuine recurring event could report "no next
            # occurrence" 3 years out of 4, even when a later year in the scanned
            # range has a perfectly valid answer. `continue`, matching the floating-
            # date branch's own "doesn't exist this year -> try the next" handling
            # two lines below.
            continue
        if d is None:  # this year's Nth-weekday doesn't exist — try the next year
            continue
        if d >= today:
            return d.isoformat()
    return None


def _span_for(e: dict, today: date) -> dict | None:
    """The current-or-next span {start, end, active} for a month-span event, else None.

    ``active`` is True when ``today`` is within the span. For the current year's span
    that has already ended, the NEXT year's span is returned (if still in range).
    """
    if not (e.get("end_month") and e.get("end_day") and e.get("month") and e.get("day")):
        return None
    origin, until = e.get("origin_year"), e.get("until_year")
    for year in (today.year - 1, today.year, today.year + 1):
        if not _in_active_range(year, origin, until):
            continue
        try:
            start = date(year, int(e["month"]), int(e["day"]))
        except (ValueError, TypeError):
            # Audit finding 2026-07-17: same fix as _next_occurrence -- a start date
            # that doesn't exist in THIS particular year (e.g. a Feb 29 start) must
            # not abandon the whole 3-year scan; try the other candidate years.
            continue
        end = _span_end_date(start, e["end_month"], e["end_day"])
        if end is None:
            return None
        if today <= end:  # the soonest span not yet finished
            return {"start": start.isoformat(), "end": end.isoformat(),
                    "active": start <= today <= end}
    return None


def agenda(
    *,
    category: str | None = None,
    calendar: str | None = None,
    country: str | None = None,
    tag: str | None = None,
    today: date | None = None,
) -> list[dict]:
    """Events matching the given facets, enriched with ``next_occurrence``, soonest-first.

    All facets are AND-combined; any omitted facet is a wildcard. Fixed-date events are
    ordered by next occurrence; movable events (no exact date) follow, alphabetically.
    """
    today = today or date.today()
    cc = (country or "").upper() or None
    items = []
    for e in load_events():
        if category and e["category"] != category:
            continue
        if calendar and e["calendar"] != calendar:
            continue
        if cc and (e["country"] or "").upper() != cc:
            continue
        if tag and tag not in e["tags"]:
            continue
        nxt = _next_occurrence(
            e["month"], e["day"], today,
            origin_year=e.get("origin_year"), until_year=e.get("until_year"),
            weekday=e.get("weekday"), week=e.get("week"),
        )
        items.append({**e, "next_occurrence": nxt, "span": _span_for(e, today)})
    items.sort(key=lambda x: (x["next_occurrence"] is None, x["next_occurrence"] or "", x["title"]))
    return items


def facets() -> dict:
    """Available filter values + per-calendar counts (drives the agenda filter UI)."""
    evs = load_events()
    cal_counts = Counter(e["calendar"] for e in evs)
    cals = [{**c, "count": cal_counts.get(c["key"], 0)} for c in load_calendars()]
    tags = sorted({t for e in evs for t in e["tags"]})
    countries = sorted({e["country"] for e in evs if e["country"]})
    categories = sorted({e["category"] for e in evs})
    return {"calendars": cals, "tags": tags, "countries": countries, "categories": categories}
