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


def _add_candidate(session, *, domain: str, name: str | None, channel: str, evidence: dict):
    from src.database.models import SourceCandidate

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


def citation_channel(session, *, cap: int, min_citations: int = _CITATION_MIN) -> list[str]:
    """Suggest external domains that >= min_citations distinct stored articles cite."""
    from src.catalog.normalize import is_social, registrable_domain
    from src.database.models import ArticleLink

    known = _existing_domains(session)
    pairs = session.query(ArticleLink.normalized_url, ArticleLink.article_id).distinct().all()
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs:
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom.lower()].add(aid)

    created: list[str] = []
    skipped = {"commerce": 0, "social": 0, "infrastructure": 0}
    for dom, ids in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        if len(created) >= cap:
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
        _add_candidate(
            session,
            domain=dom,
            name=None,
            channel="citation",
            evidence={
                "reason": "frequently cited by your stored articles",
                "distinct_citing_articles": len(ids),
                "sample_article_ids": sorted(ids)[:5],
            },
        )
        created.append(dom)
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    if any(skipped.values()):
        _LOG.debug(
            "citation discovery skipped commerce=%(commerce)d social=%(social)d "
            "infrastructure=%(infrastructure)d domain(s)",
            skipped,
        )
    return created


def catalog_channel(session, *, cap: int, thin_threshold: int = 3) -> list[str]:
    """Suggest packaged-catalog entries for countries where coverage is thin."""
    from src.catalog.coverage import country_counts_from_session, coverage_report
    from src.ingest.seed_sources import load_sources_from_yaml

    known = _existing_domains(session)
    report = coverage_report(
        country_counts_from_session(session), thin_threshold=thin_threshold
    )
    targets = set(report.get("thin", []) or []) | set(report.get("missing", []) or [])
    if not targets:
        return []
    try:
        catalog = load_sources_from_yaml()  # the packaged configs/sources.yml
    except Exception:  # noqa: BLE001 - a catalog problem must not break a scrape
        _LOG.warning("could not load the packaged catalog for discovery", exc_info=True)
        return []

    created: list[str] = []
    for entry in catalog:
        if len(created) >= cap:
            break
        dom = str(entry.get("domain") or "").lower()
        country = str(entry.get("country") or "").lower()
        # `dom in known` also catches a domain ALREADY proposed earlier in THIS
        # batch (we add each created domain to `known` below): the packaged
        # catalog can list the same domain more than once (e.g. several language
        # editions), and adding it twice violated the source_candidates.domain
        # UNIQUE constraint — which used to poison the whole scrape transaction
        # and silently roll back the articles just stored (field log 2026-06-18).
        if not dom or dom in known or country not in targets:
            continue
        n_there = country_counts_from_session(session).get(country, 0)
        _add_candidate(
            session,
            domain=dom,
            name=entry.get("name"),
            channel="catalog",
            evidence={
                "reason": "packaged-catalog entry for a country your corpus covers thinly",
                "country": country,
                "your_sources_there": n_there,
                "thin_threshold": thin_threshold,
            },
        )
        created.append(dom)
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
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


def wikipedia_reference_channel(session, *, cap: int, min_pages: int = _WIKI_MIN_PAGES) -> list[str]:
    """Discover source domains from the REFERENCES of the already-stored watched Wikipedia pages,
    across ALL editions (ZERO-NETWORK — reuses the compressed wikitext the tracker already holds).
    A domain cited by >= ``min_pages`` DISTINCT watched pages becomes a candidate (registered
    DISABLED via ``SourceCandidate``, channel ``wikipedia``); the citing editions ride in the
    evidence as the diversity signal. Never auto-scraped; promotion stays consented + audited."""
    from src.database.models import WikiPage
    from src.wiki.corpus import _page_text

    known = _existing_domains(session)
    by_domain_pages: dict[str, set[int]] = defaultdict(set)
    by_domain_editions: dict[str, set[str]] = defaultdict(set)
    for page in session.query(WikiPage).filter(WikiPage.watched.is_(True)):
        text, _revid = _page_text(page)
        if not text:
            continue
        for dom in extract_reference_domains(text):
            by_domain_pages[dom].add(page.id)
            by_domain_editions[dom].add(page.wiki)

    created: list[str] = []
    # rank by breadth of citing pages (the independence proxy at the page level), then domain
    for dom, pageids in sorted(by_domain_pages.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(created) >= cap:
            break
        if len(pageids) < min_pages or dom in known:
            continue
        editions = sorted(by_domain_editions[dom])
        _add_candidate(
            session,
            domain=dom,
            name=None,
            channel="wikipedia",
            evidence={
                "reason": "cited in the references of your watched Wikipedia pages",
                "distinct_citing_pages": len(pageids),
                "editions": editions,  # the multi-edition de-biasing signal (never a score)
                "sample_page_ids": sorted(pageids)[:5],
            },
        )
        created.append(dom)
        known.add(dom)  # never propose the same domain twice in one batch (UNIQUE guard)
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    return created


def prune_noise_candidates(session) -> int:
    """Delete already-staged PENDING candidates the noise filters now reject (commerce /
    social / infrastructure). Discovery filtering is forward-only, so a candidate staged
    before a filter existed (e.g. fonts.googleapis.com/bsky.app before 2026-07-10) lingers
    in the list; this self-cleans it on the next discovery pass. Only ``status='candidate'``
    rows are removed — a promoted source or a REMEMBERED dismissal is never touched."""
    from src.catalog.normalize import is_social
    from src.database.models import SourceCandidate

    removed = 0
    for r in session.query(SourceCandidate).filter(SourceCandidate.status == "candidate").all():
        dom = (r.domain or "").lower()
        if is_commerce_domain(dom) or is_social(dom) or is_infrastructure_domain(dom):
            session.delete(r)
            removed += 1
    if removed:
        session.flush()
    return removed


def run_discovery(session, *, per_run: int = 10) -> dict:
    """Run the offline channels under the operator's budget. Returns the report
    that goes into the scheduler run log (the visible record of what happened)."""
    if per_run <= 0:
        return {"enabled": False, "created": 0}
    # Run discovery inside a SAVEPOINT (nested transaction). Discovery is a
    # best-effort post-scrape step; if it raises (e.g. a UNIQUE collision on
    # source_candidates.domain) the savepoint rolls back ONLY discovery's own
    # rows, leaving the outer transaction — and the articles the scrape just
    # stored — intact and committable. Before this, any discovery error poisoned
    # the shared session, every pass was recorded ok:false, and NO new articles
    # were committed: "scraping stopped" (field log 2026-06-18). Data collection
    # must never be broken by this side feature.
    try:
        with session.begin_nested():
            pruned = prune_noise_candidates(session)  # self-clean earlier noise
            # three channels share the per-run budget: citations, Wikipedia references, catalog.
            third = max(1, per_run // 3)
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
