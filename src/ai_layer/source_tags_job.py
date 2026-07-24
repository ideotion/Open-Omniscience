"""
The REAL, operator-runnable LLM source-tag ASSIGNMENT run (design entry + GO ruling,
maintainer 2026-07-20 -- same day as the Section 8 triage real-run).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Thin ``BackgroundJob`` wiring around ``src/ai_layer/source_tags.py``'s core --
mirrors ``triage_job.py`` exactly (the "same chassis" the ruling calls for): select
candidates (evidence floor applied), resolve the live closed vocabulary, batch
through ``run_source_tag_batch`` (canaries on every batch), append EXPORT-ONLY
JSONL, a trailing summary record so a cancelled/aborted run is self-describing.

HONESTY BY CONSTRUCTION
  * EXPORT-ONLY: the ONLY DB access is READ (the source/keyword_mentions covering
    scan + the live ``Source.tags`` vocabulary read); the ONLY write anywhere is
    the append-only JSONL. ``Source.tags`` is NEVER touched -- the apply-reviewed-
    batch step is later, explicit, maintainer-gated work (design brief Section 6).
  * The EVIDENCE FLOOR is applied in ``select_source_tag_candidates`` before this
    module ever builds a prompt -- a skipped source never reaches the model.
  * Degrades LOUDLY on an Ollama outage mid-run, exactly like the triage job.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from src.ai_layer import source_tags as ST

_LOG = logging.getLogger("ai_layer.source_tags_job")

SOURCE_TAGS_RUN_HEADER_SCHEMA = "oo-source-tags-run-1"
SOURCE_TAGS_RUN_SUMMARY_SCHEMA = "oo-source-tags-run-summary-1"
SOURCE_TAGS_DETAIL_SCHEMA = "oo-source-tags-detail-1"

DEFAULT_BATCH_SIZE = 20
DEFAULT_TOP_N = 200
DEFAULT_MIN_ARTICLES = 5
DEFAULT_LIMIT_SOURCES = 200
_MAX_LOG_TERMS = ST._MAX_LOG_TERMS

# B5 (2026-07-24 Session B): the progressive-toggle sweep's persisted cursor filename
# -- lives beside the JSONL logs, excluded from last_source_tags_report's
# oo-source-tags-*.jsonl glob (a different name, never a run log itself).
_PROGRESS_STATE_FILENAME = "source_tags_progress_state.json"

# Hand-known, obvious CANARY sources (never real corpus rows) -- a sports outlet and
# a stats/economics agency, per the ruling's own wording. Only evaluated against
# whichever expected tag actually exists in THIS install's live vocabulary
# (``check_source_canaries``); an install without a 'sports'/'finance'-ish tag simply
# skips that canary rather than failing on a vocabulary the corpus never had.
CANARIES: tuple[ST.SourceTagItem, ...] = (
    ST.SourceTagItem(
        "canary-sports-outlet.example",
        article_count=999,
        mention_count=9999,
        language="en",
        top_terms=("football", "basketball", "olympics", "tennis", "athletes", "league standings"),
    ),
    ST.SourceTagItem(
        "canary-stats-agency.example",
        article_count=999,
        mention_count=9999,
        language="en",
        top_terms=(
            "gdp growth",
            "inflation rate",
            "unemployment",
            "trade balance",
            "economic indicators",
        ),
    ),
)
CANARY_EXPECTED: dict[str, frozenset[str]] = {
    "canary-sports-outlet.example": frozenset({"sports", "sport", "athletics"}),
    "canary-stats-agency.example": frozenset({"finance", "economy", "economics", "business"}),
}


def _dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "triage"  # same log home as keyword-triage, per the design brief
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path() -> Path:
    # Microsecond precision -- see triage_job._export_path for why.
    return _dir() / f"oo-source-tags-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.jsonl"


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def run_source_tags_job(
    ctx,
    *,
    model: str,
    top_n: int = DEFAULT_TOP_N,
    min_articles: int = DEFAULT_MIN_ARTICLES,
    min_mentions: int = 0,
    limit_sources: int = DEFAULT_LIMIT_SOURCES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    keep_alive: str | None = None,
) -> dict:
    """``BackgroundJob`` worker: resolve the live vocabulary + evidence-floored
    candidates, batch through ``run_source_tag_batch`` (canaries every batch),
    append EXPORT-ONLY JSONL, return ``{path, filename, state, totals, ...}``.

    Read-only on the corpus; the ONLY write is the JSONL file. ``Source.tags`` is
    read (to build the vocabulary) but NEVER written -- the deduced tags proposed
    here live ONLY in the JSONL log (this run's separate, labelled channel)."""
    from src.database.session import session_scope
    from src.llm.ollama import LLMUnavailable, OllamaClient

    client = OllamaClient()
    started_at = datetime.now().isoformat(timespec="seconds")

    with session_scope() as session:
        vocabulary = ST.resolve_tag_vocabulary(session)
        items, skipped, _last_domain = ST.select_source_tag_candidates(
            session,
            top_n=top_n,
            min_articles=min_articles,
            min_mentions=min_mentions,
            limit_sources=limit_sources,
        )

    path = _export_path()
    header = ST.source_tag_run_header(model=model, vocabulary=vocabulary)
    header["started_at"] = started_at
    header["params"] = {
        "top_n": top_n,
        "min_articles": min_articles,
        "min_mentions": min_mentions,
        "limit_sources": limit_sources,
        "batch_size": batch_size,
    }
    header["candidates"] = len(items)
    header["skipped_evidence_floor"] = len(skipped)
    ST.export_source_tags_jsonl(path, [header])
    # Record every skip honestly in the log too (the verification contract wants the
    # full picture, not just what was sent to the model).
    if skipped:
        ST.export_source_tags_jsonl(
            path,
            [
                {
                    "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                    "domain": s.domain,
                    "article_count": s.article_count,
                    "mention_count": s.mention_count,
                    "status": "skipped",
                    "reason": s.reason,
                }
                for s in skipped
            ],
        )

    if not vocabulary:
        # EMPTY VOCABULARY (the ruling's own skeptic, brief Section 3.5): no source in
        # the corpus carries an ASSERTED tag yet, so there is nothing to close the
        # model's vocabulary against. Sending prompts anyway would still produce an
        # honest empty (every proposed tag is out-of-vocabulary and rejected), but
        # that burns real inference time to prove nothing -- skip the model entirely
        # and say so, rather than a silent zero-length 'done'.
        footer = {
            "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
            "state": "done",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "batches_completed": 0,
            "batches_total": 0,
            "sources_in": 0,
            "assigned_count": 0,
            "none_count": 0,
            "parse_failures": 0,
            "missing": 0,
            "skipped_evidence_floor": len(skipped),
            "canary_ok_overall": True,
            "wall_s_total": 0.0,
            "throughput_valid_per_s": None,
            "error": None,
            "note": (
                "no source in the corpus carries an asserted tag yet, so the closed "
                "vocabulary is empty -- nothing was sent to the model (an honest no-op, "
                "not a silent skip)."
            ),
        }
        ST.export_source_tags_jsonl(path, [footer])
        return {
            "path": str(path),
            "filename": path.name,
            "state": "done",
            "totals": {
                "sources_in": 0,
                "assigned_count": 0,
                "none_count": 0,
                "parse_failures": 0,
                "missing": 0,
            },
            "batches_total": 0,
            "batches_completed": 0,
            "skipped_evidence_floor": len(skipped),
            "canary_ok_overall": True,
            "error": None,
            "note": footer["note"],
        }

    batches = list(_chunks(items, max(1, batch_size)))
    ctx.set_progress(done=0, total=len(batches), detail="starting")

    totals = {
        "sources_in": 0,
        "assigned_count": 0,
        "none_count": 0,
        "parse_failures": 0,
        "missing": 0,
    }
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
            out = ST.run_source_tag_batch(
                client,
                chunk,
                vocabulary=vocabulary,
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
        rec = ST.source_tag_batch_record(
            started_at=t0,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            gen_meta=out["gen_meta"],
            pb=pb,
            canary=out["canary"],
            model=model,
        )
        by_domain = {it.domain: it for it in chunk}
        detail_records = []
        for domain, tags in pb.tags.items():
            it = by_domain.get(domain)
            detail_records.append(
                {
                    "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                    "batch": i,
                    "domain": domain,
                    "language": it.language if it else None,
                    "article_count": it.article_count if it else None,
                    "mention_count": it.mention_count if it else None,
                    "evidence_sample": list((it.top_terms if it else ())[:_MAX_LOG_TERMS]),
                    "status": "none" if not tags else "tagged",
                    "proposed_tags": list(tags),
                    "provenance": "ai-proposed",  # never asserted -- see module docstring
                }
            )
        for domain in pb.missing:
            it = by_domain.get(domain)
            detail_records.append(
                {
                    "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                    "batch": i,
                    "domain": domain,
                    "language": it.language if it else None,
                    "article_count": it.article_count if it else None,
                    "mention_count": it.mention_count if it else None,
                    "evidence_sample": list((it.top_terms if it else ())[:_MAX_LOG_TERMS]),
                    "status": "rejected",
                    "proposed_tags": [],
                    "provenance": "ai-proposed",
                }
            )
        ST.export_source_tags_jsonl(path, [rec, *detail_records])
        totals["sources_in"] += pb.sources_in
        totals["assigned_count"] += pb.assigned_count
        totals["none_count"] += pb.none_count
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

    from src.ai_layer.triage import valid_verdicts_per_sec

    footer = {
        "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
        "state": state,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "batches_completed": batches_completed,
        "batches_total": len(batches),
        **totals,
        "skipped_evidence_floor": len(skipped),
        "canary_ok_overall": canary_ok_overall,
        "wall_s_total": round(wall_total, 3),
        "throughput_valid_per_s": valid_verdicts_per_sec(
            totals["assigned_count"] + totals["none_count"], wall_total
        ),
        "error": error_msg,
    }
    ST.export_source_tags_jsonl(path, [footer])
    _LOG.info(
        "source-tags run %s: state=%s batches=%s/%s assigned=%s none=%s skipped=%s",
        path.name,
        state,
        batches_completed,
        len(batches),
        totals["assigned_count"],
        totals["none_count"],
        len(skipped),
    )
    return {
        "path": str(path),
        "filename": path.name,
        "state": state,
        "totals": totals,
        "batches_total": len(batches),
        "batches_completed": batches_completed,
        "skipped_evidence_floor": len(skipped),
        "canary_ok_overall": canary_ok_overall,
        "error": error_msg,
    }


# --------------------------------------------------------------------------- #
# B5 (2026-07-24 Session B, ruled): the numeric top-N/limit-sources inputs are
# REPLACED by an ON/OFF toggle driving a PROGRESSIVE sweep across ALL sources with
# sufficient evidence -- mirrors triage_job.run_progressive_triage_job exactly (the
# "same chassis" the design brief calls for): a persisted cursor (the domain of the
# last VISITED source), one continuing JSONL log per sweep, honest pauses on a
# local-model outage or a genuine cancel (never a fabricated completion).
# --------------------------------------------------------------------------- #
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


def run_progressive_source_tags_job(
    ctx,
    *,
    model: str,
    top_n: int = DEFAULT_TOP_N,
    min_articles: int = DEFAULT_MIN_ARTICLES,
    min_mentions: int = 0,
    batch_size: int = DEFAULT_BATCH_SIZE,
    keep_alive: str | None = None,
    restart: bool = False,
    max_batches: int | None = None,
    session_factory=None,
    client=None,
    state_path: Path | None = None,
) -> dict:
    """``BackgroundJob`` worker (the progressive toggle): sweep EVERY source in the
    corpus in bounded PAGES (``batch_size`` sources per page -- a page's evidence-
    floor survivors ride ONE model call, so page size and prompt-batch size are the
    same granularity here), resuming from a PERSISTED domain cursor
    (``select_source_tag_candidates``'s ``after_domain``) so a cancel, an app
    restart, or a local-model outage all resume exactly where the sweep left off.

    The cursor only advances (and a page's skip-detail records only get logged)
    once a page is FULLY SETTLED -- either it had nothing to send (every source in
    it hit the evidence floor) or its model call succeeded; a failed model call
    leaves the cursor untouched so the SAME page is retried on the next start,
    never silently skipped and never double-logged.

    ``max_batches`` bounds ONE call (a clean bounded end, ``complete: False``).
    ``restart=True`` discards any saved cursor and starts a brand-new sweep (a new
    dated log file). Read-only on the corpus except the ONE append-only JSONL log +
    this small local progress-cursor file; ``Source.tags`` is read (to build the
    vocabulary) but NEVER written."""
    from src.database.session import session_scope
    from src.llm.ollama import LLMUnavailable

    if session_factory is None:
        session_factory = session_scope
    if client is None:
        from src.llm.backend import get_client_with_name

        _, client = get_client_with_name()

    path_state = state_path or _progress_state_path()
    state = {} if restart else load_progress_state(path_state)

    cursor: str | None = None if restart else state.get("cursor")

    with session_factory() as session:
        vocabulary = ST.resolve_tag_vocabulary(session)

    saved_log = state.get("log_path")
    started_fresh = False
    if saved_log and Path(saved_log).exists() and not restart and not state.get("completed_at"):
        path = Path(saved_log)
    else:
        path = _export_path()
        started_fresh = True
        cursor = None
        header = ST.source_tag_run_header(model=model, vocabulary=vocabulary)
        header["started_at"] = datetime.now().isoformat(timespec="seconds")
        header["params"] = {
            "top_n": top_n,
            "min_articles": min_articles,
            "min_mentions": min_mentions,
            "batch_size": batch_size,
            "mode": "progressive",
        }
        ST.export_source_tags_jsonl(path, [header])
        state = {"started_at": header["started_at"]}

    if not vocabulary:
        # Same honest early-exit as the one-shot job (brief Section 3.5's skeptic):
        # nothing in the corpus asserts a tag yet, so the closed vocabulary is empty
        # -- sending prompts anyway would only prove the same empty result at real
        # inference cost.
        footer = {
            "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
            "state": "done",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "batches_completed": 0,
            "sources_in": 0, "assigned_count": 0, "none_count": 0,
            "parse_failures": 0, "missing": 0, "skipped_evidence_floor": 0,
            "canary_ok_overall": True, "wall_s_total": 0.0,
            "throughput_valid_per_s": None, "error": None,
            "note": (
                "no source in the corpus carries an asserted tag yet, so the closed "
                "vocabulary is empty -- nothing was sent to the model."
            ),
        }
        ST.export_source_tags_jsonl(path, [footer])
        state.update({"completed_at": footer["finished_at"], "log_path": str(path)})
        _save_progress_state(state, path_state)
        return {
            "path": str(path), "filename": path.name, "complete": True,
            "batches_completed": 0,
            "totals": {"sources_in": 0, "assigned_count": 0, "none_count": 0,
                       "parse_failures": 0, "missing": 0},
            "canary_ok_overall": True, "cursor": None, "note": footer["note"],
        }

    if not started_fresh and cursor is not None:
        ST.export_source_tags_jsonl(
            path,
            [{
                "schema": "oo-source-tags-resume-1",
                "resumed_at": datetime.now().isoformat(timespec="seconds"),
                "cursor": cursor,
            }],
        )

    totals = dict(
        state.get("totals")
        or {"sources_in": 0, "assigned_count": 0, "none_count": 0, "parse_failures": 0, "missing": 0}
    )
    skipped_evidence_floor_total = int(state.get("skipped_evidence_floor_total", 0))
    batches_completed = int(state.get("batches_completed", 0))
    canary_ok_overall = bool(state.get("canary_ok_overall", True))
    wall_total = float(state.get("wall_s_total", 0.0))

    with session_factory() as session:
        from src.database.models import Source

        total_estimate = int(session.query(Source.id).count())

    paused_reason: str | None = None
    complete = False
    batches_this_call = 0

    ctx.set_progress(
        done=batches_completed * max(1, batch_size), total=total_estimate, detail="starting…"
    )

    while True:
        if ctx.stopping:
            paused_reason = "cancelled — progress is saved; start again to resume"
            break
        if max_batches is not None and batches_this_call >= max_batches:
            break

        with session_factory() as session:
            items, skipped, last_domain = ST.select_source_tag_candidates(
                session,
                top_n=top_n,
                min_articles=min_articles,
                min_mentions=min_mentions,
                limit_sources=batch_size,
                after_domain=cursor,
            )
        if last_domain is None:
            complete = True
            break

        rec = None
        if items:
            t0 = datetime.now().isoformat(timespec="seconds")
            try:
                out = ST.run_source_tag_batch(
                    client,
                    items,
                    vocabulary=vocabulary,
                    model=model,
                    canaries=CANARIES,
                    canary_expected=CANARY_EXPECTED,
                    keep_alive=keep_alive,
                )
            except LLMUnavailable as exc:
                paused_reason = (
                    f"the local model became unavailable — progress is saved; "
                    f"start again to resume ({str(exc)[:200]})"
                )
                break  # cursor/state untouched -- the SAME page is retried on resume
            pb = out["parsed"]
            rec = ST.source_tag_batch_record(
                started_at=t0,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                gen_meta=out["gen_meta"],
                pb=pb,
                canary=out["canary"],
                model=model,
            )
            by_domain = {it.domain: it for it in items}
            detail_records = []
            for domain, tags in pb.tags.items():
                it = by_domain.get(domain)
                detail_records.append({
                    "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                    "batch": batches_completed,
                    "domain": domain,
                    "language": it.language if it else None,
                    "article_count": it.article_count if it else None,
                    "mention_count": it.mention_count if it else None,
                    "evidence_sample": list((it.top_terms if it else ())[:_MAX_LOG_TERMS]),
                    "status": "none" if not tags else "tagged",
                    "proposed_tags": list(tags),
                    "provenance": "ai-proposed",
                })
            for domain in pb.missing:
                it = by_domain.get(domain)
                detail_records.append({
                    "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                    "batch": batches_completed,
                    "domain": domain,
                    "language": it.language if it else None,
                    "article_count": it.article_count if it else None,
                    "mention_count": it.mention_count if it else None,
                    "evidence_sample": list((it.top_terms if it else ())[:_MAX_LOG_TERMS]),
                    "status": "rejected",
                    "proposed_tags": [],
                    "provenance": "ai-proposed",
                })
            ST.export_source_tags_jsonl(path, [rec, *detail_records])
            totals["sources_in"] += pb.sources_in
            totals["assigned_count"] += pb.assigned_count
            totals["none_count"] += pb.none_count
            totals["parse_failures"] += pb.parse_failures
            totals["missing"] += len(pb.missing)
            canary_ok_overall = canary_ok_overall and bool(out["canary"].get("ok", True))
            wall_total += out["wall_s"]

        # Reaching here means the page is SETTLED (nothing to send, or a
        # successful model call) -- safe to log its skips + advance the cursor.
        if skipped:
            ST.export_source_tags_jsonl(
                path,
                [
                    {
                        "schema": SOURCE_TAGS_DETAIL_SCHEMA,
                        "batch": batches_completed,
                        "domain": s.domain,
                        "article_count": s.article_count,
                        "mention_count": s.mention_count,
                        "status": "skipped",
                        "reason": s.reason,
                    }
                    for s in skipped
                ],
            )
        skipped_evidence_floor_total += len(skipped)
        cursor = last_domain
        batches_completed += 1
        batches_this_call += 1

        state.update({
            "cursor": cursor,
            "log_path": str(path),
            "totals": totals,
            "skipped_evidence_floor_total": skipped_evidence_floor_total,
            "batches_completed": batches_completed,
            "canary_ok_overall": canary_ok_overall,
            "wall_s_total": round(wall_total, 3),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        _save_progress_state(state, path_state)
        ctx.set_progress(
            done=batches_completed * max(1, batch_size),
            total=max(total_estimate, batches_completed * max(1, batch_size)),
            detail=(
                f"batch {batches_completed} · {totals['assigned_count']} tagged · "
                f"{skipped_evidence_floor_total} skipped so far"
            ),
        )

    if complete:
        from src.ai_layer.triage import valid_verdicts_per_sec

        footer = {
            "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
            "state": "done",
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "batches_completed": batches_completed,
            **totals,
            "skipped_evidence_floor": skipped_evidence_floor_total,
            "canary_ok_overall": canary_ok_overall,
            "wall_s_total": round(wall_total, 3),
            "throughput_valid_per_s": valid_verdicts_per_sec(
                totals["assigned_count"] + totals["none_count"], wall_total
            ),
            "error": None,
        }
        ST.export_source_tags_jsonl(path, [footer])
        state["completed_at"] = datetime.now().isoformat(timespec="seconds")
        _save_progress_state(state, path_state)

    _LOG.info(
        "progressive source-tags %s: complete=%s batches=%s assigned=%s skipped=%s",
        path.name,
        complete,
        batches_completed,
        totals["assigned_count"],
        skipped_evidence_floor_total,
    )
    summary = {
        "path": str(path),
        "filename": path.name,
        "complete": complete,
        "batches_completed": batches_completed,
        "batches_this_call": batches_this_call,
        "totals": totals,
        "skipped_evidence_floor": skipped_evidence_floor_total,
        "canary_ok_overall": canary_ok_overall,
        "cursor": cursor,
    }
    if paused_reason:
        summary["paused_reason"] = paused_reason
    return summary


def last_source_tags_report() -> dict:
    """A JSON SUMMARY of the newest saved run (never the raw JSONL). Mirrors
    ``triage_job.last_keyword_triage_report`` exactly."""
    import json

    try:
        files = sorted(_dir().glob("oo-source-tags-*.jsonl"))
        if not files:
            return {
                "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
                "available": False,
                "note": (
                    "no source-tag run has been made yet -- run it from Settings -> "
                    "Diagnostics, or POST /api/diagnostics/source-tags/run."
                ),
            }
        path = files[-1]
        header: dict = {}
        footer: dict | None = None
        details = 0
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                schema = rec.get("schema")
                if schema == SOURCE_TAGS_RUN_HEADER_SCHEMA:
                    header = rec
                elif schema == SOURCE_TAGS_DETAIL_SCHEMA:
                    details += 1
                elif schema == SOURCE_TAGS_RUN_SUMMARY_SCHEMA:
                    footer = rec
        return {
            "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
            "available": True,
            "filename": path.name,
            "run_header": header,
            "detail_records_logged": details,
            "summary": footer or {"state": "in_progress"},
        }
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {
            "schema": SOURCE_TAGS_RUN_SUMMARY_SCHEMA,
            "available": False,
            "error": str(exc)[:300],
        }
