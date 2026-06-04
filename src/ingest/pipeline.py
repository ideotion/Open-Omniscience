"""
Ingestion pipeline: ethical fetch -> extract -> dedup -> store with provenance.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the spine of the product: it turns a source (an RSS feed or a single URL)
into deduplicated, provenance-tagged Article rows in the unified store. Every step
either succeeds explicitly or reports a typed failure -- there is no double-fetch,
no raw-requests bypass, and no silently-stored junk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import feedparser
from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.ingest import (
    EthicalFetcher,
    FetchError,
    RobotsDisallowed,
    RobotsUnavailable,
)
from src.ingest.extract import extract_article
from src.utils.url_utils import canonicalize_url, generate_content_hash


class IngestResult(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    BLOCKED_ROBOTS = "blocked_robots"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    FETCH_FAILED = "fetch_failed"
    EXTRACT_FAILED = "extract_failed"


@dataclass
class IngestOutcome:
    url: str
    result: IngestResult
    article_id: int | None = None
    detail: str | None = None


def ingest_url(
    session: Session,
    source: Source,
    url: str,
    *,
    fetcher: EthicalFetcher,
) -> IngestOutcome:
    """Fetch, extract, dedup and store a single article URL.

    Deduplication is by canonical URL (cheap, pre-fetch) and by content hash
    (post-extract, catches the same article served at different URLs).
    """
    canonical = canonicalize_url(url)

    if _exists(session, canonical_url=canonical):
        return IngestOutcome(url, IngestResult.DUPLICATE, detail="canonical url already stored")

    try:
        fetched = fetcher.fetch(url, require_html=True)
    except RobotsDisallowed as exc:
        return IngestOutcome(url, IngestResult.BLOCKED_ROBOTS, detail=str(exc))
    except RobotsUnavailable as exc:
        return IngestOutcome(url, IngestResult.ROBOTS_UNAVAILABLE, detail=str(exc))
    except FetchError as exc:
        return IngestOutcome(url, IngestResult.FETCH_FAILED, detail=str(exc))

    doc = extract_article(fetched.content, url=fetched.final_url)
    if doc is None:
        return IngestOutcome(url, IngestResult.EXTRACT_FAILED, detail="no article body extracted")

    content_hash = generate_content_hash(doc.text)
    if _exists(session, hash=content_hash):
        return IngestOutcome(url, IngestResult.DUPLICATE, detail="content hash already stored")

    # Prefer the page's declared canonical link; fall back to the final fetched URL.
    canonical_final = canonicalize_url(doc.canonical_url or fetched.final_url)
    now = datetime.now(UTC)
    article = Article(
        url=fetched.requested_url,
        canonical_url=canonical_final,
        source_id=source.id,
        title=doc.title,
        content=doc.text,
        published_at=doc.published_at,
        language=doc.language or source.language,
        hash=content_hash,
        author=doc.author,
        word_count=len(doc.text.split()),
        created_at=now,
        updated_at=now,
    )
    session.add(article)
    session.commit()
    return IngestOutcome(url, IngestResult.STORED, article_id=article.id)


def ingest_source(
    session: Session,
    source: Source,
    *,
    fetcher: EthicalFetcher,
    max_items: int = 50,
) -> dict[str, int]:
    """Ingest a source's RSS/Atom feed (the feed is fetched through the ethical path).

    Returns a tally keyed by IngestResult value, plus the feed entry count.
    """
    tally = {r.value: 0 for r in IngestResult}
    tally["entries"] = 0

    if not source.rss_url:
        return tally

    try:
        feed_resp = fetcher.fetch(source.rss_url, require_html=False)
    except FetchError:
        # Feed itself blocked/unavailable: nothing to ingest, but not an article failure.
        return tally

    parsed = feedparser.parse(feed_resp.content)
    links = [e.link for e in parsed.entries if getattr(e, "link", None)][:max_items]
    tally["entries"] = len(links)

    for link in links:
        outcome = ingest_url(session, source, link, fetcher=fetcher)
        tally[outcome.result.value] += 1

    return tally


def _exists(session: Session, **filters) -> bool:
    return session.query(Article.id).filter_by(**filters).first() is not None
