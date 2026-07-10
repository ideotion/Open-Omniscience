"""
Auto-integrate in-article SECONDARY sources (cited domains) as new sources.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An article's outbound links ARE its secondary sources. This promotes a domain that
enough of the corpus cites into a new, DISABLED source tagged with the ``cited``
provenance class (see src/catalog/provenance.py). Design rulings (2026-07-01):

- INDEPENDENCE is measured by DISTINCT CITING SOURCES, never article count -- a single
  chatty source citing a domain in 20 articles is ONE independent citer, not 20 (the
  same anti-false-triangulation principle as the source-laundering card). This is the
  key difference from the older ``citation_channel`` (which counts distinct articles
  and emits review CANDIDATES); that channel stays as-is.
- NEVER auto-scraped: a promoted source is created ``enabled=False``. Registration is
  metadata-only (zero network); ENABLING it to fetch stays the user's consented choice.
- The ``cited`` label is a DESCRIPTIVE channel, never a quality/credibility score (no
  ``reliability_score`` is set) -- a widely-cited primary source and a laundering hub
  look identical here; the user judges. The citing TRAIL (who cited it) is derivable
  from ``article_links`` on demand, so no new table is needed.
- Commerce/social storefronts are excluded (reuses the discovery filters); dedup against
  existing sources is ALIAS-AWARE (bbc.com == bbc.co.uk) so a known outlet is never
  re-created under a sibling domain.

PERF: the citing-source map is a COVERING index-only scan of ``articles(source_id)``
(``idx_article_source_id`` stores ``(source_id, rowid=id)``), so it never drags the
encrypted article rows through the codec (the column-order decrypt trap). The link scan
touches only ``article_links``. Bounded + intended as a user-triggered maintenance pass;
a very large corpus should run it as a background job (a future slice).
"""

from __future__ import annotations

import logging
import os

_LOG = logging.getLogger(__name__)

# A domain must be cited by at least this many DISTINCT sources to be promoted. 2 =
# "more than one independent outlet points here" -- conservative, avoids flooding the
# source list with one-off references. Override with OO_CITED_MIN_SOURCES.
_DEFAULT_MIN_SOURCES = 2
# Cap per pass so one run can never register an unbounded number of sources.
_DEFAULT_CAP = 200


def _min_sources() -> int:
    try:
        return max(1, int(os.environ.get("OO_CITED_MIN_SOURCES", _DEFAULT_MIN_SOURCES)))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_SOURCES


def cited_domain_stats(session) -> dict[str, dict]:
    """Per externally-cited registrable domain: the distinct citing SOURCES + ARTICLES.

    Returns ``{domain: {"sources": set[int], "articles": set[int]}}``. Independence is
    the size of ``sources`` (distinct outlets), never ``articles``.
    """
    from src.catalog.normalize import registrable_domain
    from src.database.models import Article, ArticleLink

    # article_id -> source_id, via the covering source_id index (no row decrypt).
    art_source: dict[int, int] = dict(session.query(Article.id, Article.source_id))

    by_sources: dict[str, set[int]] = {}
    by_articles: dict[str, set[int]] = {}
    # Only EXTERNAL links are secondary sources (internal links resolve to the citing
    # article's own domain -> deduped anyway; images/scripts are not citations).
    q = session.query(ArticleLink.normalized_url, ArticleLink.article_id).filter(
        ArticleLink.link_type == "external"
    )
    for nu, aid in q:
        dom = registrable_domain(nu)
        if not dom:
            continue
        dom = dom.lower()
        by_articles.setdefault(dom, set()).add(aid)
        sid = art_source.get(aid)
        if sid is not None:
            by_sources.setdefault(dom, set()).add(sid)

    return {
        dom: {"sources": by_sources.get(dom, set()), "articles": arts}
        for dom, arts in by_articles.items()
    }


def promote_cited_sources(
    session, *, min_source_citers: int | None = None, cap: int = _DEFAULT_CAP, dry_run: bool = False
) -> dict:
    """Register domains cited by >= ``min_source_citers`` DISTINCT sources as DISABLED
    ``cited`` sources. Idempotent, commerce/social-filtered, alias-deduped, never scraped.

    ``dry_run=True`` reports the candidates without creating anything (the preview the UI
    uses). Returns ``{"created": [...], "candidates": [...], "skipped": {...}, ...}``.
    """
    from src.catalog.normalize import is_social
    from src.catalog.provenance import CITED
    from src.database.models import Source
    from src.discovery.channels import is_commerce_domain, is_infrastructure_domain
    from src.utils.url_utils import is_equivalent_domain

    threshold = _min_sources() if min_source_citers is None else max(1, min_source_citers)

    # Existing source domains for ALIAS-AWARE dedup (never re-create a known outlet).
    existing = [d.lower() for (d,) in session.query(Source.domain) if d]
    existing_set = set(existing)

    stats = cited_domain_stats(session)
    created: list[dict] = []
    candidates: list[dict] = []
    skipped = {"below_gate": 0, "commerce": 0, "social": 0, "infrastructure": 0, "already_a_source": 0}

    # Most-cited (by distinct sources) first, so a capped run keeps the strongest.
    for dom, s in sorted(stats.items(), key=lambda kv: -len(kv[1]["sources"])):
        n_sources = len(s["sources"])
        if n_sources < threshold:
            skipped["below_gate"] += 1
            continue
        if is_commerce_domain(dom):
            skipped["commerce"] += 1
            continue
        if is_social(dom):
            skipped["social"] += 1
            continue
        if is_infrastructure_domain(dom):  # CDN / analytics / boilerplate-legal (field 2026-07-10)
            skipped["infrastructure"] += 1
            continue
        if dom in existing_set or any(is_equivalent_domain(dom, e) for e in existing):
            skipped["already_a_source"] += 1
            continue
        if len(created) >= cap:
            break

        entry = {
            "domain": dom,
            "source_citers": n_sources,
            "article_citers": len(s["articles"]),
        }
        candidates.append(entry)
        if not dry_run:
            session.add(
                Source(
                    name=dom,
                    domain=dom,
                    enabled=False,  # metadata only; enabling to fetch stays consented
                    source_type=CITED,  # the descriptive provenance class (never a score)
                    tags="cited",
                    reliability_score=None,  # NEVER a fabricated score
                )
            )
            created.append(entry)
        existing_set.add(dom)  # never register the same domain twice in one pass

    if created and not dry_run:
        session.flush()  # autoflush is off app-wide; make the new rows visible to callers

    return {
        "created": created,
        "candidates": candidates,
        "skipped": skipped,
        "min_source_citers": threshold,
        "dry_run": dry_run,
    }
