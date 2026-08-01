"""
Story clusters — grouping a period's articles into the things they are about.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §9 (the story-cluster unit). Narration works one story at a time,
so this is what decides what a narrated paragraph is about.

HOW, and the honesty of the method is the whole of it: articles are grouped by
the overlap of their KEYWORD sets — the rule-based, trusted index — not by a
semantic model. Two articles land together when they share enough indexed terms.
That is a LEXICAL grouping and the payload says so: it will split one story told
in two languages, and it will join two unrelated stories that share a vocabulary.
Neither is a bug to be hidden; both are properties of grouping by words.

The alternative — an embedding model deciding what is "the same story" — would
put an unverifiable judgement underneath every narrated paragraph, which is
exactly what the deterministic-first design exists to avoid.

Cost: keyword sets come from ``keyword_mentions``, which is indexed and carries
``source_id`` denormalised, so building them costs no article decrypt at all.
Only the narration step reads article text, and only for the articles it narrates.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func

from src.bulletin.period import Period
from src.database.models import Article, Keyword, KeywordMention, Source

_LOG = logging.getLogger(__name__)

_CLOCK = func.coalesce(Article.published_at, Article.created_at)

#: Terms per article used to compare. The most-mentioned terms in that article —
#: enough to characterise it, few enough that two articles sharing a handful of
#: incidental words do not join.
_TERMS_PER_ARTICLE = 12

#: Jaccard overlap at or above which two articles are the same story. Deliberately
#: high: over-merging is the worse failure, because a merged cluster invites a
#: narrated sentence spanning two unrelated things, and no downstream check would
#: catch that.
_JOIN_AT = 0.34

#: A story with fewer articles than this is not narrated as a story — one article
#: is not a story, it is an article, and calling it one would inflate the shape of
#: the period. Single articles are still counted everywhere else.
_MIN_ARTICLES = 2


def article_keyword_sets(session, period: Period) -> dict[int, set[int]]:
    """Each in-period article's characterising keyword ids.

    Reads ``keyword_mentions`` only — indexed, no article decrypt. Per article the
    top ``_TERMS_PER_ARTICLE`` by mention count; ties broken by keyword id so the
    grouping is deterministic across runs, which is what lets an edition be
    regenerated and come out the same.
    """
    lo, hi = period.start, period.end
    rows = (
        session.query(
            KeywordMention.article_id, KeywordMention.keyword_id, KeywordMention.count
        )
        .filter(and_(KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi))
        .all()
    )
    per: dict[int, list[tuple[int, int]]] = {}
    for aid, kid, cnt in rows:
        per.setdefault(int(aid), []).append((int(cnt or 0), int(kid)))
    out: dict[int, set[int]] = {}
    for aid, pairs in per.items():
        pairs.sort(key=lambda p: (-p[0], p[1]))
        out[aid] = {kid for _c, kid in pairs[:_TERMS_PER_ARTICLE]}
    return out


def cluster_articles(
    sets: dict[int, set[int]], *, threshold: float = _JOIN_AT, min_articles: int = _MIN_ARTICLES
) -> list[list[int]]:
    """Group article ids whose keyword sets overlap, using the proven primitives.

    Exact Jaccard (the sets are small, so exact rather than MinHash-estimated) and
    the shared union-find from ``src.signals.near_dup``. Returns clusters of at
    least ``min_articles``, each sorted, the whole list ordered largest first then
    by lowest id — deterministic, so a regenerated edition matches.

    O(n²) in the number of articles, which is why the caller bounds what it hands
    in. That bound is disclosed by the caller, not hidden here.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    from src.signals.near_dup import _connected_components

    ids = sorted(sets)
    labels = {str(i): i for i in ids}
    edges: set[tuple[str, str]] = set()
    for i, a in enumerate(ids):
        sa = sets[a]
        if not sa:
            continue
        for b in ids[i + 1 :]:
            sb = sets[b]
            if not sb:
                continue
            union = sa | sb
            if union and len(sa & sb) / len(union) >= threshold:
                edges.add((str(a), str(b)))
    comps = _connected_components({str(i) for i in ids}, edges)
    clusters = [sorted(labels[lbl] for lbl in comp) for comp in comps]
    clusters = [c for c in clusters if len(c) >= min_articles]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def build_stories(
    session,
    period: Period,
    *,
    limit: int = 12,
    max_articles: int = 4000,
    threshold: float = _JOIN_AT,
) -> dict:
    """The period's story clusters, with the facts each one is built from.

    ``max_articles`` bounds the pairwise comparison. It is a bound on WHICH
    articles were compared, disclosed in the payload — the period's article COUNT
    stays exact everywhere else, and this never changes it. When the bound bites,
    the payload says how many were compared out of how many there were.

    ``limit`` bounds the stories RETURNED, and likewise says so.
    """
    sets = article_keyword_sets(session, period)
    total_articles = len(sets)
    compared = sets
    bounded = False
    if total_articles > max_articles:
        # Take the articles with the richest keyword sets: an article with two
        # indexed terms cannot characterise a story anyway. Deterministic tie-break.
        keep = sorted(sets, key=lambda a: (-len(sets[a]), a))[:max_articles]
        compared = {a: sets[a] for a in keep}
        bounded = True

    clusters = cluster_articles(compared, threshold=threshold)
    shown = clusters[:limit]

    # Terms and sources per shown cluster — small lookups over ids we already hold.
    kw_names: dict[int, str] = {}
    wanted = {k for c in shown for a in c for k in compared[a]}
    for i in range(0, len(wanted), 900):
        chunk = list(wanted)[i : i + 900]
        for kid, term in session.query(Keyword.id, Keyword.term).filter(Keyword.id.in_(chunk)):
            kw_names[int(kid)] = term

    stories: list[dict[str, Any]] = []
    for cluster in shown:
        shared: set[int] | None = None
        for a in cluster:
            shared = compared[a] if shared is None else (shared & compared[a])
        shared = shared or set()
        srcs = _sources_of(session, cluster)
        stories.append(
            {
                "article_ids": cluster,
                "articles": len(cluster),
                "distinct_sources": len(srcs),
                "sources": sorted(srcs.values()),
                "shared_terms": sorted(
                    (kw_names.get(k) for k in shared if kw_names.get(k)), key=str
                ),
                "single_source": len(srcs) <= 1,
            }
        )

    return {
        "stories": stories,
        "stories_found": len(clusters),
        "stories_shown": len(shown),
        "articles_in_period": total_articles,
        "articles_compared": len(compared),
        "comparison_bounded": bounded,
        "threshold": threshold,
        "method": (
            f"articles grouped by the overlap of their top {_TERMS_PER_ARTICLE} indexed "
            f"keywords (exact Jaccard >= {threshold}); clusters of at least "
            f"{_MIN_ARTICLES} articles, largest first. Built from keyword_mentions only "
            "— no article text is read here."
        ),
        "caveat": (
            "A LEXICAL grouping, not a semantic one. It will split one story told in two "
            "languages, and it will join two unrelated stories that share a vocabulary. "
            "Both are properties of grouping by words, not faults to be read around. "
            "`single_source` marks a cluster carried by one source: repetition by one "
            "voice, not corroboration by several."
            + (
                f" Only {len(compared):,} of {total_articles:,} in-period articles were "
                "compared (the richest keyword sets first) — the period's article counts "
                "elsewhere are unaffected and exact."
                if bounded
                else ""
            )
        ),
    }


def _sources_of(session, article_ids: list[int]) -> dict[int, str]:
    """The distinct sources behind a cluster, as {source_id: display name}."""
    rows = (
        session.query(Article.source_id, Source.name, Source.domain)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(Article.id.in_(article_ids[:900]))
        .all()
    )
    return {int(sid): (name or domain or f"source {sid}") for sid, name, domain in rows}


def story_evidence(session, article_ids: list[int], *, budget_chars: int) -> dict:
    """The text a story's narration is grounded in, and nothing else.

    Reads article text — the only place in Layer A/B's fact path that does — and
    only for the articles of ONE story, bounded by ``budget_chars``. Returns the
    excerpt set plus the ids it actually covers, so a narrated sentence's
    provenance names the articles it could possibly have come from rather than the
    whole cluster.

    Lead-first: an article contributes its opening paragraphs, which is where a
    news article states what happened. Truncation is disclosed per article.
    """
    rows = (
        session.query(Article.id, Article.title, Article.published_at)
        .filter(Article.id.in_(article_ids[:900]))
        .order_by(Article.published_at.asc().nullslast(), Article.id)
        .all()
    )
    order = [int(r[0]) for r in rows]
    titles = {int(r[0]): r[1] for r in rows}
    per = max(400, budget_chars // max(1, len(order))) if order else 0

    excerpts: list[dict] = []
    covered: list[int] = []
    used = 0
    for aid in order:
        if used >= budget_chars:
            break
        art = session.get(Article, aid)
        if art is None:
            continue
        try:
            text = (art.get_content() or "").strip()
        except Exception:  # noqa: BLE001 - one unreadable article never loses the story
            _LOG.warning("bulletin: article %s unreadable for narration", aid, exc_info=True)
            continue
        take = text[:per]
        used += len(take)
        covered.append(aid)
        excerpts.append(
            {
                "article_id": aid,
                "title": titles.get(aid),
                "published_at": None
                if not isinstance(art.published_at, datetime)
                else art.published_at.isoformat(),
                "text": take,
                "truncated": len(text) > len(take),
                "chars": len(take),
            }
        )

    return {
        "excerpts": excerpts,
        "article_ids": covered,
        "articles_requested": len(article_ids),
        "articles_covered": len(covered),
        "chars": used,
        "budget_chars": budget_chars,
        "method": (
            "the opening of each article in the story, oldest first, within a character "
            "budget shared across the cluster; truncation is marked per excerpt"
        ),
        "caveat": (
            "Narration may only use what is here. An article the budget did not reach is "
            "NOT part of the evidence, and article_ids lists exactly what is — so a "
            "sentence's provenance names what it could have come from, not the whole cluster."
        ),
    }
