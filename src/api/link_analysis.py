"""
Read-only link / co-citation analysis over ``article_links``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest aggregation only — counts of who cites what, nothing scored or judged. This
answers "which articles cite the same source" and "what links are most-cited"
(see docs/DESIGN.md). It is NOT the quarantined, fabricated
"credibility/relationship" link analyzer (see docs/HISTORY.md); it surfaces
structure for the user, who decides.

Outbound external links are populated on ingest (see
``src/ingest/pipeline.py:_maybe_index_links``). Empty until articles with links
are ingested.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.catalog.normalize import registrable_domain
from src.database.models import Article, ArticleLink, Source
from src.database.session import get_db

router = APIRouter(prefix="/api/links", tags=["links"])


def _cutoff(days: int | None) -> datetime | None:
    return datetime.now(UTC) - timedelta(days=days) if days else None


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Corpus-wide link totals (all real COUNT(*) — nothing estimated)."""
    return {
        "external_links": db.query(func.count(ArticleLink.id)).scalar() or 0,
        "distinct_links": db.query(func.count(func.distinct(ArticleLink.normalized_url))).scalar() or 0,
        "articles_with_links": db.query(func.count(func.distinct(ArticleLink.article_id))).scalar() or 0,
    }


@router.get("/top-cited")
def top_cited(
    by: str = Query("url", pattern="^(url|domain)$"),
    window_days: int | None = Query(None, ge=1, le=3650),
    min_citations: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Most-cited external links (``by=url``) or domains (``by=domain``).

    "Citations" = number of *distinct articles* in the corpus that link to it — a
    citation-graph trend signal grounded in what reporters actually reference.
    """
    cutoff = _cutoff(window_days)

    if by == "url":
        q = db.query(
            ArticleLink.normalized_url.label("nu"),
            func.count(func.distinct(ArticleLink.article_id)).label("citations"),
            func.max(ArticleLink.url).label("sample_url"),
            func.max(ArticleLink.link_text).label("sample_text"),
        )
        if cutoff is not None:
            q = q.join(Article, ArticleLink.article_id == Article.id).filter(
                func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        q = (q.group_by(ArticleLink.normalized_url)
              .having(func.count(func.distinct(ArticleLink.article_id)) >= min_citations)
              .order_by(desc("citations")).limit(limit))
        items = [{
            "normalized_url": r.nu,
            "sample_url": r.sample_url,
            "link_text": r.sample_text,
            "domain": registrable_domain(r.nu),
            "citations": r.citations,
        } for r in q.all()]
        return {"by": "url", "window_days": window_days, "items": items}

    # by == "domain": parse the registrable domain in Python (portable across SQLite).
    pairs = db.query(ArticleLink.normalized_url, ArticleLink.article_id)
    if cutoff is not None:
        pairs = pairs.join(Article, ArticleLink.article_id == Article.id).filter(
            func.coalesce(Article.published_at, Article.created_at) >= cutoff)
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs.distinct().all():
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom].add(aid)
    items = sorted(
        ({"domain": d, "citations": len(ids)} for d, ids in by_domain.items() if len(ids) >= min_citations),
        key=lambda x: -x["citations"],
    )[:limit]
    return {"by": "domain", "window_days": window_days, "items": items}


@router.get("/articles-by-link")
def articles_by_link(
    url: str | None = Query(None, description="a cited link (raw or normalized)"),
    domain: str | None = Query(None, description="a cited domain, e.g. reuters.com"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Every article in the corpus that cites a given link (or domain).

    This is "assemble all articles talking about the same link" — the basis for
    spotting echo and tracing toward an original source. The user reads and judges.
    """
    if not url and not domain:
        raise HTTPException(status_code=400, detail="Provide ?url= or ?domain=")

    if url:
        try:
            from src.services.link_analyzer import LinkExtractor
            norm = LinkExtractor().normalize_url(url)
        except Exception:  # noqa: BLE001 - normalisation is best-effort
            norm = url
        match = {"url": url, "normalized_url": norm}
        ids = [a for (a,) in db.query(ArticleLink.article_id).filter(
            (ArticleLink.normalized_url == norm) | (ArticleLink.normalized_url == url) | (ArticleLink.url == url)
        ).distinct().all()]
    else:
        dom = domain.strip().lower()
        match = {"domain": dom}
        # LIKE pre-filter, then exact registrable-domain check (avoids false hits).
        ids = sorted({
            aid for (aid, nu) in db.query(ArticleLink.article_id, ArticleLink.normalized_url)
            .filter(ArticleLink.normalized_url.like(f"%{dom}%")).all()
            if registrable_domain(nu) == dom
        })

    total = len(ids)
    articles = []
    if ids:
        rows = (db.query(Article, Source.name)
                .outerjoin(Source, Article.source_id == Source.id)
                .filter(Article.id.in_(ids[:limit]))
                .order_by(desc(func.coalesce(Article.published_at, Article.created_at)))
                .all())
        for art, source_name in rows:
            articles.append({
                "id": art.id, "title": art.title, "url": art.url,
                "source": source_name, "language": art.language,
                "published_at": art.published_at.isoformat() if art.published_at else None,
            })
    return {"match": match, "count": total, "articles": articles}
