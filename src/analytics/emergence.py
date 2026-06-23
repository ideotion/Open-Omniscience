"""Manufactured emergence — zero-to-everywhere (manipulation-pattern card #3, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent: a keyword with essentially NO prior history that
appears RECENTLY across MANY distinct sources at once — "born wide". On its own that
describes every genuine breaking story, so the card includes the maintainer's
ANCHOR GATE (spine #3, ruling Q7): it fires ONLY when the emergent articles cite NO
datable primary anchor (no recent mentioned date / no agenda event near the onset).
A real news event leaves a datable trace; an anchor-less wide-and-sudden appearance is
the shape worth a look. The FALSE-NEGATIVE honesty is stated too: a missing anchor may
just mean we did not ingest the trigger or the date extractor missed it.

HONESTY (enforced in code):
  * independence is measured by DISTINCT SOURCES (born-wide), never article count — a
    chatty single source can't manufacture an emergence;
  * the trigger is real measured COMPONENTS (prior count ~0, recent sources, recent
    articles), never a blended score;
  * the anchor gate is precision-biased: ANY datable anchor near the onset suppresses
    the card (bias toward staying silent);
  * the innocent twin + the FN caveat travel with every item; the scan is bounded.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import distinct, func

EMERGENCE_CAVEAT = (
    "A term with almost no prior history appeared suddenly across many distinct sources, "
    "and the articles cite no datable event to anchor it. Genuine breaking news also "
    "appears wide and fast — but it usually has a datable trigger; an anchor-less one is "
    "the shape worth a look. A missing anchor may also just mean we didn't ingest the "
    "trigger or the date extractor missed it. The shape is 'new, wide, unanchored', never "
    "a claim it was coordinated. Read the sources and judge."
)


def find_manufactured_emergence(
    session,
    *,
    recent_days: int = 7,
    prior_days: int = 30,
    max_prior: int = 1,
    min_recent_articles: int = 4,
    min_sources: int = 3,
    anchor_lookback_days: int = 30,
    max_candidates: int = 80,
    max_items: int = 12,
) -> dict:
    """New keywords that appeared wide-and-sudden with NO datable anchor.

    A candidate keyword has prior-period distinct-article count <= ``max_prior`` (≈0,
    truly new) AND recent distinct-article count >= ``min_recent_articles`` across
    >= ``min_sources`` distinct sources (born wide). It FIRES only if its recent
    articles cite no datable anchor (no ArticleMentionedDate within ``anchor_lookback_days``
    of the onset). Read-only; counts only; no score.
    """
    from src.database.models import Article, ArticleMentionedDate, Keyword, KeywordMention

    today = date.today()
    r_start = today - timedelta(days=recent_days)
    p_start = r_start - timedelta(days=prior_days)
    anchor_lo = r_start - timedelta(days=anchor_lookback_days)

    def _article_counts(lo, hi):
        return dict(
            session.query(
                KeywordMention.keyword_id,
                func.count(distinct(KeywordMention.article_id)),
            )
            .filter(KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi)
            .group_by(KeywordMention.keyword_id)
            .all()
        )

    recent = _article_counts(r_start, today + timedelta(days=1))
    prior = _article_counts(p_start, r_start)

    # Candidate = new (prior ~0) AND frequent-now, ordered by recent volume, bounded.
    cands = sorted(
        (
            (kid, int(rc or 0))
            for kid, rc in recent.items()
            if int(rc or 0) >= min_recent_articles and int(prior.get(kid, 0) or 0) <= max_prior
        ),
        key=lambda t: -t[1],
    )[:max_candidates]

    from src.analytics.queries import _hidden_predicate

    is_hidden = _hidden_predicate()
    items: list[dict] = []
    for kid, _rc in cands:
        kw = session.get(Keyword, kid)
        if kw is None or is_hidden(kw.normalized_term):
            continue
        # Born-wide: the distinct sources of this keyword's RECENT articles.
        rows = (
            session.query(Article.id, Article.source_id)
            .join(KeywordMention, KeywordMention.article_id == Article.id)
            .filter(
                KeywordMention.keyword_id == kid,
                KeywordMention.observed_on >= r_start,
                KeywordMention.observed_on < today + timedelta(days=1),
            )
            .distinct()
            .all()
        )
        article_ids = sorted({r[0] for r in rows})
        sources = {r[1] for r in rows if r[1] is not None}
        if len(sources) < min_sources:
            continue  # a chatty single/few source(s) can't manufacture an emergence

        # Anchor gate: ANY datable mention near the onset suppresses the card (genuine
        # news leaves a datable trace). Precision-biased -> bias toward staying silent.
        anchored = (
            session.query(ArticleMentionedDate.article_id)
            .filter(
                ArticleMentionedDate.article_id.in_(article_ids),
                ArticleMentionedDate.mentioned_on.isnot(None),
                ArticleMentionedDate.mentioned_on >= anchor_lo,
                ArticleMentionedDate.mentioned_on <= today,
                ArticleMentionedDate.status != "rejected",
            )
            .first()
            is not None
        )
        if anchored:
            continue  # has a datable primary anchor -> likely genuine news, stay silent

        items.append(
            {
                "term": kw.normalized_term,
                "keyword_id": kid,
                "recent_articles": len(article_ids),
                "recent_sources": len(sources),
                "prior_count": int(prior.get(kid, 0) or 0),
                "anchored": False,
                "article_ids": article_ids,
            }
        )

    # Most-widespread first (real measured breadth, not a score).
    items.sort(key=lambda x: (-x["recent_sources"], -x["recent_articles"]))
    items = items[:max_items]

    return {
        "items": items,
        "count": len(items),
        "recent_days": recent_days,
        "prior_days": prior_days,
        "min_sources": min_sources,
        "method": (
            "A keyword with <= {mp} distinct articles in the prior {pd} days (≈new) that "
            "appears in >= {mr} articles across >= {ms} distinct sources in the last {rd} "
            "days (born wide), AND whose recent articles cite NO datable mention within {al} "
            "days of the onset (the anchor gate). Bounded to {mc} candidates. Counts only, "
            "no score.".format(
                mp=max_prior, pd=prior_days, mr=min_recent_articles, ms=min_sources,
                rd=recent_days, al=anchor_lookback_days, mc=max_candidates,
            )
        ),
        "caveat": EMERGENCE_CAVEAT,
    }
