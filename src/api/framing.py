"""
Framing API: compare how different outlets cover the same event.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest, sourced signals only (see src/awareness/framing.py). Requires the
[analysis] extra (VADER); included defensively in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from src.awareness.framing import compare_framing
from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article
from src.database.session import get_db

router = APIRouter(prefix="/api/framing", tags=["framing"])

# Framing is a COARSE signal (per-source tone via VADER + emphasised terms by
# frequency), not a verdict. Running VADER over the FULL text of every article —
# and the corpus includes long Wikipedia pages — made this the slowest endpoint
# (≈141 s on the field corpus). The lead of an article carries its tone and its
# emphasis, so we bound the text fed to the computation; typical news articles are
# well under this, so their result is unchanged, while a pathological long page no
# longer dominates. (The decrypt of the content column is inherent; this bounds the
# pure-Python VADER + concatenation + term-frequency work, which was the hot cost.)
_FRAMING_MAX_CHARS = 8000


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
    # Eager-load the source: ``a.source.name`` below otherwise fires one extra
    # decrypt-query PER article (an N+1 that, at limit=1000, is a large hidden cost).
    q = db.query(Article).options(joinedload(Article.source))
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
                "content": (a.content or "")[:_FRAMING_MAX_CHARS],
                "url": a.url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
        )

    result = compare_framing(by_source)
    return {"query": query, **result}
