"""Recycled-claim detection (manipulation-pattern card, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent or truth (the manipulation-card doctrine): when a
RECENT article is near-identical to a MUCH OLDER one, the same text has resurfaced
after lying dormant. Recycling old content as if it were new is a known information
tactic — but the innocent explanations are many (an anniversary piece, an evergreen
explainer re-run, a wire story re-published), so the shape flagged is only "the same
text, much later", never a claim it was deliberate.

This is the TEMPORAL sibling of the coordination/echo signals: it reuses the proven,
deterministic near-duplicate primitive (MinHash + LSH, high-precision / biased toward
under-merging) rather than any fuzzy NLP, so it is honest and testable. It differs from
echo-chamber (near-duplication inside a SHORT publishing window = coordinated
co-publication) by requiring a LARGE dormancy gap between the oldest and newest member.

HONESTY (enforced in code, not just prose):
  * the trigger is a measured time GAP (days between the oldest and newest member),
    never a score;
  * a cluster only surfaces when at least one member is RECENT (a current resurfacing,
    not two equally-old near-dups);
  * a single source re-running its own evergreen content is surfaced but FLAGGED
    ``single_source`` (one voice, not cross-source spread);
  * the scan is bounded (a recent pool + an older pool, both capped) and that bound is
    stated in the method; NO score, NO verdict — the exact article set + real dates
    travel with the card and the innocent explanation is stated beside the pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

RECYCLED_CAVEAT = (
    "Near-identical text that has resurfaced long after it first appeared. The innocent "
    "explanations are many — an anniversary piece, an evergreen explainer re-run, a wire "
    "story re-published — but recycling old content as if it were new is also a known "
    "tactic. The shape is 'the same text, much later', never a claim it was deliberate. "
    "Read both and judge."
)


def find_recycled_claims(
    session,
    *,
    recent_days: int = 14,
    lookback_days: int = 365,
    min_gap_days: int = 60,
    threshold: float = 0.7,
    min_chars: int = 200,
    recent_limit: int = 800,
    older_limit: int = 1200,
    max_clusters: int = 12,
) -> dict:
    """Recent articles that near-duplicate a much OLDER one — a claim resurfacing.

    Pulls a bounded RECENT pool (``observed >= now - recent_days``) and a bounded OLDER
    pool (``now - lookback_days <= observed < now - recent_days``), clusters both with the
    high-precision near-duplicate clusterer, and keeps clusters that (a) span at least
    ``min_gap_days`` between their oldest and newest member AND (b) contain at least one
    recent member. Read-only; counts + real dates only; no score.
    """
    from src.database.models import Article, Source

    now = datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=recent_days)).replace(tzinfo=None)
    lookback_cutoff = (now - timedelta(days=lookback_days)).replace(tzinfo=None)
    observed = func.coalesce(Article.published_at, Article.created_at)

    def _pull(lo, hi, cap):
        q = (
            session.query(Article, Source.name, Source.domain)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(observed >= lo)
        )
        if hi is not None:
            q = q.filter(observed < hi)
        return q.order_by(Article.id.desc()).limit(cap).all()

    rows = _pull(recent_cutoff, None, recent_limit) + _pull(
        lookback_cutoff, recent_cutoff, older_limit
    )

    docs: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for a, sname, sdom in rows:
        text = ((a.title or "") + "\n" + (a.get_content() or "")).strip()
        if len(text) < min_chars:
            continue
        when = a.published_at or a.created_at
        docs[str(a.id)] = text
        meta[str(a.id)] = {
            "id": a.id,
            "title": a.title,
            "source": sname or sdom or f"source-{a.source_id}",
            "url": a.url,
            "when": when,
        }

    from src.signals.near_dup import near_duplicate_clusters

    res = near_duplicate_clusters(docs, threshold=threshold)

    clusters: list[dict] = []
    for c in res.clusters:
        members = [meta[m] for m in c.members if m in meta and meta[m]["when"]]
        if len(members) < 2:
            continue
        members.sort(key=lambda m: m["when"])
        oldest, newest = members[0], members[-1]
        gap_days = (newest["when"] - oldest["when"]).days
        if gap_days < min_gap_days:
            continue  # not dormant long enough — that's echo-chamber territory
        if newest["when"] < recent_cutoff:
            continue  # no current resurfacing — both members are old
        srcs = sorted({m["source"] for m in members})
        clusters.append({
            "gap_days": gap_days,
            "n_articles": len(members),
            "distinct_sources": len(srcs),
            "single_source": len(srcs) <= 1,
            "sources": srcs,
            "first_seen": oldest["when"].date().isoformat(),
            "resurfaced": newest["when"].date().isoformat(),
            "original_title": oldest["title"],
            "recent_title": newest["title"],
            "article_ids": sorted(m["id"] for m in members),
            "avg_similarity": round(c.avg_similarity, 3),
        })

    clusters.sort(key=lambda x: (-x["gap_days"], -x["n_articles"]))
    clusters = clusters[:max_clusters]

    return {
        "clusters": clusters,
        "count": len(clusters),
        "min_gap_days": min_gap_days,
        "recent_days": recent_days,
        "lookback_days": lookback_days,
        "method": (
            "Near-duplicate clusters (MinHash+LSH, Jaccard >= {th}) spanning >= {g} days "
            "between the oldest and newest member, with at least one member in the last "
            "{r} days. Bounded scan: up to {rl} recent + {ol} older articles. The gap is a "
            "measured time span, not a score.".format(
                th=threshold,
                g=min_gap_days,
                r=recent_days,
                rl=recent_limit,
                ol=older_limit,
            )
        ),
        "caveat": RECYCLED_CAVEAT,
    }
