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
from sqlalchemy.exc import IntegrityError
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

    return store_fetched(session, source, fetched)


def store_fetched(session: Session, source: Source, fetched) -> IngestOutcome:
    """Extract, dedup and store an already-fetched page.

    Split out of :func:`ingest_url` so callers that have *already* fetched a page
    (notably the recursive crawler, which harvests links from the same bytes) can
    store it without a second network round-trip -- preserving the "one fetch per
    URL" invariant. ``fetched`` is an :class:`~src.ingest.FetchResult`.
    """
    doc = extract_article(fetched.content, url=fetched.final_url)
    if doc is None:
        return IngestOutcome(fetched.requested_url, IngestResult.EXTRACT_FAILED,
                             detail="no article body extracted")

    content_hash = generate_content_hash(doc.text)
    if _exists(session, hash=content_hash):
        return IngestOutcome(fetched.requested_url, IngestResult.DUPLICATE,
                             detail="content hash already stored")

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
    try:
        session.commit()
    except IntegrityError:
        # Another entry in the same loop (or a concurrent writer) inserted the same
        # content hash between the _exists check and here. Roll back so the loop
        # continues, and report the duplicate rather than aborting the batch.
        session.rollback()
        return IngestOutcome(fetched.requested_url, IngestResult.DUPLICATE,
                             detail="content hash already stored (race)")
    _maybe_record_custody(article)
    _maybe_index_keywords(session, article, source)
    _maybe_index_links(session, article, fetched.content, fetched.final_url)
    return IngestOutcome(fetched.requested_url, IngestResult.STORED, article_id=article.id)


def _maybe_index_keywords(session: Session, article: Article, source: Source) -> None:
    """Best-effort keyword/entity indexing on ingest (fast baseline extractor).

    Fail-open and isolated: indexing must never break ingestion, so any error is
    swallowed (and logged) and the already-committed article is untouched. Disable
    with OO_NO_INDEX=1. City is taken from the source's metadata when known
    (the reliable "source-based" location signal).
    """
    import os

    if os.getenv("OO_NO_INDEX") == "1":
        return
    try:
        from src.analytics.extract import get_extractor
        from src.analytics.store import index_article

        city = None
        try:
            meta = source.source_metadata
            city = meta.city if meta else None
        except Exception:  # noqa: BLE001 - metadata is optional
            city = None
        index_article(session, article, extractor=get_extractor("baseline"),
                      country=source.country, city=city)
    except Exception:  # noqa: BLE001 - analytics is auxiliary; never fail ingestion
        session.rollback()
        import logging
        logging.getLogger(__name__).warning("keyword indexing on ingest failed", exc_info=True)


def _maybe_index_links(session: Session, article: Article, html: str | None, base_url: str) -> None:
    """Best-effort extraction of outbound EXTERNAL links into ``article_links``.

    Powers co-citation analysis ("which articles cite the same source", "most-cited
    links") — see docs/DESIGN.md. Fail-open and isolated like
    keyword indexing: never breaks ingestion. Only genuine *external* links are kept
    — internal navigation, images, ads, social and trackers are excluded, in line
    with docs/ROADMAP.md. De-duplicated per article and capped. Disable with
    OO_NO_INDEX=1.
    """
    import os

    if os.getenv("OO_NO_INDEX") == "1" or not html:
        return
    try:
        from src.database.models import ArticleLink
        from src.services.link_analyzer import LinkExtractor

        links = LinkExtractor().extract_links(html, base_url=base_url, article_id=article.id)
        seen: set[str] = set()
        rows: list[ArticleLink] = []
        for ln in links:
            if ln.get("link_type") != "external":
                continue
            nu = ln.get("normalized_url") or ln.get("url")
            if not nu or nu in seen:
                continue
            seen.add(nu)
            text = ln.get("link_text") or None
            rows.append(ArticleLink(
                article_id=article.id,
                url=(ln.get("url") or nu)[:1000],
                normalized_url=nu[:1000],
                link_text=text[:500] if text else None,
                position=ln.get("position"),
                link_type="external",
            ))
            if len(rows) >= 300:  # guard against pathological link-farm pages
                break
        if rows:
            session.add_all(rows)
            session.commit()
    except Exception:  # noqa: BLE001 - link analysis is auxiliary; never fail ingestion
        session.rollback()
        import logging
        logging.getLogger(__name__).warning("link indexing on ingest failed", exc_info=True)


def _maybe_record_custody(article: Article) -> None:
    """Opt-in: append a signed custody entry for a freshly stored article.

    Best-effort and fail-open: custody logging must never break ingestion, so any
    error here is swallowed (and logged). Controlled by the GUI-editable custody
    setting ``auto_log_on_ingest`` (which defaults to the legacy
    OO_CUSTODY_ON_INGEST flag until a preference is saved). The item_hash is the
    article's content hash, so the custody entry binds to exactly the bytes that
    were stored.
    """
    try:
        from src.custody.settings import load_settings

        prefs = load_settings()
        if not prefs.auto_log_on_ingest:
            return
        from src.custody.log import CustodyAction, CustodyLog

        with CustodyLog() as log:
            log.record(
                f"article:{article.id}",
                article.hash,
                CustodyAction.INGEST,
                actor=prefs.default_actor or "ingest-pipeline",
                metadata={"url": article.url, "canonical_url": article.canonical_url,
                          "source_id": article.source_id},
            )
    except Exception:  # noqa: BLE001 - custody is auxiliary; never fail ingestion
        import logging

        logging.getLogger(__name__).warning("custody logging on ingest failed", exc_info=True)


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
