"""
The perception-extract sweep job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 5911-6062 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import os

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from src.jobs.background import BackgroundJob, register_job

from ._base import router

# ---------------------------------------------------------------------------
#  Who/where/when PERCEPTION EXTRACTION -- eval-gated AI-layer candidates (B6,
#  2026-07-24 Session B, the NEW ask). §6.1 (the harness-against-the-active-model
#  run) is /perception-eval-live above; this is §6.2/§6.3 -- the REAL per-article
#  extraction sweep, same progressive-toggle chassis as keyword-triage/source-tags.
#  NEVER writes the trusted rule-based tables (article_mentioned_dates/_places/
#  article_entities); a language the harness failed ships DISABLED, shown via
#  /perception-extract/gate before the toggle is ever started.
# ---------------------------------------------------------------------------


class PerceptionExtractRunBody(BaseModel):
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


def _perception_extract_worker(ctx, **kwargs) -> dict:
    # A MANUAL sweep run is a user-initiated batch (2026-08-01 ruling 13): it
    # takes the exclusive hold so the coordinator stands down instead of
    # competing with it for the same single-generation backend. When the
    # COORDINATOR itself drives this sweep it calls the underlying function
    # directly, so it never holds against itself.
    from src.ai_layer.coordinator import user_batch_hold
    from src.ai_layer.perception_extract_job import run_progressive_perception_extract_job

    with user_batch_hold("manual perception extract run"):
        return run_progressive_perception_extract_job(ctx, **kwargs)


_PERCEPTION_EXTRACT_JOB = register_job(
    BackgroundJob(
        "perception-extract", "Who/where/when extraction (AI-derived candidates)",
        _perception_extract_worker, is_writer=True, cancellable=True,
    )
)


@router.get("/perception-extract/gate")
def perception_extract_gate() -> JSONResponse:
    """Which languages the LAST live perception-eval run cleared for extraction, and
    why not for the rest (read-only, cheap -- computed from the saved report; never
    starts an eval or a sweep). The standing "gate bites" ruling: the toggle UI shows
    which strata are active and why, even before the toggle is ever clicked."""
    from src.ai_layer.perception_extract_job import current_language_gate

    return JSONResponse(current_language_gate())


@router.post("/perception-extract/run")
def perception_extract_run(body: PerceptionExtractRunBody) -> JSONResponse:
    """Start (or resume) the who/where/when EXTRACTION progressive sweep as a
    BACKGROUND job: every non-quarantined article, id-ascending, in bounded batches,
    through the active backend -- a language that failed the last live perception-eval
    run (``/perception-extract/gate``) is honestly SKIPPED, never attempted. Writes
    ONLY ``ai_keyword`` candidates (kinds ``ai-who``/``ai-place``/``ai-date``, labelled
    "AI-derived - unreliable"); NEVER the trusted ``article_mentioned_*``/
    ``article_entities`` tables. A PERSISTED CURSOR survives a cancel, a crash, or an
    app restart. Loopback inference is airplane-safe. ``model`` omitted falls
    back to the operator's active model (2026-07-26 field-remarks item 2 --
    ``active_model()``, the same house-wide fallback every other AI feature
    already uses); also (400) if the resolved model is not an installed tag on
    the active backend. Poll ``/perception-extract/status``; download the
    dated log via ``/perception-extract/download``. 409-free for an
    already-running job: returns its current status with ``started:false``."""
    from src.api.llm import active_model
    from src.llm.backend import get_client_with_name
    from src.llm.ollama import LLMUnavailable

    model = body.model or active_model()
    try:
        _, active_client = get_client_with_name()
        installed = active_client.list_installed()
    except LLMUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model not in installed:
        raise HTTPException(
            status_code=400,
            detail=f"model {model!r} is not installed ({installed}); "
            "pull/serve it first, or check the active backend in Settings -> AI.",
        )
    try:
        st = _PERCEPTION_EXTRACT_JOB.start(model=model, restart=body.restart)
        st["started"] = True
    except RuntimeError:
        st = _PERCEPTION_EXTRACT_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/perception-extract/status")
def perception_extract_status() -> JSONResponse:
    """Live status of the perception-extract job (state, per-batch progress; when
    done, the ready download filename + the run summary in ``result``). No score."""
    st = _PERCEPTION_EXTRACT_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/perception-extract/cancel")
def perception_extract_cancel() -> JSONResponse:
    """Ask the running perception-extract job to stop at its next safe point (between
    batches; a batch already in flight always finishes). Idempotent."""
    _PERCEPTION_EXTRACT_JOB.cancel()
    return JSONResponse(_PERCEPTION_EXTRACT_JOB.status())


@router.get("/perception-extract/last")
def perception_extract_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved perception-extract run (read-only; never
    runs a sweep). Returns ``{available:false}`` honestly when none has been run."""
    from src.ai_layer.perception_extract_job import last_perception_extract_report

    return JSONResponse(last_perception_extract_report())


@router.get("/perception-extract/download")
def perception_extract_download() -> Response:
    """Serve the newest perception-extract JSONL log. 404 until a run has produced
    one."""
    st = _PERCEPTION_EXTRACT_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="no perception-extract log is ready -- start one with "
            "POST /api/diagnostics/perception-extract/run",
        )
    return FileResponse(
        path, media_type="application/x-jsonlines",
        filename=res.get("filename") or "oo-perception-extract.jsonl",
    )
