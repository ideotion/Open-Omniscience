"""Source concentration / flood (manipulation-pattern card #4, ruling #13 + Q8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent: a single SOURCE devotes an unusually large share of
its RECENT output to one topic, relative to its OWN history -- the "flood the zone"
shape. The signal is a two-proportion z-test of the source's recent share of a keyword
versus its prior-period share (a real statistic, the spine's "surprise vs the corpus's
OWN baseline", never a composite score). The innocent twin is stated plainly: volume is
not importance -- a genuinely big story legitimately dominates a source's coverage.

Efficient by construction: it reads ONLY the denormalised ``keyword_mentions.source_id``
+ ``observed_on`` (grouped per source, per keyword) -- never the keyword_mentions ->
articles content-decrypt join. It therefore sees only RE-INDEXED articles (source_id is
populated forward at index time); coverage grows as the corpus is re-indexed.

HONESTY (enforced in code):
  * per-source baseline -- the comparison is the SOURCE's own prior share, so a source
    that always covers a beat heavily does not flag (no jump = no z);
  * the signal carries its COMPONENTS (z, share_now, baseline_share, counts), no blend;
  * a minimum prior sample is required (small-n degrades to silence, never a guess);
  * the caveat names the innocent twin; the scan is bounded; no score.

The "bury" half (a source UNDER-covering a topic that is big elsewhere) needs a real
external trigger and is left to a follow-on -- this is the FLOOD half.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import distinct, func

FLOOD_CAVEAT = (
    "One source is giving an unusually large share of its recent coverage to a single "
    "topic, compared with its own past. Volume is not importance — a genuinely big story "
    "legitimately dominates a source's coverage — so the shape is 'this source, this "
    "topic, far above its own norm', never a claim it was deliberate. Read it and judge."
)


def find_flooded_topics(
    session,
    *,
    recent_days: int = 7,
    baseline_days: int = 84,
    min_recent_articles: int = 8,
    min_share: float = 0.25,
    z_min: float = 2.5,
    min_prior_articles: int = 10,
    max_sources: int = 120,
    max_items: int = 12,
) -> dict:
    """Sources flooding a single topic vs their own history (two-proportion z-test)."""
    from src.database.models import Keyword, KeywordMention, Source

    today = date.today()
    r_start = today - timedelta(days=recent_days)
    b_start = r_start - timedelta(days=baseline_days)
    r_hi = today + timedelta(days=1)

    def _distinct_articles(source_id, lo, hi):
        return (
            session.query(func.count(distinct(KeywordMention.article_id)))
            .filter(
                KeywordMention.source_id == source_id,
                KeywordMention.observed_on >= lo,
                KeywordMention.observed_on < hi,
            )
            .scalar()
            or 0
        )

    def _per_keyword(source_id, lo, hi):
        return dict(
            session.query(
                KeywordMention.keyword_id, func.count(distinct(KeywordMention.article_id))
            )
            .filter(
                KeywordMention.source_id == source_id,
                KeywordMention.observed_on >= lo,
                KeywordMention.observed_on < hi,
            )
            .group_by(KeywordMention.keyword_id)
            .all()
        )

    # Candidate sources: enough RECENT articles (km-only, source_id index).
    src_recent = dict(
        session.query(KeywordMention.source_id, func.count(distinct(KeywordMention.article_id)))
        .filter(
            KeywordMention.observed_on >= r_start,
            KeywordMention.observed_on < r_hi,
            KeywordMention.source_id.isnot(None),
        )
        .group_by(KeywordMention.source_id)
        .all()
    )
    cands = sorted(
        ((s, int(n or 0)) for s, n in src_recent.items() if int(n or 0) >= min_recent_articles),
        key=lambda t: -t[1],
    )[:max_sources]

    from src.analytics.queries import _hidden_predicate

    is_hidden = _hidden_predicate()
    items: list[dict] = []
    for source_id, n_now in cands:
        n_prior = int(_distinct_articles(source_id, b_start, r_start))
        if n_prior < min_prior_articles:
            continue  # not enough baseline -> stay silent
        recent_kw = _per_keyword(source_id, r_start, r_hi)
        prior_kw = _per_keyword(source_id, b_start, r_start)
        for kid, a_now in recent_kw.items():
            a_now = int(a_now or 0)
            p_now = a_now / n_now
            if p_now < min_share:
                continue  # not a flood share
            a_prior = int(prior_kw.get(kid, 0) or 0)
            p_prior = a_prior / n_prior
            # Two-proportion z (one-sided: is the recent share ABOVE the prior share?).
            pooled = (a_now + a_prior) / (n_now + n_prior)
            se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_now + 1.0 / n_prior))
            if se <= 0:
                continue
            z = (p_now - p_prior) / se
            if z < z_min:
                continue
            kw = session.get(Keyword, kid)
            if kw is None or is_hidden(kw.normalized_term):
                continue
            article_ids = sorted(
                r[0]
                for r in session.query(KeywordMention.article_id)
                .filter(
                    KeywordMention.source_id == source_id,
                    KeywordMention.keyword_id == kid,
                    KeywordMention.observed_on >= r_start,
                    KeywordMention.observed_on < r_hi,
                )
                .distinct()
            )
            src = session.get(Source, source_id)
            items.append(
                {
                    "term": kw.normalized_term,
                    "keyword_id": kid,
                    "source": (src.name or src.domain) if src else f"source-{source_id}",
                    "source_id": source_id,
                    "share_zscore": round(z, 2),
                    "share_now": round(p_now, 3),
                    "baseline_share": round(p_prior, 3),
                    "recent_articles": a_now,
                    "recent_total": n_now,
                    "article_ids": article_ids,
                }
            )

    items.sort(key=lambda x: -x["share_zscore"])
    items = items[:max_items]

    return {
        "items": items,
        "count": len(items),
        "recent_days": recent_days,
        "baseline_days": baseline_days,
        "min_share": min_share,
        "z_min": z_min,
        "method": (
            "Per source with >= {mra} recent articles and >= {mpa} prior-period articles: a "
            "two-proportion z-test of its recent share of a keyword (>= {ms}) vs its own "
            "prior share. Fires at z >= {zm}. Reads the denormalised source_id only (no "
            "content decrypt), so it covers re-indexed articles. Counts only, no score.".format(
                mra=min_recent_articles, mpa=min_prior_articles, ms=min_share, zm=z_min,
            )
        ),
        "caveat": FLOOD_CAVEAT,
    }
