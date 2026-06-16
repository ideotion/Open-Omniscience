"""
Read-only link / co-citation analysis over ``article_links``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest aggregation only — counts of who cites what, nothing scored or judged. This
answers "which articles cite the same source" and "what links are most-cited"
(see docs/DESIGN.md). It is NOT the quarantined, fabricated
"credibility/relationship" link analyzer (see docs/HISTORY.md); it surfaces
structure for the user, who decides.

Outbound external links are populated on ingest (see
``src/ingest/pipeline.py:_maybe_index_links``). Empty until articles with links
are ingested.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.catalog.normalize import registrable_domain
from src.database.models import Article, ArticleLink, Source
from src.database.session import get_db

router = APIRouter(prefix="/api/links", tags=["links"])


def _cutoff(days: int | None) -> datetime | None:
    return datetime.now(UTC) - timedelta(days=days) if days else None


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """Corpus-wide link totals (all real COUNT(*) — nothing estimated)."""
    return {
        "external_links": db.query(func.count(ArticleLink.id)).scalar() or 0,
        "distinct_links": db.query(func.count(func.distinct(ArticleLink.normalized_url))).scalar()
        or 0,
        "articles_with_links": db.query(func.count(func.distinct(ArticleLink.article_id))).scalar()
        or 0,
    }


@router.get("/top-cited")
def top_cited(
    by: str = Query("url", pattern="^(url|domain)$"),
    window_days: int | None = Query(None, ge=1, le=3650),
    min_citations: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Most-cited external links (``by=url``) or domains (``by=domain``).

    "Citations" = number of *distinct articles* in the corpus that link to it — a
    citation-graph trend signal grounded in what reporters actually reference.
    """
    cutoff = _cutoff(window_days)

    if by == "url":
        q = db.query(
            ArticleLink.normalized_url.label("nu"),
            func.count(func.distinct(ArticleLink.article_id)).label("citations"),
            func.max(ArticleLink.url).label("sample_url"),
            func.max(ArticleLink.link_text).label("sample_text"),
        )
        if cutoff is not None:
            q = q.join(Article, ArticleLink.article_id == Article.id).filter(
                func.coalesce(Article.published_at, Article.created_at) >= cutoff
            )
        q = (
            q.group_by(ArticleLink.normalized_url)
            .having(func.count(func.distinct(ArticleLink.article_id)) >= min_citations)
            .order_by(desc("citations"))
            .limit(limit)
        )
        items = [
            {
                "normalized_url": r.nu,
                "sample_url": r.sample_url,
                "link_text": r.sample_text,
                "domain": registrable_domain(r.nu),
                "citations": r.citations,
            }
            for r in q.all()
        ]
        return {"by": "url", "window_days": window_days, "items": items}

    # by == "domain": parse the registrable domain in Python (portable across SQLite).
    pairs = db.query(ArticleLink.normalized_url, ArticleLink.article_id)
    if cutoff is not None:
        pairs = pairs.join(Article, ArticleLink.article_id == Article.id).filter(
            func.coalesce(Article.published_at, Article.created_at) >= cutoff
        )
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs.distinct().all():
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom].add(aid)
    items = sorted(
        (
            {"domain": d, "citations": len(ids)}
            for d, ids in by_domain.items()
            if len(ids) >= min_citations
        ),
        key=lambda x: -x["citations"],
    )[:limit]
    return {"by": "domain", "window_days": window_days, "items": items}


@router.get("/corpus")
def corpus_links(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    min_citations: int = Query(2, ge=1, le=100),
    limit: int = Query(40, ge=1, le=200),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Outbound links SHARED across the analysis corpus (an explicit article-id set or
    the search) — the Links tab. Surfaces shared-ORIGIN structure: a URL cited by
    several of the articles. Convergence corroborates ONLY when the paths are
    independent -- several articles citing the SAME origin are one source wearing
    several hats, NOT independent confirmation. Counts only; bounded to ``cap``
    (disclosed via ``total_matched``/``capped``)."""
    from src.api.insights import _resolve_corpus

    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    items: list[dict] = []
    if ids:
        cit = func.count(func.distinct(ArticleLink.article_id))
        rows = (
            db.query(
                ArticleLink.normalized_url.label("nu"),
                cit.label("citations"),
                func.max(ArticleLink.url).label("sample_url"),
                func.max(ArticleLink.link_text).label("sample_text"),
            )
            .filter(ArticleLink.article_id.in_(ids))
            .group_by(ArticleLink.normalized_url)
            .having(cit >= min_citations)
            .order_by(desc("citations"))
            .limit(limit)
            .all()
        )
        items = [
            {
                "normalized_url": r.nu,
                "sample_url": r.sample_url,
                "link_text": r.sample_text,
                "domain": registrable_domain(r.nu),
                "citations": int(r.citations),
            }
            for r in rows
        ]
    return {
        "n_articles": len(ids),
        "total_matched": total,
        "capped": total > len(ids),
        "min_citations": min_citations,
        "items": items,
        "method": (
            "Outbound URLs cited by at least min_citations of the matched articles "
            "(distinct-article counts)."
        ),
        "caveat": (
            "Shared-origin structure, counts only. Several articles citing the SAME "
            "link are not independent confirmation -- one origin, several echoes."
        ),
    }


@router.get("/articles-by-link")
def articles_by_link(
    url: str | None = Query(None, description="a cited link (raw or normalized)"),
    domain: str | None = Query(None, description="a cited domain, e.g. reuters.com"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Every article in the corpus that cites a given link (or domain).

    This is "assemble all articles talking about the same link" — the basis for
    spotting echo and tracing toward an original source. The user reads and judges.
    """
    if not url and not domain:
        raise HTTPException(status_code=400, detail="Provide ?url= or ?domain=")

    if url:
        try:
            from src.services.link_analyzer import LinkExtractor

            norm = LinkExtractor().normalize_url(url)
        except Exception:  # noqa: BLE001 - normalisation is best-effort
            norm = url
        match = {"url": url, "normalized_url": norm}
        ids = [
            a
            for (a,) in db.query(ArticleLink.article_id)
            .filter(
                (ArticleLink.normalized_url == norm)
                | (ArticleLink.normalized_url == url)
                | (ArticleLink.url == url)
            )
            .distinct()
            .all()
        ]
    else:
        dom = domain.strip().lower()
        match = {"domain": dom}
        # LIKE pre-filter, then exact registrable-domain check (avoids false hits).
        ids = sorted(
            {
                aid
                for (aid, nu) in db.query(ArticleLink.article_id, ArticleLink.normalized_url)
                .filter(ArticleLink.normalized_url.like(f"%{dom}%"))
                .all()
                if registrable_domain(nu) == dom
            }
        )

    total = len(ids)
    articles = []
    if ids:
        rows = (
            db.query(Article, Source.name)
            .outerjoin(Source, Article.source_id == Source.id)
            .filter(Article.id.in_(ids[:limit]))
            .order_by(desc(func.coalesce(Article.published_at, Article.created_at)))
            .all()
        )
        for art, source_name in rows:
            articles.append(
                {
                    "id": art.id,
                    "title": art.title,
                    "url": art.url,
                    "source": source_name,
                    "language": art.language,
                    "published_at": art.published_at.isoformat() if art.published_at else None,
                }
            )
    return {"match": match, "count": total, "articles": articles}


# --------------------------------------------------------------------------- #
#  Provenance-preserving graph export (0.0.8 part 2, WP2 / RM-15)
# --------------------------------------------------------------------------- #

_GRAPH_CAVEAT = (
    "Who-cites-whom citation graph: edges are real link counts from stored articles "
    "to external registrable domains. Counts only; no inferred credibility, no scores."
)


def _citation_graph(db, *, min_citations: int = 1, max_nodes: int = 2000) -> dict:
    """Build the article->domain citation graph from stored links (counts only)."""
    pairs = db.query(ArticleLink.normalized_url, ArticleLink.article_id).distinct().all()
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs:
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom].add(aid)
    domains = {d: ids for d, ids in by_domain.items() if len(ids) >= min_citations}
    # bound the export: keep the most-cited domains first
    keep = sorted(domains, key=lambda d: -len(domains[d]))[:max_nodes]
    article_ids = sorted({aid for d in keep for aid in domains[d]})[:max_nodes]
    kept_articles = set(article_ids)
    titles = dict(
        db.query(Article.id, Article.title).filter(Article.id.in_(article_ids)).all()
    )
    nodes = [{"id": f"d:{d}", "kind": "domain", "label": d} for d in keep] + [
        {"id": f"a:{aid}", "kind": "article", "label": titles.get(aid) or f"article {aid}"}
        for aid in article_ids
    ]
    edges = [
        {"source": f"a:{aid}", "target": f"d:{d}"}
        for d in keep
        for aid in sorted(domains[d])
        if aid in kept_articles
    ]
    return {"caveat": _GRAPH_CAVEAT, "nodes": nodes, "edges": edges}


@router.get("/export.json")
def export_graph_json(
    min_citations: int = Query(1, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    """The citation graph as JSON, wrapped in the versioned export envelope."""
    from src.utils.export_envelope import envelope

    g = _citation_graph(db, min_citations=min_citations)
    return envelope(
        kind="citation-graph",
        query={"min_citations": min_citations},
        count=len(g["edges"]),
        payload=g,
    )


@router.get("/export.graphml")
def export_graph_graphml(
    min_citations: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """The citation graph as GraphML (stdlib XML; opens in Gephi/yEd/NetworkX)."""
    import xml.etree.ElementTree as ET

    from fastapi.responses import Response

    g = _citation_graph(db, min_citations=min_citations)
    NS = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}graphml")
    root.append(ET.Comment(f" {_GRAPH_CAVEAT} "))
    for key_id, attr in (("label", "label"), ("kind", "kind")):
        k = ET.SubElement(root, f"{{{NS}}}key", id=key_id)
        k.set("for", "node")
        k.set("attr.name", attr)
        k.set("attr.type", "string")
    graph = ET.SubElement(root, f"{{{NS}}}graph", edgedefault="directed")
    for n in g["nodes"]:
        el = ET.SubElement(graph, f"{{{NS}}}node", id=n["id"])
        for key_id in ("label", "kind"):
            d = ET.SubElement(el, f"{{{NS}}}data", key=key_id)
            d.text = str(n[key_id])
    for i, e in enumerate(g["edges"]):
        ET.SubElement(graph, f"{{{NS}}}edge", id=f"e{i}", source=e["source"], target=e["target"])
    xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return Response(
        content=xml,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": "attachment; filename=citation-graph.graphml"},
    )


@router.get("/shared")
def shared_links(
    term: str,
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """The corpus LINKS view (T10): which member articles SHARE outbound links.

    METHODOLOGICAL RULING (anti-false-triangulation, 2026-06-12): convergence
    counts as corroboration ONLY when the paths are independent — three
    articles citing the same single origin are ONE source wearing three hats.
    This endpoint surfaces exactly that shared-origin structure: for the
    articles mentioning ``term``, the outbound URLs cited by MORE THAN ONE
    member, with which members cite them — counts and structure, never a
    credibility verdict.
    """
    from sqlalchemy import func

    from src.analytics import queries as q
    from src.database.models import Article, ArticleLink, KeywordMention

    kw = q.resolve_keyword(db, term)
    if kw is None:
        return {"resolved": None, "shared": [], "members": 0}
    member_ids = [
        r[0]
        for r in db.query(KeywordMention.article_id).filter_by(keyword_id=kw.id).all()
    ]
    if not member_ids:
        return {"resolved": {"term": kw.term}, "shared": [], "members": 0}

    rows = (
        db.query(
            ArticleLink.normalized_url,
            func.count(func.distinct(ArticleLink.article_id)).label("n"),
        )
        .filter(ArticleLink.article_id.in_(member_ids))
        .filter(ArticleLink.normalized_url.isnot(None))
        .group_by(ArticleLink.normalized_url)
        .having(func.count(func.distinct(ArticleLink.article_id)) > 1)
        .order_by(func.count(func.distinct(ArticleLink.article_id)).desc())
        .limit(limit)
        .all()
    )
    shared = []
    for url, n in rows:
        citers = (
            db.query(Article.id, Article.title, Article.source_id)
            .join(ArticleLink, ArticleLink.article_id == Article.id)
            .filter(ArticleLink.normalized_url == url, Article.id.in_(member_ids))
            .limit(12)
            .all()
        )
        distinct_sources = len({c[2] for c in citers})
        shared.append(
            {
                "url": url,
                "cited_by_articles": int(n),
                "citing_sources": distinct_sources,
                "citers": [{"article_id": c[0], "title": c[1]} for c in citers],
                # The independence note, per shared link (informed consent):
                "note": (
                    "shared origin: these member articles cite the SAME page — "
                    "their agreement is one path, not independent confirmation"
                )
                if distinct_sources <= 1 or int(n) > distinct_sources
                else "cited across distinct sources — paths may still share an upstream origin",
            }
        )
    return {
        "resolved": {"term": kw.term},
        "members": len(member_ids),
        "shared": shared,
        "method": (
            "Outbound links cited by >1 member article (normalized URLs), with "
            "the citing members and distinct-source counts. Structure and counts "
            "only — citation counts are NEVER independent confirmation when the "
            "paths share an origin (the Links view exists to make that visible)."
        ),
    }
