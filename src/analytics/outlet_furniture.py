"""What an outlet repeats on every page, so a comparison between articles can leave it out.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (field test 2026-11-14, report 7.1, open-on-main row 67). The reader showed one hbl.fi
article as one of about twelve "near-identical copies" of unrelated hbl.fi articles, and its
"Related in your corpus" list ranked articles by 17 shared keywords that were all the
platform's own page text. Both compare whole stored bodies, and an outlet whose template text
survives extraction makes every one of its pages look alike: the comparison measured the
template, not the story.

TWO READ-TIME MEASURES, both taken from the outlet's own recent pages, never a hand list per
site (and nothing is written, so nothing in the corpus is recomputed):

* :func:`outlet_repeated_shingles` -- the word 5-shingles (the near-duplicate check's own unit,
  :func:`src.signals.near_dup.shingles`) found in at least half of the source's most recent
  bodies. Shingles rather than lines, because a template's text is not always on lines of its
  own after extraction. Each body is first passed through :func:`src.ingest.furniture.strip_furniture`,
  the ingest's closed list of ad placeholders and app banners, so the two agree on what they
  already name.
* :func:`outlet_furniture_keywords` -- of one article's keywords, those found in at least half
  of its source's articles: what Related should not count as shared.

WHAT THIS DOES NOT CLAIM. "Half of the outlet's recent pages" is a structural fact, not a
verdict that the text is boilerplate. A single-topic outlet's topic word is also on half its
pages, and leaving it out of Related only makes Related lean on the other keywords. A story the
outlet really published twice still shares its own paragraphs, which are on two pages, not on
half of them, so it is still found, and near-identical pages in the sample (one story updated under new
URLs, a live blog) count as one page. Too few pages to tell (under ``MIN_SAMPLE`` distinct pages, under
``MIN_ARTICLES`` articles) leaves nothing out. The template is learned from the newest pages, so an older
page made under an earlier template or extractor keeps whatever of that template differs. The caches are
keyed by source id for half an hour, so after a restore to another store they can apply for that long.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict

from sqlalchemy import func
from sqlalchemy.orm import Session

#: The share of an outlet's sampled pages a shingle or keyword must be on to be left out.
MIN_SHARE = 0.5
#: Recent bodies read per source to learn its repeated text (one decrypt each, cached).
SAMPLE_BODIES = 20
#: Fewer DISTINCT pages than this, and nothing is learned: a few pages cannot tell a template from a story.
MIN_SAMPLE = 8
#: Sampled pages this similar are one page for the count (an updated story under a new URL, a live blog).
_SAME_PAGE = 0.7
#: A keyword is judged against its source's articles only from this many articles up.
MIN_ARTICLES = 10

_CACHE_MAX = 64
_CACHE_TTL_S = 1800.0
_cache: OrderedDict[int, tuple[float, frozenset[int]]] = OrderedDict()
_kw_cache: OrderedDict[int, tuple[float, frozenset[int]]] = OrderedDict()
_lock = threading.Lock()


def strip_known(text: str) -> str:
    """``text`` without the lines :func:`src.ingest.furniture.strip_furniture` names (the ingest's own list)."""
    from src.ingest.furniture import strip_furniture

    return strip_furniture(text or "")[0]


def repeated_shingles(bodies: list[str], *, min_share: float = MIN_SHARE, min_sample: int = MIN_SAMPLE) -> frozenset[int]:
    """The shingles found on at least ``min_share`` of the DISTINCT pages in ``bodies`` (and on three). Pure.

    Pages that are near-duplicates of each other (one story updated under new URLs, a live blog) count once,
    so an outlet that ran one story several times does not learn that story as its template."""
    from src.signals.near_dup import shingles

    texts = [strip_known(b) for b in bodies if b and b.strip()]
    texts = [t for t in texts if t.strip()]
    if len(texts) < min_sample:
        return frozenset()
    sets = [shingles(t) for t in texts]
    # One group per run of near-identical pages (exact Jaccard over at most SAMPLE_BODIES pages, so a
    # few hundred set comparisons); within a group a shingle counts once.
    parent = list(range(len(sets)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = len(sets[i] | sets[j])
            if union and len(sets[i] & sets[j]) / union >= _SAME_PAGE:
                parent[root(j)] = root(i)
    by_root: dict[int, list[int]] = {}
    for i in range(len(sets)):
        by_root.setdefault(root(i), []).append(i)
    groups = list(by_root.values())
    if len(groups) < min_sample:
        return frozenset()
    df: dict[int, int] = {}
    for g in groups:
        for sh in set().union(*(sets[i] for i in g)):
            df[sh] = df.get(sh, 0) + 1
    floor = max(3, math.ceil(round(min_share * len(groups), 9)))
    return frozenset(sh for sh, n in df.items() if n >= floor)


def outlet_repeated_shingles(db: Session, source_id: int | None, *, now: float | None = None) -> frozenset[int]:
    """:func:`repeated_shingles` over the source's ``SAMPLE_BODIES`` most recent articles, cached per source.

    Cached for half an hour: a template changes rarely, and the reader asks on every page view."""
    if source_id is None:
        return frozenset()
    from src.database.models import Article

    t = time.monotonic() if now is None else now
    hit = _cached(_cache, int(source_id), t)
    if hit is not None:
        return hit
    rows = (
        db.query(Article)
        .filter(Article.source_id == int(source_id))
        .order_by(Article.id.desc())
        .limit(SAMPLE_BODIES)
        .all()
    )
    learned = repeated_shingles([r.get_content() for r in rows])
    _remember(_cache, int(source_id), t, learned)
    return learned


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _kw_cache.clear()


def _cached(cache: OrderedDict[int, tuple[float, frozenset[int]]], source_id: int, t: float) -> frozenset[int] | None:
    with _lock:
        hit = cache.get(source_id)
        if hit is not None and t - hit[0] < _CACHE_TTL_S:
            cache.move_to_end(source_id)
            return hit[1]
    return None


def _remember(cache: OrderedDict[int, tuple[float, frozenset[int]]], source_id: int, t: float, value: frozenset[int]) -> None:
    with _lock:
        cache[source_id] = (t, value)
        cache.move_to_end(source_id)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def outlet_furniture_keywords(
    db: Session, source_id: int | None, keyword_ids: list[int] | None = None, *, min_share: float = MIN_SHARE,
    min_articles: int = MIN_ARTICLES, now: float | None = None,
) -> set[int]:
    """The keywords mentioned in at least ``min_share`` of the source's articles (of ``keyword_ids`` when given).

    One indexed count of the source's articles and one grouped count over the source's mentions (a mention row is
    unique per article and keyword, so a row count is an article count), cached per source for half an hour like
    the shingles: the reader asks on every page view. Mentions exist only for indexed articles while the count is
    of all of them, so during an import fewer keywords qualify, never more."""
    if source_id is None:
        return set()
    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Article

    t = time.monotonic() if now is None else now
    found = _cached(_kw_cache, int(source_id), t)
    if found is None:
        total = int(db.query(func.count(Article.id)).filter(Article.source_id == int(source_id)).scalar() or 0)
        if total < min_articles:
            found = frozenset()
        else:
            floor = max(3, math.ceil(round(min_share * total, 9)))
            found = frozenset(
                int(kid)
                for (kid,) in db.query(KeywordMentionRead.keyword_id)
                .filter(KeywordMentionRead.source_id == int(source_id))
                .group_by(KeywordMentionRead.keyword_id)
                .having(func.count(KeywordMentionRead.article_id) >= floor)
            )
        _remember(_kw_cache, int(source_id), t, found)
    return set(found) if keyword_ids is None else set(found.intersection(keyword_ids))
