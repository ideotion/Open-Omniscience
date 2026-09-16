"""
The model-bench batch/anchors/run endpoints and gates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 6460-6741 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

from ._base import router


# --------------------------------------------------------------------------- #
#  E-S2 (2026-08-01 rulings 14-16): the COMPARATIVE model bench.
#
#  The maintainer's question -- "does the ruled default model deserve to stay the
#  default, and how do the small candidates compare?" -- is answered by a
#  measurement, not an opinion. These endpoints build the FROZEN inputs once, take
#  the ~50-keyword grading sitting once, and then run every roster model on every
#  backend that serves it over exactly those inputs. Nothing here changes the
#  active model: the bench MEASURES, the decision is the maintainer's, made on the
#  verified logs (ai-proposed -> claude-verified -> maintainer-merged).
# --------------------------------------------------------------------------- #
class ModelBenchBatchBody(BaseModel):
    target_size: int = Field(
        default=450, ge=20, le=2000,
        description="how many keywords the frozen batch carries (~400-500 is the ruled size)",
    )
    source_sample: int = Field(
        default=20, ge=1, le=200,
        description="how many sources carry the tag-assignment evidence",
    )
    scan_limit: int = Field(
        default=20000, ge=100, le=200000,
        description="how deep into the article-spread order the sample is drawn from",
    )


class ModelBenchAnchorsBody(BaseModel):
    anchors: list[dict] = Field(
        description=(
            "the grading sitting: [{term, verdict: junk|content|unsure, kind?: "
            "person|org|place|other}]. An unknown verdict/kind is REFUSED, not "
            "snapped to a near value; a term graded twice is refused rather than "
            "letting one grade silently win."
        )
    )


class ModelBenchRunBody(BaseModel):
    """What a bench run may be asked for, now that there is one model to ask about.

    The roster fields this body used to carry (``models``, ``extra_models``,
    ``backends``, ``allow_backend_switch``) went with the 2026-08-12 one-model ruling.
    They existed to choose between models and to hand the GPU around between them; the
    choice has been made, and the maintainer took the handing-around back in the same
    message. What is left is the protocol: measure THE model on whichever backend the
    operator has running, once per backend, and compare the two reports.
    """

    repeats: int = Field(default=2, ge=1, le=10, description="timed calls per latency shape")
    restart: bool = Field(
        default=False, description="ignore the saved cursor and re-measure from the start"
    )


def _model_bench_worker(ctx, **kwargs) -> dict:
    """Measure the DEFAULT model on whichever backend the operator has running.

    RULED 2026-08-12 (maintainer): *"The app has failed to manage both ollama and vllm,
    so I'll do the managing myself."* So this starts nothing, stops nothing and hands
    no model over; it measures the machine as the operator arranged it and refuses
    honestly when nothing is up.
    """
    from src.ai_layer.model_bench import run_default_model_bench

    return run_default_model_bench(ctx, **kwargs)


_MODEL_BENCH_JOB = register_job(
    BackgroundJob(
        "model-bench", "Comparative model bench (every roster model, same frozen inputs)",
        _model_bench_worker, is_writer=False, cancellable=True,
    )
)


@router.post("/model-bench/batch")
def model_bench_build_batch(
    body: ModelBenchBatchBody, db: Session = Depends(get_db)
) -> JSONResponse:
    """Build and freeze the bench inputs: a stratified keyword sample (equal
    per-language quotas, head and tail apart), the source evidence, and the corpus's
    own closed tag vocabulary. Read-only on the corpus.

    Building a fresh batch per model would make the numbers LOOK comparable while
    measuring different work, so this is done once and every run reads it back --
    each bench report carries the batch's digest, and a resume whose digest moved is
    refused rather than blending two input sets."""
    from src.ai_layer.bench_batch import collect_frozen_inputs, save_frozen_batch

    payload = collect_frozen_inputs(
        db,
        scan_limit=body.scan_limit,
        source_sample=body.source_sample,
        target_size=body.target_size,
    )
    path = save_frozen_batch(payload)
    out = {k: v for k, v in payload.items() if k not in ("keywords", "sources")}
    out["path"] = str(path)
    return JSONResponse(out)


@router.get("/model-bench/batch")
def model_bench_batch() -> JSONResponse:
    """The frozen batch's summary (strata, digest, sizes) without its rows. Honest
    ``{available:false}`` with the reason when none has been built."""
    from src.ai_layer.bench_batch import BenchArtifactError, load_frozen_batch

    try:
        payload = load_frozen_batch()
    except BenchArtifactError as exc:
        return JSONResponse({"available": False, "reason": str(exc)})
    out = {k: v for k, v in payload.items() if k not in ("keywords", "sources")}
    out["available"] = True
    return JSONResponse(out)


@router.get("/model-bench/anchors")
def model_bench_anchors(sample: int = Query(0, ge=0, le=500)) -> JSONResponse:
    """The graded anchors, or -- with ``sample=N`` -- N terms drawn FROM the frozen
    batch to put in front of the maintainer for grading.

    The anchors are what turn "the models agree" into "the models are right", and
    they are drawn from the batch precisely so every graded term is one the models
    are actually asked about."""
    from src.ai_layer.bench_batch import BenchArtifactError, anchor_candidates, load_anchors

    if sample:
        from src.ai_layer.bench_batch import load_frozen_batch

        try:
            batch = load_frozen_batch()
        except BenchArtifactError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JSONResponse({"candidates": anchor_candidates(batch, sample)})
    existing = load_anchors()
    if not existing:
        return JSONResponse(
            {
                "available": False,
                "note": (
                    "no anchors have been graded yet -- anchor accuracy will report as "
                    "UNMEASURED, which is what it is. Ask for ?sample=50 to start a sitting."
                ),
            }
        )
    existing["available"] = True
    return JSONResponse(existing)


@router.post("/model-bench/anchors")
def model_bench_save_anchors(body: ModelBenchAnchorsBody) -> JSONResponse:
    """Persist a grading sitting. Graded ONCE, reused across every model and every
    future run. 400 (loudly) on a malformed grade rather than repairing it."""
    from src.ai_layer.bench_batch import BenchArtifactError, build_anchors, save_anchors

    try:
        payload = build_anchors(body.anchors)
    except BenchArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["path"] = str(save_anchors(payload))
    return JSONResponse(payload)


@router.post("/model-bench/run")
def model_bench_run(body: ModelBenchRunBody) -> JSONResponse:
    """Start (or resume) the model bench as a cancellable background job.

    Measures the DEFAULT model on whichever backend is already serving, and manages
    nothing. Resumable: a cancelled or crashed run keeps what it finished. It never
    changes the active model and never downloads weights. 409 while the frozen batch is
    missing -- the tasks have nothing to ask about without it."""
    from src.ai_layer.bench_batch import BenchArtifactError, load_frozen_batch

    try:
        load_frozen_batch()
    except BenchArtifactError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        st = _MODEL_BENCH_JOB.start(
            repeats=body.repeats,
            restart=body.restart,
        )
        st["started"] = True
    except RuntimeError:
        st = _MODEL_BENCH_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/model-bench/status")
def model_bench_status() -> JSONResponse:
    """Progress: which (model, backend) pair is being measured, and on which task."""
    return JSONResponse(_MODEL_BENCH_JOB.status())


@router.post("/model-bench/cancel")
def model_bench_cancel() -> JSONResponse:
    """Stop at the next safe point. Finished pairs are kept; the next run resumes."""
    _MODEL_BENCH_JOB.cancel()
    return JSONResponse(_MODEL_BENCH_JOB.status())


@router.get("/model-bench/last")
def model_bench_last(full: bool = Query(False)) -> JSONResponse:
    """The newest saved bench artifact, SUMMARISED by default (every metric, without
    the hundreds of per-term answers per pair). ``full=1`` returns the raw artifact --
    the per-term answers are what a verification session re-judges."""
    from src.ai_layer.model_bench import last_model_bench_report

    return JSONResponse(last_model_bench_report(summary=not full))


@router.get("/model-bench/download")
def model_bench_download() -> Response:
    """Serve the newest bench artifact whole -- the ONE log the maintainer uploads
    for the verification chain. 404 until a run has produced one."""
    from src.ai_layer.bench_batch import bench_dir

    files = sorted(bench_dir().glob("oo-model-bench-*.json"))
    if not files:
        raise HTTPException(
            status_code=404,
            detail="no model-bench artifact yet -- start one with "
            "POST /api/diagnostics/model-bench/run",
        )
    return FileResponse(files[-1], media_type="application/json", filename=files[-1].name)


@router.get("/model-bench/gates")
def model_bench_gates(model: str | None = Query(None)) -> JSONResponse:
    """The per-language task gates the newest bench artifact supports (read-only).

    Two shapes, and the difference is the point rather than an implementation
    detail. Triage and source tags know an item's language BEFORE the call, so their
    gates LICENSE: an unmeasured language refuses, because running there would be
    unmeasured work. Language detection does not know the language before the call --
    that is the question -- so its gate is a VETO on the ANSWER: only a label the
    bench measured this model getting wrong more often than right is refused, and a
    label the gold set never covered is stored exactly as it always was. Refusing
    those would disable detection for languages nobody tested rather than for
    languages that failed.

    WIRED TODAY: the langdetect veto (it STORES a label, so a measured-wrong answer
    has to be stopped). The triage and source-tag gates are computed and shown but
    not yet applied at selection -- both sweeps are EXPORT-ONLY JSONL reviewed by the
    verification chain, so an unreliable verdict there is already caught by a human
    before it becomes an artifact.
    """
    from src.ai_layer.task_gates import (
        GATED_TASKS,
        MIN_ANSWER_PRECISION,
        MIN_FORMAT_VALIDITY,
        MIN_OBSERVATIONS,
        current_task_gate,
    )

    return JSONResponse(
        {
            "gates": {task: current_task_gate(task, model=model) for task in GATED_TASKS},
            "wired": ["langdetect"],
            "floors": {
                "min_format_validity": MIN_FORMAT_VALIDITY,
                "min_answer_precision": MIN_ANSWER_PRECISION,
                "min_observations": MIN_OBSERVATIONS,
            },
            "method": (
                "Read from the newest comparative-bench artifact. Triage/source-tag gates "
                "license (unmeasured refuses); the langdetect gate vetoes (only a measured "
                "failure refuses). Tri-state throughout: cleared / failed / unmeasured, "
                "never collapsed into each other."
            ),
            "caveat": (
                "The floors are JUDGEMENTS, written in src/ai_layer/task_gates.py so the "
                "first real bench run can revise them on evidence. They are deliberately "
                "low: the gold sets are small, and a stricter floor would be a number "
                "nobody measured. Empty gates mean no bench has run — not that everything "
                "passed."
            ),
        }
    )
