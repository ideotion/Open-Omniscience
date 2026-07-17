"""Persist extracted article dates as human-confirmable date *tags*.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Bridges the pure extractor (:mod:`src.timemap.dateextract`) to the
``article_mentioned_dates`` table. Every extracted date is stored as a ``candidate``
tag with its provenance snippet and a confidence; the user confirms or rejects it. The
store is the source of truth for "what dates does this article mention" — searchable,
filterable, and a per-article tag set. Idempotent: re-indexing never duplicates a tag
nor clobbers a human decision.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from src.database.models import Article, ArticleMentionedDate
from src.timemap.dateextract import extract_dates

VALID_STATUS = ("candidate", "confirmed", "rejected")
_CONFIDENCE = {"day": 0.9, "month": 0.7}  # regex extractor: explicit day is firmer than month


def _to_row(tag: ArticleMentionedDate) -> dict:
    return {
        "id": tag.id,
        "article_id": tag.article_id,
        "date": tag.mentioned_on.isoformat() if tag.mentioned_on else None,
        "precision": tag.precision,
        "snippet": tag.snippet,
        "confidence": tag.confidence,
        "status": tag.status,
    }


def store_for_article(db: Session, article: Article, *, today: date | None = None) -> int:
    """Extract dates from one article's text and store new candidate tags. Returns the count added.

    Idempotent: an existing (article, date, precision) tag is left untouched — so a human's
    confirm/reject decision is preserved across re-runs.
    """
    if article is None or not (article.content or "").strip():
        return 0
    existing = {
        (t.mentioned_on.isoformat(), t.precision)
        for t in db.query(ArticleMentionedDate)
        .filter(ArticleMentionedDate.article_id == article.id)
        .all()
    }
    # Feed the extractor the article's OWN date + language so it can resolve the
    # commonest news forms it otherwise skips: day+month with no year ("11
    # September"), relative words ("yesterday"), bare weekdays ("on Tuesday"), and
    # language-ambiguous numeric dates (11/06 is DMY in fr, MDY in en). Both
    # signals live on the article; passing them is what makes ingest-time
    # extraction complete rather than explicit-dates-only (the reader and temporal
    # map already passed them — this aligns the source-of-truth store with them).
    observed = article.published_at or article.created_at
    anchor = observed.date() if observed else None
    added = 0
    for c in extract_dates(article.content, today=today, anchor=anchor, language=article.language):
        key = (c["date"], c["precision"])
        if key in existing:
            continue
        db.add(
            ArticleMentionedDate(
                article_id=article.id,
                mentioned_on=date.fromisoformat(c["date"]),
                precision=c["precision"],
                snippet=c["text"][:300],
                confidence=_CONFIDENCE.get(c["precision"], 0.5),
                extractor="dateextract",
                status="candidate",
            )
        )
        existing.add(key)
        added += 1
    if added:
        # SAVEPOINT-AWARE (CI red 2026-07-17, root cause of the #691 regression):
        # index_article's when/where/who pass runs this inside its own
        # session.begin_nested() savepoint. A commit() here closes that caller's
        # nested-transaction context, so the very NEXT statement (the places
        # delete in whostore) raises "Can't operate on closed transaction inside
        # context manager" — which the WWW pass swallows by design, silently
        # costing every article WITH an extracted date its places/entities.
        # Inside a caller-owned savepoint, flush so the rows join it and let the
        # caller commit; standalone callers (the /api/articles/{id}/dates
        # endpoint, index_recent) keep the direct commit unchanged.
        if db.in_nested_transaction():
            db.flush()
        else:
            db.commit()
    return added


def index_recent(
    db: Session, *, days: int | None = None, limit: int = 500, today: date | None = None
) -> dict:
    """Extract+store date tags for recent articles. Returns scan/coverage counts."""
    from datetime import datetime, timedelta

    q = db.query(Article).filter(Article.published_at.isnot(None))
    if days:
        q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=days))
    scanned = with_dates = new_tags = 0
    for art in q.order_by(Article.published_at.desc()).limit(limit).all():
        scanned += 1
        added = store_for_article(db, art, today=today)
        if added:
            new_tags += added
        # count articles that now carry at least one tag (cheap: any added, or pre-existing)
        if (
            added
            or db.query(ArticleMentionedDate.id)
            .filter(ArticleMentionedDate.article_id == art.id)
            .first()
        ):
            with_dates += 1
    return {"scanned": scanned, "articles_with_dates": with_dates, "new_tags": new_tags}


def for_article(db: Session, article_id: int) -> list[dict]:
    """All date tags on an article, soonest-first."""
    rows = (
        db.query(ArticleMentionedDate)
        .filter(ArticleMentionedDate.article_id == article_id)
        .order_by(ArticleMentionedDate.mentioned_on.asc())
        .all()
    )
    return [_to_row(t) for t in rows]


def set_status(db: Session, tag_id: int, status: str) -> dict | None:
    """Confirm / reject / reset a date tag. Returns the updated row, or None if absent."""
    if status not in VALID_STATUS:
        raise ValueError(f"status must be one of {VALID_STATUS}")
    tag = db.get(ArticleMentionedDate, tag_id)
    if tag is None:
        return None
    tag.status = status
    db.commit()
    return _to_row(tag)


def articles_for_date(
    db: Session,
    *,
    date_str: str,
    precision: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Articles that mention a given date — the corpus-filter payoff of date tags."""
    try:
        on = date.fromisoformat(date_str)
    except (TypeError, ValueError):
        return []
    q = (
        db.query(ArticleMentionedDate, Article)
        .join(Article, Article.id == ArticleMentionedDate.article_id)
        .filter(ArticleMentionedDate.mentioned_on == on)
    )
    if precision:
        q = q.filter(ArticleMentionedDate.precision == precision)
    if status:
        q = q.filter(ArticleMentionedDate.status == status)
    out = []
    for tag, art in q.limit(limit).all():
        out.append(
            {
                "article_id": art.id,
                "title": art.title,
                "url": art.url,
                "published_at": art.published_at.isoformat() if art.published_at else None,
                "precision": tag.precision,
                "status": tag.status,
                "snippet": tag.snippet,
            }
        )
    return out


def upcoming_deduced(
    db: Session,
    *,
    days_ahead: int = 120,
    min_articles: int = 2,
    limit: int = 80,
    today: date | None = None,
) -> dict:
    """Future dates DEDUCED from article text — the agenda's article-extracted
    events layer.

    Groups ``article_mentioned_dates`` whose date falls in ``[today, today +
    days_ahead]``, counting DISTINCT articles + DISTINCT sources per date. A
    surfacing gate (``>= min_articles``) keeps single-mention noise out; rejected
    tags are excluded. Each event carries the article-id set so the agenda can open
    that exact corpus. Counts only — NO score. Deduced from text, never a confirmed
    event (a date an article MENTIONS, not proof anything will happen)."""
    from datetime import timedelta

    from sqlalchemy import func

    t0 = today or date.today()
    horizon = t0 + timedelta(days=days_ahead)
    rows = (
        db.query(
            ArticleMentionedDate.mentioned_on,
            func.count(func.distinct(ArticleMentionedDate.article_id)),
            func.count(func.distinct(Article.source_id)),
        )
        .join(Article, Article.id == ArticleMentionedDate.article_id)
        .filter(
            ArticleMentionedDate.mentioned_on >= t0,
            ArticleMentionedDate.mentioned_on <= horizon,
            ArticleMentionedDate.status != "rejected",
        )
        .group_by(ArticleMentionedDate.mentioned_on)
        .having(func.count(func.distinct(ArticleMentionedDate.article_id)) >= min_articles)
        .order_by(ArticleMentionedDate.mentioned_on)
        .limit(limit)
        .all()
    )
    events = []
    for on, n_arts, n_srcs in rows:
        aids = [
            a
            for (a,) in db.query(ArticleMentionedDate.article_id)
            .filter(
                ArticleMentionedDate.mentioned_on == on,
                ArticleMentionedDate.status != "rejected",
            )
            .distinct()
            .limit(200)
            .all()
        ]
        events.append(
            {
                "date": on.isoformat(),
                "n_articles": int(n_arts),
                "n_sources": int(n_srcs),
                "article_ids": aids,
            }
        )
    return {
        "events": events,
        "count": len(events),
        "method": (
            "Future dates MENTIONED in your articles, grouped by date (distinct "
            f"articles + distinct sources); surfacing gate ≥ {min_articles} articles."
        ),
        "caveat": (
            "Deduced from article text, never confirmed — a date an article mentions, "
            "not proof an event will happen. Rejected tags excluded."
        ),
    }
