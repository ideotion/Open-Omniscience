"""AI change-summary layer for tracked law revisions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-24 field-feedback Session A3 (ruled): when a new ``LawRevision`` lands,
auto-generate a plain-language summary of the change for jurisdictions whose
document's ASSERTED language is one of the 12 UI languages; an on-demand button
(``summarize_revision`` called directly) covers the rest. Stored as a LINKED layer
(``LawRevisionSummary``, mirroring ``ArticleAnalysis``'s exact provenance shape --
model + prompt_version + the verbatim prompt_text used) so no AI text is ever shown
without its origin. Rendered "AI-derived - unreliable" (the established third
class); NEVER the trusted diff/revision record, NEVER feeds keyword indexing.

The AUTO path runs as a scheduler ride-along (``advance_law_summaries``), mirroring
``src.ai_layer.auto.run_auto_on_ingest`` -- OFF the scrape hot path (a local model
call per revision would stall collection), best-effort, bounded per pass, and a
single honest no-op when the local model is down (never a wall of failed events).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import LawDocument, LawRevision, LawRevisionSummary
from src.llm.ollama import DEFAULT_MODEL, LLMError, LLMUnavailable, OllamaClient
from src.wiki.languages import UI_LOCALE_CODES

logger = logging.getLogger(__name__)

#: Bumped when the prompt materially changes (like ArticleAnalysis's summary-vN).
SUMMARY_PROMPT_VERSION = "law-change-summary-v1"

#: Revisions scanned per ride-along pass -- a bounded per-pass LLM budget, mirroring
#: src.ai_layer.auto.AUTO_LIMIT's role for the custom-extractor ride-along.
AUTO_LIMIT = 5

#: The diff is already capped at ingest (track.py's _MAX_DIFF_LINES=4000); a second,
#: smaller bound here keeps the summarization call itself fast and cheap.
_MAX_DIFF_LINES_FOR_PROMPT = 400

_SYSTEM_PROMPT = (
    "You summarize a single amendment to a piece of legislation in plain, neutral "
    "language for a non-lawyer reader. You are given a UNIFIED DIFF of the change "
    "(lines starting with + were added, lines starting with - were removed) -- base "
    "your summary ONLY on what the diff actually shows. Never invent a reason, "
    "intent, or effect the diff does not support. If the diff is too fragmentary to "
    "say anything specific, say so plainly instead of guessing. Two to four short "
    "sentences. No preamble, no legal advice, no opinion on whether the change is "
    "good or bad -- describe what changed, not what it means."
)


def _active_model() -> str:
    """The operator's chosen model (stored UI setting) else the built-in default --
    resolved here so the scheduler ride-along never has to import the API layer."""
    try:
        from src.config.app_settings import load_settings

        return load_settings().llm_model or DEFAULT_MODEL
    except Exception:  # noqa: BLE001 - a settings hiccup must not break a scrape
        return DEFAULT_MODEL


def _build_prompt(doc: LawDocument, revision: LawRevision) -> str:
    """The user-turn prompt: the change's own diff, grounded and bounded."""
    diff_lines = (revision.diff or "").splitlines()[:_MAX_DIFF_LINES_FOR_PROMPT]
    title = doc.title or doc.jurisdiction or "this document"
    return (
        f"Document: {title}\n"
        f"Jurisdiction: {(doc.jurisdiction or '').upper()}\n\n"
        "Diff of this amendment (+ added / - removed):\n" + "\n".join(diff_lines)
    )


def summarize_revision(
    session: Session,
    doc: LawDocument,
    revision: LawRevision,
    client: OllamaClient | None = None,
    *,
    model: str | None = None,
) -> dict:
    """Generate + store ONE AI summary of a law revision's change.

    Honest and bounded, never fabricates: a revision with no diff (a baseline, not
    a change -- there is nothing to summarize) refuses with ``status="no_diff"``;
    an unavailable local model degrades to ``status="unavailable"``, never a stored
    placeholder. Commits on success (mirrors the ai_layer.jobs per-item commit) so
    a caller looping over several revisions never holds the write gate across
    multiple slow model calls.
    """
    if not (revision.diff or "").strip():
        return {"status": "no_diff", "detail": "this revision has no recorded change to summarize"}
    client = client or OllamaClient()
    try:
        if not client.is_available():
            return {"status": "unavailable"}
    except Exception:  # noqa: BLE001 - a health-check hiccup degrades, never crashes
        return {"status": "unavailable"}
    mdl = model or _active_model()
    prompt = _build_prompt(doc, revision)
    try:
        result = client.generate(prompt, model=mdl, system=_SYSTEM_PROMPT)
    except (LLMUnavailable, LLMError) as exc:
        return {"status": "unavailable", "detail": str(exc)[:200]}
    if not result.text:
        return {"status": "empty"}
    row = LawRevisionSummary(
        revision_id=revision.id,
        summary=result.text,
        model=result.model,
        prompt_version=SUMMARY_PROMPT_VERSION,
        prompt_text=_SYSTEM_PROMPT,
    )
    session.add(row)
    session.commit()
    return {"status": "ok", "summary_id": row.id, "model": result.model}


def pending_ai_summaries(
    session: Session, *, limit: int = AUTO_LIMIT
) -> list[tuple[LawRevision, LawDocument]]:
    """Genuine (non-baseline) revisions whose document's ASSERTED language is a UI
    language and that have NO summary yet -- the auto-eligible worklist, oldest
    first. A document with no stated language (most pre-S4b rows) is left to the
    on-demand button, never guessed into "auto"."""
    already = select(LawRevisionSummary.revision_id).distinct()
    rows = session.execute(
        select(LawRevision, LawDocument)
        .join(LawDocument, LawDocument.id == LawRevision.document_id)
        .where(
            LawRevision.diff.is_not(None),
            LawRevision.diff != "",
            LawDocument.language.in_(sorted(UI_LOCALE_CODES)),
            LawRevision.id.not_in(already),
        )
        .order_by(LawRevision.observed_at.asc())
        .limit(max(0, limit))
    ).all()
    return [(rev, doc) for rev, doc in rows]


def advance_law_summaries(
    session: Session, client: OllamaClient | None = None, *, limit: int = AUTO_LIMIT
) -> dict:
    """Scheduler ride-along (2026-07-24 field-feedback A3, ruled): auto-summarize a
    bounded batch of new law changes whose jurisdiction's official language is a UI
    language. Best-effort + bounded, mirroring run_auto_on_ingest -- a local model
    that is down is a single honest no-op, never a wall of failures; one bad
    revision never breaks the batch."""
    out: dict = {"ran": False, "stored": 0, "skipped": 0, "failed": 0}
    if limit <= 0:
        return out
    client = client or OllamaClient()
    try:
        if not client.is_available():
            return out  # local model down -> no-op (never spam failed events)
    except Exception:  # noqa: BLE001
        return out
    try:
        pending = pending_ai_summaries(session, limit=limit)
    except Exception:  # noqa: BLE001
        logger.warning("law auto-summary: could not list pending revisions", exc_info=True)
        return out
    if not pending:
        return out
    out["ran"] = True
    for rev, doc in pending:
        try:
            res = summarize_revision(session, doc, rev, client)
        except Exception:  # noqa: BLE001 - one bad revision never breaks the batch
            logger.warning("law auto-summary: revision %s failed", rev.id, exc_info=True)
            session.rollback()
            out["failed"] += 1
            continue
        status = res.get("status")
        if status == "ok":
            out["stored"] += 1
        elif status == "unavailable":
            out["skipped"] += 1
            break  # the model just went down mid-batch -- stop, don't hammer it
        else:
            out["skipped"] += 1
    return out
