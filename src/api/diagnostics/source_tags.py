"""
The source-tags sweep job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 5746-5910 of the pre-split module, verbatim. The
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

# ---------------------------------------------------------------------------
#  Real source-TAG assignment run (design entry + GO ruling, maintainer
#  2026-07-20 -- the same chassis as the keyword-triage run above): per-source
#  top-N post-stoplist terms -> loopback Ollama -> CLOSED-vocabulary tag
#  classification (``src/ai_layer/source_tags.py``). EXPORT-ONLY JSONL; NEVER
#  writes ``Source.tags`` (the honesty rail -- the apply-reviewed-batch step is
#  later, explicit, maintainer-gated work). Mirrors the keyword-triage job
#  surface above exactly.
# ---------------------------------------------------------------------------


class SourceTagsRunBody(BaseModel):
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


def _source_tags_worker(ctx, **kwargs) -> dict:
    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold
    from src.ai_layer.source_tags_job import run_progressive_source_tags_job

    with user_batch_hold("manual source tags run"):
        return run_progressive_source_tags_job(ctx, **kwargs)


_SOURCE_TAGS_JOB = register_job(
    BackgroundJob(
        "source-tags", "LLM source-tag assignment (real run)", _source_tags_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/source-tags/run")
def source_tags_run(body: SourceTagsRunBody) -> JSONResponse:
    """Start (or resume) the REAL source-tag-assignment PROGRESSIVE SWEEP as a
    BACKGROUND job (B5, 2026-07-24 Session B, ruled -- the numeric top-N/limit
    inputs are GONE; this is now an ON/OFF toggle): resolve the live CLOSED tag
    vocabulary from every ``Source.tags`` value in the corpus, sweep EVERY source
    with sufficient evidence in bounded pages (a source below the evidence floor
    is SKIPPED, never guessed), through the local model (canaries + echo-back +
    closed-vocabulary rejection, per ``ai_layer.source_tags``), appending
    EXPORT-ONLY JSONL to ``data_dir()/triage/oo-source-tags-<date>.jsonl``. NEVER
    writes ``Source.tags``. Loopback Ollama inference is airplane-safe -- this
    endpoint runs fine under airplane mode, gated ONLY by the client's own
    loopback-vs-clearnet check. ``model`` omitted falls back to the operator's
    active model (2026-07-26 field-remarks item 2 -- ``active_model()``, the
    same house-wide fallback every other AI feature already uses); also (400)
    if the resolved model is not an installed tag. A PERSISTED CURSOR survives
    a cancel, a crash, or an app restart, so re-calling this (without
    ``restart``) continues the SAME sweep. Poll ``/source-tags/status``;
    download via ``/source-tags/download``. 409-free for an already-running
    job."""
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
        st = _SOURCE_TAGS_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _SOURCE_TAGS_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/source-tags/status")
def source_tags_status() -> JSONResponse:
    """Live status of the source-tags job (state, per-batch progress; when done,
    the ready download filename + the run summary in ``result``). No score."""
    st = _SOURCE_TAGS_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/source-tags/cancel")
def source_tags_cancel() -> JSONResponse:
    """Ask the running source-tags job to stop at its next safe point (between
    batches). The partial JSONL log is honestly marked ``cancelled``. Idempotent."""
    _SOURCE_TAGS_JOB.cancel()
    return JSONResponse(_SOURCE_TAGS_JOB.status())


@router.get("/source-tags/last")
def source_tags_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved source-tags run (read-only; never runs
    one). Returns ``{available:false}`` honestly when none has been run."""
    from src.ai_layer.source_tags_job import last_source_tags_report

    return JSONResponse(last_source_tags_report())


@router.get("/source-tags/download")
def source_tags_download() -> Response:
    """Serve the newest source-tags JSONL log (the ai-proposed artifact a Claude
    session verifies -- and the ONLY place these proposed tags live; ``Source.tags``
    is never touched by this run). 404 until a run has produced one."""
    st = _SOURCE_TAGS_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no source-tags log is ready -- start one with "
            "POST /api/diagnostics/source-tags/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-source-tags.jsonl",
    )


@router.get("/source-tags-selftest")
def source_tags_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the LLM source-tag-assignment self-test -- the measure-before-trust GATE
    before any real run, mirroring ``/keyword-triage-selftest`` exactly. Proves the
    closed-vocabulary parser (an out-of-vocabulary tag rejects the WHOLE line),
    echo-back, the explicit 'none' verdict, and canaries on a deterministic STUB --
    no model, no network, no score. ``download=1`` returns a dated attachment."""
    from src.ai_layer.source_tags import run_source_tags_selftest

    log = run_source_tags_selftest()
    headers = {}
    if download:
        fname = f"oo-source-tags-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)
