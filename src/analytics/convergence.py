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
  * **No displayed figure is a cap** (the 2026-07-18 convergence-amendment
    ruling: "real, reliable data — never capped figures"). A cap may bound
    which EXAMPLES are listed; it must never bound a displayed NUMBER.

It scans the LOCAL substrate only and NEVER touches the network.

The DATE used is the article's MENTIONED date (the event's own date, the
When×Where×Who anchor) — not the publication date — so a 2024 piece about a
1945 event converges on 1945, which is the honest space-time reading. Rejected
date tags are excluded; candidate + confirmed both count (status is recorded).

CONVERGENCE-AMENDMENT (2026-07-18 field export, ``AUTONOMOUS_SESSION_BRIEF_
2026-07-18_CONVERGENCE_AMENDMENT.md``) + Leads-calibration S4.2:
  * **C1 exact counts** — ``_shared_origin`` reports the EXACT count of shared
    outbound origins (an aggregate over the HAVING-filtered subquery, no
    limit); the limit stays only on the fetched EXAMPLES.
  * **C2 place canonicalization** — country-level mentions cluster by their
    resolved country CODE (:mod:`src.analytics.place_identity`), so "United
    States"/"America"/"Usa" and "Allemagne"/"Deutschland" collapse to one
    identity instead of fragmenting into lookalike clusters; a city keeps its
    own identity, scoped under its country.
  * **C3 span-collapse** — a continuous story is sliced by the greedy sweep's
    anchor-reset into several CONSECUTIVE windows (Iran ×3 in the field
    export); contiguous/overlapping windows for the SAME place now merge into
    ONE span (``steps`` carries the original per-window breakdown; the full
    extent + peak step are surfaced).
  * **C4 baseline-relative ordering** — full-recall exploration is preserved
    (nothing is gated out beyond the structural min_articles/min_sources
    bars); ordering is by DEVIATION from the place's own baseline share of
    the corpus (a hub country converging at its normal saturation ranks
    below a place seeing a genuinely unusual concentration of its own
    history in this one span).
  * **City-over-country de-duplication** — a country-level span whose
    evidence is entirely explained by an overlapping city-level span (same
    country) is dropped; a country span that adds real breadth beyond any
    single city is kept.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
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
    "lexical-v1; country-level mentions canonicalize to the resolved country code, "
    "so surface-string variants of the same country never fragment) whose DEDUCED "
    "event dates (article_mentioned_dates, non-rejected) fall inside one ±window; "
    "contiguous/overlapping windows for the same place merge into one SPAN (the "
    "per-window breakdown rides along as 'steps'). Independence is measured as the "
    "count of DISTINCT sources (not the article count); shared outbound links cited "
    "by more than one member are counted EXACTLY (never capped) and flagged so "
    "common-origin convergence is visible. Exploration stays full-recall; ordering "
    "is by deviation from each place's own baseline share of the corpus, not raw "
    "volume. No score; figures are real counts only."
)


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


@dataclass
class ConvergenceCluster:
    """One space-time convergence SPAN: N articles on the same place across one or
    more contiguous windows (the greedy sweep's own steps, carried for the drill).

    Every field is a real count or a deduced provenance value — there is no
    score, no ranking number that blends dimensions.
    """

    place: str
    place_country: str | None
    place_kind: str | None
    lat: float | None
    lon: float | None
    window_start: str  # ISO date — the SPAN's full extent
    window_end: str  # ISO date — the SPAN's full extent
    n_articles: int
    distinct_sources: int
    source_names: list[str]
    source_countries: dict[str, int]
    article_ids: list[int]
    shared_origin_links: int  # EXACT count (C1) — outbound URLs cited by >1 member
    shared_origin_examples: list[str]
    steps: list[dict]  # the original per-window breakdown (C3 drill-down)
    peak_step_index: int  # index into `steps` with the most articles
    includes_future_mentions: bool
    baseline_share: float  # this span's share of the place's OWN all-time mentions
    place_total_mentions: int  # the denominator behind baseline_share, disclosed

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
            "source_countries": self.source_countries,
            "article_ids": self.article_ids,
            "shared_origin_links": self.shared_origin_links,
            "shared_origin_examples": self.shared_origin_examples,
            "steps": self.steps,
            "peak_step_index": self.peak_step_index,
            "includes_future_mentions": self.includes_future_mentions,
            "baseline_share": self.baseline_share,
            "place_total_mentions": self.place_total_mentions,
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
    """Sweep (article_id, date) pairs sorted by date into ±window_days windows.

    A new article joins the current window if its date is within ``window_days``
    of the window's first (anchor) date; otherwise it opens a new window. This is
    a deterministic single pass — no fabricated interpolation, just which
    articles share a place AND a span. UNFILTERED by size (the min_articles gate
    is applied later, AFTER contiguous windows are merged into spans — C3): a
    continuous story must not be judged one anchor-reset slice at a time.
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


def _merge_contiguous_windows(
    windows: list[tuple[date, date, set[int]]], *, merge_gap_days: int
) -> list[list[tuple[date, date, set[int]]]]:
    """Group a place's windows into SPANS (C3, row 3): windows are merged when the
    gap between one window's end and the next's start is <= ``merge_gap_days`` — a
    continuous story sliced into consecutive anchor-reset windows by the greedy
    sweep, not independent recurrences (Iran ×3 in the field export collapses to
    one span with three steps). A genuine gap larger than the analysis window's
    own scale stays a separate span (a real recurrence, not a slicing artifact)."""
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: w[0])
    spans: list[list[tuple[date, date, set[int]]]] = [[ordered[0]]]
    for w in ordered[1:]:
        prev_end = spans[-1][-1][1]
        gap = (w[0] - prev_end).days
        if gap <= merge_gap_days:
            spans[-1].append(w)
        else:
            spans.append([w])
    return spans


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
        Contiguous/overlapping windows for the SAME place merge into one SPAN
        (C3) so a continuous story is one entry, not one per anchor-reset slice.
    lookback_days
        If given, only consider mentioned dates within this many days of
        ``today`` (the recent past). ``None`` = the whole corpus history (so a
        2024 piece about a 1945 event still converges on 1945).
    min_articles, min_sources
        The conservative surfacing gate (anti-false-triangulation): a SPAN is
        surfaced only when its union article set has ``>= min_articles``
        distinct articles AND ``>= min_sources`` DISTINCT sources. A single
        chatty source publishing many copies cannot manufacture a convergence.

    Returns
    -------
    ``{"clusters": [span_dict, ...], "clusters_total": n, "scanned_places": n,
    "window_days": w, "min_articles": .., "min_sources": ..}`` — totals are
    EXACT counts, never a capped display number (the 2026-07-18 ruling); the
    display ``limit`` only bounds which spans are RETURNED, never the reported
    totals. Ordered by deviation from each place's own baseline share of the
    corpus (C4) — full recall, nothing gated beyond the structural bars above.
    """
    today = today or date.today()
    from src.analytics.place_identity import place_identity

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

    # Place identity (C2): country-level mentions key on the resolved country CODE
    # (never the free-text name); a city keeps its own identity under its country.
    place_articles: dict[str, set[int]] = defaultdict(set)
    place_meta: dict[str, dict] = {}
    for aid, name, country, kind, lat, lon in place_rows:
        pkey, display = place_identity(name, country, kind)
        if not display or display == "?":
            continue
        place_articles[pkey].add(aid)
        meta = place_meta.setdefault(
            pkey,
            {"name": display, "country": (country or "").lower() or None,
             "kind": kind, "lat": None, "lon": None},
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

    # 3) For each place, window its dated articles (UNFILTERED by size), then merge
    #    contiguous windows into SPANS (C3) — the min_articles/min_sources gate is
    #    applied to the SPAN's union set below, not to an individual slice.
    candidate_spans: list[tuple[str, list[tuple[date, date, set[int]]]]] = []
    for key, article_ids in place_articles.items():
        items: list[tuple[int, date]] = []
        for aid in article_ids:
            for d in dates_by_article.get(aid, ()):
                if cutoff is not None and d < cutoff:
                    continue
                items.append((aid, d))
        windows = _greedy_windows(items, window_days=window_days)
        for span_steps in _merge_contiguous_windows(windows, merge_gap_days=window_days):
            candidate_spans.append((key, span_steps))

    if not candidate_spans:
        return _empty(window_days, min_articles, min_sources, scanned=len(place_articles))

    # 4) Resolve source identity for the independence measure (small columns).
    need_ids = sorted({a for _, steps in candidate_spans for _, _, ids in steps for a in ids})
    src_of: dict[int, int | None] = {}
    src_name: dict[int, str | None] = {}
    src_country: dict[int, str | None] = {}
    for chunk in _chunks(need_ids):
        for aid, sid, sname, scountry in (
            session.query(Article.id, Article.source_id, Source.name, Source.country)
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(Article.id.in_(chunk))
            .all()
        ):
            src_of[aid] = sid
            src_name[aid] = sname
            src_country[aid] = (scountry or "").lower() or None

    clusters: list[ConvergenceCluster] = []
    for key, span_steps in candidate_spans:
        union_ids: set[int] = set()
        for _, _, ids in span_steps:
            union_ids |= ids
        ids_sorted = sorted(union_ids)
        source_ids = {src_of.get(a) for a in ids_sorted}
        source_ids.discard(None)
        distinct_sources = len(source_ids)
        if distinct_sources < min_sources or len(ids_sorted) < min_articles:
            continue  # the independence + volume gates, applied to the SPAN
        names = sorted({n for a in ids_sorted if (n := src_name.get(a))})
        countries: dict[str, int] = {}
        for cc in {src_country.get(a) for a in ids_sorted}:
            if cc:
                countries[cc] = len({a for a in ids_sorted if src_country.get(a) == cc})
        shared_n, shared_examples = _shared_origin(session, ids_sorted)
        meta = place_meta[key]

        steps_out = [
            {
                "window_start": wmin.isoformat(),
                "window_end": wmax.isoformat(),
                "article_ids": sorted(ids),
                "n_articles": len(ids),
                "distinct_sources": len({src_of.get(a) for a in ids if src_of.get(a) is not None}),
            }
            for wmin, wmax, ids in span_steps
        ]
        step_sizes = [len(ids) for _, _, ids in span_steps]
        peak_idx = step_sizes.index(max(step_sizes))
        full_start = min(wmin for wmin, _, _ in span_steps)
        full_end = max(wmax for _, wmax, _ in span_steps)

        place_total = len(place_articles[key])
        baseline_share = round(len(ids_sorted) / place_total, 4) if place_total else 0.0

        clusters.append(
            ConvergenceCluster(
                place=meta["name"],
                place_country=meta["country"],
                place_kind=meta["kind"],
                lat=meta["lat"],
                lon=meta["lon"],
                window_start=full_start.isoformat(),
                window_end=full_end.isoformat(),
                n_articles=len(ids_sorted),
                distinct_sources=distinct_sources,
                source_names=names,
                source_countries=countries,
                article_ids=ids_sorted,
                shared_origin_links=shared_n,
                shared_origin_examples=shared_examples,
                steps=steps_out,
                peak_step_index=peak_idx,
                includes_future_mentions=full_end > today,
                baseline_share=baseline_share,
                place_total_mentions=place_total,
            )
        )

    clusters = _drop_country_spans_explained_by_a_city(clusters)

    # Order by deviation from each place's own baseline share (C4) — a
    # suddenly-converged-upon place outranks a hub country at its normal
    # saturation; ties break on independence, then volume. Full recall: nothing
    # is gated out by this ordering, only by the structural bars above.
    clusters.sort(key=lambda c: (-c.baseline_share, -c.distinct_sources, -c.n_articles))
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


def _drop_country_spans_explained_by_a_city(
    clusters: list[ConvergenceCluster],
) -> list[ConvergenceCluster]:
    """City-over-country de-duplication (S4.2): a country-level span whose evidence
    is ENTIRELY covered by overlapping city-level span(s) of the SAME country adds
    no precision beyond them and is dropped; a country span that carries real
    breadth beyond any single city's evidence is kept (Paris kept only if it adds
    precision beyond France — the inverse: France dropped only if Paris already
    covers everything France does)."""
    by_country_cities: dict[str, list[ConvergenceCluster]] = defaultdict(list)
    for c in clusters:
        if c.place_kind and c.place_kind != "country" and c.place_country:
            by_country_cities[c.place_country].append(c)

    def _overlaps(a: ConvergenceCluster, b: ConvergenceCluster) -> bool:
        return a.window_start <= b.window_end and b.window_start <= a.window_end

    out: list[ConvergenceCluster] = []
    for c in clusters:
        if c.place_kind == "country" and c.place_country:
            cities = by_country_cities.get(c.place_country, [])
            covered: set[int] = set()
            for city in cities:
                if _overlaps(c, city):
                    covered |= set(city.article_ids)
            if covered and set(c.article_ids) <= covered:
                continue  # fully explained by city-level evidence — drop the country span
        out.append(c)
    return out


def _shared_origin(session, article_ids: list[int]) -> tuple[int, list[str]]:
    """Count outbound URLs cited by MORE THAN ONE of these articles — the EXACT
    count (C1, the 2026-07-18 ruling: no displayed figure may be a cap).

    This is the anti-false-triangulation flag: when "independent" sources in a
    cluster all cite the same origin, their convergence may be one origin echoed,
    not independent corroboration. We surface the structure (count + examples),
    never a verdict. The count is an aggregate over the HAVING-filtered grouped
    query (no LIMIT); only the returned EXAMPLES are bounded (top-3 by citing-
    article count).
    """
    if len(article_ids) < 2:
        return 0, []
    from sqlalchemy import func

    grouped = (
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
    )
    exact_count = grouped.count()  # EXACT — never capped, however many groups qualify

    example_rows = grouped.order_by(func.count(func.distinct(ArticleLink.article_id)).desc()).limit(3).all()
    examples = [url for url, _ in example_rows if url]
    return exact_count, examples


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
