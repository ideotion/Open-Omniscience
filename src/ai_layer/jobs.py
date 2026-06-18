"""
The AI keyword-extraction batch job (the first writer into the AI store).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Runs the local model over each article in a matched set and persists the extracted
terms as ``AiKeyword`` rows — the AI-derived ``ai_keyword`` table in the MAIN database
(maintainer ruling 2026-06-18), NEVER the trusted ``keyword_mentions`` index. A local
CPU model over many articles is slow, so we:
  * stream HONEST per-article progress (invariant #20: never a fabricated bar/ETA),
  * rely on the client's per-call kill-switch check (airplane mode aborts loudly),
  * commit per article (progress persists; the single-writer gate's window stays short
    and is never held across the slow LLM call),
  * skip articles already extracted for this kind (idempotent top-up).

Writes touch ONLY the ``ai_keyword`` table; the trusted rule-based keyword index reads
only ``articles.content`` and never this table (the integrity guarantee).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple

from sqlalchemy import select

from src.ai_layer import store as ai_store
from src.ai_layer.extract import EXTRACT_PROMPT_VERSION, extract_terms
from src.database.models import AiKeyword
from src.database.session import session_scope
from src.llm.ollama import LLMError, LLMUnavailable


class ArticleWork(NamedTuple):
    """A snapshot of the plain fields the job needs, so it never depends on the
    request's ORM session staying open while the (slow) model runs."""

    article_id: int
    title: str
    content: str
    language: str | None


def extract_for_articles(
    work: list[ArticleWork],
    client,
    *,
    model: str,
    kind: str = "keyword",
    max_terms: int = 20,
    keep_alive: str | None = None,
    skip_existing: bool = True,
    system: str | None = None,
    prompt_version: str = EXTRACT_PROMPT_VERSION,
) -> Iterator[dict]:
    """Extract + persist terms for each article, yielding progress events.

    Emits one ``start`` event, one ``item`` per article (status =
    stored | skipped | failed), and a final ``done`` — or an aborted ``done`` if the
    local model becomes unavailable mid-run (it won't recover, so we stop). All writes
    go to the ``ai_keyword`` table via the main session; the trusted index is never written.

    ``system`` + ``kind`` + ``prompt_version`` parametrise the extractor: the built-in
    keyword pass uses the defaults, a USER-DEFINED custom prompt passes its own system
    text, output ``kind`` (the metadata type) and ``prompt_version`` (e.g. ``custom:7``) —
    the same unified typed-metadata path either way.
    """
    total = len(work)
    yield {"event": "start", "total": total, "model": model, "kind": kind}
    stored = skipped = failed = terms_total = 0

    with session_scope() as session:
        already: set[int] = set()
        if skip_existing and work:
            ids = [w.article_id for w in work]
            already = {
                r[0]
                for r in session.execute(
                    select(AiKeyword.article_id).where(
                        AiKeyword.article_id.in_(ids), AiKeyword.kind == kind
                    )
                ).all()
            }
        for i, w in enumerate(work, 1):
            if skip_existing and w.article_id in already:
                skipped += 1
                yield {"event": "item", "i": i, "total": total,
                       "article_id": w.article_id, "status": "skipped"}
                continue
            try:
                terms = extract_terms(
                    client, w.title, w.content, model=model,
                    max_terms=max_terms, keep_alive=keep_alive, system=system,
                )
            except LLMUnavailable as exc:
                # Ollama down / model missing / airplane mode — won't recover mid-run.
                yield {"event": "done", "total": total, "stored": stored,
                       "skipped": skipped, "failed": failed, "terms": terms_total,
                       "aborted": True, "reason": str(exc)[:200]}
                return
            except LLMError as exc:
                failed += 1
                yield {"event": "item", "i": i, "total": total,
                       "article_id": w.article_id, "status": "failed",
                       "error": str(exc)[:200]}
                continue
            added = ai_store.record_keywords(
                session, w.article_id, terms, model=model, kind=kind,
                language=w.language, prompt_version=prompt_version,
            )
            session.commit()  # persist progress; release the gate between articles
            stored += 1
            terms_total += added
            yield {"event": "item", "i": i, "total": total,
                   "article_id": w.article_id, "status": "stored", "terms": added}

    yield {"event": "done", "total": total, "stored": stored, "skipped": skipped,
           "failed": failed, "terms": terms_total, "aborted": False}
