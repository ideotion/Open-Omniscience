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
from typing import cast
from urllib.parse import urldefrag, urljoin, urlparse, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from src.database.models import Source
from src.ingest import (
    CrawlDelayDeferred,
    EthicalFetcher,
    FetchError,
    RobotsDisallowed,
    RobotsUnavailable,
    _host_netloc,
)
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
    # Distinct links on the fetched pages that urllib.parse could not read: skipped, never followed (R626, see _harvest_links).
    skipped_unreadable: int = 0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "start_url": self.start_url,
            "pages_fetched": self.pages_fetched,
            "stopped_reason": self.stopped_reason,
            "tally": self.tally,
            "skipped_unreadable": self.skipped_unreadable,
        }


def _registrable_host(netloc: str) -> str:
    """The host a request to ``netloc`` goes to, without its port or a leading ``www.`` (cheap same-site heuristic).

    Read out of the fetcher's host key (:func:`src.ingest._host_netloc`, R624): the host is what follows the LAST ``@``, as
    ``urllib.parse`` reads it (lower-cased, an IPv6 literal without its brackets), so ``good.example:x@evil.example`` is
    ``evil.example``. Before, the netloc was lower-cased and cut at its first ``:`` with the userinfo still in it: that link
    read as ``good.example``, and a crawl or a sitemap index kept to good.example followed it to evil.example (robots, the SSRF
    guard and politeness still applied there; the crawl's scope did not). The same cut read a real same-host userinfo
    (``u:p@good.example``) as ``u``, and every IPv6 literal as ``[`` and its first group.

    The port is left out, as before: the check is same-site, not same-origin, and the sitemap compares with a bare domain that
    has no scheme to name a default port by. A trailing dot stays, as in the key. Never raises: a key ``urllib.parse`` cannot
    read again comes back as written, which names no readable host (the fetcher refuses such a URL)."""
    key = _host_netloc(netloc)
    try:
        host = urlsplit("//" + key).hostname or ""
    except ValueError:
        host = key
    return host[4:] if host.startswith("www.") else host


def _harvest_links(html: str, base_url: str) -> tuple[list[str], set[str]]:
    """Absolute, de-fragmented http(s) links from a page, in document order, and the hrefs ``urllib.parse`` could not read.

    An href ``urljoin``/``urldefrag``/``urlparse`` cannot read (an unclosed IPv6 bracket ``http://[::1``, a bracketed host that
    is no address, a netloc NFKC would change) raised a bare ``ValueError`` out of the harvest, which ended the source's whole
    crawl: one bad link on a page ended the pass (R626). It is skipped and handed back, as written, for the crawl to count;
    every link returned is one ``urlparse`` has read."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    unreadable: set[str] = set()
    for a in soup.find_all("a", href=True):
        # bs4 types every attribute as `str | AttributeValueList` because a few
        # (class, rel) are multi-valued. href is not one of them.
        href = cast(str, a["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        try:
            absolute, _frag = urldefrag(urljoin(base_url, href))
            parsed = urlparse(absolute)
        except ValueError:
            unreadable.add(href)
            continue
        if parsed.scheme not in ("http", "https"):
            continue
        if absolute.lower().endswith(_SKIP_SUFFIXES):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out, unreadable


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

    # STAGED is transient by contract (resolved at flush) — never a tally line.
    tally = {r.value: 0 for r in IngestResult if r is not IngestResult.STAGED}
    report = CrawlReport(source=source.name, start_url=start, tally=tally)

    queue: deque[tuple[str, int]] = deque([(start, 0)])
    queued: set[str] = {canonicalize_url(start)}
    unreadable: set[str] = set()  # the hrefs _harvest_links could not read, as written: counted once per crawl (R626)

    # P1.8 collector write batching: buffer stores across the crawl so several
    # articles share ONE gate window/fsync; fetches stay outside any gate.
    # OO_COLLECT_COMMIT_BATCH=0 restores the legacy per-article path exactly.
    from src.ingest.batch import ArticleBatch, collect_batch_size

    batch = ArticleBatch(session, source) if collect_batch_size() > 0 else None
    try:
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
            # S04-13 S2: before the FetchError base class it inherits from, so a
            # deferral is never tallied as a failure of the source.
            except CrawlDelayDeferred:
                tally[IngestResult.CRAWL_DELAY_DEFERRED.value] += 1
                continue
            except FetchError:
                tally[IngestResult.FETCH_FAILED.value] += 1
                continue

            report.pages_fetched += 1

            # Store the page if it is a real article (dedup handled inside).
            outcome = store_fetched(session, source, fetched, batch=batch)
            if outcome.result is not IngestResult.STAGED:
                tally[outcome.result.value] += 1

            # Harvest links to keep discovering, even from non-article index pages,
            # but never beyond the depth bound.
            if depth >= cfg.max_depth:
                continue
            links, page_unreadable = _harvest_links(fetched.content, fetched.final_url)
            unreadable |= page_unreadable
            for link in links:
                if cfg.same_domain_only and _registrable_host(urlparse(link).netloc) != base_host:
                    continue
                canon = canonicalize_url(link)
                if canon in queued:
                    continue
                # Skip links whose canonical form is already stored — or staged
                # in the uncommitted batch (cheap pre-filter, no double fetch).
                if batch is not None and batch.has_canonical(canon):
                    continue
                if _exists(session, canonical_url=canon):
                    continue
                queued.add(canon)
                queue.append((link, depth + 1))
    finally:
        # ZERO LOSS: staged entries always get their write attempt; the tally
        # then carries the true stored/duplicate counts.
        if batch is not None:
            batch.flush()
            for k, v in batch.tally.items():
                if v:
                    tally[k] = tally.get(k, 0) + v

    if report.stopped_reason == "completed" and report.pages_fetched >= cfg.max_pages and queue:
        report.stopped_reason = "max_pages"
    report.skipped_unreadable = len(unreadable)
    return report
