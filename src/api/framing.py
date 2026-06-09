"""
Framing API: compare how different outlets cover the same event.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest, sourced signals only (see src/awareness/framing.py). Requires the
[analysis] extra (VADER); included defensively in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.awareness.framing import compare_framing
from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article
from src.database.session import get_db

router = APIRouter(prefix="/api/framing", tags=["framing"])


@router.get("")
def framing(
    query: str | None = Query(None, description="Boolean FTS query selecting the event/topic"),
    limit: int = Query(200, ge=2, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Compare framing across outlets for the articles matching ``query``.

    Without a query, the most recent articles are used. Articles are grouped by
    source; each source's tone (VADER), emphasised terms and headlines are returned.
    """
    q = db.query(Article)
    if query:
        try:
            ids = search_ids(db, query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        if not ids:
            return {
                "query": query,
                "sources_compared": 0,
                "total_articles": 0,
                "framing": [],
                "shared_terms": [],
                "caveat": "",
            }
        articles = q.filter(Article.id.in_(ids)).limit(limit).all()
    else:
        articles = q.order_by(Article.id.desc()).limit(limit).all()

    by_source: dict[str, list[dict]] = {}
    for a in articles:
        source = a.source.name if a.source else "Unknown"
        by_source.setdefault(source, []).append(
            {
                "title": a.title,
                "content": a.content,
                "url": a.url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
        )

    result = compare_framing(by_source)
    return {"query": query, **result}
