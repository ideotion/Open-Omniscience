"""Offline discovery channels (see package docstring). DB-only by contract."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
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


def _existing_domains(session) -> set[str]:
    from src.database.models import Source, SourceCandidate

    src = {d.lower() for (d,) in session.query(Source.domain).all() if d}
    cand = {d.lower() for (d,) in session.query(SourceCandidate.domain).all() if d}
    return src | cand


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


def citation_channel(session, *, cap: int, min_citations: int = _CITATION_MIN) -> list[str]:
    """Suggest external domains that >= min_citations distinct stored articles cite."""
    from src.catalog.normalize import registrable_domain
    from src.database.models import ArticleLink

    known = _existing_domains(session)
    pairs = session.query(ArticleLink.normalized_url, ArticleLink.article_id).distinct().all()
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs:
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom.lower()].add(aid)

    created: list[str] = []
    skipped_commerce = 0
    for dom, ids in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        if len(created) >= cap:
            break
        if len(ids) < min_citations or dom in known:
            continue
        if is_commerce_domain(dom):
            # A storefront/merch domain frequently cited by articles is still not
            # a journalism source — never suggest it (field log 2026-06-13).
            skipped_commerce += 1
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
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    if skipped_commerce:
        _LOG.debug("citation discovery skipped %d commerce/storefront domain(s)", skipped_commerce)
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
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    return created


def run_discovery(session, *, per_run: int = 10) -> dict:
    """Run the offline channels under the operator's budget. Returns the report
    that goes into the scheduler run log (the visible record of what happened)."""
    if per_run <= 0:
        return {"enabled": False, "created": 0}
    half = max(1, per_run // 2)
    cited = citation_channel(session, cap=half)
    remaining = per_run - len(cited)
    catalogd = catalog_channel(session, cap=remaining) if remaining > 0 else []
    session.flush()
    return {
        "enabled": True,
        "budget": per_run,
        "created": len(cited) + len(catalogd),
        "citation": cited,
        "catalog": catalogd,
    }
