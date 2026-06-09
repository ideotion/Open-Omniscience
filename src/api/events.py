"""World-events agenda API (P0): read-only, offline, honest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Serves the curated events catalog. Fixed-date civic observances get a real
``next_occurrence``; movable summits carry ``confirmed: false`` and link to the
official source for the precise date. No fabricated dates; no network.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/events", tags=["events"])

_CAVEAT = ("A forward-looking agenda of major recurring events. Fixed civic dates are "
           "confirmed; summit/meeting dates move each year — follow the official source "
           "for the exact date. Nothing here is fabricated.")


@router.get("/calendars")
def list_calendars() -> dict:
    """Subscribable calendars (with event counts) + the available filter facets."""
    from src.events.catalog import facets

    return facets()


@router.get("")
def list_events(
    category: str | None = Query(None, description="civic|political|economic|technology"),
    calendar: str | None = Query(None, description="a calendar key, e.g. un_days"),
    country: str | None = Query(None, description="ISO country code, e.g. FR"),
    tag: str | None = Query(None, description="a single tag, e.g. press-freedom"),
) -> dict:
    """Curated world events matching the given facets, soonest fixed-date first.

    Facets (calendar / country / category / tag) are AND-combined; omit any for a
    wildcard. Subscription itself is a client preference (which calendars to show).
    """
    from src.events.catalog import agenda

    items = agenda(category=category, calendar=calendar, country=country, tag=tag)
    return {
        "count": len(items),
        "confirmed": sum(1 for e in items if e["confirmed"]),
        "caveat": _CAVEAT,
        "events": items,
    }
