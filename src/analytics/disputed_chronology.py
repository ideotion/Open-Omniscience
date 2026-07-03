"""Disputed chronology — the SAME story dated differently across sources.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names a STRUCTURE, never intent: within a near-duplicate STORY cluster (articles whose
text is near-identical — the project's canonical "same story" primitive), the DEDUCED
event dates disagree across DISTINCT sources. One source places the event on one date,
another on a materially different date, and neither's date is echoed by the other.

The honest reading is a SHAPE worth a human look, not a verdict:
  * a genuine cross-source disagreement about WHEN something happened is worth checking;
  * BUT the innocent explanations are many and stated beside it — date-extraction
    AMBIGUITY (e.g. 11/06 read day-first vs month-first, common across languages), an
    article that legitimately mentions several dates (a timeline / anniversary), or an
    update/republish date vs the event's own date. Dates are DEDUCED from text, never
    confirmed.

Independence is measured by DISTINCT SOURCES (not article count): one source disagreeing
with itself is not a disputed chronology. Reads the deduced ``article_mentioned_dates``
(day precision, non-rejected) — the same substrate the space-time convergence card uses.
No composite score; every figure is a real count.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from src.database.models import (
    Article,
    ArticleMentionedDate,
    Source,
)

_LOG = logging.getLogger(__name__)

# Bound on SQL IN() chunks (well under SQLite's variable limit).
_IN_CHUNK = 600

DISPUTED_CAVEAT = (
    "Sources telling the SAME story give it DIFFERENT event dates — a shape worth "
    "checking, never a verdict. The innocent explanations are many and common: "
    "date-extraction AMBIGUITY (11/06 read day-first vs month-first differs by "
    "languages), an article that legitimately lists several dates (a timeline or "
    "anniversary piece), or an update/republish date mistaken for the event date. "
    "Dates are DEDUCED from text, never confirmed; independence is measured by distinct "
    "sources, so one source disagreeing with itself never fires this. Read both and judge."
)

DISPUTED_METHOD = (
    "Recent articles are grouped into near-duplicate STORY clusters (MinHash+LSH over the "
    "text). Within a cluster spanning >= min_sources DISTINCT sources, the deduced "
    "day-precision event dates (article_mentioned_dates, non-rejected) are collected per "
    "source. A dispute is surfaced only when two distinct sources each assert an event "
    "date the other never asserts (within a tolerance) and the two dates differ by more "
    "than the tolerance. Counts + dates only, no score."
)


def _plain_text(content: str | None, compressed) -> str:
    """Best-effort plain text for near-dup, transparently handling compressed storage."""
    if content:
        return content
    if compressed:
        try:
            from src.utils.compression import database_compressor

            return database_compressor.decompress_text_from_storage(compressed)
        except Exception:  # noqa: BLE001 - a bad blob just means this article can't cluster
            return ""
    return ""


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _find_disagreement(
    src_dates: dict[str, set[date]], tolerance_days: int
) -> tuple[list[str], list[str]]:
    """Return (disputed_iso_dates, sources_involved) if two sources genuinely disagree.

    A disagreement exists when there are two distinct sources X != Y and dates dX, dY with
    ``|dX - dY| > tolerance_days`` such that dX is not within ``tolerance_days`` of ANY date
    Y asserts, AND dY is not within ``tolerance_days`` of any date X asserts. That rules out
    the innocent case where both sources cover the same date list (no genuine conflict).
    Returns empty lists when there is no such conflict.
    """

    def _matched(d: date, others: set[date]) -> bool:
        return any(abs((d - o).days) <= tolerance_days for o in others)

    sources = sorted(src_dates)
    disputed: set[date] = set()
    involved: set[str] = set()
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            x, y = sources[i], sources[j]
            dx = {d for d in src_dates[x] if not _matched(d, src_dates[y])}
            dy = {d for d in src_dates[y] if not _matched(d, src_dates[x])}
            conflict = [
                (a, b) for a in dx for b in dy if abs((a - b).days) > tolerance_days
            ]
            if conflict:
                for a, b in conflict:
                    disputed.add(a)
                    disputed.add(b)
                involved.add(x)
                involved.add(y)
    return [d.isoformat() for d in sorted(disputed)], sorted(involved)


def find_disputed_chronology(
    session,
    *,
    lookback_days: int = 30,
    min_sources: int = 2,
    tolerance_days: int = 2,
    threshold: float = 0.6,
    max_articles: int = 2000,
    max_items: int = 8,
    today: date | None = None,
) -> dict:
    """Scan recent near-duplicate story clusters for cross-source date disagreement.

    Returns ``{"items": [...], "count": n, "clusters_scanned": n, "lookback_days": ...,
    "min_sources": ..., "tolerance_days": ..., "method": ..., "caveat": ...}``.
    Bounded (recent window + capped article pool); degrades to an empty, honest result.
    """
    from src.signals.near_dup import near_duplicate_clusters

    today = today or datetime.now(UTC).date()
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    cutoff_naive = cutoff.replace(tzinfo=None)

    rows = (
        session.query(
            Article.id,
            Source.name,
            Article.title,
            Article.content,
            Article.compressed_content,
        )
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(
            (Article.published_at.is_(None))
            | (Article.published_at >= cutoff_naive)
            | (Article.created_at >= cutoff_naive)
        )
        .order_by(Article.id.desc())
        .limit(max_articles)
        .all()
    )

    texts: dict[str, str] = {}
    src_of: dict[str, str | None] = {}
    for aid, sname, title, content, compressed in rows:
        text = _plain_text(content, compressed) or (title or "")
        if len(text) < 200:
            continue
        sid = str(aid)
        texts[sid] = text
        src_of[sid] = sname
    if len(texts) < 2:
        return _empty(lookback_days, min_sources, tolerance_days)

    nd = near_duplicate_clusters(texts, threshold=threshold)
    clusters_scanned = len(nd.clusters)

    # Deduced day-precision event dates for the clustered articles (one bounded query).
    member_ids = [int(m) for c in nd.clusters for m in c.members]
    dates_by_article: dict[int, set[date]] = defaultdict(set)
    for chunk in _chunks(sorted(set(member_ids))):
        for aid, on in (
            session.query(ArticleMentionedDate.article_id, ArticleMentionedDate.mentioned_on)
            .filter(
                ArticleMentionedDate.article_id.in_(chunk),
                ArticleMentionedDate.mentioned_on.isnot(None),
                ArticleMentionedDate.precision == "day",
                ArticleMentionedDate.status != "rejected",
            )
            .all()
        ):
            if on is not None:
                dates_by_article[aid].add(on)

    items: list[dict] = []
    for cluster in nd.clusters:
        sources = {src_of.get(m) for m in cluster.members}
        sources.discard(None)
        if len(sources) < min_sources:
            continue
        # Per-source union of the deduced event dates in this cluster.
        src_dates: dict[str, set[date]] = defaultdict(set)
        for m in cluster.members:
            sname = src_of.get(m)
            if sname is None:
                continue
            src_dates[sname].update(dates_by_article.get(int(m), ()))
        src_dates = {s: d for s, d in src_dates.items() if d}
        if len(src_dates) < min_sources:
            continue
        disputed_dates, involved = _find_disagreement(src_dates, tolerance_days)
        if len(disputed_dates) < 2 or len(involved) < min_sources:
            continue
        span = _date_span_days(disputed_dates)
        article_ids = sorted(int(m) for m in cluster.members)
        by_date = {
            d: sorted(s for s, ds in src_dates.items() if date.fromisoformat(d) in ds)
            for d in disputed_dates
        }
        items.append(
            {
                "article_ids": article_ids,
                "n_articles": len(article_ids),
                "distinct_sources": len(involved),
                "sources": involved,
                "disputed_dates": disputed_dates,
                "distinct_dates": len(disputed_dates),
                "span_days": span,
                "dates_by_source": by_date,
                "avg_similarity": round(cluster.avg_similarity, 4),
            }
        )

    items.sort(key=lambda it: (-it["distinct_sources"], -it["span_days"]))
    items = items[:max_items]
    return {
        "items": items,
        "count": len(items),
        "clusters_scanned": clusters_scanned,
        "lookback_days": lookback_days,
        "min_sources": min_sources,
        "tolerance_days": tolerance_days,
        "method": DISPUTED_METHOD,
        "caveat": DISPUTED_CAVEAT,
    }


def _date_span_days(iso_dates: list[str]) -> int:
    """The SPAN (widest spread) of the disputed dates = latest − earliest, in days.

    For the 2-date minimum this equals the gap between them; for 3+ dates it is the
    span, not the max consecutive gap — which is exactly what we report (how far apart
    the sources' dates sit).
    """
    ds = sorted(date.fromisoformat(d) for d in iso_dates)
    return (ds[-1] - ds[0]).days if len(ds) >= 2 else 0


def _empty(lookback_days: int, min_sources: int, tolerance_days: int) -> dict:
    return {
        "items": [],
        "count": 0,
        "clusters_scanned": 0,
        "lookback_days": lookback_days,
        "min_sources": min_sources,
        "tolerance_days": tolerance_days,
        "method": DISPUTED_METHOD,
        "caveat": DISPUTED_CAVEAT,
    }
