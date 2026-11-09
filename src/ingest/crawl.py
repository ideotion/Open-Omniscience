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
from functools import lru_cache
from typing import cast
from urllib.parse import urldefrag, urljoin, urlparse, urlsplit

import idna  # UTS 46, the encoding requests' own code names a non-ASCII host with (R631; see _site_key)
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from src.database.models import Source
from src.ingest import (
    CrawlDelayDeferred,
    EthicalFetcher,
    FetchError,
    RobotsDisallowed,
    RobotsUnavailable,
    _carries_userinfo,
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
    except ValueError:  # a defence: on Python 3.13 the callers' own urlparse already raises on what would reach it
        host = key
    return host[4:] if host.startswith("www.") else host


def _off_site(netloc: str, base_host: str) -> bool:
    """Whether a harvested link or a child sitemap with ``netloc`` is outside the site ``base_host`` (R624).

    A netloc holding an ``@`` is ALWAYS off-site, even when the host after it is the site: following it would send that
    userinfo to the site as a login (requests turns it into an ``Authorization`` header) and write it into the stored article
    URL, the canonical URL and a saved sitemap address (the independent read of R624, S1). The fetcher's other lane already
    refuses any userinfo (``src/safety/fetcher.py``), and before R624 such a link read as the host ``u`` and was never followed.
    The site's own host, read from the start URL or the source's domain, still goes through :func:`_registrable_host`, so a
    start URL the operator wrote with a login keeps its host.

    Both hosts are compared in the form the request names them (:func:`_site_key`, R631): ``bücher.example`` and
    ``xn--bcher-kva.example`` are one site, either way round, and a host that cannot be encoded is off the site (fail closed)."""
    if "@" in netloc:
        return True
    ours, site = _site_key(_registrable_host(netloc)), _base_site_key(base_host)
    return ours is None or site is None or ours != site


@lru_cache(maxsize=256)
def _base_site_key(base_host: str) -> str | None:
    """:func:`_site_key` of the site's own host, the same for every link of a crawl or a sitemap: encoded once, not per link (the
    independent read of R626, a nit: 51 µs a loc for a Unicode source). Only the operator's hosts reach this cache (a start URL,
    a source's domain), never a fetched page's."""
    return _site_key(base_host)


def _site_key(host: str) -> str | None:
    """``host`` (a :func:`_registrable_host`) in its ASCII form, for the same-site comparison (R631). Never raises.

    An ASCII host is compared as it is (urllib.parse has lower-cased it), punycode included. A host with any other character
    is encoded with UTS 46 (``idna.encode(host, uts46=True)``, requests' own ``PreparedRequest._get_idna_encoded_host``), so a
    source written in its Unicode form matches the punycode links its pages and its sitemap carry, and the other way round:
    before, ``bücher.example`` and ``xn--bcher-kva.example`` read as two sites, and the three catalogue sources with a Unicode
    domain lost their punycode links and page locs. ``None`` when the host cannot be encoded (an empty label, a label over 63, a
    name over 253, a disallowed character; idna refuses a 10 MB name at once), and a comparison with ``None`` is off the site.

    This is not the encoding the connection is named by on the urllib3 the app pins (2.x): urllib3 encodes the host first, each
    label lower-cased and passed to ``idna.encode(label, strict=True, std3_rules=True)`` (IDNA 2008), so requests' UTS 46 path
    is never reached for an http(s) URL (the independent read of R626, S3). The two agree on the three catalogue domains and on
    every plain Unicode name; they differ on a capital sigma (``ΣΣ.example``), a fullwidth or other compatibility character
    (UTS 46 maps it, urllib3 refuses it) and a few hundred more of the read's 63,787 names. The fetcher refuses every such name
    before any request (R622's ``_refuse_parser_mismatch``: it lets a non-ASCII host through only when IDNA 2003 gives urllib3's
    name), so this comparison never decides a fetch on a name where it and the connection disagree; a test holds that."""
    if host.isascii():
        return host
    try:
        return idna.encode(host, uts46=True).decode("ascii")
    except ValueError:  # idna.IDNAError and UnicodeError both are one
        return None


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
                if _carries_userinfo(link):
                    # R630: a link written with a user name or password is never followed or stored, whatever the scope:
                    # requests would send it as a login and it would land in the stored URLs (R624's read)
                    continue
                if cfg.same_domain_only and _off_site(urlparse(link).netloc, base_host):
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
