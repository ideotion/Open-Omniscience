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


@lru_cache(maxsize=1)
def load_events() -> list[dict]:
    """Read and validate event definitions from the YAML catalog."""
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
                "confirmed": bool(e.get("confirmed", False)),
                "official_url": str(e["official_url"]),
                "tags": tags,
                "note": e.get("note"),
            }
        )
    return out


def _next_occurrence(month: int | None, day: int | None, today: date) -> str | None:
    """The next calendar date this (month, day) falls on, or None if not a fixed date."""
    if not month or not day:
        return None
    for year in (today.year, today.year + 1):
        try:
            d = date(year, int(month), int(day))
        except ValueError:
            return None
        if d >= today:
            return d.isoformat()
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
        items.append({**e, "next_occurrence": _next_occurrence(e["month"], e["day"], today)})
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
