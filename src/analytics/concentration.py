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

The "bury" half (a source UNDER-covering a topic that is big ELSEWHERE IN THE CORPUS) lives
below in :func:`find_buried_topics`: the corpus itself is the "elsewhere" (a real internal
trigger), and screening every (source, topic) pair is made honest with a Benjamini-Hochberg
FDR correction (:mod:`src.stats.fdr`) so the many comparisons cannot manufacture a finding.
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


BURY_CAVEAT = (
    "One source covered a topic FAR BELOW the corpus norm — a topic that many other "
    "sources covered heavily. The overwhelming innocent explanation is SPECIALIZATION: a "
    "source has a different beat, region, or language, so covering a widely-covered topic "
    "little (or not at all) is normal and expected. This names a SHAPE — 'this source, "
    "this broadly-covered topic, far below where the rest of the corpus sits' — never a "
    "claim the source deliberately buried or suppressed it. Read it and judge. And note: "
    "the absence of a flag here is NOT evidence that nothing was under-covered — this "
    "surfaces only the sharpest gaps that survive multiple-testing correction."
)


def _phi(z: float) -> float:
    """Standard-normal CDF via ``math.erf`` (no scipy at runtime). ``Phi(z)`` = the
    lower-tail probability = the one-sided p-value that a share is this LOW or lower."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def find_buried_topics(
    session,
    *,
    window_days: int = 30,
    min_source_articles: int = 20,
    min_corpus_articles: int = 25,
    min_corpus_sources: int = 5,
    min_corpus_share: float = 0.05,
    z_min: float = 3.0,
    fdr_q: float = 0.05,
    max_sources: int = 80,
    max_topics: int = 60,
    max_items: int = 12,
) -> dict:
    """Sources UNDER-covering a topic that is big across the rest of the corpus (the BURY
    half of manipulation-card #4).

    For every (candidate source, big topic) pair, a two-proportion z-test compares the
    SOURCE's share of the topic against the REST-OF-CORPUS share (one-sided: is the source
    BELOW?). The whole family of pairs is corrected with Benjamini-Hochberg FDR at ``fdr_q``
    so screening thousands of pairs cannot manufacture a "finding"; a pair is surfaced only
    if it BOTH survives FDR AND clears the effect gate ``z <= -z_min``.

    Efficient by construction (like the flood half): reads only the denormalised
    ``keyword_mentions.source_id`` + ``observed_on`` — never the article-content decrypt.
    HONESTY: distinct SOURCES (not article count) measures a topic's breadth; the innocent
    twin (specialization) is stated in the caveat; the signal carries its COMPONENTS
    (z, the two shares, counts, the BH-adjusted q-value), never a blend; no score.
    """
    from src.analytics.queries import _hidden_predicate
    from src.database.models import Keyword, KeywordMention, Source
    from src.stats.fdr import benjamini_hochberg

    today = date.today()
    cutoff = today - timedelta(days=window_days)
    hi = today + timedelta(days=1)

    def _empty(note: str) -> dict:
        return {"items": [], "count": 0, "window_days": window_days, "z_min": z_min,
                "fdr_q": fdr_q, "tests": 0, "note": note, "method": _METHOD, "caveat": BURY_CAVEAT}

    win = [
        KeywordMention.observed_on >= cutoff,
        KeywordMention.observed_on < hi,
        KeywordMention.source_id.isnot(None),
    ]

    # Corpus size N in the window (distinct sourced articles).
    n_corpus = int(
        session.query(func.count(distinct(KeywordMention.article_id))).filter(*win).scalar() or 0
    )
    if n_corpus < max(min_corpus_articles * 2, 2 * min_source_articles):
        return _empty("corpus too small in window")

    # Candidate sources: enough articles in the window (index scan on source_id).
    src_tot = dict(
        session.query(KeywordMention.source_id, func.count(distinct(KeywordMention.article_id)))
        .filter(*win)
        .group_by(KeywordMention.source_id)
        .all()
    )
    candidates = sorted(
        ((int(s), int(n or 0)) for s, n in src_tot.items() if int(n or 0) >= min_source_articles),
        key=lambda t: -t[1],
    )[:max_sources]
    if not candidates:
        return _empty("no source has enough articles in the window")
    cand_ids = [s for s, _ in candidates]

    # Big topics: broad across the corpus (distinct articles AND distinct sources), a real
    # share of the window, and not stoplisted.
    is_hidden = _hidden_predicate()
    topic_rows = (
        session.query(
            KeywordMention.keyword_id,
            func.count(distinct(KeywordMention.article_id)),
            func.count(distinct(KeywordMention.source_id)),
        )
        .filter(*win)
        .group_by(KeywordMention.keyword_id)
        .all()
    )
    big: list[tuple[int, int, int]] = []
    for kid, a_t, s_t in topic_rows:
        a_t = int(a_t or 0)
        s_t = int(s_t or 0)
        if a_t >= min_corpus_articles and s_t >= min_corpus_sources and (a_t / n_corpus) >= min_corpus_share:
            big.append((int(kid), a_t, s_t))
    big.sort(key=lambda t: -t[1])
    big = big[:max_topics]
    if not big:
        return _empty("no topic is broad enough in the window")
    topic_meta = {k: (a, s) for k, a, s in big}
    big_ids = [k for k, _, _ in big]

    # Per (source, topic) distinct articles (only non-zero pairs are returned; missing = 0).
    pair: dict[tuple[int, int], int] = {}
    for i in range(0, len(cand_ids), 400):  # bounded IN() under the SQLite variable limit
        chunk = cand_ids[i : i + 400]
        for sid, kid, a_s in (
            session.query(
                KeywordMention.source_id,
                KeywordMention.keyword_id,
                func.count(distinct(KeywordMention.article_id)),
            )
            .filter(*win)
            .filter(KeywordMention.source_id.in_(chunk))
            .filter(KeywordMention.keyword_id.in_(big_ids))
            .group_by(KeywordMention.source_id, KeywordMention.keyword_id)
        ):
            pair[(int(sid), int(kid))] = int(a_s or 0)

    # Build the test family: every (candidate source, big topic) pair, one-sided lower test.
    tests: list[dict] = []
    pvals: list[float] = []
    for sid, n_s in candidates:
        rest_n = n_corpus - n_s
        if rest_n <= 0:
            continue
        for kid in big_ids:
            a_t, _s_t = topic_meta[kid]
            a_s = pair.get((sid, kid), 0)
            rest_a = a_t - a_s
            p_s = a_s / n_s
            p_rest = rest_a / rest_n
            pooled = a_t / n_corpus
            if pooled <= 0 or pooled >= 1:
                continue
            se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_s + 1.0 / rest_n))
            if se <= 0:
                continue
            z = (p_s - p_rest) / se
            tests.append({"sid": sid, "kid": kid, "z": z, "a_s": a_s, "n_s": n_s,
                          "p_s": p_s, "p_rest": p_rest, "a_t": a_t})
            pvals.append(_phi(z))  # lower-tail p: how surprising a share THIS low is

    if not tests:
        return _empty("no comparable pairs")

    fdr = benjamini_hochberg(pvals, q=fdr_q)
    survivors = set(fdr.rejected)
    hits = [
        t for idx, t in enumerate(tests)
        if idx in survivors and t["z"] <= -z_min  # survive FDR AND clear the effect gate
    ]
    hits.sort(key=lambda t: t["z"])  # most-below first
    hits = hits[:max_items]

    items: list[dict] = []
    for t in hits:
        kw = session.get(Keyword, t["kid"])
        if kw is None or is_hidden(kw.normalized_term):
            continue
        src = session.get(Source, t["sid"])
        adj_q = fdr.adjusted[tests.index(t)] if t in tests else None
        items.append(
            {
                "term": kw.normalized_term,
                "keyword_id": t["kid"],
                "source": (src.name or src.domain) if src else f"source-{t['sid']}",
                "source_id": t["sid"],
                "gap_zscore": round(t["z"], 2),
                "source_share": round(t["p_s"], 4),
                "corpus_share": round(t["p_rest"], 4),
                "source_articles_on_topic": t["a_s"],
                "source_total": t["n_s"],
                "corpus_articles_on_topic": t["a_t"],
                "fdr_qvalue": round(adj_q, 5) if adj_q is not None else None,
            }
        )

    return {
        "items": items,
        "count": len(items),
        "window_days": window_days,
        "z_min": z_min,
        "fdr_q": fdr_q,
        "tests": len(tests),
        "survivors": len(survivors),
        "method": _METHOD,
        "caveat": BURY_CAVEAT,
    }


_METHOD = (
    "For every (source with enough articles, topic broad across the corpus) pair in the "
    "window: a two-proportion z-test of the source's share of the topic vs the "
    "rest-of-corpus share (one-sided, is the source BELOW?). The whole family of pairs is "
    "corrected with Benjamini-Hochberg FDR; a pair is surfaced only if it survives at the "
    "FDR level AND its gap clears z <= -z_min. Distinct SOURCES measure a topic's breadth. "
    "Reads the denormalised source_id only (no content decrypt). Counts only, no score."
)
