"""
Sitemap discovery — a URL-discovery channel through the ONE fetch path.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-24 throughput brief, C7 (S-E slice 1 -- "the biggest single unlock"). A
sitemap is a source's OWN structured, self-declared page list -- reading it is
cheaper and more complete than following <a> links (src.ingest.crawl), and it works
for sources whose home page never lists all of their content. THREE consumers, in
the brief's own value order:

  (a) new-URL discovery for an already-qualified source -- wired into the
      housekeeping lane's ``crawl`` rung (src.scheduler.runner._lane_step_crawl):
      when a candidate's sitemap resolves, its declared article URLs are ingested
      directly instead of falling back to blind link-following.
  (b) the qualification TRIAL channel for a FEEDLESS candidate -- src.catalog.
      qualification.trial_fetch was RSS-only, so the feedless majority of the
      discovery backlog could never produce evidence (the "no reachable feed"
      documented scope limit); see ``sitemap_trial_ingest`` below.
  (c) populate/refresh ``Source.sitemap_url`` once a source's real sitemap is
      confirmed working, so later discovery skips straight to it.

SAFETY (this is UNTRUSTED, network-fetched XML): parsed via ``defusedxml`` -- the
SAME guard ``src.wiki.dumpread`` already uses against entity-expansion ("billion
laughs") / external-entity (XXE) attacks the stdlib ``ElementTree`` is vulnerable
to. Every fetch goes through :class:`~src.ingest.EthicalFetcher` (robots.txt
fail-closed, per-host politeness, size-bounded via ``max_bytes``) -- there is no
bypass. A sitemap-index child sitemap that points OFF the source's own registrable
host is NEVER fetched (reported, not followed) -- the same "same-domain only"
discipline ``src.ingest.crawl`` applies, so a compromised/malicious sitemap can
never be used to pivot discovery onto an arbitrary host.

Scope: plain XML only (a ``.gz``-suffixed sitemap is reported as unsupported, never
guessed-at) -- gzip decompression is a documented, deliberate follow-up, not silently
mishandled here.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_fromstring
from sqlalchemy.orm import Session

from src.database.models import Source
from src.ingest import EthicalFetcher, FetchError
from src.ingest.crawl import _registrable_host
from src.ingest.pipeline import IngestResult, ingest_url

# Bounds -- a sitemap CAN legitimately be huge (a news site's index can list
# thousands of child sitemaps); these keep ONE discovery call cheap + finite,
# never a runaway crawl of the whole site's history in one pass.
DEFAULT_MAX_SITEMAPS = 5
DEFAULT_MAX_URLS = 500

# Conventional sitemap locations tried ONLY when the host declares none via
# robots.txt (declared_sitemaps() is always preferred -- it is the site's OWN
# authoritative pointer).
_CONVENTIONAL_PATHS = ("/sitemap.xml", "/sitemap_index.xml")


class SitemapError(Exception):
    """A sitemap could not be parsed (malformed / not XML / neither index nor
    urlset / an entity-expansion or external-entity attack that defusedxml
    refused). Callers treat this exactly like a fetch failure -- record and move
    on, never crash the whole discovery run."""


@dataclass
class SitemapEntry:
    loc: str
    lastmod: str | None = None


@dataclass
class SitemapParseResult:
    """``kind`` is ``"index"`` (a sitemap-index listing child sitemaps) or
    ``"urlset"`` (a leaf sitemap listing pages). Exactly one of ``sitemaps`` /
    ``urls`` is populated, per the sitemaps.org schema."""

    kind: str
    sitemaps: list[str] = field(default_factory=list)
    urls: list[SitemapEntry] = field(default_factory=list)


def _localname(tag: str) -> str:
    """Strip an XML namespace (``{uri}tag`` -> ``tag``); Google News sitemaps and
    plain sitemaps.org sitemaps both use the SAME <urlset>/<url>/<loc> skeleton,
    only the namespace declarations differ, so matching by local name handles
    both uniformly without caring about the exact namespace URI."""
    return tag.rpartition("}")[2] if "}" in tag else tag


def parse_sitemap_xml(data: bytes | str) -> SitemapParseResult:
    """Parse a sitemap-index or urlset document. PURE -- no network, no I/O.

    Raises :class:`SitemapError` on anything that isn't a well-formed, recognised
    sitemap document -- a malformed body, a non-XML body, an entity-expansion/
    external-entity attack (defusedxml refuses these before they can do any
    damage), or a root element that is neither ``sitemapindex`` nor ``urlset``.
    Never raises the underlying XML library's own exception type, so every
    caller has exactly ONE failure mode to handle.
    """
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    if not data or not data.strip():
        raise SitemapError("empty sitemap body")
    try:
        root = _safe_fromstring(data)
    except DefusedXmlException as exc:
        raise SitemapError(f"refused unsafe XML (entity expansion/external entity): {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any parse failure -> ONE typed error
        raise SitemapError(f"malformed sitemap XML: {exc}") from exc

    root_kind = _localname(root.tag)
    if root_kind == "sitemapindex":
        sitemaps: list[str] = []
        for sm in root:
            if _localname(sm.tag) != "sitemap":
                continue
            for child in sm:
                if _localname(child.tag) == "loc" and (child.text or "").strip():
                    sitemaps.append(child.text.strip())
                    break
        return SitemapParseResult(kind="index", sitemaps=sitemaps)
    if root_kind == "urlset":
        urls: list[SitemapEntry] = []
        for u in root:
            if _localname(u.tag) != "url":
                continue
            loc: str | None = None
            lastmod: str | None = None
            for child in u:
                cname = _localname(child.tag)
                if cname == "loc" and (child.text or "").strip():
                    loc = child.text.strip()
                elif cname == "lastmod" and (child.text or "").strip():
                    lastmod = child.text.strip()
            if loc:
                urls.append(SitemapEntry(loc=loc, lastmod=lastmod))
        return SitemapParseResult(kind="urlset", urls=urls)
    raise SitemapError(f"root element {root.tag!r} is neither sitemapindex nor urlset")


def declared_sitemap_urls(fetcher: EthicalFetcher, host: str) -> list[str]:
    """Sitemap URLs ``host`` declares in its OWN robots.txt (the preferred,
    authoritative discovery source). ``host`` is a bare domain (e.g.
    ``example.com``); tried over https first, then http, since we don't yet know
    which scheme the site actually serves. Returns ``[]`` (never a guess) on any
    refusal (airplane mode, robots disallow/unavailable) or when none are
    declared."""
    for scheme in ("https", "http"):
        try:
            found = fetcher.declared_sitemaps(f"{scheme}://{host}")
        except FetchError:
            continue
        if found:
            return found
    return []


def default_sitemap_candidates(host: str) -> list[str]:
    """Conventional sitemap paths to TRY when the host declares none -- still
    fetched through the full ethical path (robots/politeness/SSRF), so this is a
    guess about the URL only, never a bypass of any guard."""
    return [f"https://{host}{p}" for p in _CONVENTIONAL_PATHS]


@dataclass
class SitemapDiscoveryReport:
    source_host: str
    root_sitemap_url: str | None = None
    urls: list[str] = field(default_factory=list)
    child_sitemaps_fetched: int = 0
    skipped_off_host: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped_reason: str = "completed"


def discover_sitemap_urls(
    fetcher: EthicalFetcher,
    host: str,
    *,
    max_sitemaps: int = DEFAULT_MAX_SITEMAPS,
    max_urls: int = DEFAULT_MAX_URLS,
) -> SitemapDiscoveryReport:
    """Discover a source's own article URLs via its sitemap(s), bounded.

    Tries robots-DECLARED sitemaps first, falling back to conventional paths
    (``/sitemap.xml`` etc.) only when none are declared. A sitemap-index is
    followed ONE level (its child sitemaps are fetched too, up to
    ``max_sitemaps`` total) -- but ONLY child sitemaps on the SAME registrable
    host as ``host`` are ever fetched; an off-host child is recorded in
    ``skipped_off_host`` and never followed (the same "same-domain only"
    discipline ``src.ingest.crawl`` applies to on-page links).
    """
    base_host = _registrable_host(host)
    report = SitemapDiscoveryReport(source_host=host)

    declared = declared_sitemap_urls(fetcher, host)
    candidates = declared or default_sitemap_candidates(host)

    queue: deque[str] = deque(candidates)
    visited: set[str] = set()
    seen_urls: set[str] = set()
    tried = 0

    while queue:
        if tried >= max_sitemaps:
            report.stopped_reason = "max_sitemaps"
            break
        sm_url = queue.popleft()
        if sm_url in visited:
            continue
        visited.add(sm_url)

        if _registrable_host(urlparse(sm_url).netloc) != base_host:
            report.skipped_off_host.append(sm_url)
            continue
        if sm_url.lower().split("?")[0].endswith(".gz"):
            report.errors.append(f"unsupported (gzip): {sm_url}")
            continue

        tried += 1
        try:
            fetched = fetcher.fetch(sm_url, require_html=False)
        except FetchError as exc:
            report.errors.append(f"{sm_url}: {exc}")
            continue
        try:
            parsed = parse_sitemap_xml(fetched.content)
        except SitemapError as exc:
            report.errors.append(f"{sm_url}: {exc}")
            continue

        report.child_sitemaps_fetched += 1
        if report.root_sitemap_url is None:
            report.root_sitemap_url = sm_url

        if parsed.kind == "index":
            # Only a CANDIDATE guess (top of the queue) resolving to an index is
            # itself unexplored; a DECLARED index is trusted the same way. Either
            # way, its children are bounded by max_sitemaps like everything else.
            queue.extend(parsed.sitemaps)
            continue

        for entry in parsed.urls:
            if len(report.urls) >= max_urls:
                report.stopped_reason = "max_urls"
                break
            if entry.loc not in seen_urls:
                seen_urls.add(entry.loc)
                report.urls.append(entry.loc)
        if len(report.urls) >= max_urls:
            break

    return report


def update_source_sitemap_url(session: Session, source: Source, report: SitemapDiscoveryReport) -> bool:
    """Consumer (c): persist a confirmed working root sitemap onto
    ``SourceMetadata.sitemap_url`` (populate when empty, REFRESH when the site's
    real sitemap moved) -- NOT a ``Source`` column: ``sitemap_url`` lives on the
    one-to-one ``SourceMetadata`` side table (src/monitoring/preflight.py's
    ``_apply_to_metadata`` get-or-create pattern, reused here). Returns whether a
    write happened -- never writes when nothing was actually confirmed
    (``root_sitemap_url`` is only set once a fetch+parse round-trip succeeded)."""
    if not report.root_sitemap_url:
        return False
    from src.database.models import SourceMetadata

    meta = session.query(SourceMetadata).filter_by(source_id=source.id).first()
    if meta is None:
        meta = SourceMetadata(source_id=source.id)
        session.add(meta)
    elif meta.sitemap_url == report.root_sitemap_url:
        return False
    meta.sitemap_url = report.root_sitemap_url
    return True


def sitemap_trial_ingest(
    session: Session,
    source: Source,
    fetcher: EthicalFetcher,
    *,
    max_items: int,
    max_sitemaps: int = DEFAULT_MAX_SITEMAPS,
    max_urls: int = DEFAULT_MAX_URLS,
) -> dict:
    """Consumer (b): the qualification TRIAL channel for a FEEDLESS candidate.

    Discovers a bounded set of the source's own article URLs via its sitemap,
    then ingests up to ``max_items`` of them through the SAME real path
    (:func:`~src.ingest.pipeline.ingest_url` -- fetch, extract, dedup, store) any
    other trial uses, so a feedless candidate now produces genuine extraction-
    validity evidence exactly like an RSS-having one (2026-07-23 field-diagnostics
    fix's "no reachable feed" gap). A confirmed working sitemap is persisted onto
    ``Source.sitemap_url`` (consumer c) as a side effect.
    """
    report = discover_sitemap_urls(
        fetcher, source.domain, max_sitemaps=max_sitemaps, max_urls=max_urls
    )
    update_source_sitemap_url(session, source, report)

    tally = {r.value: 0 for r in IngestResult if r is not IngestResult.STAGED}
    attempted = 0
    for url in report.urls:
        if attempted >= max_items:
            break
        outcome = ingest_url(session, source, url, fetcher=fetcher)
        attempted += 1
        if outcome.result is not IngestResult.STAGED:
            tally[outcome.result.value] += 1

    return {
        "channel": "sitemap",
        "root_sitemap_url": report.root_sitemap_url,
        "discovered": len(report.urls),
        "attempted": attempted,
        "tally": tally,
        "errors": report.errors,
    }
