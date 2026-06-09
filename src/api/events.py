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


@router.get("")
def list_events(category: str | None = Query(None, description="civic|political|economic|technology")) -> dict:
    """Curated world events, soonest fixed-date first; movable ones grouped after."""
    from src.events.catalog import agenda

    items = agenda(category=category)
    return {
        "count": len(items),
        "confirmed": sum(1 for e in items if e["confirmed"]),
        "caveat": _CAVEAT,
        "events": items,
    }
