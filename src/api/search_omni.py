"""
The omnibar endpoint — instant, index-backed, federated search (T13 slice 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

One query fans out over the corpus's INDEXED surfaces and returns the first
few hits per group for the command palette: articles (FTS5, relevance-
ordered), keywords (prefix on the indexed normalized term), sources, watched
Wikipedia pages and law documents (small catalog tables). Never scan-on-type:
every group is served by an index or a small bounded table, the method is
stated in the response, and per-group totals are disclosed so the display
bound never silently hides how much matched.

Mid-typing honesty: a half-typed Boolean query ("drought AND") is not an
error condition — it falls back to a quoted-phrase match instead of a 400.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, Keyword, LawDocument, Source, WikiPage
from src.database.session import get_db

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_PER_GROUP = 3  # the ruled "first THREE results"; totals are always disclosed


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _articles_group(db: Session, q: str) -> dict:
    note = "FTS5 Boolean match, relevance-ordered"
    try:
        ids = search_ids(db, q)
    except SearchQueryError:
        # Half-typed operators mid-keystroke: fall back to a phrase, never 400.
        try:
            ids = search_ids(db, '"' + q.replace('"', " ") + '"')
            note = "FTS5 phrase match (the raw query was not a valid Boolean expression)"
        except SearchQueryError:
            return {"kind": "articles", "items": [], "total": 0,
                    "note": "query not searchable as typed"}
    rows = []
    if ids:
        top = ids[:_PER_GROUP]
        got = (
            db.query(Article.id, Article.title, Article.published_at)
            .filter(Article.id.in_(top))
            .all()
        )
        by_id = {r[0]: r for r in got}
        rows = [
            {
                "article_id": aid,
                "title": by_id[aid][1],
                "published_at": by_id[aid][2].isoformat() if by_id[aid][2] else None,
                "url": f"/api/articles/{aid}/view",  # the LOCAL reader first (invariant #6)
            }
            for aid in top
            if aid in by_id
        ]
    return {"kind": "articles", "items": rows, "total": len(ids), "note": note}


def _keywords_group(db: Session, q: str) -> dict:
    pat = _like_escape(q.casefold()) + "%"
    base = db.query(Keyword).filter(Keyword.normalized_term.like(pat, escape="\\"))
    total = base.count()
    rows = (
        base.order_by(Keyword.frequency.desc().nullslast(), Keyword.normalized_term)
        .limit(_PER_GROUP)
        .all()
    )
    return {
        "kind": "keywords",
        "items": [
            {"term": k.term, "normalized_term": k.normalized_term,
             "frequency": k.frequency, "is_entity": bool(k.is_entity),
             "language": k.language}
            for k in rows
        ],
        "total": total,
        "note": "prefix match on the indexed normalized term",
    }


def _sources_group(db: Session, q: str) -> dict:
    pat = "%" + _like_escape(q) + "%"
    base = db.query(Source).filter(
        or_(Source.name.ilike(pat, escape="\\"), Source.domain.ilike(pat, escape="\\"))
    )
    total = base.count()
    rows = base.order_by(Source.name).limit(_PER_GROUP).all()
    return {
        "kind": "sources",
        "items": [{"source_id": s.id, "name": s.name, "domain": s.domain} for s in rows],
        "total": total,
        "note": "name/domain contains-match over the (small) source catalog",
    }


def _wiki_group(db: Session, q: str) -> dict:
    pat = "%" + _like_escape(q) + "%"
    base = db.query(WikiPage).filter(WikiPage.title.ilike(pat, escape="\\"))
    total = base.count()
    rows = base.order_by(WikiPage.title).limit(_PER_GROUP).all()
    return {
        "kind": "wiki",
        "items": [{"page_id": p.id, "title": p.title, "wiki": p.wiki} for p in rows],
        "total": total,
        "note": "title contains-match over your watched-pages list",
    }


def _law_group(db: Session, q: str) -> dict:
    pat = "%" + _like_escape(q) + "%"
    base = db.query(LawDocument).filter(LawDocument.title.ilike(pat, escape="\\"))
    total = base.count()
    rows = base.order_by(LawDocument.title).limit(_PER_GROUP).all()
    return {
        "kind": "law",
        "items": [
            {"document_id": d.id, "title": d.title, "jurisdiction": d.jurisdiction}
            for d in rows
        ],
        "total": total,
        "note": "title contains-match over your tracked law documents",
    }


@router.get("/omni")
def omni(q: str = Query(min_length=2, max_length=200), db: Session = Depends(get_db)) -> dict:
    """Federated first-hits for the omnibar. Index-backed; totals disclosed."""
    q = " ".join(q.split())
    groups = []
    for fn in (_articles_group, _keywords_group, _sources_group, _wiki_group, _law_group):
        try:
            groups.append(fn(db, q))
        except Exception:  # noqa: BLE001 - one group must never blank the omnibar
            _LOG.warning("omni group %s failed", fn.__name__, exc_info=True)
    return {
        "q": q,
        "per_group": _PER_GROUP,
        "groups": groups,
        "method": (
            "index-backed federation: FTS5 for articles, the normalized-term index "
            "for keywords, bounded catalog tables for the rest; first "
            f"{_PER_GROUP} per group with the true totals disclosed"
        ),
    }
