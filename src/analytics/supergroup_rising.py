"""Rising super-groups — a theme's recent SHARE of corpus activity vs its own
baseline (supergroups brief S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A group "rises" when its recent SHARE of the corpus's total daily mention volume is
significantly higher than its own prior-period share — a two-proportion z-test
(the SAME closed-form test ``find_flooded_topics``/``find_buried_topics`` already
use), corrected for the ~77-group family with Benjamini-Hochberg FDR
(:mod:`src.stats.fdr`), never a bare p-value. Share-normalized against total corpus
mention volume — NEVER raw counts, which would conflate a group's own rise with the
corpus simply growing (more sources, a longer collection run).

Birth constraints (Leads-calibration lessons, prerequisites not future fixes):
  * a count floor before a group even enters the test family (no z-theater on a
    handful of mentions);
  * the FDR + effect-size (z_min) gate, exactly like the existing flood/bury cards;
  * a rise driven almost entirely by ONE member is disclosed in the card, and a rise
    driven by a member that is itself GENERIC/UBIQUITOUS (the shared DF-ubiquity
    gate — a publishing-boilerplate word, or a term nearly every active source in
    its language carries) is not a real theme rising and is never a Lead at all.

Reuses (never rebuilds): the S1 member-resolution primitive
(:mod:`src.analytics.supergroup_stats`), the rollup-serve windowed machinery, and
the shared generic-term gate (:mod:`src.analytics.generic_terms`).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from src.analytics.supergroup_stats import _chunks

RISING_CAVEAT = (
    "A theme's SHARE of your corpus's total daily activity, compared to its own prior "
    "period — never raw counts (which would just track the corpus growing), never a "
    "significance test of 'importance', and never causation. Survives multiple-testing "
    "correction across every tracked group; a rise driven almost entirely by one member "
    "is stated, and a rise driven by a generic/ubiquitous word is never surfaced at all."
)


def _phi(z: float) -> float:
    """Standard-normal CDF via ``math.erf`` — the same closed-form helper every
    two-proportion z-test producer in this codebase defines locally."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _corpus_volume(db, lo: date, hi: date) -> int:
    """Total keyword-mention volume over ``[lo, hi)`` across the WHOLE corpus — the
    honest denominator for a group's SHARE. Prefers the rollup-serve windowed
    machinery (never rebuilt here); falls back to a direct, index-driven scan of
    the denormalised ``keyword_mentions.count`` on any miss."""
    from src.analytics import rollup_serve

    served = rollup_serve.windowed_counts(db, lo=lo, hi=hi - timedelta(days=1))
    if served is not None:
        return sum(served.values())
    from sqlalchemy import func

    from src.database.models import KeywordMention

    total = (
        db.query(func.coalesce(func.sum(KeywordMention.count), 0))
        .filter(KeywordMention.observed_on >= lo, KeywordMention.observed_on < hi)
        .scalar()
    )
    return int(total or 0)


def _distinct_sources_windowed(db, keyword_ids, lo: date, hi: date) -> int:
    from src.database.models import KeywordMention

    ids = sorted(keyword_ids)
    if not ids:
        return 0
    seen: set[int] = set()
    for chunk in _chunks(ids):
        for (sid,) in (
            db.query(KeywordMention.source_id)
            .filter(
                KeywordMention.keyword_id.in_(chunk),
                KeywordMention.observed_on >= lo,
                KeywordMention.observed_on < hi,
                KeywordMention.source_id.isnot(None),
            )
            .distinct()
        ):
            seen.add(int(sid))
    return len(seen)


def _article_ids_windowed(db, keyword_ids, lo: date, hi: date) -> list[int]:
    from src.database.models import KeywordMention

    ids = sorted(keyword_ids)
    if not ids:
        return []
    out: set[int] = set()
    for chunk in _chunks(ids):
        for (aid,) in (
            db.query(KeywordMention.article_id)
            .filter(
                KeywordMention.keyword_id.in_(chunk),
                KeywordMention.observed_on >= lo,
                KeywordMention.observed_on < hi,
            )
            .distinct()
        ):
            out.add(int(aid))
    return sorted(out)


def _dominant_language(db, keyword_ids, mentions_by_id: dict[int, int]) -> str | None:
    """The mention-weighted majority language among ``keyword_ids`` (small-column
    read of ``Keyword.language`` only)."""
    from src.analytics.managed import normalize_lang
    from src.database.models import Keyword

    ids = sorted(keyword_ids)
    if not ids:
        return None
    lang_mentions: dict[str, int] = {}
    for chunk in _chunks(ids):
        for kid, lang in db.query(Keyword.id, Keyword.language).filter(Keyword.id.in_(chunk)):
            lg = normalize_lang(lang)
            if lg:
                lang_mentions[lg] = lang_mentions.get(lg, 0) + mentions_by_id.get(int(kid), 0)
    if not lang_mentions:
        return None
    return max(lang_mentions, key=lambda k: lang_mentions[k])


def find_rising_supergroups(
    db,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    min_recent_mentions: int = 20,
    z_min: float = 2.5,
    fdr_q: float = 0.05,
    max_items: int = 8,
    today: date | None = None,
) -> dict:
    """Super-groups whose recent share of corpus mention volume rose against their
    own baseline, surviving FDR correction across every tracked group.

    Returns ``{items: [...], count, tested, window_days, baseline_days, z_min,
    fdr_q, min_recent_mentions, method, caveat}``. Each item: ``{name, sg_id, z,
    share_now, share_prior, recent_mentions, prior_mentions, driven_by,
    driven_share, distinct_sources, article_ids}``. Empty when nothing survives —
    NEVER a fabricated rise."""
    from src.analytics.generic_terms import is_generic_by_df_ubiquity
    from src.analytics.supergroup_stats import _per_id_mentions, distinct_ids, resolve_member_keyword_ids
    from src.database.models import KeywordSuperGroup
    from src.stats.fdr import benjamini_hochberg

    method = (
        "Two-proportion z-test of each group's recent SHARE of the corpus's total "
        "daily mention volume vs its own prior-period share (never raw counts); "
        "corrected for the whole tested family with Benjamini-Hochberg FDR at "
        f"q={fdr_q}, then gated at z >= {z_min}. A group needs >= {min_recent_mentions} "
        "recent mentions before it is even tested (no significance theater on a "
        "handful of mentions)."
    )

    def _empty(reason: str) -> dict:
        return {
            "items": [], "count": 0, "tested": 0, "window_days": window_days,
            "baseline_days": baseline_days, "z_min": z_min, "fdr_q": fdr_q,
            "min_recent_mentions": min_recent_mentions, "method": method,
            "caveat": RISING_CAVEAT, "reason": reason,
        }

    today = today or date.today()
    w_start = today - timedelta(days=window_days)
    b_start = w_start - timedelta(days=baseline_days)
    hi = today + timedelta(days=1)

    sgs = db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    if not sgs:
        return _empty("no super-groups")

    member_rows = list({(m.normalized_term, m.ring_id) for sg in sgs for m in sg.members})
    id_sets = resolve_member_keyword_ids(db, member_rows)

    corpus_recent = _corpus_volume(db, w_start, hi)
    corpus_prior = _corpus_volume(db, b_start, w_start)
    if corpus_recent <= 0 or corpus_prior <= 0:
        return _empty("no measurable corpus activity in the compared windows")

    from sqlalchemy import distinct, func

    from src.analytics.managed import normalize_lang
    from src.database.models import KeywordMention, Source

    # Active same-language source counts over the recent window — the DF-ubiquity
    # gate's denominator, built ONCE (the find_flooded_topics pattern), not per group.
    src_recent = dict(
        db.query(KeywordMention.source_id, func.count(distinct(KeywordMention.article_id)))
        .filter(
            KeywordMention.observed_on >= w_start,
            KeywordMention.observed_on < hi,
            KeywordMention.source_id.isnot(None),
        )
        .group_by(KeywordMention.source_id)
        .all()
    )
    active_by_lang: dict[str, int] = {}
    if src_recent:
        sids = list(src_recent)
        for chunk in _chunks(sids):
            for _sid, lang in db.query(Source.id, Source.language).filter(Source.id.in_(chunk)):
                lg = normalize_lang(lang)
                if lg:
                    active_by_lang[lg] = active_by_lang.get(lg, 0) + 1

    tests: list[dict] = []
    pvals: list[float] = []
    for sg in sgs:
        member_keys = [(m.normalized_term, m.ring_id) for m in sg.members]
        group_id_sets = {k: id_sets.get(k, set()) for k, _ in member_keys}
        group_ids = distinct_ids(group_id_sets)
        if not group_ids:
            continue
        recent_by_id = _per_id_mentions(db, group_ids, w_start, hi)
        group_recent = sum(recent_by_id.values())
        if group_recent < min_recent_mentions:
            continue  # count floor -- no z-theater on tiny counts
        prior_by_id = _per_id_mentions(db, group_ids, b_start, w_start)
        group_prior = sum(prior_by_id.values())

        p_now = group_recent / corpus_recent
        p_prior = group_prior / corpus_prior
        pooled = (group_recent + group_prior) / (corpus_recent + corpus_prior)
        if pooled <= 0 or pooled >= 1:
            continue
        se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / corpus_recent + 1.0 / corpus_prior))
        if se <= 0:
            continue
        z = (p_now - p_prior) / se
        tests.append(
            {
                "sg": sg, "z": z, "group_ids": group_ids, "recent_by_id": recent_by_id,
                "group_recent": group_recent, "group_prior": group_prior,
                "p_now": p_now, "p_prior": p_prior,
            }
        )
        pvals.append(1.0 - _phi(z))  # upper-tail: how surprising a share THIS HIGH is

    if not tests:
        return _empty("no group cleared the recent-mentions floor")

    fdr = benjamini_hochberg(pvals, q=fdr_q)
    survivors = set(fdr.rejected)
    hits = [t for idx, t in enumerate(tests) if idx in survivors and t["z"] >= z_min]
    hits.sort(key=lambda t: -t["z"])

    items: list[dict] = []
    for t in hits:
        sg = t["sg"]
        recent_by_id = t["recent_by_id"]
        member_recent: dict[str, int] = {}
        for norm_term, _ring_id in ((m.normalized_term, m.ring_id) for m in sg.members):
            ids = id_sets.get(norm_term, set())
            member_recent[norm_term] = sum(recent_by_id.get(i, 0) for i in ids)
        if not member_recent or max(member_recent.values()) <= 0:
            continue
        top_key = max(member_recent, key=lambda k: member_recent[k])
        top_val = member_recent[top_key]
        driven_share = top_val / t["group_recent"]

        # The generic-ubiquity gate on the DRIVING member: a rise driven by
        # attribution boilerplate or a corpus-volume tracker is not a real theme.
        top_ids = id_sets.get(top_key, set())
        dom_lang = _dominant_language(db, top_ids, recent_by_id)
        if dom_lang:
            n_with = _distinct_sources_windowed(db, top_ids, w_start, hi)
            n_active = active_by_lang.get(dom_lang, 0)
            if is_generic_by_df_ubiquity(n_with, n_active):
                continue  # a rise driven by a generic/ubiquitous word is not a Lead

        items.append(
            {
                "name": sg.name,
                "sg_id": sg.id,
                "z": round(t["z"], 2),
                "share_now": round(t["p_now"], 5),
                "share_prior": round(t["p_prior"], 5),
                "recent_mentions": t["group_recent"],
                "prior_mentions": t["group_prior"],
                "driven_by": top_key,
                "driven_share": round(driven_share, 3),
                "distinct_sources": _distinct_sources_windowed(db, t["group_ids"], w_start, hi),
                "article_ids": _article_ids_windowed(db, t["group_ids"], w_start, hi),
            }
        )
        if len(items) >= max_items:
            break

    return {
        "items": items,
        "count": len(items),
        "tested": len(tests),
        "window_days": window_days,
        "baseline_days": baseline_days,
        "z_min": z_min,
        "fdr_q": fdr_q,
        "min_recent_mentions": min_recent_mentions,
        "method": method,
        "caveat": RISING_CAVEAT,
    }
