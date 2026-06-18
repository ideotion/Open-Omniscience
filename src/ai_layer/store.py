"""
AI-layer store helpers: record + read AI-derived keywords.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure functions over a SQLAlchemy ``Session`` (testable in-memory; the production
session is the MAIN session — the AI ``ai_keyword`` table lives in the main DB since
the 2026-06-18 ruling). Honesty by construction: every stored term carries its model
provenance, nothing is a score, and ``confirmed`` curates the AI lens IN PLACE — a
confirmed row never crosses into the trusted ``keyword_mentions`` index.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import AiKeyword


def record_keywords(
    session: Session,
    article_id: int,
    terms: Iterable[str],
    *,
    model: str,
    kind: str = "keyword",
    language: str | None = None,
    prompt_version: str | None = None,
) -> int:
    """Store AI-extracted ``terms`` for an article. Idempotent per (article, kind,
    term): a term already present for this article+kind is skipped, so a re-run tops
    up rather than duplicates. Returns the number of NEW rows added."""
    existing = {
        r[0]
        for r in session.execute(
            select(AiKeyword.term).where(
                AiKeyword.article_id == article_id, AiKeyword.kind == kind
            )
        ).all()
    }
    added = 0
    for raw in terms:
        term = (raw or "").strip()
        if not term or term in existing:
            continue
        session.add(
            AiKeyword(
                article_id=article_id,
                term=term,
                kind=kind,
                language=language,
                model=model,
                prompt_version=prompt_version,
                confirmed=False,
            )
        )
        existing.add(term)
        added += 1
    session.flush()
    return added


def keywords_for_article(
    session: Session,
    article_id: int,
    *,
    kind: str | None = None,
    confirmed_only: bool = False,
) -> list[AiKeyword]:
    """The AI-derived terms for one article (ordered by term). Read-only."""
    q = select(AiKeyword).where(AiKeyword.article_id == article_id)
    if kind:
        q = q.where(AiKeyword.kind == kind)
    if confirmed_only:
        q = q.where(AiKeyword.confirmed.is_(True))
    return list(session.execute(q.order_by(AiKeyword.term)).scalars())


def set_confirmed(session: Session, ai_keyword_id: int, confirmed: bool) -> bool:
    """Curate the lens in place: confirm/unconfirm one AI keyword. Returns False if
    the row does not exist. The row STAYS in the AI store either way."""
    row = session.get(AiKeyword, ai_keyword_id)
    if row is None:
        return False
    row.confirmed = bool(confirmed)
    session.flush()
    return True
