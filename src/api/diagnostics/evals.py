"""
Eval harnesses, the KPI board, run journal/timeline and IR-eval gold builder.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 1262-1613 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router


@router.get("/ir-eval-selftest")
def ir_eval_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the IR retrieval-eval harness self-test (keyword-engine Phase 3).

    Proves the metric MECHANISM (nDCG/MRR/Recall/P@k + per-language aggregation + the
    conflation recall/precision deltas + the regression gate) on a hand-computed fixture —
    no DB, no network, no score. A real retrieval measurement needs a human-judged GOLD
    SET over your own corpus (graded 0/1/2), fed to evaluate_against_corpus(); this
    endpoint verifies the harness is correct so that measurement can be trusted. With
    ``download=1`` it comes back as a dated attachment."""
    from src.analytics.ir_eval import run_ir_eval_selftest

    log = run_ir_eval_selftest()
    headers = {}
    if download:
        fname = f"oo-ir-eval-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/perception-eval-selftest")
def perception_eval_selftest(download: bool = Query(False)) -> JSONResponse:
    """S6.5: run the LLM-perception (who/where/when) eval-harness self-test — the GATE for the
    perception track (harness before any extraction feature, the ruled order). Proves the
    scoring MECHANISM (precision/recall/HALLUCINATION-rate per stratum vs a synthetic gold set;
    place string vs coordinate scored separately; de-US-centring split) on a hand-computed
    fixture — deterministic, no model, no network, no score. A real model is measured against
    the rule-based baseline via evaluate_perception() before it is trusted; this verifies the
    harness is correct so that measurement can be. ``download=1`` returns a dated attachment."""
    from src.analytics.perception_eval import run_perception_eval_selftest

    log = run_perception_eval_selftest()
    headers = {}
    if download:
        fname = f"oo-perception-eval-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


class PerceptionEvalLiveBody(BaseModel):
    model: str | None = Field(
        default=None,
        description="an installed model tag; defaults to the active backend's default model",
    )


@router.post("/perception-eval-live")
def perception_eval_live(body: PerceptionEvalLiveBody) -> JSONResponse:
    """B6 (2026-07-24 Session B): run the S6.5 perception harness against the
    ACTIVE model (whichever backend is resolved -- vLLM on a GPU machine,
    Ollama otherwise) over REAL generate() calls -- the gate that must pass
    BEFORE any who/where/when extraction feature ships. Bounded (one call per
    gold-set case, small by design) and synchronous, mirroring ``/ir-eval``'s
    own "bounded read-only eval, not a job" posture. Persists a dated JSON
    artifact (served via ``/perception-eval-live/last``) so the maintainer can
    download the gate evidence. Loopback inference is airplane-safe, same as
    every other local-model diagnostic here."""
    from src.ai_layer.perception_job import run_and_persist_perception_eval

    out = run_and_persist_perception_eval(model=body.model)
    return JSONResponse(out)


@router.get("/perception-eval-live/last")
def perception_eval_live_last() -> JSONResponse:
    """A JSON SUMMARY of the newest saved live perception-eval run (read-only;
    never runs an eval). Returns ``{available:false}`` honestly when none has
    been run."""
    from src.ai_layer.perception_job import last_perception_eval_live_report

    return JSONResponse(last_perception_eval_live_report())


@router.get("/keyword-triage-selftest")
def keyword_triage_selftest(download: bool = Query(False)) -> JSONResponse:
    """§8: run the LLM keyword-triage self-test — the measure-before-trust GATE before any real
    triage run. Proves the MECHANISM (the constrained-verdict parser · echo-back validation ·
    canaries · Ollama-timing pass-through · the bench metrics reported ALONE) on a deterministic
    STUB — no model, no network, no score, and NEVER the trusted keyword index (triage is
    EXPORT-ONLY JSONL). The real batch + the 7-model bench are operator-run on the Ollama rig
    (§8.3: a CPU-only box understates the real rig); this verifies the harness is correct so
    that measurement can be trusted. ``download=1`` returns a dated attachment."""
    from src.ai_layer.triage import run_triage_selftest

    log = run_triage_selftest()
    headers = {}
    if download:
        fname = f"oo-keyword-triage-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/recursive-loop")
def recursive_loop(download: bool = Query(False)) -> JSONResponse:
    """§6: the recursive-improvement loop SELF-INVENTORY — imports + runs each of the loop's own
    mechanism-proof GATES (the keyword / IR-eval / perception / keyword-triage self-tests) and
    reports per-gate importable/passed/error, so the recursive-improvement agent (or the
    maintainer) knows the MEASUREMENT INSTRUMENTS themselves are trustworthy before acting on any
    diagnostic number ("the instruments improve, which improves the loop"). Read-only,
    deterministic, no DB / no network, no score; degrades loudly (an un-importable or raising gate
    is reported with its error, never a fabricated green). ``download=1`` returns a dated
    attachment. NOTE: §6's ui_walk (screenshot/console walk) + the AppVM runner are browser/VM-
    gated and are not part of this in-process check."""
    from src.monitoring.recursive_loop import recursive_loop_report

    log = recursive_loop_report()
    headers = {}
    if download:
        fname = f"oo-recursive-loop-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/merge")
def merge_diag(
    download: bool = Query(False),
    probe: bool = Query(True),
) -> JSONResponse:
    """Where a merge's time and memory go — measured on THIS machine, not inferred.

    Five blocks, each degrading on its own: the engine's compile-time temp-storage
    default (the fact that made every plaintext probe measure the opposite of
    production); this corpus's real average article size and the window the merge
    therefore derives; which SQL statement was in flight, SAMPLED from the capped
    beat ring; exact per-statement seconds from any pre-2026-08-06 journal that
    still carries per-statement records; and a bounded synthetic INSERT..SELECT at
    this corpus's real row size, timed with temp storage in RAM and on disk.

    ``probe=0`` skips only the synthetic benchmark (~50 MB written to a swept temp
    directory under the data dir, deleted in a finally). Everything else is
    read-only: no live-corpus write, no network, no score."""
    from src.monitoring.merge_diag import merge_diagnostics

    log = merge_diagnostics(probe=probe)
    headers = {}
    if download:
        fname = f"oo-merge-diag-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/kpi")
def kpi(download: bool = Query(False)) -> JSONResponse:
    """R1 (V1_PATHWAY §2.3): the read-only K1–K14 KPI SNAPSHOT — the V1 definition made
    mechanical so the KPI differ (scripts/kpi_diff.py) can classify improved/regressed between
    two cycles. Every metric carries a declared direction-of-goodness + target + an honest
    verdict (green / red / not-measurable-here — NEVER a fabricated pass). NO composite. This GET
    reads ONLY the cheap in-process instruments (the latency reservoir K2, the locale files K11);
    every expensive or operator/gold-set/CI-gated metric reports not-measurable-here rather than
    triggering a heavy crunch. Plain def (threadpool). ``download=1`` returns a dated attachment."""
    from src.monitoring.kpi import kpi_snapshot

    log = kpi_snapshot()
    headers = {}
    if download:
        fname = f"oo-kpi-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/search-timing")
def search_timing(download: bool = Query(False)) -> JSONResponse:
    """§4: the per-search intra-request timing aggregate — per-phase (FTS MATCH · content fetch ·
    serialization) percentiles over a bounded recent-window of instrumented searches, and the
    MEASURED dominant phase (highest p95 wall-clock = the §4 optimization target chosen by
    evidence, not theory). Read-only; degrades to an honest empty report before any search is
    instrumented (wiring instrument_search into the search endpoint on the operator's live
    encrypted corpus is the §4 CI/operator step — see search_timing.py). No composite score.
    ``download=1`` returns a dated attachment."""
    from src.monitoring.search_timing import search_timing_report

    log = search_timing_report()
    headers = {}
    if download:
        fname = f"oo-search-timing-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


def _run_journal_raw() -> dict:
    from src.backup.runlog import raw_runs

    return raw_runs()


@router.get("/run-timeline")
def run_timeline(max_runs: int = Query(4, ge=1, le=20)) -> dict:
    """WHERE THE TIME WENT in each recent run -- stages, unaccounted time, and stalls.

    The run journal already recorded everything needed to explain the 2026-08-03 field
    import; extracting it took an afternoon of hand-arithmetic. That import read as
    "3h30 for 650 MB, aborted". The journal's own numbers say otherwise: eighteen
    stages in 118.6 s with the corpus committed and safe, then 2 h 20 m frozen at
    exactly article 9,000 with four worker processes measurably BUSY. Slow and hung
    are different faults needing opposite responses, and nobody should have to do
    arithmetic to tell them apart.

    Read-only over the journal files. Says "a counter did not advance", never "stuck":
    a phase that publishes no counter is not examined at all, because "not moving"
    cannot honestly be said of it.
    """
    from src.monitoring.run_timeline import latest_run_timeline

    return latest_run_timeline(max_runs=max_runs)


@router.get("/run-journal")
def run_journal(download: bool = Query(False), limit: int = Query(20, ge=1, le=200)) -> JSONResponse:
    """Import/export RUN JOURNALS — the crash-surviving record of what each run was
    doing while it ran.

    Field night 2026-07-31: a 686,896-article import sat on one progress line for
    seven hours, and answering "stuck or slow?" took manual ``ps`` sampling. When it
    was killed there was no report at all, because every number the import path
    produces is written once, at the end, on the success path. This reads the sink
    that fixes that: per-run milestones (stage begin/end, knobs, merge steps, resume
    state, errors) plus a heartbeat carrying CPU-time deltas for the parent AND its
    pool children, memory, swap, disk-free, WAL size and write-gate state.

    Read-only; an install that has never imported returns an empty list, which is a
    real answer and not an error. ``download=1`` returns a dated attachment."""
    from src.backup.runlog import list_runs, summarise

    runs = list_runs()[:limit]
    detail: list[dict] = []
    for r in runs:
        try:
            detail.append(summarise(r["run_id"]))
        except Exception as exc:  # noqa: BLE001 - one unreadable journal never hides the rest
            detail.append({"run_id": r.get("run_id"), "unreadable": f"{type(exc).__name__}"})
    payload = {
        "runs": runs,
        "detail": detail,
        "note": (
            "A run with no run_end was killed, OR had its journal disabled mid-run "
            "(e.g. a full disk). Those two are not distinguishable from the files alone, "
            "so neither is asserted."
        ),
    }
    headers = {}
    if download:
        fname = f"oo-run-journal-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


@router.get("/search-timing-selftest")
def search_timing_selftest(download: bool = Query(False)) -> JSONResponse:
    """§4: prove the search-timing MECHANISM on a deterministic injected clock — the per-phase
    wall-clock timer, the percentile aggregate, and (the point of the instrument) that the
    dominant phase is chosen by MEASURED p95, not by insertion order. No browser, no network, no
    DB, no live corpus, no score; a regression reddens both this endpoint and CI. ``download=1``
    returns a dated attachment."""
    from src.monitoring.search_timing import run_search_timing_selftest

    log = run_search_timing_selftest()
    headers = {}
    if download:
        fname = f"oo-search-timing-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/ir-eval")
def ir_eval(
    gold_path: str = Query(..., description="server-side path to a JSON gold set"),
    weights_a: str | None = Query(None, description="BM25F (title,body) weights A, e.g. '1,1'"),
    weights_b: str | None = Query(None, description="BM25F (title,body) weights B, e.g. '4,1'"),
    k: int = Query(10, ge=1, le=100),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Run the IR retrieval-eval over a human-judged GOLD SET file (the measure-before-trust
    loop, keyword-engine P3) — the in-app path that consumes what the library + template
    (``configs/ir_eval/gold_set.example.json``) make.

    Without weights it scores the LIVE search at the current BM25F default. With BOTH
    ``weights_a`` and ``weights_b`` it A/Bs two (title,body) weight sets via
    ``conflation_delta`` (recall/precision/ndcg reported SEPARATELY, no blended score), so
    the P5.1 default can be chosen on evidence. The gold set is corpus-specific + graded
    0/1/2; ``400`` on a missing/malformed gold set or bad weights (never a silent skip).
    ``download=1`` returns a dated attachment to send back."""
    from src.analytics.ir_eval import (
        GoldSetError,
        bm25f_weight_ab,
        evaluate_against_corpus,
        load_gold_set,
    )

    def _weights(spec: str) -> tuple[float, float]:
        parts = [p.strip() for p in spec.split(",")]
        if len(parts) != 2:
            raise ValueError("weights must be 'title,body' (two numbers)")
        return (float(parts[0]), float(parts[1]))

    try:
        gold = load_gold_set(gold_path)
        if weights_a and weights_b:
            out = bm25f_weight_ab(db, gold, weights_a=_weights(weights_a),
                                  weights_b=_weights(weights_b), k=k)
        elif weights_a or weights_b:
            raise ValueError("provide BOTH weights_a and weights_b to A/B, or neither")
        else:
            out = evaluate_against_corpus(db, gold, k=k)
    except GoldSetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad weights: {exc}") from exc

    payload = {"kind": "ir-eval", "n_queries": len(gold), "k": k, "result": out}
    headers = {}
    if download:
        fname = f"oo-ir-eval-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


@router.get("/gold-builder/sample")
def gold_builder_sample(
    n_queries: int = Query(15, ge=1, le=60),
    per_query: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """S5.3: sample grading candidates for the IR gold-set BUILDER — the top corpus keywords
    + their live search results (never invents a query; search history is not stored). The
    maintainer grades each result 0/1/2 in the panel, then saves via /gold-builder/save."""
    from src.analytics.gold_builder import sample_queries

    return sample_queries(db, n_queries=n_queries, per_query=per_query)


class _GoldBuilderSaveBody(BaseModel):
    path: str
    queries: list[dict] = Field(default_factory=list)


@router.post("/gold-builder/save")
def gold_builder_save(body: _GoldBuilderSaveBody) -> dict:
    """S5.3: write the graded queries as the EXACT ir_eval gold-set JSON to a server-side
    path, VALIDATED by round-trip through load_gold_set (400 on a structural problem or an
    empty set — never a silent bad file). Returns the coverage meter (queries graded per
    language / axis, n). Closes the measure-before-trust loop for OO_FAMILY_LEMMA + the BM25F
    default: the graded file feeds GET /api/diagnostics/ir-eval."""
    from src.analytics.gold_builder import build_and_save_gold_set
    from src.analytics.ir_eval import GoldSetError

    try:
        return build_and_save_gold_set(body.path, body.queries)
    except (GoldSetError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
