"""
The REAL, operator-runnable who/where/when EXTRACTION run (B6.2, 2026-07-24 field-
feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ai_layer/perception_extract.py`` has the measure-before-trust CORE (the per-
language harness gate, the per-article extraction-and-store batch runner) -- this
module is the thin, REAL wiring: a ``BackgroundJob`` worker driving that core over the
LIVE corpus, mirroring ``src/ai_layer/triage_job.py``'s progressive-toggle chassis
EXACTLY (persisted cursor, honest pauses, one continuing JSONL log per sweep).

ONE difference from the triage/source-tags chassis: ``Article.id`` is a simple,
strictly-ordered integer primary key (no ties), so the persisted cursor here is a
PLAIN INT -- no OR-decomposed keyset tuple is needed (that machinery in
``select_triage_batch_after`` exists specifically because many keywords can share the
same ``(article_count, mention_count)`` pair).

HONESTY BY CONSTRUCTION
  * EVAL-GATED: every fresh sweep re-reads the LAST live perception-eval report
    (``perception_job.last_perception_eval_live_report``) and records exactly which
    languages it cleared/disabled (and why) in the run header -- never a fabricated
    capability, and the log is self-describing about what evidence gated it.
  * The only DB writes are ``ai_keyword`` rows via ``record_keywords`` (never the
    trusted rule-based tables); the only file write is the append-only JSONL log +
    this module's own tiny cursor-state file.
  * Degrades LOUDLY: the local model going unavailable mid-sweep PAUSES it (progress
    saved, an honest reason recorded) -- never a fabricated completion.

Airplane-mode note: identical to ``triage_job.py`` -- this runs against LOOPBACK
inference, which the client's own kill-switch check treats as airplane-safe.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from src.ai_layer import perception_extract as PE

_LOG = logging.getLogger("ai_layer.perception_extract_job")

PERCEPTION_EXTRACT_RUN_HEADER_SCHEMA = "oo-perception-extract-run-1"
PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA = "oo-perception-extract-run-summary-1"
PERCEPTION_EXTRACT_BATCH_SCHEMA = "oo-perception-extract-batch-1"
PERCEPTION_EXTRACT_RESUME_SCHEMA = "oo-perception-extract-resume-1"

DEFAULT_BATCH_SIZE = 25
# Lives beside the triage/source-tags progress files (the same log home), but a
# DIFFERENT filename -- never confused with either sweep's own cursor.
_PROGRESS_STATE_FILENAME = "perception_extract_progress_state.json"


def _dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "triage"  # one AI-run archive, shared with triage/source-tags/eval logs
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path() -> Path:
    # Microsecond precision: two runs started within the same wall-clock second must
    # never collide onto one file and silently interleave two runs' records.
    return _dir() / f"oo-perception-extract-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.jsonl"


def _progress_state_path() -> Path:
    return _dir() / _PROGRESS_STATE_FILENAME


def load_progress_state(state_path: Path | None = None) -> dict:
    """The persisted sweep cursor ({} when no sweep ever ran / the file is
    unreadable -- a corrupt/missing state file just means "start fresh")."""
    p = state_path or _progress_state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_progress_state(state: dict, state_path: Path) -> None:
    """Atomic write (tmp + os.replace) so a crash mid-save never corrupts the cursor."""
    tmp = state_path.with_name(state_path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, state_path)


def run_progressive_perception_extract_job(
    ctx,
    *,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    keep_alive: str | None = None,
    restart: bool = False,
    max_batches: int | None = None,
    max_workers: int = 1,
    skip_existing: bool = True,
    session_factory=None,
    client=None,
    state_path: Path | None = None,
    gate_report: dict | None = None,
) -> dict:
    """``BackgroundJob`` worker (the B5 chassis, applied to per-article who/where/when
    extraction): sweep every non-quarantined article id-ascending, in bounded batches,
    through :func:`src.ai_layer.perception_extract.extract_perception_batch` -- a
    language that failed the S6.5 harness is honestly skipped (never attempted), a
    persisted cursor survives a cancel/restart/outage, and a local-model outage PAUSES
    the sweep (progress saved) rather than erroring out.

    ``gate_report`` is the test/injection seam for "the last live perception-eval
    report"; when ``None`` it resolves via
    :func:`src.ai_layer.perception_job.last_perception_eval_live_report` (an empty/
    never-run report gates EVERY language as "never evaluated" -- the sweep then
    honestly extracts nothing, which is the correct behaviour when no eval evidence
    exists yet, never a guessed pass).

    ``max_batches`` bounds ONE call (mirrors ``run_progressive_triage_job``'s per-call
    budget). ``restart=True`` discards any saved cursor and starts a brand-new sweep (a
    new dated log file); otherwise an existing unfinished sweep's log is REUSED."""
    from src.ai_layer.perception import PERCEPTION_PROMPT_VERSION
    from src.ai_layer.triage import export_triage_jsonl
    from src.database.session import session_scope

    if session_factory is None:
        session_factory = session_scope
    if client is None:
        from src.llm.backend import get_client_with_name

        _, client = get_client_with_name()
    if gate_report is None:
        from src.ai_layer.perception_job import last_perception_eval_live_report

        gate_report = last_perception_eval_live_report()
    gate = PE.gate_languages_from_report(gate_report)

    path_state = state_path or _progress_state_path()
    state = {} if restart else load_progress_state(path_state)

    cursor = 0 if restart else int(state.get("cursor") or 0)

    saved_log = state.get("log_path")
    started_fresh = False
    if saved_log and Path(saved_log).exists() and not restart and not state.get("completed_at"):
        path = Path(saved_log)
    else:
        path = _export_path()
        started_fresh = True
        cursor = 0
        header = {
            "schema": PERCEPTION_EXTRACT_RUN_HEADER_SCHEMA,
            "prompt_version": PERCEPTION_PROMPT_VERSION,
            "model": model,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "params": {
                "batch_size": batch_size,
                "skip_existing": skip_existing,
                "max_workers": max_workers,
            },
            "gate_source": {
                "report_status": gate_report.get("status") or (
                    "ok" if gate_report.get("available") else "none"
                ),
                "report_run_at": gate_report.get("run_at"),
                "report_model": gate_report.get("model"),
            },
            "active_languages": sorted(lang for lang, g in gate.items() if g["active"]),
            "disabled_languages": {lang: g["reason"] for lang, g in gate.items() if not g["active"]},
        }
        export_triage_jsonl(path, [header])
        # log_path is set IMMEDIATELY (not only once a batch completes) -- an outage
        # on the very FIRST batch must still resume the SAME log + carry forward its
        # partial totals on the next call, never silently start a second fresh log.
        state = {"started_at": header["started_at"], "log_path": str(path)}

    if not started_fresh and cursor:
        export_triage_jsonl(
            path,
            [{
                "schema": PERCEPTION_EXTRACT_RESUME_SCHEMA,
                "resumed_at": datetime.now().isoformat(timespec="seconds"),
                "cursor": cursor,
            }],
        )

    totals = dict(
        state.get("totals")
        or {
            "attempted": 0, "skipped_existing": 0, "gated": 0, "stored": 0,
            "who": 0, "where": 0, "when": 0,
        }
    )
    batches_completed = int(state.get("batches_completed", 0))

    with session_factory() as session:
        from src.database.models import Article

        total_estimate = int(
            session.query(Article.id).filter(Article.quarantined.isnot(True)).count()
        )

    paused_reason: str | None = None
    complete = False
    batches_this_call = 0

    ctx.set_progress(done=cursor, total=total_estimate, detail="starting…")

    while True:
        if ctx.stopping:
            paused_reason = "cancelled — progress is saved; start again to resume"
            break
        if max_batches is not None and batches_this_call >= max_batches:
            break  # the per-call budget is spent — a clean bounded end, not a pause
        with session_factory() as session:
            work = PE.select_perception_batch(session, cursor, batch_size)
            if not work:
                complete = True
                break
            t0 = datetime.now().isoformat(timespec="seconds")
            # extract_perception_batch never raises -- LLMUnavailable/per-item errors
            # are isolated by run_concurrent and reported via result["aborted"] below
            # (mirrors bulk_llm's/detect_for_articles's own convention).
            result = PE.extract_perception_batch(
                session, work, client, model=model, gate=gate,
                keep_alive=keep_alive, max_workers=max_workers, skip_existing=skip_existing,
            )

        detail_rec = {
            "schema": PERCEPTION_EXTRACT_BATCH_SCHEMA,
            "batch": batches_completed,
            "started_at": t0,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "last_id": work[-1].article_id,
            **{k: v for k, v in result.items() if k not in ("aborted", "reason")},
        }
        export_triage_jsonl(path, [detail_rec])
        for key in ("attempted", "skipped_existing", "gated", "stored", "who", "where", "when"):
            totals[key] += int(result.get(key) or 0)
        batches_completed += 1
        batches_this_call += 1

        if result.get("aborted"):
            # DO NOT advance the cursor past this batch: an abort partway through
            # ``work`` means some of its articles were never even attempted, and
            # jumping the cursor to work[-1] would skip them FOREVER. Leaving the
            # cursor where it was makes the NEXT resumed call re-fetch this exact
            # window; skip_existing then re-skips whatever already got stored, so
            # only the truly-unattempted tail is retried -- never lost, never redone.
            state.update({
                "totals": totals,
                "batches_completed": batches_completed,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            _save_progress_state(state, path_state)
            paused_reason = (
                f"the local model became unavailable — progress is saved; start "
                f"again to resume ({result.get('reason') or ''})"
            )
            break

        cursor = int(work[-1].article_id)
        state.update({
            "cursor": cursor,
            "log_path": str(path),
            "totals": totals,
            "batches_completed": batches_completed,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        _save_progress_state(state, path_state)
        ctx.set_progress(
            done=cursor, total=max(total_estimate, cursor),
            detail=f"batch {batches_completed} · {totals['stored']} articles extracted so far",
        )

    if complete:
        footer = {
            "schema": PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA,
            "state": "done",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "batches_completed": batches_completed,
            **totals,
            "error": None,
        }
        export_triage_jsonl(path, [footer])
        state["completed_at"] = datetime.now().isoformat(timespec="seconds")
        _save_progress_state(state, path_state)

    _LOG.info(
        "progressive perception-extract %s: complete=%s batches=%s stored=%s",
        path.name, complete, batches_completed, totals["stored"],
    )
    summary = {
        "path": str(path),
        "filename": path.name,
        "complete": complete,
        "batches_completed": batches_completed,
        "batches_this_call": batches_this_call,
        "totals": totals,
        "cursor": cursor,
    }
    if paused_reason:
        summary["paused_reason"] = paused_reason
    return summary


def last_perception_extract_report() -> dict:
    """A JSON SUMMARY of the newest saved extraction run (never the raw JSONL -- this
    feeds the all-diagnostics bundle + the panel). Mirrors
    ``triage_job.last_keyword_triage_report`` exactly. Honest ``{available: false}``
    stub when no run has ever been made; ``summary: {state: "in_progress"}`` when the
    file has no footer yet."""
    try:
        files = sorted(_dir().glob("oo-perception-extract-*.jsonl"))
        if not files:
            return {
                "schema": PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA,
                "available": False,
                "note": (
                    "no perception-extract run has been made yet -- run it from "
                    "Settings -> AI, or POST /api/diagnostics/perception-extract/run."
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
                if schema == PERCEPTION_EXTRACT_RUN_HEADER_SCHEMA:
                    header = rec
                elif schema == PERCEPTION_EXTRACT_BATCH_SCHEMA:
                    batches += 1
                elif schema == PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA:
                    footer = rec
        return {
            "schema": PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA,
            "available": True,
            "filename": path.name,
            "run_header": header,
            "batches_logged": batches,
            "summary": footer or {"state": "in_progress"},
        }
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {
            "schema": PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA,
            "available": False,
            "error": str(exc)[:300],
        }


def current_language_gate() -> dict[str, dict]:
    """A cheap, read-only preview of the language gate the NEXT sweep would use
    (computed from the last saved live-eval report) -- so the toggle UI can show
    which strata are active and why WITHOUT starting a job (the standing "gate bites"
    ruling: the toggle UI shows which strata are active and why)."""
    from src.ai_layer.perception_job import last_perception_eval_live_report

    return PE.gate_languages_from_report(last_perception_eval_live_report())


__all__ = [
    "current_language_gate",
    "last_perception_extract_report",
    "load_progress_state",
    "run_progressive_perception_extract_job",
]
