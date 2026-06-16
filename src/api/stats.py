"""
Official-statistics API (Group N): the descriptive directory of statistical
producers (the curated data-layer slice).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and OFFLINE: serves the curated catalog of official statistical agencies
(to be ingested LATER as controversial sources). NO figures, NO scores, NO network.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/agencies")
def stat_agencies() -> dict:
    """The curated directory of official statistical producers — government +
    international agencies, deliberately global (BRICS, Africa and smaller economies
    included alongside Western producers + IGOs). Each is flagged ``controversial``
    (an official figure is a STANCED source — stated, never a score). Descriptive
    only: no figures, no ranking, no network. ``continents_covered`` is an honest
    coverage metric (the ruling measures coverage, never assumes it)."""
    from src.stats.agencies import continents_covered, list_agencies

    agencies = list_agencies()
    return {
        "agencies": [a.to_dict() for a in agencies],
        "count": len(agencies),
        "continents_covered": sorted(continents_covered()),
        "caveat": (
            "A directory of WHO publishes official statistics — every entry is a "
            "STANCED source (a producing state has interests), never a credibility "
            "verdict. Figures, vintages and methodology come later, triangulated "
            "side by side and never averaged."
        ),
    }
