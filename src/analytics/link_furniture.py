"""Outlet furniture among an article's cited links.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD TEST 2026-11-14, ROW 68 (report 7.1, 7.2): the reader's "Sources this article cites" listed an outlet's
footer as citations -- ``apps.apple.com`` "also cited by 494" of the outlet's 495 articles, ``prenumerera.hbl.fi``
by 486. A link that sits on most of ONE outlet's articles is that outlet's page furniture (an app badge, a
subscription link), not something the article cites.

Measured per outlet, from the corpus itself: a link is furniture when at least :data:`FURNITURE_SHARE` of the
articles stored from this article's source carry the same normalized URL, and the source has at least
:data:`FURNITURE_MIN_ARTICLES` articles (below that, "most of the outlet" is a handful of pages and proves nothing).
Nothing is deleted or rewritten: the reader lists such links apart, with the counts that put them there.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

#: The share of one outlet's stored articles that must carry a link for it to be read as that outlet's furniture.
FURNITURE_SHARE = 0.5

#: The fewest articles an outlet must have stored before any of its links is read as furniture.
FURNITURE_MIN_ARTICLES = 20

METHOD = (
    f"a link is listed as the outlet's own page furniture (footer, app or subscription link) when at least "
    f"{FURNITURE_SHARE:.0%} of the articles stored from this source carry the same address, and the source has at "
    f"least {FURNITURE_MIN_ARTICLES} stored articles; measured on your corpus, per source"
)


def outlet_link_shares(session: Session, source_id: int | None, normalized_urls: list[str]) -> dict[str, Any]:
    """For each normalized URL, how many of the source's stored articles carry it, and which are furniture.

    Returns ``{"source_articles": n | None, "carried_by": {url: count}, "furniture": set_of_urls, "method": str}``.
    With no source, or fewer than :data:`FURNITURE_MIN_ARTICLES` articles, nothing is furniture.
    """
    from src.database.models import Article, ArticleLink
    from src.database.stand_in import not_a_stand_in_article

    out: dict[str, Any] = {"source_articles": None, "carried_by": {}, "furniture": set(), "method": METHOD}
    urls = sorted({u for u in normalized_urls if u})
    if source_id is None or not urls:
        return out
    total = int(
        session.query(func.count(Article.id)).filter(Article.source_id == source_id).filter(not_a_stand_in_article()).scalar()
        or 0
    )
    out["source_articles"] = total
    if total < FURNITURE_MIN_ARTICLES:
        return out
    rows = (
        session.query(ArticleLink.normalized_url, func.count(func.distinct(ArticleLink.article_id)))
        .join(Article, Article.id == ArticleLink.article_id)
        .filter(Article.source_id == source_id)
        .filter(ArticleLink.normalized_url.in_(urls))
        .group_by(ArticleLink.normalized_url)
        .all()
    )
    carried = {str(u): int(n) for u, n in rows}
    out["carried_by"] = carried
    out["furniture"] = {u for u, n in carried.items() if n >= FURNITURE_SHARE * total}
    return out
