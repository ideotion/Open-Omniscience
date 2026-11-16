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
page made under an earlier template or extractor keeps whatever of that template differs. The caches hold
a source's sets for half an hour, keyed by the store's engine as well as the source id.
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
#: The source's newest articles a keyword is counted over (an index-only read of their mentions; the
#: template of today, like the shingles' newest pages).
KEYWORD_SAMPLE_ARTICLES = 500

_CACHE_MAX = 64
_CACHE_TTL_S = 1800.0
_cache: OrderedDict[tuple[int, int], tuple[float, frozenset[int]]] = OrderedDict()
_kw_cache: OrderedDict[tuple[int, int], tuple[float, frozenset[int]]] = OrderedDict()
_lock = threading.Lock()


def strip_known(text: str) -> str:
    """``text`` without the lines :func:`src.ingest.furniture.strip_furniture` names (the ingest's own list)."""
    from src.ingest.furniture import strip_furniture

    return strip_furniture(text or "")[0]


def repeated_shingles(
    bodies: list[str], *, titles: list[str] | None = None, min_share: float = MIN_SHARE, min_sample: int = MIN_SAMPLE
) -> frozenset[int]:
    """The shingles found on at least ``min_share`` of the DISTINCT pages in ``bodies`` (and on three). Pure.

    Pages that are near-duplicates of each other (one story updated under new URLs, a live blog) count once,
    so an outlet that ran one story several times does not learn that story as its template. Pages are one page
    when what is left of them once the provisional template is removed is near-identical, or when their titles
    are (``titles``, aligned with ``bodies``): a live blog on half the pages has one title and is one story,
    where a template on half the pages sits under as many titles as there are stories."""
    from src.signals.near_dup import shingles

    pairs = [(strip_known(b), (titles[i] if titles and i < len(titles) else "") or "") for i, b in enumerate(bodies) if b and b.strip()]
    pairs = [(t, ti) for t, ti in pairs if t.strip()]
    texts = [t for t, _ti in pairs]
    title_sets = [shingles(ti, k=3) if len(ti.split()) >= 3 else set() for _t, ti in pairs]
    if len(texts) < min_sample:
        return frozenset()
    sets = [shingles(t) for t in texts]
    # Two passes. A first count over the raw pages finds the provisional template; pages are then grouped by
    # what is LEFT once it is removed, because a template large enough to cause row 67 makes unrelated pages
    # of one outlet near-identical as a whole (the second independent read), and grouping on whole pages would
    # merge them all into one group and learn nothing.
    provisional = _on_half(sets, min_share)
    rest = [st - provisional for st in sets]
    # One group per run of near-identical pages (exact Jaccard over at most SAMPLE_BODIES pages, so a
    # few hundred set comparisons); within a group a shingle counts once.
    parent = list(range(len(sets)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rest)):
        for j in range(i + 1, len(rest)):
            if _similar(rest[i], rest[j]) or _similar(title_sets[i], title_sets[j]):
                parent[root(j)] = root(i)
    by_root: dict[int, list[int]] = {}
    for i in range(len(sets)):
        by_root.setdefault(root(i), []).append(i)
    groups = list(by_root.values())
    if len(groups) < min_sample:
        return frozenset()
    return _on_half([set().union(*(sets[i] for i in g)) for g in groups], min_share)


def _similar(a: set[int], b: set[int]) -> bool:
    union = len(a | b)
    return bool(union) and len(a & b) / union >= _SAME_PAGE


def _on_half(sets: list[set[int]], min_share: float) -> frozenset[int]:
    """The members of at least ``min_share`` of ``sets`` (and of at least three)."""
    df: dict[int, int] = {}
    for st in sets:
        for sh in st:
            df[sh] = df.get(sh, 0) + 1
    floor = max(3, math.ceil(round(min_share * len(sets), 9)))
    return frozenset(sh for sh, n in df.items() if n >= floor)


def outlet_repeated_shingles(db: Session, source_id: int | None, *, now: float | None = None) -> frozenset[int]:
    """:func:`repeated_shingles` over the source's ``SAMPLE_BODIES`` most recent articles, cached per source.

    Cached for half an hour: a template changes rarely, and the reader asks on every page view."""
    if source_id is None:
        return frozenset()
    from src.database.models import Article

    t = time.monotonic() if now is None else now
    hit = _cached(_cache, _key(db, source_id), t)
    if hit is not None:
        return hit
    rows = (
        db.query(Article)
        .filter(Article.source_id == int(source_id))
        .order_by(Article.id.desc())
        .limit(SAMPLE_BODIES)
        .all()
    )
    learned = repeated_shingles([r.get_content() for r in rows], titles=[r.title or "" for r in rows])
    _remember(_cache, _key(db, source_id), t, learned)
    return learned


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _kw_cache.clear()


def _key(db: Session, source_id: int) -> tuple[int, int]:
    """A source of THIS store: the engine's identity beside the id, so a store opened after a restore, a swap or
    an unlock (a new engine) never reads another store's sets for a source with the same number."""
    return (id(db.get_bind()), int(source_id))


def _cached(cache: OrderedDict[tuple[int, int], tuple[float, frozenset[int]]], key: tuple[int, int], t: float) -> frozenset[int] | None:
    with _lock:
        hit = cache.get(key)
        if hit is not None and t - hit[0] < _CACHE_TTL_S:
            cache.move_to_end(key)
            return hit[1]
    return None


def _remember(cache: OrderedDict[tuple[int, int], tuple[float, frozenset[int]]], key: tuple[int, int], t: float, value: frozenset[int]) -> None:
    with _lock:
        cache[key] = (t, value)
        cache.move_to_end(key)
        while len(cache) > _CACHE_MAX:
            cache.popitem(last=False)


def outlet_furniture_keywords(
    db: Session, source_id: int | None, keyword_ids: list[int] | None = None, *, min_share: float = MIN_SHARE,
    min_articles: int = MIN_ARTICLES, now: float | None = None,
) -> set[int]:
    """The keywords mentioned in at least ``min_share`` of the source's newest ``KEYWORD_SAMPLE_ARTICLES`` articles
    (of ``keyword_ids`` when given).

    One indexed read of those article ids and one grouped count over their mentions (a mention row is unique per
    article and keyword, so a row count is an article count), cached per source for half an hour like the
    shingles: the reader asks on every page view. Mentions exist only for indexed articles while the count is of
    all of them, so during an import fewer keywords qualify, never more."""
    if source_id is None:
        return set()
    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Article

    t = time.monotonic() if now is None else now
    found = _cached(_kw_cache, _key(db, source_id), t)
    if found is None:
        newest = [
            int(i)
            for (i,) in db.query(Article.id)
            .filter(Article.source_id == int(source_id))
            .order_by(Article.id.desc())
            .limit(KEYWORD_SAMPLE_ARTICLES)
        ]
        if len(newest) < min_articles:
            found = frozenset()
        else:
            floor = max(3, math.ceil(round(min_share * len(newest), 9)))
            found = frozenset(
                int(kid)
                for (kid,) in db.query(KeywordMentionRead.keyword_id)
                .filter(KeywordMentionRead.article_id.in_(newest))
                .group_by(KeywordMentionRead.keyword_id)
                .having(func.count(KeywordMentionRead.article_id) >= floor)
            )
        _remember(_kw_cache, _key(db, source_id), t, found)
    return set(found) if keyword_ids is None else set(found.intersection(keyword_ids))
