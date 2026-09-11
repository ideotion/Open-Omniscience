"""Offline discovery channels (see package docstring). DB-only by contract."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

_CITATION_MIN = 3  # distinct citing articles before a domain becomes a candidate

# Commerce/storefront filter for the citation channel (field log 2026-06-13:
# citation discovery surfaced shop.popsci.com, store.popsci.com and
# popularscienceprints.com — merch, not journalism). Conservative + explainable:
# a leftmost storefront subdomain, a commercial gTLD, a print-shop name, or a
# hyphen-delimited shop/store/merch suffix on the registrable name.
# Discovery candidates are never auto-enabled, so the only cost of a rare
# false positive is one un-suggested domain; the win is not nudging the operator
# toward a brand's shop as if it were a source.
_COMMERCE_LABELS = frozenset(
    {
        "shop", "shops", "store", "stores", "buy", "cart", "checkout",
        "merch", "shopping", "deals", "coupons", "ecommerce", "basket", "boutique",
    }
)
_COMMERCE_TLDS = frozenset({"shop", "store", "buy", "deals", "tickets", "boutique"})
# Suffix tokens on the registrable name — matched ONLY after a hyphen boundary
# ("acme-shop", "band-merch", "big-store"). A hyphen makes the token a deliberate
# compound, so this stays clear of legitimate names that merely END in these
# letters: restore.com, workshop.com, bookstore-review.org, superstore-news.com
# all pass through. We deliberately do NOT match a bare (un-hyphenated) suffix
# like "acmeshop"/"bigbrandstore" — without a dictionary it cannot be told from
# "workshop"/"bishop"/"restore", and inventing that precision would be exactly
# the kind of fabricated confidence this project forbids (provenance over guesses).
_COMMERCE_NAME_SUFFIXES = ("-shop", "-shops", "-store", "-stores", "-merch", "-shopping")


def is_commerce_domain(host: str | None) -> bool:
    """True for a storefront/merch domain a journalism source-discovery should
    not suggest. HEURISTIC, conservative, label/boundary-based — it catches the
    OBVIOUS storefronts, never all commerce. It fires on:

    * a leftmost ``shop.``/``store.``/``buy.`` (etc.) subdomain label;
    * a ``.shop``/``.store`` (etc.) commercial gTLD;
    * a ``…prints`` second-level name (popularscienceprints.com and kin);
    * a hyphen-delimited ``-shop``/``-store``/``-merch`` suffix on the
      registrable name (acme-shop.com).

    It deliberately does NOT match a substring buried in an unrelated word
    (restore.com, workshop.com, bookstore-review.org) — false positives only
    cost one un-suggested domain (candidates are never auto-enabled), so we err
    toward under-filtering rather than wrongly skipping a real source."""
    if not host:
        return False
    labels = host.lower().split(".")
    if len(labels) < 2:
        return False
    if labels[0] in _COMMERCE_LABELS:  # shop./store./buy.<domain>
        return True
    if labels[-1] in _COMMERCE_TLDS:  # <name>.shop / <name>.store gTLD
        return True
    name = labels[-2]  # the registrable name, e.g. "popularscienceprints"
    if name.endswith("prints"):  # popularscienceprints.com and kin
        return True
    return name.endswith(_COMMERCE_NAME_SUFFIXES)  # acme-shop / band-merch


# Infrastructure / CDN / analytics / boilerplate-legal filter (maintainer field 2026-07-10:
# citation discovery surfaced fonts.googleapis.com, policies.google.com, creativecommons.org,
# bsky.app, t.me — ranked HIGH precisely because they are ubiquitous footer/asset links on
# nearly every page, not because they are sources). These are never journalism sources.
# Conservative + explainable, mirroring is_commerce_domain: an exact infrastructure
# registrable domain (or a subdomain of one) OR a leftmost non-content host label. A false
# positive costs only one un-suggested candidate (never auto-enabled), so we err toward
# under-filtering, never toward wrongly skipping a real outlet.
# EXACT registrable domains that are PURELY infrastructure/tracking/boilerplate and are never
# a plausible journalism source. DELIBERATELY EXCLUDES real content publishers a corpus might
# legitimately cite (w3.org / gnu.org / iana.org / whatwg.org / cloudflare.com's blog) — the
# err-toward-under-filtering rule: a false positive here would silently drop a real source.
_INFRA_DOMAINS = frozenset(
    {
        # CDN / asset / font / script / media hosts
        "googleapis.com", "gstatic.com", "googleusercontent.com", "ytimg.com",
        "jsdelivr.net", "unpkg.com", "jquery.com", "bootstrapcdn.com", "cloudfront.net",
        "akamaihd.net", "akamai.net", "fastly.net", "cloudflareinsights.com",
        "gravatar.com", "wp.com", "twimg.com", "fbcdn.net", "staticflickr.com",
        # analytics / tracking / ads
        "google-analytics.com", "googletagmanager.com", "doubleclick.net",
        "googlesyndication.com", "googleadservices.com", "scorecardresearch.com",
        "quantserve.com", "hotjar.com", "mixpanel.com", "chartbeat.com",
        # licenses / markup / boilerplate (footer/markup links on nearly every page)
        "creativecommons.org", "schema.org", "gdpr.eu", "gdpr-info.eu",
        # share widgets (2026-07-18 Leads-calibration field export: addtoany.com surfaced
        # as a "source-laundering origin" — a share-button widget embedded on countless
        # unrelated pages, never a corroborating citation)
        "addtoany.com",
    }
)
_INFRA_LABELS = frozenset(
    {
        "fonts", "cdn", "cdns", "static", "assets", "ajax", "img", "imgs",
        "analytics", "ads", "adservice", "adservices", "pixel", "telemetry",
        "tagmanager", "gtm", "doubleclick",
        "policies", "policy", "legal", "gdpr", "cookies", "consent",
    }
)


def is_infrastructure_domain(host: str | None) -> bool:
    """True for a CDN / asset / analytics / boilerplate-legal host a journalism
    source-discovery must never suggest (fonts.googleapis.com, policies.google.com,
    creativecommons.org …).

    Fires on: (a) a leftmost non-content label (``fonts.``/``cdn.``/``static.``/``policies.``
    …) ONLY on a SUBDOMAIN (``len(labels) >= 3``) — so ``policies.google.com`` is caught but a
    real 2-label registrable org whose NAME happens to be an infra word (``policy.org``,
    ``legal.io``, ``ads.net``) is NOT (skeptic finding: the leftmost-label rule must never fire
    on a registrable name); or (b) an exact infrastructure registrable domain (or a subdomain
    of one). Conservative — a content aggregator on the same parent (news.google.com) passes.

    Residual (accepted, err-under-filter): a multi-part-eTLD registrable name whose second
    level is an infra word (``policy.co.uk``) can still match the label rule — rare, and a
    false positive only costs one un-suggested candidate (never auto-enabled)."""
    if not host:
        return False
    h = host.lower().strip(".")
    labels = h.split(".")
    if len(labels) < 2:
        return False
    if len(labels) >= 3 and labels[0] in _INFRA_LABELS:  # a SUBDOMAIN label: fonts.X / policies.X
        return True
    return any(h == d or h.endswith("." + d) for d in _INFRA_DOMAINS)


def _existing_domains(session) -> set[str]:
    from src.database.models import Source, SourceCandidate

    src = {d.lower() for (d,) in session.query(Source.domain).all() if d}
    cand = {d.lower() for (d,) in session.query(SourceCandidate.domain).all() if d}
    return src | cand


def resolve_external_source(session, *, domain: str, name: str | None, discovered_via: str) -> None:
    """Q4a: resolve a discovered/cited domain into the ``external_sources`` REGISTRY with provenance
    -- the dormancy-ending wiring. Idempotent upsert keyed on the unique domain: a NEW domain is
    inserted with ``discovered_via`` (the channel) + ``source_type='unknown'`` (never a credibility
    score -- that legacy column stays NULL); an EXISTING row keeps its FIRST provenance
    (first-writer-wins) and only fills a missing ``discovered_via``/``name``. Descriptive only."""
    from src.database.models import ExternalSource

    dom = domain.lower()
    row = session.query(ExternalSource).filter_by(domain=dom).first()
    if row is None:
        session.add(ExternalSource(
            domain=dom, name=name or dom, source_type="unknown", discovered_via=discovered_via,
        ))
        return
    # first-writer-wins on provenance; only backfill what is missing (never overwrite)
    if not row.discovered_via:
        row.discovered_via = discovered_via
    # upgrade a domain-placeholder name to a real one, but never overwrite a real existing name
    if name and (not row.name or row.name == row.domain):
        row.name = name


def is_disqualified_domain(session, domain: str) -> bool:
    """Has this instance JUDGED this domain and refused it?

    Indexed seeks on the unique ``domain`` column, over the spellings the same host
    can legitimately arrive as. Asking only for ``domain.lower()`` -- the first cut --
    was strictly WORSE than not normalising at all: ``Source.domain`` is compared with
    SQLite's BINARY collation and is stored unnormalised by ``POST /api/sources``
    (``SourceManager.create_source`` does not run it through :func:`registrable_domain`),
    so a source an operator typed as ``Example.COM`` and later disqualified was
    unrefusable by EVERY spelling, the exact-case caller included.

    HONEST LIMIT, because this is a refusal and a refusal that quietly does not fire is
    the bad direction: this catches a stored domain written the way it is asked for, in
    lowercase, or with a ``www.`` the caller supplied. It cannot catch a domain STORED
    with uppercase and asked in lowercase -- nothing here can, short of a scan over
    ``lower(Source.domain)`` that no index serves, or normalising on write, which is
    where the asymmetry actually belongs. Every catalogue this app ships is entirely
    lowercase, so the gap is reachable only through a hand-typed source.

    Deliberately a per-domain question rather than a set built once: a set snapshot is
    the shape that goes stale. The cost is bounded by the callers, not by this function
    -- see ``promote_cited_sources``, which asks only about domains it already knows are
    sources.
    """
    from src.catalog.normalize import registrable_domain
    from src.catalog.qualification import STATUS_DISQUALIFIED
    from src.database.models import Source

    spellings = {domain, domain.lower()}
    reg = registrable_domain(domain)
    if reg:
        spellings.add(reg)
    return (
        session.query(Source.id)
        .filter(Source.domain.in_(spellings), Source.status == STATUS_DISQUALIFIED)
        .first()
        is not None
    )


def _add_candidate(session, *, domain: str, name: str | None, channel: str, evidence: dict) -> bool:
    """Stage one discovery candidate. Returns False when the domain is REFUSED.

    RULING 2026-07-20 clause (d): a fresh citation of a DISQUALIFIED domain must never
    re-register or re-trial it -- a mis-interpreted marketplace or a video blog the
    operator's own instance already judged does not come back because three more
    articles happened to link to it.

    That property HELD before this check existed, but only as a side effect: every
    channel dedupes against ``_existing_domains``, which contains every ``Source``
    domain including disqualified ones, so a disqualified domain never reached here.
    Verified live before the check was added -- both funnels already skipped it. The
    problem was that nothing said so and nothing tested it, so the guarantee lived in
    a dedup set whose PURPOSE is something else entirely; narrowing that set (scoping
    it to enabled sources, say -- exactly the shape the open ``enabled``-vs-qualified
    question would take) would reopen the hole silently.

    So the refusal lives HERE, at the one chokepoint every channel stages through,
    rather than in each channel: a channel added later cannot forget a check it never
    had to write.

    It is not merely "not the everyday path" -- through the three channels it is
    UNREACHABLE, provably: each computes ``known = _existing_domains(session)``, which
    lowercases every ``Source`` domain, and passes an already-lowercased ``dom``, and
    each skips on ``dom in known`` BEFORE staging. A disqualified domain is a Source
    domain, so it is in ``known``, so it never arrives. That is why the sibling test
    drives this function directly: it is the only level at which this particular
    refusal discriminates. The counter ``citation_channel`` keeps for it is therefore
    structurally zero today -- kept because the whole point of moving the check here is
    the day ``known`` is narrowed (scoping it to enabled sources, say), when it starts
    firing and a silent ``continue`` would be a refusal nobody could see.
    """
    from src.database.models import SourceCandidate

    if is_disqualified_domain(session, domain):
        return False
    session.add(
        SourceCandidate(
            domain=domain.lower(),
            suggested_name=name,
            channel=channel,
            evidence=json.dumps(evidence, sort_keys=True, default=str),
            status="candidate",
            first_seen=datetime.now(UTC).replace(tzinfo=None),
            last_seen=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    # Q4a: the same discovered domain resolves into the external_sources registry with provenance.
    resolve_external_source(session, domain=domain, name=name, discovered_via=channel)
    return True


def _citation_scan_budget_s() -> float:
    """Soft wall-clock budget for the citation channel's article_links scan (finding
    A2: the field corpus has 1.3M+ distinct (url, article_id) pairs, and an unbounded
    scan pinned a pooled connection for 26 minutes). Default
    ``OO_DISCOVERY_CITATION_BUDGET_S`` = 30s; <= 0 = unbounded. Same grammar as
    ``src/analytics/store.py``'s ``_maint_budget_s``/``prune_orphan_keywords``."""
    import os

    try:
        return float(os.getenv("OO_DISCOVERY_CITATION_BUDGET_S", "30"))
    except ValueError:
        return 30.0


def citation_candidates(
    session,
    *,
    cap: int,
    min_citations: int = _CITATION_MIN,
    budget_s: float | None = None,
    extra_known: set[str] | None = None,
) -> dict:
    """DECIDE phase for the citation channel: PURE reads, no DB writes. Returns plain
    Python values (dicts of primitives), never ORM objects, so nothing here can
    lazy-load once the caller ends the read transaction. Safe to run OUTSIDE the
    write gate and OUTSIDE any savepoint (see ``run_discovery``'s comment for why
    that split fixes SQLITE_BUSY_SNAPSHOT rather than merely relocating it).

    Streams the ``(normalized_url, article_id)`` pairs via ``yield_per`` -- the
    field corpus has 1.3M+ distinct pairs, so the whole result is never
    materialised at once -- under a soft wall-clock DEADLINE (``budget_s``; default
    :func:`_citation_scan_budget_s`, <= 0 unbounded). A truncated scan reports
    ``complete: False`` with the rows actually scanned and a stated reason, and
    every per-domain citation count in that case is a FLOOR
    (``distinct_citing_articles_at_least``), never presented under the
    complete-scan key (``distinct_citing_articles``) -- a truncated number dressed
    as a complete one is exactly the defect this fix exists to avoid.

    ``extra_known`` carries domains already DECIDED (but not yet inserted) by an
    earlier channel in the same ``run_discovery`` pass -- standing in for the
    flush-based cross-channel dedup the old single continuous transaction gave for
    free (see ``run_discovery``).
    """
    import time as _time

    from src.catalog.normalize import is_social, registrable_domain
    from src.database.models import ArticleLink

    budget = budget_s if budget_s is not None else _citation_scan_budget_s()
    deadline = (_time.monotonic() + budget) if budget > 0 else None

    known = _existing_domains(session) | (extra_known or set())
    by_domain: dict[str, set[int]] = defaultdict(set)
    rows_scanned = 0
    complete = True
    q = session.query(ArticleLink.normalized_url, ArticleLink.article_id).distinct()
    for nu, aid in q.yield_per(2000):
        rows_scanned += 1
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom.lower()].add(aid)
        if deadline is not None and _time.monotonic() > deadline:
            complete = False
            break

    decisions: list[dict] = []
    skipped = {"commerce": 0, "social": 0, "infrastructure": 0}
    for dom, ids in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        if len(decisions) >= cap:
            break
        if len(ids) < min_citations or dom in known:
            continue
        # A domain frequently cited by articles is NOT automatically a source: storefronts
        # (field 2026-06-13), social platforms, and CDN/analytics/boilerplate-legal hosts
        # (bsky.app/t.me/fonts.googleapis.com/policies.google.com/creativecommons.org —
        # field 2026-07-10) are ubiquitous footer/asset links, ranked HIGH by raw citation
        # count precisely because they appear everywhere. Never suggest them.
        if is_commerce_domain(dom):
            skipped["commerce"] += 1
            continue
        if is_social(dom):
            skipped["social"] += 1
            continue
        if is_infrastructure_domain(dom):
            skipped["infrastructure"] += 1
            continue
        evidence: dict = {"sample_article_ids": sorted(ids)[:5]}
        if complete:
            evidence["reason"] = "frequently cited by your stored articles"
            evidence["distinct_citing_articles"] = len(ids)
        else:
            evidence["reason"] = (
                "frequently cited by your stored articles (the scan was cut short by "
                "its wall-clock budget; this count is a floor, not the true total)"
            )
            evidence["distinct_citing_articles_at_least"] = len(ids)
            evidence["rows_scanned"] = rows_scanned
        decisions.append({"domain": dom, "name": None, "channel": "citation", "evidence": evidence})
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)

    reason = None
    if not complete:
        reason = f"wall-clock budget ({budget:.0f}s) reached after {rows_scanned} row(s) scanned"
    return {
        "decisions": decisions,
        "skipped": skipped,
        "complete": complete,
        "rows_scanned": rows_scanned,
        "budget_s": budget,
        "reason": reason,
    }


def _apply_candidate_decisions(session, decisions: list[dict]) -> tuple[list[str], int]:
    """APPLY phase shared by every channel: mechanical ``_add_candidate`` inserts only
    -- no scanning, no aggregation. When called from ``run_discovery`` this runs with
    the write gate held (see its comment); a standalone channel entry point (below)
    may call it ungated, exactly as every channel always could before this split.
    Returns ``(created_domains, disqualified_count)``."""
    created: list[str] = []
    disqualified = 0
    for d in decisions:
        if _add_candidate(
            session, domain=d["domain"], name=d.get("name"), channel=d["channel"], evidence=d["evidence"]
        ):
            created.append(d["domain"])
        else:
            disqualified += 1
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    return created, disqualified


def citation_channel(
    session, *, cap: int, min_citations: int = _CITATION_MIN, _decided: dict | None = None
) -> list[str]:
    """Suggest external domains that >= min_citations distinct stored articles cite.

    Compat entry point: decide (:func:`citation_candidates`) + apply
    (:func:`_apply_candidate_decisions`) in one call when ``_decided`` is omitted --
    this function never took the write gate itself (only ``run_discovery``'s caller
    wraps the apply step), so every existing direct caller (tests/scripts) keeps its
    old one-call, atomic-per-this-session behaviour unchanged. ``run_discovery``
    passes a pre-computed ``_decided`` (from a call made BEFORE the write gate is
    taken) so this call only does the write-side work."""
    result = _decided if _decided is not None else citation_candidates(session, cap=cap, min_citations=min_citations)
    created, disqualified = _apply_candidate_decisions(session, result["decisions"])
    skipped = dict(result.get("skipped") or {}, disqualified=disqualified)
    if any(skipped.values()):
        _LOG.debug(
            "citation discovery skipped commerce=%(commerce)d social=%(social)d "
            "infrastructure=%(infrastructure)d disqualified=%(disqualified)d domain(s)",
            skipped,
        )
    return created


def catalog_candidates(
    session, *, cap: int, thin_threshold: int = 3, extra_known: set[str] | None = None
) -> dict:
    """DECIDE phase for the catalog channel: PURE reads (see ``citation_candidates``
    for why that matters and is safe). Small/bounded by construction (the packaged
    catalog is a static file), so no scan budget is needed here -- unlike the
    citation channel's article_links scan (finding A2)."""
    from src.catalog.coverage import country_counts_from_session, coverage_report
    from src.ingest.seed_sources import load_sources_from_yaml

    known = _existing_domains(session) | (extra_known or set())
    counts = country_counts_from_session(session)
    report = coverage_report(counts, thin_threshold=thin_threshold)
    targets = set(report.get("thin", []) or []) | set(report.get("missing", []) or [])
    if not targets:
        return {"decisions": []}
    try:
        catalog = load_sources_from_yaml()  # the packaged configs/sources.yml
    except Exception:  # noqa: BLE001 - a catalog problem must not break a scrape
        _LOG.warning("could not load the packaged catalog for discovery", exc_info=True)
        return {"decisions": []}

    decisions: list[dict] = []
    for entry in catalog:
        if len(decisions) >= cap:
            break
        dom = str(entry.get("domain") or "").lower()
        country = str(entry.get("country") or "").lower()
        # `dom in known` also catches a domain ALREADY proposed earlier in THIS
        # batch (we add each decided domain to `known` below): the packaged
        # catalog can list the same domain more than once (e.g. several language
        # editions), and adding it twice violated the source_candidates.domain
        # UNIQUE constraint — which used to poison the whole scrape transaction
        # and silently roll back the articles just stored (field log 2026-06-18).
        if not dom or dom in known or country not in targets:
            continue
        n_there = counts.get(country, 0)  # computed once above, not re-queried per entry
        decisions.append(
            {
                "domain": dom,
                "name": entry.get("name"),
                "channel": "catalog",
                "evidence": {
                    "reason": "packaged-catalog entry for a country your corpus covers thinly",
                    "country": country,
                    "your_sources_there": n_there,
                    "thin_threshold": thin_threshold,
                },
            }
        )
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)
    return {"decisions": decisions}


def catalog_channel(
    session, *, cap: int, thin_threshold: int = 3, _decided: dict | None = None
) -> list[str]:
    """Suggest packaged-catalog entries for countries where coverage is thin.

    Compat entry point: decide (:func:`catalog_candidates`) + apply
    (:func:`_apply_candidate_decisions`) in one call when ``_decided`` is omitted --
    see :func:`citation_channel`'s docstring for the same shape and why it keeps
    every existing direct caller working unchanged."""
    result = (
        _decided if _decided is not None else catalog_candidates(session, cap=cap, thin_threshold=thin_threshold)
    )
    created, _disqualified = _apply_candidate_decisions(session, result["decisions"])
    return created


# --------------------------------------------------------------------------- #
# Channel (b): Wikipedia REFERENCES — the flagship, ZERO-NETWORK channel (Q3a).
# Parse the external references cited in the already-stored watched-page WIKITEXT
# (cite templates / <ref> / bare external links), across ALL editions. A citation
# graph over-represents established/Western sources, so the multi-edition harvest is
# a built-in de-biasing (fr.wikipedia cites French sources, etc.) but is NOT enough on
# its own — the diversity weighting in the promotion frontier is the enforcement.
# --------------------------------------------------------------------------- #
_WIKI_MIN_PAGES = 2  # a domain cited by >= this many DISTINCT watched pages becomes a candidate
_URL_RE = re.compile(r"""https?://[^\s\]|}<>"'()]+""", re.IGNORECASE)
# Wikimedia's own hosts are never a "discovered source" (self-reference / interwiki / asset host).
_WIKI_SELF = (
    "wikipedia.org", "wikimedia.org", "wikidata.org", "wiktionary.org", "wikisource.org",
    "wikivoyage.org", "wikibooks.org", "wikinews.org", "wikiquote.org", "wikiversity.org",
    "mediawiki.org", "wikimediafoundation.org", "wmflabs.org", "toolforge.org", "wmcloud.org",
    "dbpedia.org",
)
# Inline-image URLs are assets, not references — skip by extension (a .pdf CAN be a real report, so keep it).
_ASSET_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tiff")


def extract_reference_domains(wikitext: str | None) -> Counter:
    """Registrable domains of the EXTERNAL references cited in ``wikitext`` — PURE, zero-network.
    Finds every external http(s) URL (which in a wiki article are overwhelmingly citations: cite
    templates, ``<ref>`` tags, bare external links), takes its registrable domain, and EXCLUDES
    Wikimedia's own hosts, inline-image assets, and the commerce/social/infrastructure noise hosts
    (a footer/asset/interwiki link is not a source). Returns a ``Counter {domain: n_urls}``; a text
    with no external references (empty, or only ``[[internal]]`` links / Wikimedia hosts) returns an
    EMPTY counter — never a fabricated candidate."""
    from src.catalog.normalize import is_social, registrable_domain

    counts: Counter = Counter()
    if not wikitext:
        return counts
    for m in _URL_RE.finditer(wikitext):
        url = m.group(0).rstrip(".,;:!?")  # trailing sentence punctuation is not part of the URL
        low_url = url.lower()
        if any(low_url.split("?", 1)[0].endswith(ext) for ext in _ASSET_EXT):
            continue  # an inline image, not a reference
        dom = registrable_domain(url)
        if not dom:
            continue
        dl = dom.lower()
        if any(dl == w or dl.endswith("." + w) for w in _WIKI_SELF):
            continue
        if is_commerce_domain(dl) or is_social(dl) or is_infrastructure_domain(dl):
            continue
        counts[dl] += 1
    return counts


def wikipedia_reference_candidates(
    session, *, cap: int, min_pages: int = _WIKI_MIN_PAGES, extra_known: set[str] | None = None
) -> dict:
    """DECIDE phase for the Wikipedia-reference channel: PURE reads, streamed via
    ``yield_per`` (see ``citation_candidates`` for why that matters and is safe).
    Every watched page's wikitext is fully processed (``extract_reference_domains``)
    within this same read, before the caller ends the transaction -- nothing here
    lazy-loads afterward."""
    from src.database.models import WikiPage
    from src.wiki.corpus import _page_text

    known = _existing_domains(session) | (extra_known or set())
    by_domain_pages: dict[str, set[int]] = defaultdict(set)
    by_domain_editions: dict[str, set[str]] = defaultdict(set)
    q = session.query(WikiPage).filter(WikiPage.watched.is_(True))
    for page in q.yield_per(200):
        text, _revid = _page_text(page)
        if not text:
            continue
        for dom in extract_reference_domains(text):
            by_domain_pages[dom].add(page.id)
            by_domain_editions[dom].add(page.wiki)

    decisions: list[dict] = []
    # rank by breadth of citing pages (the independence proxy at the page level), then domain
    for dom, pageids in sorted(by_domain_pages.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(decisions) >= cap:
            break
        if len(pageids) < min_pages or dom in known:
            continue
        editions = sorted(by_domain_editions[dom])
        decisions.append(
            {
                "domain": dom,
                "name": None,
                "channel": "wikipedia",
                "evidence": {
                    "reason": "cited in the references of your watched Wikipedia pages",
                    "distinct_citing_pages": len(pageids),
                    "editions": editions,  # the multi-edition de-biasing signal (never a score)
                    "sample_page_ids": sorted(pageids)[:5],
                },
            }
        )
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)
    return {"decisions": decisions}


def wikipedia_reference_channel(
    session, *, cap: int, min_pages: int = _WIKI_MIN_PAGES, _decided: dict | None = None
) -> list[str]:
    """Discover source domains from the REFERENCES of the already-stored watched Wikipedia pages,
    across ALL editions (ZERO-NETWORK — reuses the compressed wikitext the tracker already holds).
    A domain cited by >= ``min_pages`` DISTINCT watched pages becomes a candidate (registered
    DISABLED via ``SourceCandidate``, channel ``wikipedia``); the citing editions ride in the
    evidence as the diversity signal. Never auto-scraped; promotion stays consented + audited.

    Compat entry point: decide (:func:`wikipedia_reference_candidates`) + apply
    (:func:`_apply_candidate_decisions`) in one call when ``_decided`` is omitted --
    see :func:`citation_channel`'s docstring for the same shape and why it keeps
    every existing direct caller working unchanged."""
    result = (
        _decided
        if _decided is not None
        else wikipedia_reference_candidates(session, cap=cap, min_pages=min_pages)
    )
    created, _disqualified = _apply_candidate_decisions(session, result["decisions"])
    return created


def noise_candidates_to_prune(session) -> list[int]:
    """DECIDE phase for the noise self-clean: PURE read, streamed via ``yield_per``.
    Returns the ids of already-staged PENDING candidates the noise filters now
    reject (commerce / social / infrastructure) -- plain ints, so nothing here can
    lazy-load once the caller ends the read transaction."""
    from src.catalog.normalize import is_social
    from src.database.models import SourceCandidate

    ids: list[int] = []
    q = session.query(SourceCandidate).filter(SourceCandidate.status == "candidate")
    for r in q.yield_per(500):
        dom = (r.domain or "").lower()
        if is_commerce_domain(dom) or is_social(dom) or is_infrastructure_domain(dom):
            ids.append(r.id)
    return ids


def prune_candidates_by_id(session, ids: list[int]) -> int:
    """APPLY phase: delete staged candidates by id. Must run with the write gate
    held when called from ``run_discovery`` (see its comment); a standalone caller
    may call it ungated exactly as ``prune_noise_candidates`` always could.

    Re-filters on ``status == 'candidate'`` at delete time (not just at decide
    time): a candidate promoted or dismissed in the gap between the decide read and
    this apply write must never be swept up by a stale id list -- "a promoted
    source or a REMEMBERED dismissal is never touched" (the original guarantee)
    still has to hold even though decide and apply are no longer one continuous
    transaction. Chunked under SQLite's 999-variable cap."""
    from src.database.models import SourceCandidate

    if not ids:
        return 0
    removed = 0
    for i in range(0, len(ids), 500):
        batch = ids[i : i + 500]
        removed += (
            session.query(SourceCandidate)
            .filter(SourceCandidate.id.in_(batch), SourceCandidate.status == "candidate")
            .delete(synchronize_session=False)
        )
    if removed:
        session.flush()
    return removed


def prune_noise_candidates(session, *, _decided_ids: list[int] | None = None) -> int:
    """Delete already-staged PENDING candidates the noise filters now reject (commerce /
    social / infrastructure). Discovery filtering is forward-only, so a candidate staged
    before a filter existed (e.g. fonts.googleapis.com/bsky.app before 2026-07-10) lingers
    in the list; this self-cleans it on the next discovery pass. Only ``status='candidate'``
    rows are removed — a promoted source or a REMEMBERED dismissal is never touched.

    Compat entry point: decide (:func:`noise_candidates_to_prune`) + apply
    (:func:`prune_candidates_by_id`) in one call when ``_decided_ids`` is omitted --
    see :func:`citation_channel`'s docstring for the same shape and why it keeps
    every existing direct caller working unchanged."""
    ids = _decided_ids if _decided_ids is not None else noise_candidates_to_prune(session)
    return prune_candidates_by_id(session, ids)


def _run_discovery_on_a_shared_session(session, *, per_run: int, third: int) -> dict:
    """FALLBACK shape, used only when the caller handed ``run_discovery`` a session
    that ALREADY had an open transaction (pending work from before this call) --
    the pre-A2 (S2.4) shape, unchanged: gate held from before the first read, one
    savepoint wrapping decide+apply for every channel.

    WHY THIS BRANCH EXISTS: the A2 perf fix below ends discovery's OWN read
    snapshot with ``session.rollback()`` before taking the write gate -- safe only
    when that snapshot is discovery's alone. If the session already carries
    uncommitted work from BEFORE this call (a caller sharing its own
    mid-transaction session -- exactly what
    ``tests/test_discovery_isolation.py`` drives directly, and what discovery's
    OWN docstring/comments describe as the pre-S2.4 shape: "on the SAME session as
    the scrape"), that rollback would discard the caller's work too, not just
    discovery's. This fallback never ends a snapshot it did not itself open, so it
    is safe on ANY session -- at the cost of not getting the A2 fix (the scan runs
    gated again) for that one call. Acceptable: a caller in this shape is, by
    construction, not the scheduler's long pass tail (S2.4 already gives that one
    its own fresh session via ``session_scope()``), so the 26-minute-scan-under-
    the-gate risk (finding A2) does not apply to it.
    """
    from src.database.writer import write_lock

    try:
        with write_lock(), session.begin_nested():
            pruned = prune_noise_candidates(session)
            cited = citation_channel(session, cap=third)
            remaining = per_run - len(cited)
            wiki = wikipedia_reference_channel(session, cap=max(1, remaining // 2)) if remaining > 0 else []
            remaining -= len(wiki)
            catalogd = catalog_channel(session, cap=remaining) if remaining > 0 else []
            session.flush()
    except Exception:  # noqa: BLE001 - discovery must never break the scrape
        _LOG.warning(
            "source discovery failed; rolled back its savepoint, the scrape is unaffected",
            exc_info=True,
        )
        return {"enabled": True, "budget": per_run, "created": 0, "error": "discovery_rolled_back"}
    return {
        "enabled": True,
        "budget": per_run,
        "created": len(cited) + len(wiki) + len(catalogd),
        "pruned_noise": pruned,
        "citation": cited,
        "wikipedia": wiki,
        "catalog": catalogd,
    }


def run_discovery(session, *, per_run: int = 10) -> dict:
    """Run the offline channels under the operator's budget. Returns the report
    that goes into the scheduler run log (the visible record of what happened).

    THE SHAPE (A2 fix, 2026-09-11): a DECIDE phase (pure reads, no gate, no
    savepoint) followed by an APPLY phase (mechanical inserts/deletes only, gated)
    -- ONLY on a session that is FRESH when this is called (see
    ``_run_discovery_on_a_shared_session`` for the fallback and why it exists).
    The field measurement that forced this: pass-tail phase `discovery` clocked
    1,590,907 ms (26.5 min), with a SAVEPOINT statement itself measured at 664,207
    ms -- gate wait recorded *inside* a single statement, because S2.4's fix (gate
    held from before the first read) serialised the whole citation-channel scan
    (citation_channel's ArticleLink.query(...).distinct().all() -- 1.3M+ pairs on
    the field corpus) behind the single-writer gate. S2.4 was a correct, narrow fix
    for SQLITE_BUSY_SNAPSHOT; it also made every OTHER writer in the process queue
    behind a 26-minute scan, draining the connection pool (finding A2).
    """
    if per_run <= 0:
        return {"enabled": False, "created": 0}

    from src.database.writer import write_lock

    third = max(1, per_run // 3)

    # `session.in_transaction()` is False on a session with nothing pending since
    # its last commit/rollback, and True the moment ANY statement -- including a
    # caller's own flush, made before this call -- has run. Only a FRESH session
    # makes the "end the read snapshot with a rollback" step below safe (that
    # snapshot is then provably ours alone, opened by our own first read); a
    # session that already has pending work needs the safe fallback instead. This
    # is the general form of the "run_discovery always gets its own short-lived
    # session" fact the fix relies on for the scheduler's real call site
    # (src/scheduler/runner.py's `with session_scope() as _disc_session:` hands
    # it a session on which nothing has run yet, so `in_transaction()` is False
    # there) -- checked here rather than merely assumed, because a direct caller
    # (a unit test, a script) is not obliged to give discovery a fresh session.
    if session.in_transaction():
        return _run_discovery_on_a_shared_session(session, per_run=per_run, third=third)

    # ----------------------------------------------------------------------- #
    # DECIDE phase: plain reads ONLY -- no write_lock, no begin_nested(). Every
    # *_candidates()/*_to_prune() helper returns plain Python values (dicts/lists
    # of primitives, never ORM objects), so nothing here can lazy-load once the
    # read transaction below is ended. `extra_known` threads each channel's
    # just-decided domains into the next channel's dedup set -- standing in for
    # the flush-based visibility the OLD single continuous transaction gave for
    # free (channel 1 flushed its inserts, so channel 2's `_existing_domains`
    # read saw them; here nothing is inserted until the APPLY phase below, so the
    # decide calls must be told explicitly).
    # ----------------------------------------------------------------------- #
    try:
        prune_ids = noise_candidates_to_prune(session)
        extra_known: set[str] = set()

        cite_result = citation_candidates(session, cap=third, extra_known=extra_known)
        extra_known |= {d["domain"] for d in cite_result["decisions"]}
        remaining = per_run - len(cite_result["decisions"])

        wiki_cap = max(1, remaining // 2)
        wiki_result = (
            wikipedia_reference_candidates(session, cap=wiki_cap, extra_known=extra_known)
            if remaining > 0
            else {"decisions": []}
        )
        extra_known |= {d["domain"] for d in wiki_result["decisions"]}
        remaining -= len(wiki_result["decisions"])

        catalog_cap = remaining
        catalog_result = (
            catalog_candidates(session, cap=catalog_cap, extra_known=extra_known)
            if remaining > 0
            else {"decisions": []}
        )
    except Exception:  # noqa: BLE001 - discovery must never break the scrape
        _LOG.warning(
            "source discovery failed during the read/decide phase; nothing was written",
            exc_info=True,
        )
        session.rollback()  # end whatever read transaction the failed scan left open
        return {"enabled": True, "budget": per_run, "created": 0, "error": "discovery_rolled_back"}

    # End the read transaction/snapshot BEFORE taking the write gate. This is SAFE
    # ONLY because run_discovery always gets its OWN short-lived session (S2.4,
    # src/scheduler/runner.py: `with session_scope() as _disc_session: run_discovery
    # (_disc_session, ...)`) -- never the pass's own session -- so there is no
    # caller's uncommitted work on `session` for this rollback to discard. Pinned by
    # tests/test_discovery_busy_snapshot.py::test_the_tail_ride_alongs_use_their_own_session.
    session.rollback()

    # ----------------------------------------------------------------------- #
    # APPLY phase: mechanical inserts/deletes only, GATED. Still wrapped in a
    # SAVEPOINT -- discovery is a best-effort post-scrape step; if it raises (e.g.
    # a UNIQUE collision on source_candidates.domain) the savepoint rolls back
    # ONLY discovery's own rows, leaving the outer transaction intact and
    # committable (field log 2026-06-18: before this guard, a discovery error
    # poisoned the whole session and no new articles were committed).
    #
    # WHY SQLITE_BUSY_SNAPSHOT CANNOT RECUR under this shape: the rollback above
    # means NO snapshot is held when this `with` block starts. `begin_nested()`
    # therefore opens a FRESH transaction -- taken WHILE the gate is already held.
    # SQLITE_BUSY_SNAPSHOT needs a read snapshot to be open BEFORE a write promotion
    # is attempted, with some OTHER commit landing in between; here there is no
    # "in between" -- the first read this transaction performs (if any, e.g. inside
    # `_add_candidate`'s disqualified check) and the eventual write both happen
    # after the gate is acquired, so no other writer's commit can land between
    # them (the gate serialises every in-process writer). This is the same
    # precondition S2.4 relied on ("gate held from before the first read");  the
    # difference is WHICH transaction is gated -- a fresh, short write transaction
    # instead of the one carrying the 26-minute scan.
    # ----------------------------------------------------------------------- #
    try:
        with write_lock(), session.begin_nested():
            pruned = prune_noise_candidates(session, _decided_ids=prune_ids)
            cited = citation_channel(session, cap=third, _decided=cite_result)
            wiki = wikipedia_reference_channel(session, cap=wiki_cap, _decided=wiki_result)
            catalogd = catalog_channel(session, cap=catalog_cap, _decided=catalog_result)
            session.flush()
    except Exception:  # noqa: BLE001 - discovery must never break the scrape
        _LOG.warning(
            "source discovery failed; rolled back its savepoint, the scrape is unaffected",
            exc_info=True,
        )
        return {"enabled": True, "budget": per_run, "created": 0, "error": "discovery_rolled_back"}

    report = {
        "enabled": True,
        "budget": per_run,
        "created": len(cited) + len(wiki) + len(catalogd),
        "pruned_noise": pruned,
        "citation": cited,
        "wikipedia": wiki,
        "catalog": catalogd,
    }
    # HONESTY (Part 2): if the citation scan was cut short by its wall-clock budget,
    # say so in the report a human/operator actually reads -- never let a floor
    # count travel silently as if it were the true total.
    if not cite_result["complete"]:
        report["citation_scan"] = {
            "complete": False,
            "rows_scanned": cite_result["rows_scanned"],
            "budget_s": cite_result["budget_s"],
            "reason": cite_result["reason"],
        }
    return report
