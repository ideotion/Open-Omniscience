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

import logging
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
        items, skipped = ST.select_source_tag_candidates(
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
