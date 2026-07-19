"""Source-laundering detection (manipulation-pattern card #6, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent or truth (the manipulation-card doctrine): when many
articles from MANY DISTINCT SOURCES all cite the SAME single external origin, the
apparent independent corroboration is an illusion — they are one source wearing many
hats (the anti-false-triangulation rule, surfaced proactively as a Home Lead). This is
the citation-graph sibling of the convergence/echo signals: it reads ``article_links``,
not text.

HONESTY (enforced in code, not just prose):
  * the independence measure is DISTINCT SOURCES, not article count (a chatty single
    source re-citing one URL can never trip it);
  * the surfacing gate is ``>= min_sources`` AND ``>= min_articles``;
  * social / platform / storefront origins are excluded (everyone links those for
    reasons that are not corroboration — they would only manufacture false positives);
  * NO score, NO verdict — the card carries the real counts + the exact article set and
    states the INNOCENT explanation beside the pattern (a widely-cited primary source —
    a study, a filing, a wire report — looks identical; the shape is "corroboration that
    is not independent", never a claim of manipulation).
"""

from __future__ import annotations

from sqlalchemy import func

from src.catalog.normalize import is_social, registrable_domain
from src.discovery.channels import is_commerce_domain, is_infrastructure_domain

LAUNDERING_CAVEAT = (
    "Several sources citing the same single origin are NOT independent corroboration — "
    "one source wearing many hats. That origin may be a perfectly legitimate primary "
    "source everyone cites (a study, a filing, a wire), OR a single-origin claim dressed "
    "as consensus. The shape is what's flagged, never intent — read the origin yourself."
)


def _noise_origin(url: str | None) -> bool:
    """True for an origin everyone links for non-corroboration reasons (social/store/
    infrastructure — CDNs, cookie/privacy-policy pages, share widgets, license footers)."""
    dom = registrable_domain(url)
    if not dom:
        return True  # unparseable -> not a usable origin
    return is_social(dom) or is_commerce_domain(dom) or is_infrastructure_domain(dom)


def find_source_laundering(
    session,
    *,
    min_sources: int = 3,
    min_articles: int = 3,
    days: int | None = None,
    limit: int = 12,
) -> dict:
    """Origins cited by many DISTINCT sources — apparent corroboration that isn't.

    Groups ``article_links`` by ``normalized_url``, counts distinct citing ARTICLES and
    distinct citing SOURCES, keeps those over both gates, drops social/commerce noise,
    and returns the clusters newest-spread first with their exact article set. Read-only;
    counts only; no score.
    """
    from src.database.models import Article, ArticleLink, Source

    arts = func.count(func.distinct(ArticleLink.article_id))
    srcs = func.count(func.distinct(Article.source_id))
    q = (
        session.query(ArticleLink.normalized_url, arts.label("arts"), srcs.label("srcs"))
        .join(Article, Article.id == ArticleLink.article_id)
        .filter(ArticleLink.normalized_url.isnot(None))
    )
    if days and days > 0:
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(tzinfo=None)
        q = q.filter(Article.published_at >= cutoff)
    rows = (
        q.group_by(ArticleLink.normalized_url)
        .having(srcs >= min_sources)
        .having(arts >= min_articles)
        .order_by(srcs.desc(), arts.desc())
        .all()
    )

    clusters = []
    seen_domains: set[str] = set()
    for url, n_arts, n_srcs in rows:
        if _noise_origin(url):
            continue
        dom = registrable_domain(url)
        if dom is None or dom in seen_domains:
            # One card per registrable origin domain (row 2) — rows are already ordered
            # srcs desc, arts desc, so the first occurrence is the strongest cluster for
            # this domain; a second URL path on the same domain is not a distinct origin.
            continue
        seen_domains.add(dom)
        # The exact citing articles + the distinct source names (provenance the card shows).
        members = (
            session.query(Article.id, Source.name)
            .join(ArticleLink, ArticleLink.article_id == Article.id)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(ArticleLink.normalized_url == url)
            .all()
        )
        article_ids = sorted({m[0] for m in members})
        source_names = sorted({m[1] for m in members if m[1]})
        clusters.append({
            "origin": url,
            "origin_domain": registrable_domain(url),
            "n_articles": int(n_arts),
            "distinct_sources": int(n_srcs),
            "source_names": source_names[:12],
            "article_ids": article_ids,
        })
        if len(clusters) >= limit:
            break

    return {
        "clusters": clusters,
        "count": len(clusters),
        "min_sources": min_sources,
        "min_articles": min_articles,
        "method": (
            "Outbound origins cited by >= {ms} distinct sources (and >= {ma} articles); "
            "social/storefront/infrastructure origins excluded (CDNs, cookie/privacy-policy "
            "pages, share widgets, license footers); at most one card per registrable origin "
            "domain. Independence = distinct sources, not article count.".format(
                ms=min_sources, ma=min_articles
            )
        ),
        "caveat": LAUNDERING_CAVEAT,
    }
