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

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.monitoring.secret_scrub import http_detail, log_failure

_LOG = logging.getLogger("api.geo")

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


# --- Which optional border files this install holds (row 158) -------------- #
# The OSM-derived border files are OPERATOR-BUILT (scripts/build_admin_boundaries.py), so most
# installs hold none of them. The map used to find out by asking for each one, and every absent
# file was a 404 the browser logged as an error: four per map open, for an install working as
# designed. The map now asks here first and requests only the files that exist. A fixed list of
# names, never a path from the caller; only whether each one is a file is read.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BORDER_FILES = (
    "osm_borders/admin0.world.json",
    "osm_admin0.json",
    "osm_borders/admin1.world.json",
    "osm_admin1.json",
)


@router.get("/border-files")
def border_files() -> dict:
    """The optional border files present in this install: "not installed" is an answer here, so
    the map never has to learn it from a 404. Local, read-only, no network."""
    return {"installed": [name for name in BORDER_FILES if (_STATIC_DIR / name).is_file()]}


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
        raise HTTPException(status_code=400, detail=http_detail(exc)) from exc
    except RuntimeError as exc:
        # The worker thread could not start (R393/R398): a named conflict the caller can retry, never a 500. Logged because the 409 reaches
        # only the caller (R386).
        log_failure(_LOG, f"the OSM region download for {region.code} was refused at start", exc, level=logging.WARNING)
        raise HTTPException(status_code=409, detail=http_detail(exc)) from exc


@router.post("/downloads/size")
def osm_download_size(
    code: str = Query(..., description="a catalogued download code"),
    consent: bool = Query(False, description="true only after the page's one online consent ran (ensureOnline)"),
) -> dict:
    """Read the mirror's EXACT size for one download before it starts (S05-04 S4, Q814 = b).

    A NETWORK read (one HEAD), so the Settings button that calls it passes the one online
    consent first (invariant #14e: the gate covers what helps you decide) AND the route itself
    refuses without it: no ``consent=true`` is a 400 and the kill switch is a 409 that says so,
    both before any socket is opened (v0.6 C3; the consent used to be held only in the page, so a
    script or a future surface reached the HEAD with none). A plain ``def``: the HEAD blocks, and
    Starlette runs it in the threadpool. A size that could not be read carries a NAMED reason
    (``airplane``, ``unreachable``, ``no-content-length``), never a 0.
    """
    from src.geo.osm_downloads import get_manager
    from src.geo.osm_regions import get_region
    from src.ingest import kill_switch_active

    region = get_region(code)
    if region is None:
        raise HTTPException(status_code=404, detail=f"unknown OSM download {code!r}")
    if not consent:
        raise HTTPException(status_code=400, detail="this size read contacts the mirror and needs the online consent; it was not given")
    if kill_switch_active():
        raise HTTPException(status_code=409, detail="refused: airplane mode is engaged, so the mirror was not asked for the size")
    return get_manager().size_reading(region.code)


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
        raise HTTPException(status_code=400, detail=http_detail(exc)) from exc
    except RuntimeError as exc:
        # The worker thread could not start (R393/R398): a named conflict the caller can retry, never a 500. Logged because the 409 reaches
        # only the caller (R386).
        log_failure(_LOG, f"the OSM region download resume for {region.code} was refused", exc, level=logging.WARNING)
        raise HTTPException(status_code=409, detail=http_detail(exc)) from exc


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


# Hard ceiling on the preview slice: a region .osm.pbf can be GBs, so the
# in-browser renderer (THEME-2 .pbf parser) reads only a BOUNDED PREFIX — the
# parser stops at the last complete block and flags the rest as truncated. 16 MB
# is plenty for a glanceable preview without shipping a huge file to the browser.
_PREVIEW_MAX = 16 * 1024 * 1024


@router.get("/regions/{code}/preview")
def osm_region_preview(
    code: str,
    max_bytes: int = Query(8 * 1024 * 1024, ge=4096, le=_PREVIEW_MAX),
) -> object:
    """A bounded byte PREFIX of a DOWNLOADED region's local ``.osm.pbf`` for the
    in-browser offline-map renderer. LOOPBACK + zero-network (it only reads a file
    already on disk). Honest: it serves a PREVIEW (the first ``max_bytes``), never
    the whole multi-GB extract — the parser renders complete blocks up to the cut
    and says so. 404 if the region has not been downloaded yet."""
    from fastapi import Response

    from src.geo.osm_downloads import osm_filename
    from src.geo.osm_regions import is_valid_code

    if not is_valid_code(code):  # path-safety: only catalogued region codes
        raise HTTPException(status_code=400, detail="unknown or malformed region code")
    from src.geo.osm_downloads import get_manager

    path = get_manager().base_dir / osm_filename(code)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="region not downloaded yet")
    cap = min(int(max_bytes), _PREVIEW_MAX)
    with open(path, "rb") as fh:
        data = fh.read(cap)
    total = path.stat().st_size
    # The DATE of the data, so the map that draws it can state it (0.6 gate, row 259): the
    # extract's replication timestamp, read from its header block alone. A file that does not
    # stamp one, or whose header cannot be read, says "unknown": never today's date.
    extract_date = "unknown"
    try:
        from src.osm.pbf import read_header

        stamp = read_header(path).replication_timestamp
        if stamp is not None:
            extract_date = stamp.date().isoformat()
    except Exception as exc:  # noqa: BLE001 - the preview is still served; the date is said to be unknown
        log_failure(_LOG, f"the header of the downloaded region {code} could not be read for its date", exc, level=logging.INFO)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "X-OO-Region-Total-Bytes": str(total),
            "X-OO-Region-Preview-Bytes": str(len(data)),
            "X-OO-Region-Truncated": "1" if len(data) < total else "0",
            "X-OO-Region-Extract-Date": extract_date,
        },
    )
