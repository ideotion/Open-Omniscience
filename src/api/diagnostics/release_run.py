"""
The 0.4 release acceptance run -- the job's routes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ADDED 2026-09-18 (maintainer ask: "automate them with a one time single (fully automated)
button in the advanced settings in the diagnostics tab"). Its OWN last-imported slice of
the diagnostics package, because the Q1139 split guard pins every earlier route's
position -- the same reason ``qualification_merge.py`` sits where it does.

The worker is :mod:`src.monitoring.release_run`; this file is the job control around it,
in the shape ``p0.py`` established: start (409-free), status, cancel, collect-now, last,
download. Every payload that leaves the process passes ``_p0_scrub`` -- the report is
passphrase-free by construction and the scrub makes that a property of the endpoint.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from src.jobs.background import BackgroundJob, register_job

from ._base import router
from .p0 import _p0_scrub


class ReleaseRunBody(BaseModel):
    dest_dir: str = Field(..., description="a separate directory with room for about three corpus copies")
    passphrase: str = Field(..., description="the backup passphrase (never stored/logged)")
    profile: str = Field("release-scale", description="release-scale | million")
    soak_hours: float = Field(72.0, gt=0, le=24 * 60)
    include_newsletters: bool = True
    online_probes: bool = True
    run_row5_quarantine: bool = False
    legacy_backup_path: str = ""
    keep_fresh_install: bool = False
    note: str = ""


def _release_run_worker(ctx, **kwargs) -> dict:
    """Lazy import so the monitoring module (and everything it composes) loads only
    when a run actually starts."""
    from src.monitoring.release_run import run_release_run

    return run_release_run(ctx, **kwargs)


_RELEASE_RUN_JOB = register_job(
    BackgroundJob(
        "release-run-0-4", "0.4 release acceptance run", _release_run_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/release-run")
def release_run_start(body: ReleaseRunBody) -> JSONResponse:
    """Start the 0.4 release acceptance run as a BACKGROUND job. Returns immediately;
    poll ``/release-run/status`` (or the task manager). 409-free: an already-running
    run is returned with ``started:false``. The destination is validated up front (400):
    a separate, writable directory that does not overlap the live data dir."""
    from src.monitoring.p0_validation import validate_dest_dir
    from src.monitoring.release_run import PROFILES

    if not body.passphrase:
        raise HTTPException(status_code=400, detail="a backup passphrase is required")
    if body.profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"profile must be one of {PROFILES}")
    try:
        validate_dest_dir(body.dest_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        job = _RELEASE_RUN_JOB.start(**body.model_dump())
        return JSONResponse({"started": True, "job": _p0_scrub(job)})
    except RuntimeError:
        return JSONResponse({"started": False, "job": _p0_scrub(_RELEASE_RUN_JOB.status())})


def _status_payload() -> dict:
    """The live job status merged with the persisted state -- so a run the process lost
    (a restart mid-soak) is reported as INTERRUPTED at the phase it was in, rather than
    vanishing into an idle job whose last report says nothing."""
    from src.monitoring.release_run import read_state

    st = _RELEASE_RUN_JOB.status()
    state = read_state()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    st["persisted"] = {
        k: state.get(k)
        for k in ("run_id", "profile", "started_at", "phase", "outcome", "report_path",
                  "updated_at", "soak", "warnings", "heartbeats_dropped", "pid")
    }
    st["persisted"]["heartbeats"] = len(state.get("heartbeats") or [])
    st["persisted"]["phases"] = [
        {k: v for k, v in ph.items() if k != "result"} for ph in (state.get("phases") or [])
    ]
    st["interrupted"] = bool(
        state and state.get("outcome") is None and not st.get("running")
        and state.get("pid") != os.getpid()
    )
    return _p0_scrub(st)


@router.get("/release-run/status")
def release_run_status() -> JSONResponse:
    """Live status (state, phase, progress detail) plus the persisted record."""
    return JSONResponse(_status_payload())


@router.post("/release-run/cancel")
def release_run_cancel() -> JSONResponse:
    """Ask the run to stop at its next safe point. A cancel mid-soak still COLLECTS the
    end-of-window readings and writes the report, because whatever the window gave is
    worth reading. Idempotent."""
    _RELEASE_RUN_JOB.cancel()
    return JSONResponse(_status_payload())


@router.post("/release-run/collect")
def release_run_collect_now() -> JSONResponse:
    """End the soak window NOW and take the end-of-window readings. The report then
    says the window was ended by the operator and how long it was -- never that the
    72 h bar was reached when it was not."""
    from src.monitoring.release_run import request_collect_now

    st = _RELEASE_RUN_JOB.status()
    if st.get("state") != "running":
        return JSONResponse({"requested": False, "reason": "no run is in progress", **_status_payload()})
    request_collect_now()
    return JSONResponse({"requested": True, **_status_payload()})


@router.get("/release-run/last")
def release_run_last() -> JSONResponse:
    """The newest saved report (read-only; never runs anything). ``{available:false}``
    honestly when none exists."""
    from src.monitoring.release_run import last_release_run_report

    return JSONResponse(_p0_scrub(last_release_run_report()))


@router.get("/release-run/download")
def release_run_download(fmt: str = Query("json", alias="format")) -> Response:
    """Serve the newest report: ``format=json`` (default) or ``format=txt``. Falls back to
    the newest file ON DISK when the in-memory job result is gone (an app restart between
    the finish and the click), like the all-diagnostics download does."""
    from src.monitoring.release_run import last_release_run_report, render_release_run_text

    st = _RELEASE_RUN_JOB.status()
    res = st.get("result") or {}
    path = res.get("path") if st.get("state") == "done" else None
    if not path or not os.path.exists(path):
        last = last_release_run_report()
        if not last.get("available"):
            raise HTTPException(status_code=404, detail="no 0.4 release run report is ready")
        from src.monitoring.release_run import _run_dir

        path = str(_run_dir() / last["source_file"])
        report = last
    else:
        report = res.get("report") or last_release_run_report()
    if fmt == "txt":
        fname = f"oo-release-run-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        return Response(
            content=render_release_run_text(_p0_scrub(report)),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return FileResponse(path, media_type="application/json", filename=os.path.basename(path))
