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

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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


# --- The offline-map download manager (Group M) ---------------------------- #
# Mirrors the Wikipedia dump endpoints (start/pause/resume/cancel/reorder/list):
# an OSM region download is a task-manager job that writes a FILE (no DB-writer
# contention), runs in PARALLEL up to a capacity with the excess QUEUING
# reorderably, and rides the guarded socket factory (kill switch + proxy). The
# manager is lazy (no network at import/boot); a download starts only on the
# explicit, consented operator action the frontend gates behind the network popup.


class StartRegion(BaseModel):
    code: str


class ReorderRegions(BaseModel):
    keys: list[str]


@router.get("/downloads")
def osm_downloads() -> dict:
    """Current OSM region download jobs (live state from the manager)."""
    from src.geo.osm_downloads import get_manager

    return {"downloads": get_manager().list()}


@router.post("/downloads/start")
def osm_download_start(payload: StartRegion) -> dict:
    """Begin (or resume) a region download — a task-manager job.

    The code MUST be a catalog region (the curated, dated list); unknown codes are
    refused (404) rather than guessed. Path-unsafe codes are refused (400). The
    actual fetch rides the guarded factory, so the kill switch (airplane mode)
    refuses it at the socket — this endpoint never bypasses that.
    """
    from src.geo.osm_downloads import get_manager
    from src.geo.osm_regions import get_region

    region = get_region(payload.code)
    if region is None:
        raise HTTPException(status_code=404, detail=f"unknown OSM region {payload.code!r}")
    try:
        return get_manager().start(region.code, region.name)
    except ValueError as exc:  # path-unsafe code (defense in depth)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/downloads/pause")
def osm_download_pause(key: str = Query(..., description="region code of the download")) -> dict:
    """Pause a running or queued region download (resumable; the partial file stays)."""
    from src.geo.osm_downloads import get_manager

    return {"paused": get_manager().pause(key)}


@router.post("/downloads/resume")
def osm_download_resume(key: str = Query(..., description="region code of the download")) -> dict:
    """Resume a paused region download (re-enters the queue / starts a slot)."""
    from src.geo.osm_downloads import get_manager
    from src.geo.osm_regions import get_region

    region = get_region(key)
    if region is None:
        raise HTTPException(status_code=404, detail=f"unknown OSM region {key!r}")
    try:
        return get_manager().start(region.code, region.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/downloads")
def osm_download_delete(key: str = Query(..., description="region code of the download")) -> dict:
    """Cancel a download and remove its partial file."""
    from src.geo.osm_downloads import get_manager

    return {"deleted": get_manager().delete(key)}


@router.post("/downloads/reorder")
def osm_download_reorder(payload: ReorderRegions) -> dict:
    """Reorder the QUEUED region downloads (prioritisation, like the wiki dump queue)."""
    from src.geo.osm_downloads import get_manager

    return {"queue_order": get_manager().reorder(payload.keys)}
