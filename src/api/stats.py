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


@router.post("/sources/ingest")
def ingest_stat_sources() -> dict:
    """Register the curated statistical producers as DISABLED, controversial sources.

    Each agency is added to the source catalog as a ``source_type="statistics"``
    Source, carrying the ``official-statistics`` + ``controversial`` tags (an
    official figure is a STANCED source — by ruling, every producer is
    ``controversial``; there is no "controversial" column). Rows are created
    DISABLED — registered, NOT scraped: official machine endpoints (SDMX / APIs)
    are preferred over scraping, wired up in a later slice.

    Additive and IDEMPOTENT — a domain already in the catalog is left untouched, so
    this is safe to call repeatedly; an operator's curation is never clobbered. NO
    ``reliability_score`` is written (no fabricated credibility score, ever). LOCAL
    DB write only: no network — ``home_url`` is reduced to a registrable domain
    locally, never fetched."""
    from src.database.session import session_scope
    from src.stats.ingest import ingest_agencies_as_sources

    with session_scope() as db:
        return ingest_agencies_as_sources(db)
