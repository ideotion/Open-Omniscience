"""
The keyword-triage sweep job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 5570-5745 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

from ._base import router

# ---------------------------------------------------------------------------
#  Real keyword-TRIAGE run (Section 8, maintainer-ruled 2026-07-20): the batch
#  runner + parser + canaries + EXPORT-ONLY JSONL already existed
#  (``src/ai_layer/triage.py``) but its only caller was its own selftest. This is
#  the REAL wiring -- a visible, abortable BackgroundJob over the live corpus,
#  driving the SAME core. Mirrors the p0-validation job surface
#  exactly. NEVER writes the trusted keyword index -- EXPORT-ONLY JSONL, per the
#  ruling. The airplane/Ollama gate split (2026-07-24 field-feedback Session A,
#  §7) landed: this runs offline too, gated only by the client's own loopback-
#  vs-clearnet check -- no blanket airplane-mode refusal here anymore.
# ---------------------------------------------------------------------------


class KeywordTriageRunBody(BaseModel):
    model: str | None = Field(
        default=None,
        description=(
            "an INSTALLED model tag on the active backend (refused if not "
            "installed); omitted or null falls back to the operator's chosen "
            "active model (Settings -> AI) -- there is no need to type a model "
            "for a routine run."
        ),
    )
    restart: bool = Field(
        default=False,
        description=(
            "discard any saved sweep cursor and start a brand-new sweep (a new "
            "dated log file); otherwise an unfinished sweep RESUMES where it left "
            "off (default)."
        ),
    )


def _keyword_triage_worker(ctx, **kwargs) -> dict:
    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold
    from src.ai_layer.triage_job import run_progressive_triage_job

    with user_batch_hold("manual keyword triage run"):
        return run_progressive_triage_job(ctx, **kwargs)


_KEYWORD_TRIAGE_JOB = register_job(
    BackgroundJob(
        "keyword-triage", "LLM keyword triage (Section 8, real run)", _keyword_triage_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/keyword-triage/run")
def keyword_triage_run(body: KeywordTriageRunBody) -> JSONResponse:
    """Start (or resume) the REAL keyword-triage PROGRESSIVE SWEEP as a BACKGROUND
    job (B5, 2026-07-24 Session B, ruled -- the numeric limit/batch-size inputs are
    GONE; this is now an ON/OFF toggle): sweep the ENTIRE head scope, in bounded
    batches, through the local model (canaries on every batch, echo-back +
    constrained-verdict validation, per ``ai_layer.triage``), appending EXPORT-ONLY
    JSONL to ``data_dir()/triage/oo-keyword-triage-<date>.jsonl``. NEVER writes the
    trusted keyword index. Loopback Ollama inference is airplane-safe (the socket
    never leaves 127.0.0.1) -- so this endpoint runs fine under airplane mode,
    gated ONLY by the client's own loopback-vs-clearnet check. ``model`` omitted
    falls back to the operator's active model (2026-07-26 field-remarks item 2 --
    ``active_model()``, the same house-wide fallback every other AI feature
    already uses); also (400) if the resolved model is not an INSTALLED tag
    (``verify_roster`` -- never substitutes a 'close' tag). A PERSISTED CURSOR
    survives a cancel, a crash, or an app restart, so re-calling this (without
    ``restart``) continues the SAME sweep instead of starting over. Poll
    ``/keyword-triage/status``; download the dated log via
    ``/keyword-triage/download``. 409-free for an already-running job: returns
    its current status with ``started:false``."""
    from src.ai_layer.triage import verify_roster
    from src.api.llm import active_model
    from src.llm.backend import get_client_with_name
    from src.llm.ollama import LLMUnavailable

    model = body.model or active_model()
    try:
        _, active_client = get_client_with_name()
        installed = active_client.list_installed()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    roster = verify_roster([model], installed)
    if not roster["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"model {model!r} is not installed ({installed}); "
            "pull/serve it first, or check the active backend in Settings -> AI.",
        )
    try:
        st = _KEYWORD_TRIAGE_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _KEYWORD_TRIAGE_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/keyword-triage/status")
def keyword_triage_status() -> JSONResponse:
    """Live status of the keyword-triage job (state, per-batch progress; when done,
    the ready download filename + the run summary in ``result``). No score."""
    st = _KEYWORD_TRIAGE_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/keyword-triage/cancel")
def keyword_triage_cancel() -> JSONResponse:
    """Ask the running keyword-triage job to stop at its next safe point (between
    batches; a batch already in flight always finishes). The partial JSONL log is
    honestly marked ``cancelled`` in its trailing summary record. Idempotent."""
    _KEYWORD_TRIAGE_JOB.cancel()
    return JSONResponse(_KEYWORD_TRIAGE_JOB.status())


@router.get("/keyword-triage/last")
def keyword_triage_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved keyword-triage run (read-only; never runs
    a triage). Returns ``{available:false}`` honestly when none has been run.
    Serves the raw JSONL from ``/keyword-triage/download`` instead."""
    from src.ai_layer.triage_job import last_keyword_triage_report

    return JSONResponse(last_keyword_triage_report())


@router.get("/keyword-triage/proposal")
def keyword_triage_proposal(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """The REVIEWABLE artifact built from a finished run: junk verdicts grouped PER
    LANGUAGE (the collision-free scoped channel), kind overrides, and the evidence behind
    each proposed term — plus an explicit account of what was held back and why.

    Read-only and model-free: it reads the saved JSONL and joins the judged terms back to
    the live keyword rows for the language the log does not carry. Nothing is applied —
    a stoplist entry hides existing mentions at query time AND stops new ones being stored
    at index time, and only the second is undoable without a full re-index, which is
    exactly why this stays a proposal a human merges."""
    from src.ai_layer.triage_proposal import build_triage_proposal

    out = build_triage_proposal(db)
    headers = {}
    if download:
        fname = f"oo-keyword-triage-proposal-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(out, headers=headers)


@router.get("/keyword-triage/download")
def keyword_triage_download() -> Response:
    """Serve the newest keyword-triage JSONL log (the ai-proposed artifact a Claude
    session verifies before anything is applied). 404 until a run has produced one."""
    st = _KEYWORD_TRIAGE_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no keyword-triage log is ready -- start one with "
            "POST /api/diagnostics/keyword-triage/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-keyword-triage.jsonl",
    )
