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
from datetime import UTC, date, datetime, timedelta

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
    min_recent_count: int = 5,
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

    from src.analytics.generic_terms import GENERIC_TERM_MIN_SHARE, is_generic_by_df_ubiquity
    from src.analytics.managed import normalize_lang
    from src.analytics.queries import _hidden_predicate
    from src.catalog.provenance import WEB, provenance_of

    # Internal-channel exemption (S1.3, row 7): this producer is about PUBLISHER conduct,
    # so a source that is not a plain web publisher -- the user's own newsletter import,
    # a law-tracker synthetic source, a wiki edition -- is never a flood candidate; an
    # unresolvable source (deleted between queries) defaults to web (not exempted, the
    # pre-existing behaviour).
    if cands:
        cids = [s for s, _ in cands]
        prov: dict[int, str] = {}
        for i in range(0, len(cids), 400):
            chunk = cids[i : i + 400]
            for sid, dom, st in session.query(Source.id, Source.domain, Source.source_type).filter(
                Source.id.in_(chunk)
            ):
                prov[int(sid)] = provenance_of(dom, st)
        cands = [(s, n) for s, n in cands if prov.get(s, WEB) == WEB]

    # Per-language active-source counts over the RECENT window (the DF-ubiquity gate's
    # denominator, S1.2): every source with any recent activity, bucketed by language, in
    # ONE small query -- not per-candidate.
    active_by_lang: dict[str, int] = {}
    if src_recent:
        sids = list(src_recent.keys())
        for i in range(0, len(sids), 400):
            chunk = sids[i : i + 400]
            for _sid, lang in session.query(Source.id, Source.language).filter(
                Source.id.in_(chunk)
            ):
                lg = normalize_lang(lang)
                if lg:
                    active_by_lang[lg] = active_by_lang.get(lg, 0) + 1

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
            if a_now < min_recent_count:
                continue  # too few articles for the normal approximation behind the z-test
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
            kw_lang = normalize_lang(kw.language) if kw.language else None
            if kw_lang:
                term_sources = int(
                    session.query(func.count(distinct(KeywordMention.source_id)))
                    .filter(
                        KeywordMention.keyword_id == kid,
                        KeywordMention.observed_on >= r_start,
                        KeywordMention.observed_on < r_hi,
                    )
                    .scalar()
                    or 0
                )
                if is_generic_by_df_ubiquity(term_sources, active_by_lang.get(kw_lang, 0)):
                    continue  # publishing furniture / a term nearly every active source carries
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
        "min_recent_count": min_recent_count,
        "method": (
            "Per WEB-publisher source (a newsletter import / law tracker / wiki edition is "
            "not a publisher and is excluded) with >= {mra} recent articles and >= {mpa} "
            "prior-period articles, and the keyword itself mentioned in >= {mrc} recent "
            "articles (a count floor so the z-test's normal approximation is not asked to "
            "trust 2-3 articles): a two-proportion z-test of its recent share of a keyword "
            "(>= {ms}) vs its own prior share. Fires at z >= {zm}. Excludes a keyword carried "
            "by >= {gts:.0%} of same-language active sources in the window (publishing "
            "furniture / attribution boilerplate, not a real topic). Reads the denormalised "
            "source_id only (no content decrypt), so it covers re-indexed articles. Counts "
            "only, no score.".format(
                mra=min_recent_articles, mpa=min_prior_articles, ms=min_share, zm=z_min,
                mrc=min_recent_count, gts=GENERIC_TERM_MIN_SHARE,
            )
        ),
        "caveat": FLOOD_CAVEAT,
    }


BURY_CAVEAT = (
    "One source covered a topic FAR BELOW the norm of OTHER SOURCES IN ITS OWN LANGUAGE — "
    "a topic those same-language peers covered heavily. (The comparison is language-scoped "
    "so a source is never flagged for not covering a topic simply because it writes in a "
    "different language.) The overwhelming innocent explanation is still SPECIALIZATION: a "
    "source has a different beat or region, so covering a widely-covered topic little (or "
    "not at all) is normal and expected. This names a SHAPE — 'this source, this "
    "broadly-covered topic, far below where its same-language peers sit' — never a claim "
    "the source deliberately buried or suppressed it. Read it and judge. And note: the "
    "absence of a flag here is NOT evidence that nothing was under-covered — this surfaces "
    "only the sharpest gaps that survive multiple-testing correction."
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

    # SAME-LANGUAGE COHORT SCOPING (field test 2026-07-08): a source is only compared
    # against other sources for a keyword OF ITS OWN LANGUAGE. Without this, a non-English
    # source that simply writes in its own language (covering "verkiezingen", not the
    # English keyword "election") looked like it was "burying" every English topic — a
    # false positive, not suppression. A pair whose source-language or keyword-language is
    # unknown is skipped (miss over invent). (Ring translations that bridge languages —
    # election/verkiezingen as one concept — are a labelled follow-up.)
    from src.analytics.managed import normalize_lang

    source_lang: dict[int, str] = {}
    for i in range(0, len(cand_ids), 400):
        for sid, lang in session.query(Source.id, Source.language).filter(
            Source.id.in_(cand_ids[i : i + 400])
        ):
            source_lang[int(sid)] = normalize_lang(lang)
    keyword_lang: dict[int, str] = {}
    for i in range(0, len(big_ids), 400):
        for kid, lang in session.query(Keyword.id, Keyword.language).filter(
            Keyword.id.in_(big_ids[i : i + 400])
        ):
            keyword_lang[int(kid)] = normalize_lang(lang)

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
        s_lang = source_lang.get(sid)
        for kid in big_ids:
            # Same-language cohort: exclude a pair only when we have POSITIVE evidence the
            # source and keyword are in DIFFERENT languages — a non-English source does not
            # "bury" an English keyword it simply never uses (it writes its own language).
            # When either language is unknown we cannot rule out same-language, so the pair
            # is still compared (the pre-change behaviour); a real corpus carries languages
            # (Source.language from the catalog, Keyword.language from the reconcile pass),
            # so the labelled cross-language false positive is the case actually fixed.
            kw_lang = keyword_lang.get(kid)
            if kw_lang and s_lang and s_lang != kw_lang:
                continue
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
        # The exact analyzed set for a click-through: the widely-covered topic's own
        # corpus-wide articles in this window -- the "elsewhere" this source is under-
        # covering (the source's own on-topic set, t["a_s"], is often near-empty by
        # construction, which is the whole point of the finding and not useful to open).
        article_ids = sorted(
            r[0]
            for r in session.query(KeywordMention.article_id)
            .filter(
                KeywordMention.keyword_id == t["kid"],
                KeywordMention.observed_on >= cutoff,
                KeywordMention.observed_on < hi,
            )
            .distinct()
        )
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
                "cohort_language": keyword_lang.get(t["kid"]),
                "fdr_qvalue": round(adj_q, 5) if adj_q is not None else None,
                "article_ids": article_ids,
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
        "same_language_scoped": True,
        "method": _METHOD,
        "caveat": BURY_CAVEAT,
    }


_METHOD = (
    "For every (source with enough articles, topic broad across the corpus) pair in the "
    "window: a two-proportion z-test of the source's share of the topic vs the "
    "rest-of-corpus share (one-sided, is the source BELOW?). SAME-LANGUAGE COHORT SCOPING: "
    "a pair whose source and keyword are KNOWN to be in different languages is excluded, so "
    "a non-English source is never flagged for 'burying' an English keyword it simply never "
    "uses (it writes its own language) — only under-coverage relative to same-language peers "
    "counts (when either language is unknown the pair is still compared). The whole family "
    "of pairs is corrected with Benjamini-Hochberg FDR; a pair is surfaced only if it "
    "survives at the FDR level AND its gap clears z <= -z_min. Distinct SOURCES measure a "
    "topic's breadth. Reads the denormalised source_id + the small source/keyword language "
    "columns only (no content decrypt). Counts only, no score."
)


# --------------------------------------------------------------------------- #
#  Reading diet BY CONTENT CHANNEL — content-provenance S3
#
#  The SAME concentration/diet lens as the source-axis ``diet_self_audit`` producer
#  (src/briefing/producers.py), applied to the CHANNEL axis (``Source.source_type``):
#  over a window, what SHARE of the articles you COLLECTED each content channel
#  (news / newsletter / wiki / statistics / law / market / discovery / ...) accounts
#  for, plus a concentration measure (dominant-channel share + Gini) and an honest
#  95% interval. "How much of my reading is newsletters vs web vs wiki."
#
#  It reuses the shared honest machinery — ``src.signals.concentration.concentration``
#  (Gini + top-N share) and ``src.signals.intervals.wilson_interval`` (the closed-form
#  95% CI the cards use) — so the maths is byte-identical to the source-axis path.
# --------------------------------------------------------------------------- #

DIET_BY_TYPE_CAVEAT = (
    "This is a descriptive breakdown of WHERE your recent reading came from, by content "
    "channel — an asserted fact known by construction (the ingest path / catalog sets the "
    "channel), never a quality or credibility score. Counts only. Concentration (the "
    "dominant-channel share and the Gini coefficient) measures how unevenly your intake is "
    "spread across channels, not whether that spread is good or bad. The 95% interval "
    "describes uncertainty WITHIN your corpus — a self-selected sample you chose the "
    "sources for — never the world. Selection is yours: this is a mirror, not a cap."
)

# Below this many articles in the window the split is a thin sample: still a real count,
# but the caveat says so (mirrors the source-axis diet producer's early-corpus note).
_DIET_SMALL_N = 20


def reading_diet_by_type(
    session,
    *,
    days: int = 30,
    top_n: int = 1,
) -> dict:
    """Reading diet across content CHANNELS (``Source.source_type``) over a window.

    Over the last ``days`` days, the SHARE of the articles you COLLECTED that each content
    channel accounts for, with a concentration measure (the dominant-channel share + the
    Gini coefficient over the channel counts) and an honest Wilson 95% interval on that
    share. Counts only, NO score. Method + caveat + n travel in the payload; a corpus too
    small for the window degrades to an honest empty state, never a fabricated split.

    Window: ``Article.created_at`` (the acquisition time — the un-spoofable "when it
    entered your corpus", matching the source-axis diet path), never the source-controlled
    ``published_at``. The window is served by ``idx_article_created_at``.

    PERF (SQLCipher column-order codec trap): a GROUP BY over articles joined to the small
    ``sources`` table. The window is a range scan on ``idx_article_created_at`` (EXPLAIN
    QUERY PLAN: SEARCH articles USING INDEX idx_article_created_at) joined to sources by
    primary key; it reads only small columns (``source_type`` / ``created_at`` / ``id`` /
    ``source_id``) and NEVER the article ``content`` column, so the codec never drags the
    large content payload (the 35 KB-row trap). ``Article.source_id`` is NOT NULL, so every
    windowed article is counted exactly once, and a channel's articles match the BUCKETING of
    the /api/articles ``source_type`` filter (identical normalisation), so the two never
    disagree on which channel an article belongs to.

    ``top_n`` defaults to 1 (not the source axis's 3): a channel axis has FEW actors, so the
    single dominant-channel share is the interpretable concentration headline — the full
    per-channel breakdown (``channels``) and the Gini carry the rest. The Wilson CI is on the
    top-``top_n`` share, computed from the exact integer channel counts (never a float round).
    """
    from src.analytics.queries import SOURCE_TYPE_UNTYPED
    from src.database.models import Article, Source
    from src.signals.concentration import concentration as _concentration
    from src.signals.intervals import wilson_interval

    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        session.query(Source.source_type, func.count(Article.id))
        .join(Article, Article.source_id == Source.id)
        .filter(Article.created_at >= cutoff)
        .group_by(Source.source_type)
        .all()
    )

    # Normalise identically to source_type_facets / the /api/articles filter (lowercase;
    # NULL/blank -> untyped), so a channel here is the SAME bucket clicking that channel gives.
    counts: dict[str, int] = {}
    for st, c in rows:
        key = (st or "").strip().lower() or SOURCE_TYPE_UNTYPED
        counts[key] = counts.get(key, 0) + int(c)

    # Pass a float-valued mapping (the shared primitive is typed dict[str, float]); the
    # integer counts stay in ``counts`` for the exact top-count arithmetic below.
    result = _concentration({k: float(v) for k, v in counts.items()}, top_n=top_n)
    total = int(result.total)

    channels = [
        {"source_type": str(s["label"]), "articles": int(s["value"]), "share": s["share"]}
        for s in result.shares
    ]
    # Exact top-``top_n`` count from the integer channel counts (never a float round),
    # for a Wilson 95% CI on the dominant-channel share.
    ordered = sorted(counts.values(), reverse=True)
    k = max(1, min(top_n, len(ordered))) if ordered else 0
    top_count = sum(ordered[:k])
    ci = wilson_interval(top_count, total) if total > 0 else None

    extra = ""
    if total == 0:
        extra = " No articles were collected in this window, so there is no diet to show."
    else:
        if result.n < 2:
            extra += (
                " Only one channel is present in this window, so there is no concentration to "
                "compare across channels — the Gini is undefined (null) and the share is 100% "
                "of a single channel."
            )
        if total < _DIET_SMALL_N:
            extra += (
                f" Early-corpus note: only {total} article(s) in this window — read this as a "
                "first hint from a small sample, not an established reading pattern."
            )

    payload = {
        "days": days,
        "total": total,
        "n_channels": result.n,
        "top_n": result.top_n,
        "top_share": result.top_share,
        "top_channels": [c["source_type"] for c in channels[:k]],
        "gini": result.gini,
        "interval": (
            {"low": ci.low, "high": ci.high, "method": ci.method} if ci is not None else None
        ),
        "small_n": 0 < total < _DIET_SMALL_N,  # a thin but NON-empty sample (empty -> note)
        "channels": channels,
        "method": (
            "Article counts grouped by the source's asserted source_type channel over the "
            f"last {days} days (windowed on created_at, the acquisition time; lowercased, a "
            f"source with no asserted channel is bucketed '{SOURCE_TYPE_UNTYPED}'). Share = a "
            "channel's articles / all windowed articles. Concentration = the Gini coefficient "
            f"over the channel counts + the top-{result.top_n} channel share, with a Wilson "
            "score 95% interval on that share. Reads only small columns (never the article "
            "content), so no large-payload codec decrypt. Counts only, no score."
        ),
        "caveat": DIET_BY_TYPE_CAVEAT + extra,
    }
    if total == 0:
        payload["note"] = "no articles collected in this window"
    return payload
