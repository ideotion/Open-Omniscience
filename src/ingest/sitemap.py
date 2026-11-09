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
never be used to pivot discovery onto an arbitrary host. A urlset's page locs are
held to the same host by the same rule (R627; before, they were handed on unchecked),
and a loc urllib.parse cannot read is skipped and counted (R626), never raised.

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
from src.ingest.crawl import _off_site, _registrable_host
from src.ingest.fetch_verdict import failure_url
from src.ingest.pipeline import IngestResult, ingest_url
from src.monitoring.secret_scrub import record_text

# Bounds -- a sitemap CAN legitimately be huge (a news site's index can list
# thousands of child sitemaps); these keep ONE discovery call cheap + finite,
# never a runaway crawl of the whole site's history in one pass.
DEFAULT_MAX_SITEMAPS = 5
DEFAULT_MAX_URLS = 500
# A discovery keeps the first 100 skipped-off-host lines and counts them all (the independent read of R626, S2): nothing reads the
# list but tests and a person debugging, and five 9.9 MB urlsets of off-host locs made it 1,191,790 lines and 83 MB.
SKIPPED_OFF_HOST_KEPT = 100
# A discovery stops once it has skipped four times ``max_urls`` page locs (off the host or unreadable), so the locs it walks and
# remembers stay bounded. Never narrower than before R627: then every loc counted toward ``max_urls``, so a page this stop leaves
# unread was left unread then too.
SKIPPED_LOCS_PER_URL = 4

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
        raise SitemapError(f"refused unsafe XML (entity expansion/external entity): {record_text(exc, typed=False)}") from None
    except Exception as exc:  # noqa: BLE001 - any parse failure -> ONE typed error
        raise SitemapError(f"malformed sitemap XML: {record_text(exc, typed=False)}") from None

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


def _off_host(url: str, base_host: str) -> bool | None:
    """Whether ``url`` is off the source's host ``base_host``, by the ONE rule both checks of :func:`discover_sitemap_urls` use
    (a child sitemap's, and since R627 a urlset page loc's); ``None`` when ``urllib.parse`` cannot read ``url`` (R626). Never
    raises.

    - Unreadable: ``urlparse`` raises a bare ``ValueError`` on a lone or unclosed IPv6 bracket (``http://[::1``,
      ``http://good.example]/``), a bracketed host that is no address (``http://[foo]/``) and a netloc NFKC would change
      (``http://a\uff03b/``). Raised, one such child sitemap or page loc ended the whole discovery of its source; the loops skip
      it and count it.
    - Otherwise the host is :func:`~src.ingest.crawl._registrable_host`'s (after the last ``@``, lower-cased, without its port
      or a leading ``www.``), and must be ``base_host``. A loc with no host (``/relative``) is therefore off the host; a port out
      of range is compared like any other port (not at all), and the fetcher refuses such a URL before any request.
    - A netloc holding an ``@`` is always off the host, even when the host after it is the source's (R624's ``_off_site``):
      a child sitemap or a page address written with a user name or password is never fetched or stored (R630)."""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return None
    return _off_site(netloc, base_host)


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
    # Child sitemaps AND page locs off the source's host, never fetched or handed on (page locs since R627, written through
    # failure_url so no user name or password is kept here): the first SKIPPED_OFF_HOST_KEPT of them, and the count of all.
    skipped_off_host: list[str] = field(default_factory=list)
    skipped_off_host_count: int = 0
    # Distinct child sitemap and page locs urllib.parse could not read, skipped (R626).
    skipped_unreadable: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_reason: str = "completed"

    def skip_off_host(self, url: str) -> None:
        """Count ``url`` off the host, and list it (its userinfo masked, R621) while the list is under its cap."""
        self.skipped_off_host_count += 1
        if len(self.skipped_off_host) < SKIPPED_OFF_HOST_KEPT:
            self.skipped_off_host.append(failure_url(url))


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

    A urlset's page locs are held to the same host by the same rule (R627, :func:`_off_host`): before, they were never
    checked, so a sitemap could hand the caller pages on any other site to fetch and store as this source's. An off-host page
    loc is recorded in ``skipped_off_host`` (through ``failure_url``) and never returned. A child sitemap or page loc
    ``urllib.parse`` cannot read (``http://[::1``) is counted in ``skipped_unreadable`` and skipped (R626): its bare
    ``ValueError`` ended the whole discovery, and a page loc handed on ended the caller's walk of the rest.

    Both kinds of skip are bounded: ``skipped_off_host`` keeps its first :data:`SKIPPED_OFF_HOST_KEPT` lines beside
    ``skipped_off_host_count``, and once :data:`SKIPPED_LOCS_PER_URL` times ``max_urls`` page locs have been skipped the
    discovery stops (``stopped_reason`` ``"max_skipped"``).
    """
    base_host = _registrable_host(host)
    report = SitemapDiscoveryReport(source_host=host)

    declared = declared_sitemap_urls(fetcher, host)
    candidates = declared or default_sitemap_candidates(host)

    queue: deque[str] = deque(candidates)
    visited: set[str] = set()
    seen_urls: set[str] = set()
    tried = 0
    skipped_locs = 0
    max_skipped_locs = SKIPPED_LOCS_PER_URL * max_urls

    while queue:
        if tried >= max_sitemaps:
            report.stopped_reason = "max_sitemaps"
            break
        sm_url = queue.popleft()
        if sm_url in visited:
            continue
        visited.add(sm_url)

        # the host the fetch would go to (after the last ``@``), and never a child that carries a userinfo (R624)
        off = _off_host(sm_url, base_host)
        if off is None:  # urllib.parse cannot read it (R626)
            report.skipped_unreadable += 1
            continue
        if off:
            report.skip_off_host(sm_url)  # a report line: the userinfo masked (R621)
            continue
        if sm_url.lower().split("?")[0].endswith(".gz"):
            report.errors.append(f"unsupported (gzip): {failure_url(sm_url)}")
            continue

        tried += 1
        try:
            fetched = fetcher.fetch(sm_url, require_html=False)
        except FetchError as exc:
            report.errors.append(f"{failure_url(sm_url)}: {record_text(exc, typed=False)}")
            continue
        try:
            parsed = parse_sitemap_xml(fetched.content)
        except SitemapError as exc:
            report.errors.append(f"{failure_url(sm_url)}: {record_text(exc, typed=False)}")
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
            if skipped_locs >= max_skipped_locs:
                report.stopped_reason = "max_skipped"
                break
            if entry.loc in seen_urls:
                continue
            seen_urls.add(entry.loc)
            off = _off_host(entry.loc, base_host)  # the child sitemaps' rule (R627), a userinfo always off (R630)
            if off is None:  # urllib.parse cannot read it (R626)
                report.skipped_unreadable += 1
                skipped_locs += 1
                continue
            if off:
                report.skip_off_host(entry.loc)
                skipped_locs += 1
                continue
            report.urls.append(entry.loc)
        if len(report.urls) >= max_urls:
            break
        if skipped_locs >= max_skipped_locs:
            report.stopped_reason = "max_skipped"
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
