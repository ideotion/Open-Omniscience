"""Per-source discovery trail + qualified-citations tally (L5, 2026-07-21 build).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two read-only aggregations backing the Settings -> Sources provenance panel, per the
ruling recorded in CLAUDE.md 2026-07-20 (DISCOVERY PROVENANCE TRAIL / QUALIFIED-
CITATIONS TALLY):

- :func:`source_provenance` -- WHERE a source entered the catalogue: the discovery
  channel (a promoted :class:`SourceCandidate`, a catalog ``via:*`` tag, the ``cited``
  auto-integration channel, or ``ExternalSource.discovered_via``) plus, when the
  source was discovered because articles CITE it, the citing TRAIL -- the first
  citing article (earliest ``created_at`` among citers) and ITS source, so the user
  can check "the source's source". The trail always recomputes from ``article_links``
  (never trusts a cached example-id in evidence JSON), per the ruling's own wording.

- :func:`source_citation_tally` -- for a source's OWN articles, how many of the
  domains they cite are qualified / disqualified / pending (registered but not yet
  qualified) vs never entered the qualification funnel at all (commerce/social/
  infrastructure-filtered, tallied SEPARATELY so the ratio is not diluted by
  legitimately-non-article links). Per-class DOMAIN LISTS are returned (not just
  counts) so each class is a clickable drill, in both directions (this source's
  citations, but the SAME shape also answers "which qualified sources has X cited" --
  no separate reciprocal endpoint, per the ruling).

DESCRIPTIVE ONLY, no interpretation: disqualification is an extraction-validity fact,
never editorial badness; citing many qualified domains is not an endorsement (wire
services get cited by everyone; a laundering hub can cite reputable sources on
purpose). No score/rating/grade/ranking key anywhere in these payloads.
"""

from __future__ import annotations

import json
import logging

_LOG = logging.getLogger(__name__)

# Descriptive-only: citing a disqualified domain is not guilt, and citing many
# qualified domains is not an endorsement. Carried on every tally payload (the
# maintainer's own framing: "not interpretation, just a ratio").
TALLY_CAVEAT = (
    "Descriptive only, not a judgement: disqualified means the domain failed "
    "extraction validity (not a content source), never editorial badness -- citing "
    "a disqualified domain is not guilt. Citing many qualified domains is likewise "
    "not an endorsement or quality signal (wire services get cited by everyone; a "
    "laundering hub can cite reputable sources deliberately)."
)

NO_PROVENANCE_DETAIL = (
    "No recorded discovery provenance -- likely catalog-seeded before provenance "
    "tracking (or a manually-added source)."
)


def _first_citing_article(session, domain: str) -> dict | None:
    """Earliest article whose external link resolves (alias-aware) to ``domain``,
    plus that article's own source -- the "source's source" click-through. A column-
    projected scan over ``article_links`` (never a row/codec touch), same perf
    convention as :func:`src.discovery.cited_sources.cited_domain_stats`. Returns
    ``None`` when nothing cites this domain.
    """
    from src.catalog.normalize import registrable_domain
    from src.database.models import Article, ArticleLink, Source
    from src.utils.url_utils import is_equivalent_domain

    dom = domain.lower()
    rows = (
        session.query(ArticleLink.normalized_url, ArticleLink.article_id)
        .filter(ArticleLink.link_type == "external")
        .all()
    )
    matching_ids: set[int] = set()
    for nu, aid in rows:
        d = registrable_domain(nu)
        if d and is_equivalent_domain(d.lower(), dom):
            matching_ids.add(aid)
    if not matching_ids:
        return None

    first = (
        session.query(Article.id, Article.created_at, Article.source_id, Article.title)
        .filter(Article.id.in_(matching_ids))
        .order_by(Article.created_at.asc())
        .first()
    )
    if first is None:
        return None
    article_id, created_at, citer_source_id, title = first
    citer = session.query(Source.id, Source.name, Source.domain).filter_by(id=citer_source_id).first()
    return {
        "article_id": article_id,
        "article_title": title,
        "created_at": created_at.isoformat() if created_at else None,
        "citing_source_id": citer[0] if citer else None,
        "citing_source_name": citer[1] if citer else None,
        "citing_source_domain": citer[2] if citer else None,
        "distinct_citing_articles": len(matching_ids),
    }


def source_provenance(session, source_id: int) -> dict:
    """WHERE a source was first discovered, channel-appropriate.

    Returns ``{"found": False}`` for an unknown id. Otherwise:
    ``channel`` (the discovery channel, or ``None`` if never recorded), ``evidence``
    (the channel's own reasoning, when a :class:`SourceCandidate` recorded one),
    ``first_seen``, ``detail`` (a human sentence), ``citing_trail`` (see
    :func:`_first_citing_article`; ``None`` when nothing cites this domain), and
    ``qualification_status`` (L1's ``Source.status`` -- surfaced here too since a
    provenance panel is exactly where "is this admitted yet" belongs).
    """
    from src.database.models import ExternalSource, Source, SourceCandidate

    source = session.query(Source).filter_by(id=source_id).first()
    if source is None:
        return {"found": False}

    dom = (source.domain or "").lower() or None
    channel: str | None = None
    evidence: dict = {}
    first_seen = None
    detail = NO_PROVENANCE_DETAIL

    candidate = session.query(SourceCandidate).filter_by(domain=dom).first() if dom else None
    if candidate is not None:
        channel = candidate.channel
        evidence = json.loads(candidate.evidence) if candidate.evidence else {}
        first_seen = candidate.first_seen
        detail = f"Discovered via the '{candidate.channel}' channel (promoted from a candidate)."
    else:
        tags = [t.strip() for t in (source.tags or "").split(",") if t.strip()]
        via_tag = next((t for t in tags if t.startswith("via:")), None)
        if via_tag:
            channel = via_tag.split(":", 1)[1] or None
            detail = f"Catalog-seeded, tagged '{via_tag}'."
        elif source.source_type == "cited":
            channel = "cited"
            detail = "Auto-registered because enough distinct sources cite this domain."
        else:
            ext = session.query(ExternalSource).filter_by(domain=dom).first() if dom else None
            if ext is not None and ext.discovered_via:
                channel = ext.discovered_via
                detail = f"External-source registry records discovered_via='{ext.discovered_via}'."

    citing_trail = _first_citing_article(session, dom) if dom else None

    return {
        "found": True,
        "source_id": source.id,
        "domain": source.domain,
        "channel": channel,
        "evidence": evidence,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "detail": detail,
        "citing_trail": citing_trail,
        "qualification_status": source.status,
    }


def source_citation_tally(session, source_id: int) -> dict:
    """This source's OWN articles: how many distinct cited domains are qualified /
    disqualified / pending, vs never entering the funnel (commerce/social/
    infrastructure-filtered, tallied separately so the ratio stays meaningful).

    Matching is an EXACT registrable-domain match against the ``sources`` table
    (deliberately conservative -- no alias heuristic here, unlike the citing-trail
    lookup above, since a false alias match would misclassify a domain's
    qualification bucket). Each class is returned as a DOMAIN LIST (clickable
    drills, both directions: "domains this source cites" IS "which qualified
    sources this source has mentioned" -- one shape answers both, per the ruling).
    """
    from src.catalog.normalize import is_social, registrable_domain
    from src.database.models import Article, ArticleLink, Source
    from src.discovery.channels import is_commerce_domain, is_infrastructure_domain

    # Domains are returned as dicts everywhere (never a bare string) so EVERY class
    # carries "sample_article_ids" -- the reciprocal drill's "citing articles" link
    # (the ruling: each row links to that source's own management row AND to the
    # citing articles) applies uniformly, not only to domains that matched a Source.
    _ARTICLE_SAMPLE_CAP = 10

    source = session.query(Source).filter_by(id=source_id).first()
    if source is None:
        return {"found": False}

    empty = {
        "found": True,
        "source_id": source_id,
        "domain": source.domain,
        "qualified": [],
        "disqualified": [],
        "pending": [],
        "never_registered": [],
        "filtered": {"commerce": [], "social": [], "infrastructure": []},
        "counts": {
            "qualified": 0, "disqualified": 0, "pending": 0, "never_registered": 0,
            "filtered_commerce": 0, "filtered_social": 0, "filtered_infrastructure": 0,
        },
        "caveat": TALLY_CAVEAT,
    }

    article_ids = [aid for (aid,) in session.query(Article.id).filter(Article.source_id == source_id)]
    if not article_ids:
        return empty

    rows = (
        session.query(ArticleLink.normalized_url, ArticleLink.article_id)
        .filter(ArticleLink.article_id.in_(article_ids), ArticleLink.link_type == "external")
    )
    domain_articles: dict[str, set[int]] = {}
    for nu, aid in rows:
        d = registrable_domain(nu)
        if d:
            domain_articles.setdefault(d.lower(), set()).add(aid)
    domain_articles.pop((source.domain or "").lower(), None)  # self-links are not citations
    if not domain_articles:
        return empty

    by_domain: dict[str, tuple[int, str, str]] = {}
    for sid, name, sdom, status in session.query(Source.id, Source.name, Source.domain, Source.status).all():
        if sdom:
            by_domain[sdom.lower()] = (sid, name, status)

    qualified: list[dict] = []
    disqualified: list[dict] = []
    pending: list[dict] = []
    never_registered: list[dict] = []
    filtered: dict[str, list[dict]] = {"commerce": [], "social": [], "infrastructure": []}

    for d in sorted(domain_articles):
        sample_ids = sorted(domain_articles[d])[:_ARTICLE_SAMPLE_CAP]
        match = by_domain.get(d)
        if match is not None:
            sid, name, status = match
            entry = {"domain": d, "source_id": sid, "name": name, "sample_article_ids": sample_ids}
            if status == "qualified":
                qualified.append(entry)
            elif status == "disqualified":
                disqualified.append(entry)
            else:  # "unqualified" (the only other lifecycle value) -> pending review
                pending.append(entry)
            continue
        entry = {"domain": d, "sample_article_ids": sample_ids}
        if is_commerce_domain(d):
            filtered["commerce"].append(entry)
        elif is_social(d):
            filtered["social"].append(entry)
        elif is_infrastructure_domain(d):
            filtered["infrastructure"].append(entry)
        else:
            never_registered.append(entry)

    return {
        "found": True,
        "source_id": source_id,
        "domain": source.domain,
        "qualified": qualified,
        "disqualified": disqualified,
        "pending": pending,
        "never_registered": never_registered,
        "filtered": filtered,
        "counts": {
            "qualified": len(qualified),
            "disqualified": len(disqualified),
            "pending": len(pending),
            "never_registered": len(never_registered),
            "filtered_commerce": len(filtered["commerce"]),
            "filtered_social": len(filtered["social"]),
            "filtered_infrastructure": len(filtered["infrastructure"]),
        },
        "caveat": TALLY_CAVEAT,
    }
