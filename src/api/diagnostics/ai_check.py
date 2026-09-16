"""
The one-button AI check job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 6063-6192 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from src.jobs.background import BackgroundJob, register_job

from ._base import router


# --------------------------------------------------------------------------- #
#  ONE BUTTON: every AI check on this machine, in order, one report.
#  Maintainer 2026-08-09, after running four of them by hand: "Can you simplify all
#  AI related diagnostics into one single button to test everything at once?"
# --------------------------------------------------------------------------- #
class AiCheckRunBody(BaseModel):
    repeats: int = Field(default=2, ge=1, le=10, description="timed calls per latency shape")
    levels: str = Field(
        default="1,2,4,8",
        description="comma-separated concurrency levels for the throughput sweep",
    )
    calls_per_level: int = Field(default=8, ge=1, le=200)
    include_perception: bool = Field(
        default=True,
        description=(
            "run the live who/where/when eval — the gate that decides which languages "
            "may store extractions. One call per gold case, so it is the slow step on a "
            "slow machine."
        ),
    )
    deep: bool = Field(
        default=False,
        description=(
            "also run the model bench: the frozen input set through the model task by "
            "task, on whichever backend is already serving. It starts, stops and "
            "switches nothing. Minutes become tens of minutes; the frozen inputs are "
            "built on first use and reused after, so runs stay comparable."
        ),
    )
    refresh_batch: bool = Field(
        default=False,
        description=(
            "re-sample the frozen bench inputs from the corpus. Changes the questions, so "
            "the run is NOT comparable with earlier ones and starts the bench from scratch."
        ),
    )


def _ai_check_worker(ctx, **kwargs) -> dict:
    from src.monitoring.ai_check import run_and_persist_ai_check

    return run_and_persist_ai_check(ctx, **kwargs)


_AI_CHECK_JOB = register_job(
    BackgroundJob(
        "ai-check", "AI checks (backend, latency, throughput, extraction gate, self-tests)",
        _ai_check_worker, is_writer=False, cancellable=True,
    )
)


@router.post("/ai-check/run")
def ai_check_run(body: AiCheckRunBody) -> JSONResponse:
    """Run every AI check this machine can do, in one background pass.

    A job rather than a synchronous call because the throughput sweep and the live eval
    take minutes on a slow machine, and a request that long would hold the one worker.
    Cancellable between steps; each step is timed and guarded, so a step that fails
    records why and the run continues rather than losing the ones that worked.

    Loopback inference only: no egress, airplane-safe, and it writes nothing to the
    corpus.

    ``deep`` adds the COMPARATIVE bench: every roster model, on every backend that
    serves it, over frozen inputs this endpoint builds on first use and reuses after
    (rebuilding per run would make each run incomparable with the last). It restarts
    vLLM between models and hands the GPU back and forth with Ollama, so it is measured
    in hours where the rest is measured in minutes — which is why it is a choice on one
    button rather than a second button. Whatever the run does NOT cover is listed in the
    report's ``not_run_here``, computed from what actually ran.
    """
    levels = tuple(
        int(x) for x in (body.levels or "").split(",") if x.strip().isdigit() and int(x) > 0
    )
    try:
        st = _AI_CHECK_JOB.start(
            repeats=body.repeats,
            levels=levels or None,
            calls_per_level=body.calls_per_level,
            include_perception=body.include_perception,
            deep=body.deep,
            refresh_batch=body.refresh_batch,
        )
    except RuntimeError as exc:
        st = _AI_CHECK_JOB.status()
        st["already_running"] = True
        st["detail"] = str(exc)
    return JSONResponse(st)


@router.get("/ai-check/status")
def ai_check_status() -> JSONResponse:
    """Live status of the AI-check run (state, which step, and the report when done)."""
    return JSONResponse(_AI_CHECK_JOB.status())


@router.post("/ai-check/cancel")
def ai_check_cancel() -> JSONResponse:
    """Stop the run at its next step boundary. The steps already measured are kept."""
    _AI_CHECK_JOB.cancel()
    return JSONResponse(_AI_CHECK_JOB.status())


@router.get("/ai-check/last")
def ai_check_last() -> JSONResponse:
    """The newest saved AI-check report (read-only; never starts a run). Honest
    ``{available:false}`` when none has been run on this machine."""
    from src.monitoring.ai_check import last_ai_check_report

    return JSONResponse(last_ai_check_report())


@router.get("/ai-check/download")
def ai_check_download() -> Response:
    """The newest AI-check report as one downloadable .json — the file to attach to a
    bug report. 404 until a run has produced one."""
    from src.monitoring.ai_check import last_ai_check_report

    out = last_ai_check_report()
    if not out.get("available"):
        raise HTTPException(
            status_code=404,
            detail=out.get("reason")
            or "no AI check has been run — start one with POST /api/diagnostics/ai-check/run",
        )
    fname = out.get("filename") or "oo-ai-check.json"
    return JSONResponse(out, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
