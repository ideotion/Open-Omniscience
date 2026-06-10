"""
Diagnostics log: shareable, on-demand syntheses of back-end state.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer↔developer feedback channel (CLAUDE.md ruling 2026-06-10): the
corpus is private and local by design, so improving data-shaped behaviour
(keyword grouping first) needs an export the operator can *choose* to share.
Precedent: ``data/source_preflight.jsonl`` plays this role for sources.

Honesty constraints (FUTURE_DEVELOPMENTS design):
- generated ON DEMAND only — nothing is written or sent automatically;
- carries date, app version and corpus size so the reader knows the context;
- synthesizes, never editorialises: counts and structures, no scores;
- bounded (the same discipline as every other scan) and says so when capped.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.database.models import (
    Article,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    Source,
)
from src.database.session import get_db
from src.utils.export_envelope import envelope

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# Bounded scan: more than enough vocabulary to diagnose grouping, never unbounded.
_MAX_KEYWORDS = 5000


@router.get("/keywords")
def keyword_log(db: Session = Depends(get_db)) -> JSONResponse:
    """The keyword diagnostics log: every gathered keyword (bounded, mentions-desc)
    with its counts, plus the computed families, the user's merge/split overrides
    and the super-groups — exactly the structures the grouping logic works on."""
    rows = (
        db.query(
            Keyword,
            func.coalesce(func.sum(KeywordMention.count), 0).label("mentions"),
            func.count(func.distinct(KeywordMention.article_id)).label("articles"),
            func.min(KeywordMention.observed_on).label("first_seen"),
            func.max(KeywordMention.observed_on).label("last_seen"),
        )
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
        .order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(_MAX_KEYWORDS + 1)
        .all()
    )
    capped = len(rows) > _MAX_KEYWORDS
    rows = rows[:_MAX_KEYWORDS]

    # The stoplist verdict is part of the diagnosis: leaked function words the
    # operator hid are exactly what grouping fixes need to see — flag, not omit.
    is_hidden = q._hidden_predicate()
    keywords = [
        {
            "term": k.term,
            "normalized": k.normalized_term,
            "kind": q.kind_of(k),
            "language": k.language,
            "mentions": int(m),
            "articles": int(a),
            "first_seen": first.isoformat() if first else None,
            "last_seen": last.isoformat() if last else None,
            "hidden": bool(is_hidden(k.normalized_term)),
        }
        for k, m, a, first, last in rows
    ]

    overrides = q.load_overrides(db)
    fam_items = [
        {
            "term": kw["term"],
            "normalized": kw["normalized"],
            "kind": kw["kind"],
            "mentions": kw["mentions"],
            "articles": kw["articles"],
        }
        for kw in keywords
        if not kw["hidden"]
    ]
    families = [f.to_dict() for f in build_families(fam_items, overrides)]

    supergroups = [
        {
            "name": sg.name,
            "members": sorted(m.normalized_term for m in sg.members),
        }
        for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    ]

    payload = {
        "corpus": {
            "articles": int(db.query(func.count(Article.id)).scalar() or 0),
            "sources": int(db.query(func.count(Source.id)).scalar() or 0),
            "keywords_total": int(db.query(func.count(Keyword.id)).scalar() or 0),
            "keywords_exported": len(keywords),
            "capped": capped,
        },
        "method": (
            f"All gathered keywords (top {_MAX_KEYWORDS} by total mentions) with real "
            "counts; families computed by the live grouping logic incl. the user's "
            "merge/split overrides; super-groups as curated. No scores, no inference."
        ),
        "keywords": keywords,
        "families": families,
        "overrides": [
            {"normalized_term": term, **data} for term, data in sorted(overrides.items())
        ],
        "supergroups": supergroups,
    }
    body = envelope(
        kind="keyword-diagnostics", query={}, count=len(keywords), payload=payload
    )
    fname = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
