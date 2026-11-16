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
half of them, so it is still found. Too few pages to tell (under ``MIN_SAMPLE`` bodies, under
``MIN_ARTICLES`` articles) leaves nothing out.
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
#: Fewer bodies than this, and nothing is learned: two or three pages cannot tell a template from a story.
MIN_SAMPLE = 4
#: A keyword is judged against its source's articles only from this many articles up.
MIN_ARTICLES = 10

_CACHE_MAX = 64
_CACHE_TTL_S = 1800.0
_cache: OrderedDict[int, tuple[float, frozenset[int]]] = OrderedDict()
_lock = threading.Lock()


def repeated_shingles(bodies: list[str], *, min_share: float = MIN_SHARE, min_sample: int = MIN_SAMPLE) -> frozenset[int]:
    """The shingles found in at least ``min_share`` of ``bodies`` (and in at least three of them). Pure."""
    from src.ingest.furniture import strip_furniture
    from src.signals.near_dup import shingles

    texts = [b for b in bodies if b and b.strip()]
    if len(texts) < min_sample:
        return frozenset()
    df: dict[int, int] = {}
    for text in texts:
        for sh in shingles(strip_furniture(text)[0]):
            df[sh] = df.get(sh, 0) + 1
    floor = max(3, math.ceil(round(min_share * len(texts), 9)))
    return frozenset(sh for sh, n in df.items() if n >= floor)


def outlet_repeated_shingles(db: Session, source_id: int | None, *, now: float | None = None) -> frozenset[int]:
    """:func:`repeated_shingles` over the source's ``SAMPLE_BODIES`` most recent articles, cached per source.

    Cached for half an hour: a template changes rarely, and the reader asks on every page view."""
    if source_id is None:
        return frozenset()
    from src.database.models import Article

    t = time.monotonic() if now is None else now
    with _lock:
        hit = _cache.get(int(source_id))
        if hit is not None and t - hit[0] < _CACHE_TTL_S:
            _cache.move_to_end(int(source_id))
            return hit[1]
    rows = (
        db.query(Article)
        .filter(Article.source_id == int(source_id))
        .order_by(Article.id.desc())
        .limit(SAMPLE_BODIES)
        .all()
    )
    learned = repeated_shingles([r.get_content() for r in rows])
    with _lock:
        _cache[int(source_id)] = (t, learned)
        _cache.move_to_end(int(source_id))
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return learned


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def outlet_furniture_keywords(
    db: Session, source_id: int | None, keyword_ids: list[int], *, min_share: float = MIN_SHARE,
    min_articles: int = MIN_ARTICLES,
) -> set[int]:
    """Of ``keyword_ids``, those mentioned in at least ``min_share`` of the source's articles.

    One indexed count of the source's articles and one grouped count over the given keywords'
    mentions within the source (a mention row is unique per article and keyword, so a row count
    is an article count)."""
    if source_id is None or not keyword_ids:
        return set()
    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Article

    total = int(db.query(func.count(Article.id)).filter(Article.source_id == int(source_id)).scalar() or 0)
    if total < min_articles:
        return set()
    floor = max(3, math.ceil(round(min_share * total, 9)))
    wanted = sorted(set(keyword_ids))
    out: set[int] = set()
    for i in range(0, len(wanted), 900):  # under SQLite's bound-variable limit
        chunk = wanted[i : i + 900]
        rows = (
            db.query(KeywordMentionRead.keyword_id, func.count(KeywordMentionRead.article_id))
            .filter(KeywordMentionRead.source_id == int(source_id), KeywordMentionRead.keyword_id.in_(chunk))
            .group_by(KeywordMentionRead.keyword_id)
            .all()
        )
        out.update(int(kid) for kid, n in rows if int(n) >= floor)
    return out
