"""
Retroactive article QUARANTINE -- API endpoints (S3.2, 2026-07-23 field-feedback workflow).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Starts/controls the resumable background job (:mod:`src.analytics.quarantine_job`) that
detects already-flagged non-article junk (the #659 URL-shape rules + the NAV-SOUP prose
gate) and, when explicitly asked (``write=True``), stamps it REVERSIBLY (a flag, never a
delete -- an already-quarantined row's rows/keywords/provenance stay fully intact).

``write=False`` (the endpoint's default) is pure DETECTION, byte-identical to running the
scaffold before this slice. Starting a REAL WRITE run is a deliberate per-call choice --
the binding execution gate from the brief: the S3.1 criteria-calibration report ships and
is reviewed BEFORE any real write executes against a maintainer's corpus. Local disk/DB
work only, no network -- never airplane/consent-gated (mirrors the reindex job's own
"local DB work" posture). Pause/resume/cancel are ALSO reachable through the generic
``/api/jobs/{job_id}/...`` dispatcher (job_id="quarantine") for the task-manager UI.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/quarantine", tags=["quarantine"])


@router.post("/start")
def quarantine_start(write: bool = Query(False)) -> dict:
    """Start the retroactive quarantine job. ``write=False`` (default): pure detection,
    no database mutation. ``write=True``: additionally stamps each detected candidate,
    idempotently (an already-quarantined row is skipped, never re-stamped). 409 if a run
    is already in progress."""
    from src.analytics.quarantine_job import get_quarantine_manager

    try:
        return get_quarantine_manager().start(write=write)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def quarantine_status() -> dict:
    """Live state of the (single) background quarantine job -- for the UI + /api/jobs."""
    from src.analytics.quarantine_job import get_quarantine_manager

    return get_quarantine_manager().status()


@router.post("/{action}")
def quarantine_action(action: str) -> dict:
    """Pause / resume / cancel the running background quarantine job. A resume always
    continues in the SAME write/dry-run mode the paused run was in (never a silent flip)."""
    from src.analytics.quarantine_job import get_quarantine_manager

    mgr = get_quarantine_manager()
    if action == "pause":
        mgr.pause()
        return mgr.status()
    if action == "resume":
        try:
            return mgr.resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if action == "cancel":
        mgr.cancel()
        return mgr.status()
    raise HTTPException(status_code=400, detail=f"unknown action {action!r}")
