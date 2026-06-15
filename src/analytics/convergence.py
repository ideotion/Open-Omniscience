"""
Space-time co-occurrence — the convergence flagship, slice 1 (read-only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 0.0.9 flagship, finally unblocked now that When×Where×Who PERSISTS at ingest
(``article_mentioned_places`` + ``article_mentioned_dates``). This module is the
FIRST, READ-ONLY slice: it surfaces clusters of articles that converge on the
SAME PLACE within the SAME TIME WINDOW. The user-defined "if-this-then-WATCH"
alert engine is a LATER slice and is deliberately NOT built here.

BINDING ETHICS (maintainer-ruled, non-negotiable — carried on every cluster):
  * **Co-occurrence is NEVER causation.** We report "these N articles mention
    place P around date D" — never that one thing caused another, never a
    narrative. The caveat states this verbatim.
  * **Anti-false-triangulation (the Links methodological ruling, 2026-06-12):**
    convergence corroborates ONLY across INDEPENDENT paths. Articles sharing a
    single origin are ONE source wearing many hats, so the honest measure of a
    cluster is its DISTINCT-SOURCE spread, not the raw article count. A single
    chatty source cannot manufacture a convergence: the surfacing gate requires
    ≥2 distinct sources AND ≥3 articles. We additionally FLAG shared-origin
    structure (outbound URLs cited by more than one member) so the reader can
    see when "independent" sources lean on the same citation.
  * **No composite score** (CardSchemaError). Every figure is a real count: n
    articles, distinct sources, the place, the time window, the date/place
    provenance ("deduced, never confirmed"). Method + caveat always present.

It scans the LOCAL substrate only and NEVER touches the network.

The DATE used is the article's MENTIONED date (the event's own date, the
When×Where×Who anchor) — not the publication date — so a 2024 piece about a
1945 event converges on 1945, which is the honest space-time reading. Rejected
date tags are excluded; candidate + confirmed both count (status is recorded).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.database.models import (
    Article,
    ArticleLink,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Source,
)

_LOG = logging.getLogger(__name__)

# Bound on SQL IN() chunks (well under SQLite's variable limit) — never an
# unbounded scan (the bounded-crawler discipline).
_IN_CHUNK = 600

# The caveat is verbatim and constant (so the i18n engine can translate it
# exactly) — it states the two non-negotiables on every cluster.
CONVERGENCE_CAVEAT = (
    "Co-occurrence in space and time — never causation; convergence corroborates "
    "only across independent sources. Places and dates are deduced from text, never "
    "confirmed. Articles may discuss past, future or figurative events, so a shared "
    "place-and-window is a prompt to read, not proof anything happened."
)

CONVERGENCE_METHOD = (
    "Articles grouped by a DEDUCED place (article_mentioned_places, extractor "
    "lexical-v1) whose DEDUCED event dates (article_mentioned_dates, non-rejected) "
    "fall inside one ±window. Independence is measured as the count of DISTINCT "
    "sources (not the article count); shared outbound links cited by more than one "
    "member are flagged so common-origin convergence is visible. No score; figures "
    "are real counts only."
)


def _normalize_place(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


@dataclass
class ConvergenceCluster:
    """One space-time convergence: N articles on the same place within a window.

    Every field is a real count or a deduced provenance value — there is no
    score, no ranking number that blends dimensions.
    """

    place: str
    place_country: str | None
    place_kind: str | None
    lat: float | None
    lon: float | None
    window_start: str  # ISO date
    window_end: str  # ISO date
    n_articles: int
    distinct_sources: int
    source_names: list[str]
    article_ids: list[int]
    shared_origin_links: int  # outbound URLs cited by >1 member (false-triangulation flag)
    shared_origin_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "place": self.place,
            "place_country": self.place_country,
            "place_kind": self.place_kind,
            "lat": self.lat,
            "lon": self.lon,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "n_articles": self.n_articles,
            "distinct_sources": self.distinct_sources,
            "source_names": self.source_names,
            "article_ids": self.article_ids,
            "shared_origin_links": self.shared_origin_links,
            "shared_origin_examples": self.shared_origin_examples,
            "method": CONVERGENCE_METHOD,
            "caveat": CONVERGENCE_CAVEAT,
        }


def _window_dates_for_articles(
    session, article_ids: list[int]
) -> dict[int, list[date]]:
    """Map article_id -> its non-rejected mentioned event dates (deduced)."""
    out: dict[int, list[date]] = defaultdict(list)
    for chunk in _chunks(article_ids):
        rows = (
            session.query(
                ArticleMentionedDate.article_id, ArticleMentionedDate.mentioned_on
            )
            .filter(
                ArticleMentionedDate.article_id.in_(chunk),
                ArticleMentionedDate.mentioned_on.isnot(None),
                ArticleMentionedDate.status != "rejected",
            )
            .all()
        )
        for aid, on in rows:
            if on is not None:
                out[aid].append(on)
    return out


def _greedy_windows(
    items: list[tuple[int, date]], *, window_days: int
) -> list[tuple[date, date, set[int]]]:
    """Sweep (article_id, date) pairs sorted by date into ±window_days clusters.

    A new article joins the current window if its date is within ``window_days``
    of the window's first (anchor) date; otherwise it opens a new window. This is
    a deterministic single pass — no fabricated interpolation, just which
    articles share a place AND a span. The same article can legitimately appear in
    more than one window if it mentions dates far apart; each window dedups its
    own article set.
    """
    if not items:
        return []
    items = sorted(items, key=lambda p: p[1])
    windows: list[tuple[date, date, set[int]]] = []
    anchor = items[0][1]
    cur_ids: set[int] = set()
    cur_min = cur_max = anchor
    for aid, d in items:
        if (d - anchor).days <= window_days:
            cur_ids.add(aid)
            cur_min = min(cur_min, d)
            cur_max = max(cur_max, d)
        else:
            windows.append((cur_min, cur_max, cur_ids))
            anchor = d
            cur_ids = {aid}
            cur_min = cur_max = d
    windows.append((cur_min, cur_max, cur_ids))
    return windows


def find_convergences(
    session,
    *,
    window_days: int = 7,
    lookback_days: int | None = None,
    min_articles: int = 3,
    min_sources: int = 2,
    limit: int = 12,
    today: date | None = None,
) -> dict:
    """Scan the local When×Where×Who substrate for space-time convergences.

    Parameters
    ----------
    window_days
        Half-width of the time window in days (the documented default is 7, i.e.
        a ±7-day span around an anchor event date). Articles whose deduced event
        dates fall within this span of one another, sharing a place, converge.
    lookback_days
        If given, only consider mentioned dates within this many days of
        ``today`` (the recent past). ``None`` = the whole corpus history (so a
        2024 piece about a 1945 event still converges on 1945).
    min_articles, min_sources
        The conservative surfacing gate (anti-false-triangulation): a cluster is
        surfaced only when it has ``>= min_articles`` distinct articles AND
        ``>= min_sources`` DISTINCT sources. A single chatty source publishing
        many copies cannot manufacture a convergence.

    Returns
    -------
    ``{"clusters": [cluster_dict, ...], "clusters_total": n, "scanned_places": n,
    "window_days": w, "min_articles": .., "min_sources": ..}`` — totals are
    always disclosed so the display ``limit`` never silently hides how much
    qualified.
    """
    today = today or date.today()

    # 1) Pull the deduced place rows (small columns only — the SQLCipher lesson:
    #    never drag whole article rows through the codec for an aggregate).
    place_rows = session.query(
        ArticleMentionedPlace.article_id,
        ArticleMentionedPlace.name,
        ArticleMentionedPlace.country,
        ArticleMentionedPlace.kind,
        ArticleMentionedPlace.lat,
        ArticleMentionedPlace.lon,
    ).all()
    if not place_rows:
        return _empty(window_days, min_articles, min_sources)

    # place identity (country, normalized-name) -> articles + a representative
    # display name / kind / coordinate.
    place_articles: dict[tuple[str, str], set[int]] = defaultdict(set)
    place_meta: dict[tuple[str, str], dict] = {}
    for aid, name, country, kind, lat, lon in place_rows:
        pk = _normalize_place(name)
        if not pk:
            continue
        key = (country or "", pk)
        place_articles[key].add(aid)
        meta = place_meta.setdefault(
            key,
            {"name": name, "country": country, "kind": kind, "lat": None, "lon": None},
        )
        if meta["lat"] is None and lat is not None and lon is not None:
            meta["lat"], meta["lon"] = lat, lon
            meta["kind"] = kind or meta["kind"]

    # 2) Event dates for the candidate articles (deduced; rejected excluded).
    all_article_ids = sorted({a for ids in place_articles.values() for a in ids})
    dates_by_article = _window_dates_for_articles(session, all_article_ids)
    if not dates_by_article:
        return _empty(window_days, min_articles, min_sources, scanned=len(place_articles))

    cutoff = today - timedelta(days=lookback_days) if lookback_days else None

    # 3) For each place, window its dated articles and keep the windows that pass
    #    the article gate (the source gate needs the source lookup; do it after).
    candidate_windows: list[tuple[tuple[str, str], date, date, set[int]]] = []
    for key, article_ids in place_articles.items():
        items: list[tuple[int, date]] = []
        for aid in article_ids:
            for d in dates_by_article.get(aid, ()):
                if cutoff is not None and d < cutoff:
                    continue
                items.append((aid, d))
        for wmin, wmax, ids in _greedy_windows(items, window_days=window_days):
            if len(ids) >= min_articles:
                candidate_windows.append((key, wmin, wmax, ids))

    if not candidate_windows:
        return _empty(window_days, min_articles, min_sources, scanned=len(place_articles))

    # 4) Resolve source identity for the independence measure (small columns).
    need_ids = sorted({a for _, _, _, ids in candidate_windows for a in ids})
    src_of: dict[int, int | None] = {}
    src_name: dict[int, str | None] = {}
    for chunk in _chunks(need_ids):
        for aid, sid, sname in (
            session.query(Article.id, Article.source_id, Source.name)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(Article.id.in_(chunk))
            .all()
        ):
            src_of[aid] = sid
            src_name[aid] = sname

    clusters: list[ConvergenceCluster] = []
    for key, wmin, wmax, ids in candidate_windows:
        ids_sorted = sorted(ids)
        source_ids = {src_of.get(a) for a in ids_sorted}
        source_ids.discard(None)
        distinct_sources = len(source_ids)
        if distinct_sources < min_sources:
            continue  # the independence gate: one source wearing many hats ≠ convergence
        names = sorted({n for a in ids_sorted if (n := src_name.get(a))})
        shared_n, shared_examples = _shared_origin(session, ids_sorted)
        meta = place_meta[key]
        clusters.append(
            ConvergenceCluster(
                place=meta["name"],
                place_country=meta["country"] or None,
                place_kind=meta["kind"],
                lat=meta["lat"],
                lon=meta["lon"],
                window_start=wmin.isoformat(),
                window_end=wmax.isoformat(),
                n_articles=len(ids_sorted),
                distinct_sources=distinct_sources,
                source_names=names,
                article_ids=ids_sorted,
                shared_origin_links=shared_n,
                shared_origin_examples=shared_examples,
            )
        )

    # Order by independence first (distinct sources), then volume, then recency —
    # never a blended score, just a tuple of honest counts.
    clusters.sort(key=lambda c: (-c.distinct_sources, -c.n_articles, c.window_end))
    return {
        "clusters": [c.to_dict() for c in clusters[:limit]],
        "clusters_total": len(clusters),
        "scanned_places": len(place_articles),
        "window_days": window_days,
        "min_articles": min_articles,
        "min_sources": min_sources,
        "method": CONVERGENCE_METHOD,
        "caveat": CONVERGENCE_CAVEAT,
    }


def _shared_origin(session, article_ids: list[int]) -> tuple[int, list[str]]:
    """Count outbound URLs cited by MORE THAN ONE of these articles.

    This is the anti-false-triangulation flag: when "independent" sources in a
    cluster all cite the same origin, their convergence may be one origin echoed,
    not independent corroboration. We surface the structure (count + examples),
    never a verdict.
    """
    if len(article_ids) < 2:
        return 0, []
    from sqlalchemy import func

    rows = (
        session.query(
            ArticleLink.normalized_url,
            func.count(func.distinct(ArticleLink.article_id)).label("n"),
        )
        .filter(
            ArticleLink.article_id.in_(article_ids),
            ArticleLink.normalized_url.isnot(None),
        )
        .group_by(ArticleLink.normalized_url)
        .having(func.count(func.distinct(ArticleLink.article_id)) > 1)
        .order_by(func.count(func.distinct(ArticleLink.article_id)).desc())
        .limit(50)
        .all()
    )
    examples = [url for url, _ in rows[:3] if url]
    return len(rows), examples


def _empty(
    window_days: int,
    min_articles: int,
    min_sources: int,
    *,
    scanned: int = 0,
) -> dict:
    return {
        "clusters": [],
        "clusters_total": 0,
        "scanned_places": scanned,
        "window_days": window_days,
        "min_articles": min_articles,
        "min_sources": min_sources,
        "method": CONVERGENCE_METHOD,
        "caveat": CONVERGENCE_CAVEAT,
    }
