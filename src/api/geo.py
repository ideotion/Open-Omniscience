"""
Geo / offline-map API (Group M): the OSM region catalog for the offline-map
download manager.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and OFFLINE: serves the bundled, dated OSM region catalog with size
ESTIMATES so the picker is informative without any network call (zero-network boot /
airplane mode intact). The actual download manager (its own task-manager job, like
the Wikipedia dumps) is a follow-up slice.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/geo", tags=["geo"])


@router.get("/regions")
def osm_regions() -> dict:
    """Curated OSM region extracts (Geofabrik-style) with bundled, DATED size
    estimates — the offline-map download picker. Zero network; the exact size is
    read from the mirror at download time. ``size_estimate_as_of`` dates the
    estimates (they go stale; a freshness test forces re-review)."""
    from src.geo.osm_regions import OSM_SIZES_AS_OF, list_regions

    return {
        "regions": [r.to_dict() for r in list_regions()],
        "size_estimate_as_of": OSM_SIZES_AS_OF,
        "caveat": (
            "Sizes are estimates (reviewed "
            f"{OSM_SIZES_AS_OF}); the exact size is read from the mirror on download."
        ),
    }
