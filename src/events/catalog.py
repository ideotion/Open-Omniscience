"""Loader for the curated world-events catalog (configs/world_events.yml).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Offline, dependency-light. Computes ``next_occurrence`` ONLY for fixed-date entries
(month + day known) — never invents a date for a summit whose exact date moves each
year (those carry ``confirmed: false`` and the user follows the official_url, or the
P1 iCal import resolves them). Honest by construction.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "world_events.yml"

_CATEGORIES = ("civic", "political", "economic", "technology")


@lru_cache(maxsize=1)
def load_events() -> list[dict]:
    """Read and validate event definitions from the YAML catalog."""
    if not CATALOG_PATH.exists():
        return []
    data = yaml.safe_load(CATALOG_PATH.read_text("utf-8")) or {}
    out = []
    for e in data.get("events", []):
        if not (isinstance(e, dict) and e.get("title") and e.get("official_url")):
            continue
        out.append({
            "title": str(e["title"]),
            "category": str(e.get("category", "other")),
            "region": e.get("region"),
            "cadence": str(e.get("cadence", "annual")),
            "month": e.get("month"),
            "day": e.get("day"),
            "confirmed": bool(e.get("confirmed", False)),
            "official_url": str(e["official_url"]),
            "note": e.get("note"),
        })
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


def agenda(category: str | None = None, today: date | None = None) -> list[dict]:
    """Events enriched with ``next_occurrence`` (fixed-date only), sorted soonest-first.

    Fixed-date events are ordered by their next occurrence; recurring/movable events
    (no exact date) follow, grouped after the dated ones, alphabetically.
    """
    today = today or date.today()
    items = []
    for e in load_events():
        if category and e["category"] != category:
            continue
        items.append({**e, "next_occurrence": _next_occurrence(e["month"], e["day"], today)})
    items.sort(key=lambda x: (x["next_occurrence"] is None, x["next_occurrence"] or "", x["title"]))
    return items
