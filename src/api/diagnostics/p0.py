"""
The P0 data-safety validation job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 5425-5569 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from src.jobs.background import BackgroundJob, register_job

from ._base import router

# --------------------------------------------------------------------------- #
# P0 DATA-SAFETY VALIDATION (S1.2) — the push-button acceptance run.
#
# The v0.2.0 tag is HELD on the maintainer's live-corpus validation of the P0
# set. This job makes that run push-button: it drives the REAL backup engine
# against the operator's live corpus, verifies it, probes a STAGED restore + a
# dry-run merge PREVIEW (the live corpus is only ever read, never committed), and
# reads the merged unlock + collector instrumentation, emitting ONE report with a
# per-check verdict against the written acceptance bars. Heavy work runs on the
# job thread; the backup owns its own writer-gate + disk preflight. is_writer=False
# (it never commits the live corpus), cancellable (the backup checks should_stop).
# --------------------------------------------------------------------------- #


class P0ValidationBody(BaseModel):
    dest_dir: str = Field(..., description="a separate, empty directory for the backup (e.g. an external drive)")
    passphrase: str = Field(..., description="the backup passphrase (encrypts the volumes; never stored/logged)")
    include_newsletters: bool = True
    measure_incremental: bool = True


def _p0_validation_worker(ctx, **kwargs) -> dict:
    """Thin wrapper so the heavy p0_validation import stays lazy (only when the job
    actually runs). Returns {path, filename, report}; the passphrase never lands in
    the returned dict (BackgroundJob does not store the worker kwargs either)."""
    from src.monitoring.p0_validation import run_p0_validation

    return run_p0_validation(ctx, **kwargs)


_P0_VALIDATION_JOB = register_job(
    BackgroundJob(
        "p0-validation", "P0 data-safety validation", _p0_validation_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/p0-validation")
def p0_validation_start(body: P0ValidationBody) -> JSONResponse:
    """Start the P0 data-safety validation as a BACKGROUND job (S1.2). Returns
    immediately; poll ``/p0-validation/status`` (or the task manager) for progress,
    then GET ``/p0-validation/download`` for the report (``?format=txt`` for the
    readable version). 409-free: if one is already running, the current status is
    returned with ``started:false``.

    Validates the destination up front (400) — it must be a separate, writable
    directory that does NOT overlap the live data dir. Local only, no network."""
    from src.monitoring.p0_validation import validate_dest_dir

    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a backup passphrase is required")
    try:
        validate_dest_dir(body.dest_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job = _P0_VALIDATION_JOB.start(
            dest_dir=body.dest_dir,
            passphrase=body.passphrase,
            include_newsletters=body.include_newsletters,
            measure_incremental=body.measure_incremental,
        )
        return JSONResponse({"started": True, "job": _p0_scrub(job)})
    except RuntimeError:
        return JSONResponse({"started": False, "job": _p0_scrub(_P0_VALIDATION_JOB.status())})


def _p0_scrub(obj):
    """Defense-in-depth: recursively redact any value under a secret-looking KEY
    (passphrase / password / secret) before a job payload leaves the process.
    BackgroundJob already never stores the worker kwargs, and the report is
    passphrase-free by construction, so this changes nothing today — it makes the
    absence of a secret a PROPERTY of the endpoint, not a convention every future
    report author must remember (so a later field named e.g. 'passphrase' cannot
    silently ride out on /status)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower() if isinstance(k, str) else ""
            out[k] = "***redacted***" if any(s in kl for s in ("passphrase", "password", "secret")) else _p0_scrub(v)
        return out
    if isinstance(obj, list):
        return [_p0_scrub(v) for v in obj]
    return obj


@router.get("/p0-validation/status")
def p0_validation_status() -> JSONResponse:
    """Live status of the P0 validation job (state, per-check progress, and — when
    done — the ready report filename + the full report in ``result``). No score. The
    payload is passphrase-free by construction; _p0_scrub is a defense-in-depth net."""
    st = _P0_VALIDATION_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(_p0_scrub(st))


@router.post("/p0-validation/cancel")
def p0_validation_cancel() -> JSONResponse:
    """Ask the running P0 validation to stop at its next safe point (the backup
    checks should_stop; the throwaway restore staging and any partial backup are
    cleaned up). Idempotent."""
    _P0_VALIDATION_JOB.cancel()
    return JSONResponse(_P0_VALIDATION_JOB.status())


@router.get("/p0-validation/last")
def p0_validation_last() -> JSONResponse:
    """The newest saved P0 validation report (read-only; does NOT run a backup).
    Returns ``{available:false}`` honestly when none has been run."""
    from src.monitoring.p0_validation import last_p0_validation_report

    return JSONResponse(last_p0_validation_report())


@router.get("/p0-validation/download")
def p0_validation_download(fmt: str = Query("json", alias="format")) -> Response:
    """Serve the finished P0 validation report (S1.2). ``format=json`` (default) or
    ``format=txt`` for the readable rendering. 404 until a run has completed."""
    from src.monitoring.p0_validation import render_p0_validation_text

    st = _P0_VALIDATION_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no P0 validation report is ready — start one with POST /api/diagnostics/p0-validation",
        )
    report = res.get("report") or {}
    if fmt == "txt":
        fname = f"oo-p0-validation-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        return Response(
            content=render_p0_validation_text(report),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return FileResponse(
        path, media_type="application/json",
        filename=res.get("filename") or "oo-p0-validation.json",
    )
