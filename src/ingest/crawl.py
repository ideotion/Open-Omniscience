"""
Bounded, ethical recursive crawl of a single source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is article *discovery*, not site *mirroring*. The product is explicitly NOT
a general-purpose web crawler/mirror (PRODUCT_SYNTHESIS §7); so this crawler is
deliberately fenced:

  * **Same fetch path.** Every request goes through :class:`EthicalFetcher`, so
    robots.txt (fail-closed) and per-host rate limits apply to crawling exactly as
    they do to single-URL ingest. There is no bypass.
  * **One fetch per URL.** Each page is fetched once; the article body is
    extracted *and* outgoing links harvested from the same bytes (via
    :func:`store_fetched`). No double-fetch.
  * **Same-domain only (default).** Links off the source's registrable host are
    not followed, so a crawl cannot wander the whole web.
  * **Hard caps.** ``max_depth`` and ``max_pages`` bound every run; the crawl
    stops at the first limit hit and reports *why*.
  * **Stores only real articles.** A fetched page is stored only if trafilatura
    extracts a genuine body; otherwise it is counted as ``extract_failed`` and
    nothing junk is written. Links are still harvested from non-article pages
    (e.g. a section index) so the crawl can reach the articles they list.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from src.database.models import Source
from src.ingest import EthicalFetcher, FetchError, RobotsDisallowed, RobotsUnavailable
from src.ingest.pipeline import IngestResult, _exists, store_fetched
from src.utils.url_utils import canonicalize_url

# Conservative defaults: a shallow, small discovery crawl, not a mirror.
DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES = 50

# Link targets that are never worth fetching as article pages.
_SKIP_SUFFIXES = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".css",
    ".js",
    ".rss",
    ".xml",
    ".json",
    ".woff",
    ".woff2",
    ".ttf",
)


@dataclass
class CrawlConfig:
    max_depth: int = DEFAULT_MAX_DEPTH
    max_pages: int = DEFAULT_MAX_PAGES
    same_domain_only: bool = True

    def normalised(self) -> CrawlConfig:
        """Clamp to sane, safe bounds so a config can never request a runaway crawl."""
        return CrawlConfig(
            max_depth=max(0, min(int(self.max_depth), 6)),
            max_pages=max(1, min(int(self.max_pages), 500)),
            same_domain_only=bool(self.same_domain_only),
        )


@dataclass
class CrawlReport:
    source: str
    start_url: str
    pages_fetched: int = 0
    stopped_reason: str = "completed"
    tally: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "start_url": self.start_url,
            "pages_fetched": self.pages_fetched,
            "stopped_reason": self.stopped_reason,
            "tally": self.tally,
        }


def _registrable_host(netloc: str) -> str:
    """Lowercased host without a leading ``www.`` (cheap same-site heuristic)."""
    host = netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _harvest_links(html: str, base_url: str) -> list[str]:
    """Absolute, de-fragmented http(s) links from a page, in document order."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        absolute, _frag = urldefrag(urljoin(base_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if absolute.lower().endswith(_SKIP_SUFFIXES):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def crawl_source(
    session: Session,
    source: Source,
    *,
    fetcher: EthicalFetcher,
    config: CrawlConfig | None = None,
    start_url: str | None = None,
) -> CrawlReport:
    """Crawl ``source`` breadth-first within its own domain, storing articles found.

    Returns a :class:`CrawlReport` with the per-outcome tally, how many pages were
    fetched, and the reason the crawl stopped (completed / max_pages / max_depth).
    """
    cfg = (config or CrawlConfig()).normalised()
    start = start_url or f"https://{source.domain}"
    base_host = _registrable_host(urlparse(start).netloc)

    tally = {r.value: 0 for r in IngestResult}
    report = CrawlReport(source=source.name, start_url=start, tally=tally)

    queue: deque[tuple[str, int]] = deque([(start, 0)])
    queued: set[str] = {canonicalize_url(start)}

    while queue:
        if report.pages_fetched >= cfg.max_pages:
            report.stopped_reason = "max_pages"
            break

        url, depth = queue.popleft()

        try:
            fetched = fetcher.fetch(url, require_html=True)
        except RobotsDisallowed:
            tally[IngestResult.BLOCKED_ROBOTS.value] += 1
            continue
        except RobotsUnavailable:
            tally[IngestResult.ROBOTS_UNAVAILABLE.value] += 1
            continue
        except FetchError:
            tally[IngestResult.FETCH_FAILED.value] += 1
            continue

        report.pages_fetched += 1

        # Store the page if it is a real article (dedup handled inside).
        outcome = store_fetched(session, source, fetched)
        tally[outcome.result.value] += 1

        # Harvest links to keep discovering, even from non-article index pages,
        # but never beyond the depth bound.
        if depth >= cfg.max_depth:
            continue
        for link in _harvest_links(fetched.content, fetched.final_url):
            if cfg.same_domain_only and _registrable_host(urlparse(link).netloc) != base_host:
                continue
            canon = canonicalize_url(link)
            if canon in queued:
                continue
            # Skip links whose canonical form is already stored (cheap pre-filter).
            if _exists(session, canonical_url=canon):
                continue
            queued.add(canon)
            queue.append((link, depth + 1))

    if report.stopped_reason == "completed" and report.pages_fetched >= cfg.max_pages and queue:
        report.stopped_reason = "max_pages"
    return report
