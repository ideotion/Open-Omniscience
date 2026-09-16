"""
Source enrichment and world-discovery job endpoints.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 1085-1261 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

from ._base import router


@router.post("/enrich-sources")
def enrich_sources(db: Session = Depends(get_db)) -> JSONResponse:
    """Enrich source metadata from the LOCAL corpus (deduced topic tags).

    Zero-network: deduces each source's topics from the keywords it actually
    publishes (keyword_tags axis="topic") and unions them into ``Source.tags`` --
    additive, never overwrites a curated tag, idempotent. This is the same pass the
    scheduler runs automatically (freshness-gated); the button forces it now. The
    networked Wikidata ``source_type`` pass is a SEPARATE, consented action (it
    egresses to Wikidata over clearnet)."""
    from src.analytics.source_topics import apply_source_topics

    result = apply_source_topics(db)
    return JSONResponse({"mode": "corpus", **result})


def _enrich_source_types_worker(ctx, *, limit: int) -> dict:
    """The Wikidata source-type enrichment, off the request thread (field test Item 8 P1).
    Opaque to progress (apply_source_types loops internally); cancel is soft — it takes
    effect when the bounded ``limit`` pass returns. Its own write_lock keeps the gate
    window bounded to the final commit."""
    from src.catalog.wikidata_apply import apply_source_types
    from src.database.session import session_scope

    with session_scope() as db:
        return apply_source_types(db, limit=limit)


_ENRICH_JOB = register_job(
    BackgroundJob(
        "enrich-source-types", "Enriching source types (Wikidata)", _enrich_source_types_worker,
        is_writer=True,
    )
)


@router.post("/enrich-source-types")
def enrich_source_types(limit: int = Query(200, ge=1, le=2000)) -> JSONResponse:
    """Fill ``Source.source_type`` from Wikidata — the NETWORKED enrichment pass, run as a
    BACKGROUND JOB so it no longer freezes the app for ~8 min (field test 2026-07-08,
    Item 8 P1). Egresses to Wikidata over clearnet (through the guarded factory: kill switch
    + proxy), so the frontend gates it with the one network consent. Refuses up front with a
    clean 409 while airplane mode is engaged. Bounded per call (``limit``) since each source
    costs two lookups; click again to continue. Poll ``/enrich-source-types/status`` or the
    task manager for progress."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    try:
        return JSONResponse({"mode": "wikidata", "started": True, "job": _ENRICH_JOB.start(limit=limit)})
    except RuntimeError:
        return JSONResponse({"mode": "wikidata", "started": False, "job": _ENRICH_JOB.status()})


@router.get("/enrich-source-types/status")
def enrich_source_types_status() -> JSONResponse:
    """Live status of the background Wikidata source-type enrichment."""
    return JSONResponse(_ENRICH_JOB.status())


@router.post("/discover-sources")
def discover_sources_endpoint(
    countries: str = Query(..., description="comma-separated ISO-2 country codes, e.g. ke,ng,br"),
    per_spec_limit: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """DISCOVER new sources from Wikidata for the given countries (enabled:false).

    Adds NEW sources (news orgs / institutions with an official website) as DISABLED
    rows for review -- never enables or scrapes anything on its own. Networked: 409
    under airplane mode, egresses through the guarded factory. Bounded to a handful of
    countries per call (each queries several media types); pick UNDER-REPRESENTED
    countries to keep the catalogue's coverage balanced."""
    codes = [c.strip().lower() for c in countries.split(",") if c.strip()]
    if not codes or not all(len(c) == 2 and c.isalpha() for c in codes):
        raise HTTPException(status_code=400, detail="countries must be ISO-2 codes, e.g. ke,ng,br")
    if len(codes) > 12:
        raise HTTPException(status_code=400, detail="at most 12 countries per call (be polite)")
    from src.catalog.discover import discover_sources

    try:
        result = discover_sources(db, codes, per_spec_limit=per_spec_limit)
    except RuntimeError as exc:  # the kill-switch up-front refusal
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse({"mode": "discovery", **result})


def _world_discovery_worker(ctx, *, countries=None, per_spec_limit=None, restart=False):
    from src.catalog.discover_job import run_world_discovery

    return run_world_discovery(
        ctx, countries=countries, per_spec_limit=per_spec_limit, restart=restart
    )


_WORLD_DISCOVERY_JOB = register_job(
    BackgroundJob(
        "discover-world-sources",
        "Discovering worldwide sources (Wikidata)",
        _world_discovery_worker,
        is_writer=True,
        cancellable=True,  # the worker checks ctx.stopping between countries
    )
)


@router.post("/discover-world")
def discover_world_sources(
    countries: str | None = Query(
        None, description="optional comma-separated ISO-2 codes; omit for ALL countries"
    ),
    per_spec_limit: int | None = Query(None, ge=1, le=5000),
    restart: bool = Query(False, description="ignore the saved cursor and re-run everything"),
) -> JSONResponse:
    """Discover new sources from Wikidata for EVERY country (or the listed ones) as a
    BACKGROUND JOB — the whole-world automation of ``/discover-sources`` (which stays
    bounded to 12 countries per synchronous call). One country at a time through the
    guarded transport; every insert is a DISABLED row for review (never auto-scraped);
    progress persists per country, so cancel / airplane / crash all RESUME instead of
    re-querying the world. Cancellable from the task manager; 409 under airplane mode."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    codes = None
    if countries:
        from src.catalog.countries import ISO_3166_1_ALPHA2

        codes = [c.strip().lower() for c in countries.split(",") if c.strip()]
        bad = [c for c in codes if c not in ISO_3166_1_ALPHA2]
        if not codes or bad:
            raise HTTPException(
                status_code=400,
                detail=f"countries must be ISO-2 codes, e.g. ke,ng,br (unrecognised: {bad})",
            )
    try:
        return JSONResponse(
            {
                "started": True,
                "job": _WORLD_DISCOVERY_JOB.start(
                    countries=codes, per_spec_limit=per_spec_limit, restart=restart
                ),
            }
        )
    except RuntimeError:
        return JSONResponse({"started": False, "job": _WORLD_DISCOVERY_JOB.status()})


@router.get("/discover-world/status")
def discover_world_status() -> JSONResponse:
    """Live status of the world discovery job + the persisted cursor (countries done /
    added totals survive restarts, so the panel can show resume state while idle)."""
    from src.catalog.discover_job import load_state

    st = load_state()
    return JSONResponse(
        {
            **_WORLD_DISCOVERY_JOB.status(),
            "cursor": {
                "countries_done": len(st.get("done", [])),
                "added_total": st.get("added_total", 0),
                "completed_at": st.get("completed_at"),
                "updated_at": st.get("updated_at"),
            },
        }
    )


@router.post("/discover-world/cancel")
def discover_world_cancel() -> JSONResponse:
    """Ask the world discovery job to stop at the next country boundary (progress is
    saved — starting it again resumes). Also reachable via the task manager's cancel."""
    _WORLD_DISCOVERY_JOB.cancel()
    return JSONResponse(_WORLD_DISCOVERY_JOB.status())
