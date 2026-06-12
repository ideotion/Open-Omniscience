"""
Local link preview — what THIS app already knows about an outbound URL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Invariant #6 EXTENDED (maintainer-ruled 2026-06-10, first target the Home
cards): no bare "source ↗" shortcut — before leaving the machine the user
sees the database extraction for the link (known source, local copy,
how many of their own articles cite it, tracked law/wiki matches, keywords)
and the outbound anchor whose visible text IS the full URL. This endpoint is
the extraction; it reads the LOCAL database only and never fetches anything.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.database.models import (
    Article,
    ArticleLink,
    Keyword,
    KeywordMention,
    LawDocument,
    Source,
    WikiPage,
)
from src.database.session import get_db

router = APIRouter(prefix="/api/links", tags=["links"])


def _normalized(url: str) -> str:
    from src.services.link_analyzer.extractor import LinkExtractor

    return LinkExtractor().normalize_url(url)


@router.get("/preview")
def link_preview(url: str, db: Session = Depends(get_db)) -> dict:
    """The database extraction for one URL — local reads only, zero network."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="an absolute http(s) URL is required")
    host = (parsed.hostname or "").lower()
    bare_host = host.removeprefix("www.")
    norm = _normalized(url) or url

    # A stored local copy of this exact page? (Local reader first — invariant #6.)
    local = (
        db.query(Article.id, Article.title)
        .filter(or_(Article.url == url, Article.canonical_url == url))
        .first()
    )

    # The source catalog's view of the domain.
    src_row = (
        db.query(Source.id, Source.name, Source.domain, Source.country)
        .filter(or_(Source.domain == host, Source.domain == bare_host))
        .first()
    )

    # How much of the user's own corpus cites this URL (the citation substrate).
    cite_q = db.query(ArticleLink.article_id).filter(
        or_(ArticleLink.normalized_url == norm, ArticleLink.url == url)
    )
    citing_ids = sorted({aid for (aid,) in cite_q.all()})
    citing = []
    if citing_ids:
        rows = (
            db.query(Article.id, Article.title)
            .filter(Article.id.in_(citing_ids[:3]))
            .all()
        )
        citing = [{"article_id": a, "title": t} for a, t in rows]

    law = (
        db.query(LawDocument.id, LawDocument.title, LawDocument.jurisdiction)
        .filter(or_(LawDocument.url == url, LawDocument.official_url == url))
        .first()
    )
    wiki = None
    if bare_host.endswith("wikipedia.org") and "/wiki/" in (parsed.path or ""):
        title = parsed.path.split("/wiki/", 1)[1].replace("_", " ")
        wiki_code = host.split(".", 1)[0]
        w = (
            db.query(WikiPage.id, WikiPage.title, WikiPage.wiki)
            .filter(func.lower(WikiPage.title) == title.lower(), WikiPage.wiki == wiki_code)
            .first()
        )
        if w:
            wiki = {"page_id": w[0], "title": w[1], "wiki": w[2]}

    # Keywords of the local copy, when one exists (small columns only).
    keywords: list[str] = []
    if local:
        kw_rows = (
            db.query(Keyword.term)
            .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
            .filter(KeywordMention.article_id == local[0])
            .order_by(KeywordMention.count.desc())
            .limit(6)
            .all()
        )
        keywords = [t for (t,) in kw_rows]

    return {
        "url": url,
        "domain": host,
        "local_article": (
            {"article_id": local[0], "title": local[1], "reader_url": f"/api/articles/{local[0]}/view"}
            if local
            else None
        ),
        "known_source": (
            {"source_id": src_row[0], "name": src_row[1], "domain": src_row[2],
             "country": src_row[3]}
            if src_row
            else None
        ),
        "cited_by_articles": len(citing_ids),
        "citing_examples": citing,
        "law_document": (
            {"document_id": law[0], "title": law[1], "jurisdiction": law[2]} if law else None
        ),
        "wiki_page": wiki,
        "keywords": keywords,
        "method": "local database reads only — building this preview made no network call",
    }
