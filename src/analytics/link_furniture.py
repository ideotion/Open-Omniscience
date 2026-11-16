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

from collections import defaultdict
from collections.abc import Iterable
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

# Bind parameters per IN list: well under SQLite's limit, so a large corpus never fails the query.
_CHUNK = 500

# (database, source id, its article count) -> that source's furniture {url: carried}. Bounded; oldest entry leaves first.
_SOURCE_CACHE: dict[tuple[str, int, int], dict[str, int]] = {}
_SOURCE_CACHE_MAX = 4096


def is_furniture(carried: int, source_articles: int) -> bool:
    """THE rule, in one place: carried by at least :data:`FURNITURE_SHARE` of a source with enough stored articles."""
    return source_articles >= FURNITURE_MIN_ARTICLES and carried >= FURNITURE_SHARE * source_articles


def source_article_totals(session: Session, source_ids: Iterable[int]) -> dict[int, int]:
    """Stored articles per source, stand-ins left out (the denominator of the share). One grouped query per chunk."""
    from src.database.models import Article
    from src.database.stand_in import not_a_stand_in_article

    ids = sorted({int(s) for s in source_ids if s is not None})
    out: dict[int, int] = {}
    for i in range(0, len(ids), _CHUNK):
        part = ids[i : i + _CHUNK]
        for sid, n in (
            session.query(Article.source_id, func.count(Article.id))
            .filter(Article.source_id.in_(part))
            .filter(not_a_stand_in_article())
            .group_by(Article.source_id)
            .all()
        ):
            out[int(sid)] = int(n or 0)
    return out


def source_furniture(session: Session, source_id: int, source_articles: int) -> dict[str, int]:
    """Every URL that is this source's furniture, with how many of its articles carry it.

    Read from the source's side (its articles, then the covering ``(article_id, normalized_url)`` index), which costs the
    source's own links; asking from the URL side instead costs every link of every popular URL in the corpus, and
    measured ~400 times slower on a synthetic 500 k-link corpus (1.6 s per 500 URLs against 3.7 ms per source).
    Remembered per (database, source, article count): a new article changes the count, so the answer is read again.
    """
    from math import ceil

    from src.database.models import Article, ArticleLink

    if source_articles < FURNITURE_MIN_ARTICLES:
        return {}
    bind = session.get_bind()
    engine: Any = getattr(bind, "engine", bind)  # a Connection carries its Engine; the URL (password masked) names the database
    key = (str(engine.url), int(source_id), int(source_articles))
    hit = _SOURCE_CACHE.get(key)
    if hit is not None:
        return hit
    need = ceil(FURNITURE_SHARE * source_articles)
    n = func.count(func.distinct(ArticleLink.article_id))
    found = {
        str(u): int(c)
        for u, c in session.query(ArticleLink.normalized_url, n)
        .join(Article, Article.id == ArticleLink.article_id)
        .filter(Article.source_id == source_id, ArticleLink.normalized_url.isnot(None))
        .group_by(ArticleLink.normalized_url)
        .having(n >= need)
        .all()
        if u and is_furniture(int(c), source_articles)
    }
    if len(_SOURCE_CACHE) >= _SOURCE_CACHE_MAX:
        _SOURCE_CACHE.pop(next(iter(_SOURCE_CACHE)))
    _SOURCE_CACHE[key] = found
    return found


def furniture_pairs(session: Session, pairs: Iterable[tuple[int | None, str | None]]) -> dict[tuple[int, str], tuple[int, int]]:
    """Which of these (source_id, normalized_url) pairs are that source's furniture.

    Returns ``{(source_id, url): (carried, source_articles)}`` for the furniture pairs only; a pair absent from the
    answer is an ordinary link. Sources under :data:`FURNITURE_MIN_ARTICLES` are never read, so their links cost
    nothing. Every surface that counts citations calls this, so there is one definition, never a second.
    """
    by_source: dict[int, set[str]] = defaultdict(set)
    for sid, url in pairs:
        if sid is not None and url:
            by_source[int(sid)].add(str(url))
    if not by_source:
        return {}
    totals = source_article_totals(session, by_source)
    out: dict[tuple[int, str], tuple[int, int]] = {}
    for sid, urls in by_source.items():
        total = totals.get(sid, 0)
        if total < FURNITURE_MIN_ARTICLES:
            continue
        furniture = source_furniture(session, sid, total)
        for url in urls & furniture.keys():
            out[(sid, url)] = (furniture[url], total)
    return out


def outlet_link_shares(session: Session, source_id: int | None, normalized_urls: list[str]) -> dict[str, Any]:
    """For each normalized URL, how many of the source's stored articles carry it, and which are furniture.

    Returns ``{"source_articles": n | None, "carried_by": {url: count}, "furniture": set_of_urls, "method": str}``.
    With no source, or fewer than :data:`FURNITURE_MIN_ARTICLES` articles, nothing is furniture.
    """
    from src.database.models import Article, ArticleLink

    out: dict[str, Any] = {"source_articles": None, "carried_by": {}, "furniture": set(), "method": METHOD}
    urls = sorted({u for u in normalized_urls if u})
    if source_id is None or not urls:
        return out
    total = source_article_totals(session, [source_id]).get(int(source_id), 0)
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
    out["furniture"] = {u for u, n in carried.items() if is_furniture(n, total)}
    return out
