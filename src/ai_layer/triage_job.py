"""
The REAL, operator-runnable LLM keyword-TRIAGE RUN (Section 8, maintainer-ruled 2026-07-20).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ai_layer/triage.py`` HAS the measure-before-trust core (head-scope selection,
the batch runner, the constrained-verdict parser, echo-back validation, canaries,
timing pass-through, EXPORT-ONLY JSONL) -- but ``run_triage_batch``'s only caller was
its own selftest (a stub client, no network). This module is the thin, REAL wiring:
a ``BackgroundJob`` worker that drives the SAME core over the LIVE corpus and appends
to a dated JSONL log, per the ruling ("ai-proposed -> claude-verified ->
maintainer-merged"). Nothing here is a new mechanism -- every validation rule (echo-
back, canaries, constrained verdicts, EXPORT-ONLY) is triage.py's, reused wholesale.

HONESTY BY CONSTRUCTION
  * EXPORT-ONLY: the only DB access is a READ (``select_triage_head``, a counter-only
    scan); the only write anywhere is the append-only JSONL. A crash or Ctrl-C leaves
    the trusted keyword index untouched.
  * CANARIES ride every batch (a fixed, hand-graded anchor set -- never corpus-derived,
    so the model can never learn to game them from the batch itself).
  * The RUN HEADER is written first (model + prompt version + selection params +
    corpus snapshot + started_at); a trailing SUMMARY record (this module's addition,
    since the header is written before the outcome is known and JSONL is append-only)
    carries the honest terminal state -- ``done`` / ``cancelled`` / ``error`` -- so a
    partial log is self-describing, never silently mistaken for a completed run.
  * A per-batch VERDICTS detail record (this module's addition; triage.py's own
    ``batch_record`` is counts-only, by design, to keep its 18-check selftest stable)
    carries the actual echo-validated verdicts, so a later Claude verification session
    can re-judge a stratified sample against what the model actually said.
  * Degrades LOUDLY: Ollama going unavailable mid-run (model unloaded, the process
    killed, or -- for a misconfigured non-loopback ``OO_OLLAMA_URL`` -- airplane
    mode engaged) stops the job and marks the summary ``error`` -- never a
    fabricated completion.

Airplane-mode note: this job runs against LOOPBACK Ollama, which the client's own
``_check_kill_switch`` (``src/llm/ollama.py``) treats as airplane-safe -- the run
starts and generates fine while airplane mode is engaged, same as every other
loopback LLM feature in the app. Only a genuinely non-loopback backend URL still
refuses under airplane mode (defense in depth against a misconfigured client).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from src.ai_layer import triage as T

_LOG = logging.getLogger("ai_layer.triage_job")

KEYWORD_TRIAGE_RUN_HEADER_SCHEMA = "oo-keyword-triage-run-1"  # T.run_header's own schema
KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA = "oo-keyword-triage-run-summary-1"
KEYWORD_TRIAGE_VERDICTS_SCHEMA = "oo-keyword-triage-verdicts-1"

DEFAULT_BATCH_SIZE = 25
DEFAULT_LIMIT = 500

# Fixed, hand-graded CANARY anchors -- mixed into EVERY batch (never corpus-derived,
# so the model cannot learn to special-case them). Deliberately simple/obvious verdicts;
# a real triage run's canary set is a tripwire, not a hard eval.
CANARIES: tuple[T.TriageItem, ...] = (
    T.TriageItem("cookie banner", language="en"),
    T.TriageItem("subscribe to our newsletter", language="en"),
)
CANARY_EXPECTED: dict[str, dict] = {
    "cookie banner": {"verdict": "junk"},
    "subscribe to our newsletter": {"verdict": "junk"},
}


def _triage_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "triage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path() -> Path:
    # Microsecond precision: two runs started within the same wall-clock second (a
    # tight automated loop, never a human click) must never collide onto one file
    # and silently interleave two runs' records.
    return _triage_dir() / f"oo-keyword-triage-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.jsonl"


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def run_keyword_triage_job(
    ctx,
    *,
    model: str,
    limit: int = DEFAULT_LIMIT,
    min_articles: int = 1,
    batch_size: int = DEFAULT_BATCH_SIZE,
    keep_alive: str | None = None,
) -> dict:
    """``BackgroundJob`` worker: select the head scope, batch it through
    ``run_triage_batch`` (canaries on every batch), append EXPORT-ONLY JSONL,
    return ``{path, filename, state, totals, batches_total}``.

    Read-only on the corpus (``select_triage_head`` is a counter-only scan); the
    ONLY write is the JSONL file. ``ctx.stopping`` is checked between batches
    (cooperative cancel -- a batch already in flight always finishes); an Ollama
    outage mid-run (``LLMUnavailable``) stops the job with an honest ``error``
    summary, never a fabricated completion."""
    from src.database.session import session_scope
    from src.llm.ollama import LLMUnavailable, OllamaClient

    client = OllamaClient()
    started_at = datetime.now().isoformat(timespec="seconds")

    with session_scope() as session:
        from src.database.models import Keyword

        items = T.select_triage_head(session, limit, min_articles=min_articles)
        corpus_snapshot = {
            "keywords_considered": len(items),
            "keywords_total": int(session.query(Keyword.id).count()),
        }

    path = _export_path()
    header = T.run_header(model=model, model_digest=None, hardware=None)
    header["started_at"] = started_at
    header["params"] = {
        "limit": limit,
        "min_articles": min_articles,
        "batch_size": batch_size,
    }
    header["corpus"] = corpus_snapshot
    T.export_triage_jsonl(path, [header])

    batches = list(_chunks(items, max(1, batch_size)))
    ctx.set_progress(done=0, total=len(batches), detail="starting")

    totals = {"keywords_in": 0, "verdicts_out": 0, "parse_failures": 0, "missing": 0}
    canary_ok_overall = True
    wall_total = 0.0
    state = "done"
    error_msg: str | None = None
    batches_completed = 0

    for i, chunk in enumerate(batches):
        if ctx.stopping:
            state = "cancelled"
            break
        t0 = datetime.now().isoformat(timespec="seconds")
        try:
            out = T.run_triage_batch(
                client,
                chunk,
                model=model,
                canaries=CANARIES,
                canary_expected=CANARY_EXPECTED,
                keep_alive=keep_alive,
            )
        except LLMUnavailable as exc:
            state = "error"
            error_msg = str(exc)[:300]
            break
        pb = out["parsed"]
        rec = T.batch_record(
            started_at=t0,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            gen_meta=out["gen_meta"],
            pb=pb,
            canary=out["canary"],
            model=model,
        )
        detail = {
            "schema": KEYWORD_TRIAGE_VERDICTS_SCHEMA,
            "batch": i,
            "verdicts": pb.verdicts,
            "missing": pb.missing,
        }
        T.export_triage_jsonl(path, [rec, detail])
        totals["keywords_in"] += pb.keywords_in
        totals["verdicts_out"] += pb.verdicts_out
        totals["parse_failures"] += pb.parse_failures
        totals["missing"] += len(pb.missing)
        canary_ok_overall = canary_ok_overall and bool(out["canary"].get("ok", True))
        wall_total += out["wall_s"]
        batches_completed += 1
        ctx.set_progress(
            done=batches_completed,
            total=len(batches),
            detail=f"batch {batches_completed}/{len(batches)}",
        )

    footer = {
        "schema": KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA,
        "state": state,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "batches_completed": batches_completed,
        "batches_total": len(batches),
        **totals,
        "canary_ok_overall": canary_ok_overall,
        "wall_s_total": round(wall_total, 3),
        "throughput_valid_per_s": T.valid_verdicts_per_sec(totals["verdicts_out"], wall_total),
        "error": error_msg,
    }
    T.export_triage_jsonl(path, [footer])
    _LOG.info(
        "keyword-triage run %s: state=%s batches=%s/%s verdicts_out=%s",
        path.name,
        state,
        batches_completed,
        len(batches),
        totals["verdicts_out"],
    )
    return {
        "path": str(path),
        "filename": path.name,
        "state": state,
        "totals": totals,
        "batches_total": len(batches),
        "batches_completed": batches_completed,
        "canary_ok_overall": canary_ok_overall,
        "error": error_msg,
    }


def last_keyword_triage_report() -> dict:
    """A JSON SUMMARY of the newest saved run (never the raw JSONL -- this feeds the
    all-diagnostics bundle + the panel, both of which want a small parsed dict).
    Reads the header (first line) + summary footer (if the run finished/aborted
    cleanly) + a batch count. An honest ``{available: false}`` stub when no run has
    ever been made; ``summary: {state: "in_progress"}`` when the file has no footer
    yet (a run currently in flight, or one that crashed hard before writing one)."""
    import json

    try:
        files = sorted(_triage_dir().glob("oo-keyword-triage-*.jsonl"))
        if not files:
            return {
                "schema": KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA,
                "available": False,
                "note": (
                    "no keyword-triage run has been made yet -- run it from Settings -> "
                    "Diagnostics, or POST /api/diagnostics/keyword-triage/run."
                ),
            }
        path = files[-1]
        header: dict = {}
        footer: dict | None = None
        batches = 0
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                schema = rec.get("schema")
                if schema == KEYWORD_TRIAGE_RUN_HEADER_SCHEMA:
                    header = rec
                elif schema == "oo-keyword-triage-batch-1":
                    batches += 1
                elif schema == KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA:
                    footer = rec
        return {
            "schema": KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA,
            "available": True,
            "filename": path.name,
            "run_header": header,
            "batches_logged": batches,
            "summary": footer or {"state": "in_progress"},
        }
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {
            "schema": KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA,
            "available": False,
            "error": str(exc)[:300],
        }
