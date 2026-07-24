"""
Scrape execution + the in-app background scheduler.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two layers, kept separate so the work is testable without timing or threads:

  * :func:`run_scrape_once` -- a pure, synchronous pass over the enabled sources
    (RSS feeds or a bounded recursive crawl, per the settings), returning an
    aggregated tally. No threads, no globals: hand it a session + fetcher.
  * :class:`BackgroundScheduler` -- a single daemon thread that calls the runner
    on an interval, with explicit start/stop and a non-overlapping "run now".
    All time/work is injectable so tests drive it deterministically.

Everything still flows through the one ethical fetch path, so periodic scraping
is exactly as robots-respecting and rate-limited as a manual ingest.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from datetime import UTC, datetime, timedelta

from src.database.query import capped
from src.ingest.tor_throughput import KindLadder
from src.scheduler.settings import SchedulerSettings, load_settings

_LOG = logging.getLogger(__name__)

# Inter-pass gap in CONTINUOUS mode: short enough that passes are effectively
# back-to-back (a real pass takes minutes), long enough to yield CPU and let a
# pathologically fast/empty pass (e.g. every feed answered 304) not hot-spin.
# Interruptible (Event.wait), so stop() still returns promptly.
_CONTINUOUS_GAP_S = 5.0

# A10 off-peak maintenance: the minimum interval between idle-window keyword
# maintenance runs (counter reconcile + orphan prune + language reconcile), so it
# does not fire on every 5 s continuous gap. Default 300 s; 0 = every idle window.
_MAINT_INTERVAL_S_DEFAULT = 300.0


def _maint_interval_s() -> float:
    """Min seconds between off-peak maintenance runs (OO_MAINT_INTERVAL_S)."""
    import os

    try:
        return max(0.0, float(os.getenv("OO_MAINT_INTERVAL_S", str(_MAINT_INTERVAL_S_DEFAULT))))
    except (TypeError, ValueError):
        return _MAINT_INTERVAL_S_DEFAULT


def _mem_reclaim_interval_s() -> float:
    """Min seconds between active memory reclaims WHILE collection is paused low on
    memory (OO_MEM_PAUSE_RECLAIM_S, default 30; 0 = reclaim on every poll)."""
    import os

    try:
        return max(0.0, float(os.getenv("OO_MEM_PAUSE_RECLAIM_S", "") or 30.0))
    except (TypeError, ValueError):
        return 30.0


# --------------------------------------------------------------------------- #
# Pass recycling (P0.3 E2, field event 2026-07-09): ONE continuous crawl pass
# ran 21.6 hours and accumulated per-pass memory until the kernel OOM-killer
# fired. A pass is therefore BOUNDED — in wall-clock (OO_PASS_BUDGET_MINUTES,
# default 60; 0 = unbounded, the old behaviour) and optionally in work
# (OO_PASS_MAX_SOURCES, default 0 = off). When the budget expires the pass ends
# CLEANLY: in-flight sources finish (politeness untouched, no thread is ever
# interrupted), the not-yet-started remainder is DEFERRED and runs FIRST next
# pass (ordering, never exclusion — no source starved), per-pass state is
# released (src/scheduler/hygiene), and continuous mode starts the next pass.
# --------------------------------------------------------------------------- #


def _env_pass_float(name: str, default: float) -> float:
    try:
        v = float(os.getenv(name, "") or default)
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def _pass_budget_s() -> float:
    """The per-pass wall-clock budget in seconds (0 disables recycling). Resolved via the
    power-profile knob (OO_PASS_BUDGET_MINUTES override, else the active profile; Optimized =
    60, byte-identical to today). Read PER PASS, so a profile switch is LIVE on the next pass."""
    from src.config.power_profiles import pass_budget_minutes

    return pass_budget_minutes() * 60.0


def _pass_max_sources() -> int:
    """Optional per-pass work cap (sources admitted); 0 = off."""
    return int(_env_pass_float("OO_PASS_MAX_SOURCES", 0.0))


# Source ids deferred at the last pass boundary, in their fair-rotation order.
# In-process state on purpose: a restart simply runs a fresh full pass (the
# rotation covers everyone over time); within a process the carryover
# guarantees a deferred source is FIRST in line, so recycling never starves.
_DEFER_LOCK = threading.Lock()
_DEFERRED_IDS: list[int] = []


def _record_deferred(ids: list[int]) -> None:
    with _DEFER_LOCK:
        _DEFERRED_IDS[:] = list(ids)


def _consume_deferred() -> list[int]:
    with _DEFER_LOCK:
        ids = list(_DEFERRED_IDS)
        _DEFERRED_IDS.clear()
        return ids


def deferred_carryover_count() -> int:
    """How many sources the last pass boundary deferred (status honesty)."""
    with _DEFER_LOCK:
        return len(_DEFERRED_IDS)


class _PassWindDown:
    """Decides when an in-flight pass stops taking NEW sources.

    Workers consult :meth:`admit` BEFORE starting a source — a cheap check
    (the guard's own mutex + this class's counter mutex, both leaf-level and
    held for nanoseconds), so nothing is ever interrupted mid-fetch. Reasons:
    ``"memory"`` (the RSS memory guard engaged — P0.3 E3,
    checked FIRST: new work must never start under proven memory pressure),
    ``"budget"`` (wall-clock budget expired), ``"work"`` (per-pass source cap
    reached). ``now`` is injectable for deterministic tests. Thread-safe.
    """

    def __init__(self, *, budget_s: float, max_sources: int, now=time.monotonic) -> None:
        self._now = now
        self._deadline = (now() + budget_s) if budget_s > 0 else None
        self._max = max(0, int(max_sources))
        self._admitted = 0
        self._lock = threading.Lock()

    def admit(self) -> str | None:
        """None = process the next source; else the wind-down reason."""
        # Module-attribute access on purpose (memguard.memory_guard), so tests
        # can swap the singleton.
        from src.scheduler import memguard

        if memguard.memory_guard.engaged:
            return "memory"
        with self._lock:
            # Forward-progress floor (skeptic-hardened): a pathologically small
            # budget (an env typo) must never yield zero progress forever — the
            # FIRST source of a pass is always admitted; only the budget defers
            # after it. The memory reason above deliberately has NO floor (under
            # proven memory pressure zero new work is the point).
            if (
                self._deadline is not None
                and self._now() >= self._deadline
                and self._admitted > 0
            ):
                return "budget"
            if self._max and self._admitted >= self._max:
                return "work"
            self._admitted += 1
        return None


def round_robin_interleave(sources: list, *, rng: random.Random | None = None) -> list:
    """Reorder sources into a per-country round-robin: one source per country
    per round, country order shuffled each call, within-country order preserved
    (the incoming priority/id order).

    This breaks the volume bias of source-rich countries structurally — every
    country gets equal turns, not turns proportional to how many sources it has
    (maintainer 2026-06-11). Sources without a country share one "unknown"
    bucket. ``rng`` is injectable so tests are deterministic.
    """
    if not sources:
        return []
    chooser = rng or random
    buckets: dict[str, list] = {}
    for s in sources:
        key = (getattr(s, "country", None) or "").strip().lower() or "·unknown"
        buckets.setdefault(key, []).append(s)
    order = list(buckets.keys())
    chooser.shuffle(order)
    queues = [list(buckets[k]) for k in order]
    out: list = []
    while queues:
        # One full round: take the head of each still-nonempty country queue.
        out.extend(q.pop(0) for q in queues)
        queues = [q for q in queues if q]
    return out


def _source_lang(s) -> str:
    """A source's stratum LANGUAGE (the bucket stratified_interleave round-robins by);
    blank/missing share an '·unknown' bucket so they are never dropped."""
    return (getattr(s, "language", None) or "").strip().lower() or "·unknown"


def _source_tag(s) -> str:
    """A source's stratum TAG = its FIRST tag (a multi-tag source picks one
    representative); blank/missing share an '·untagged' bucket."""
    raw = getattr(s, "tags", None) or ""
    first = raw.split(",")[0].strip().lower() if raw else ""
    return first or "·untagged"


def _source_country(s) -> str:
    return (getattr(s, "country", None) or "").strip().lower()


def stratified_interleave(
    sources: list,
    *,
    rng: random.Random | None = None,
    country_priority: dict | None = None,
) -> list:
    """Order sources with TRUE per-pass randomness, fairly STRATIFIED by LANGUAGE
    then by SOURCE TAG (maintainer-ruled 2026-06-17 — supersedes the per-country
    round-robin for the default collection pass).

    Each language gets equal round-robin turns (language order shuffled EVERY call);
    within a language each distinct tag gets equal turns (tag order shuffled); within
    a (language, tag) group the sources are shuffled truly randomly. So no language
    and no topic-tag is over-represented merely by having more sources, and the order
    differs every pass (true randomness, not a fixed rotation). A source's stratum tag
    is its FIRST tag (a multi-tag source picks one representative); sources with no
    language / no tag share an "·unknown" / "·untagged" bucket so they are never
    dropped. Per-host politeness is unaffected (it lives in the fetcher's host lock);
    this only decides ORDER. ``rng`` is injectable so tests are deterministic.

    ``country_priority`` (a ``{iso2: weight>0}`` dict, default OFF/None = byte-identical to
    the pure stratified order) applies the maintainer's bandwidth PRIORITY LADDER: it decides
    what runs FIRST under constrained bandwidth, NEVER what runs at all (ordering != exclusion).
    A STABLE sort by descending country weight lifts higher-priority countries earlier while
    preserving the fair language/tag interleave among equal-weight sources — every source
    still runs, an unlisted country just sorts at weight 0 (its existing fair position kept).
    """
    if not sources:
        return []
    chooser = rng or random

    by_lang: dict[str, dict[str, list]] = {}
    for s in sources:
        by_lang.setdefault(_source_lang(s), {}).setdefault(_source_tag(s), []).append(s)

    # Flatten each language into a tag-round-robin (tag order + within-tag shuffled).
    lang_queues: list[list] = []
    langs = list(by_lang.keys())
    chooser.shuffle(langs)
    for lang in langs:
        tag_map = by_lang[lang]
        tags = list(tag_map.keys())
        chooser.shuffle(tags)
        tag_queues = []
        for t in tags:
            grp = list(tag_map[t])
            chooser.shuffle(grp)            # true randomness within a (lang, tag) group
            tag_queues.append(grp)
        flat: list = []
        while tag_queues:
            flat.extend(q.pop(0) for q in tag_queues)
            tag_queues = [q for q in tag_queues if q]
        lang_queues.append(flat)

    # Round-robin across languages: one source per language per round.
    out: list = []
    while lang_queues:
        out.extend(q.pop(0) for q in lang_queues)
        lang_queues = [q for q in lang_queues if q]

    # Bandwidth priority ladder (opt-in): a STABLE sort by descending country weight lifts
    # prioritised countries to the front WITHOUT dropping anyone (unlisted = weight 0, its
    # fair position preserved by the stable sort). Empty/None = byte-identical (no sort).
    if country_priority:
        out.sort(key=lambda s: -float(country_priority.get(_source_country(s), 0.0)))
    return out


def _filter_due_feeds(session, sources: list) -> tuple[list, int]:
    """Split RSS sources into (due, backed_off_count) by their feed backoff state.

    A source is "backed off" (skipped THIS pass) when its FeedFetchState carries a
    ``skip_until`` deadline in the future — set after a 200 that served only
    duplicates (field log finding F). The cap on that deadline guarantees the feed
    becomes due again soon, so this is a transport de-churn, never an exclusion.

    Sources without a feed (no ``rss_url``) and sources with no/expired state are
    always due. One bulk query for the relevant states keeps this cheap. Any
    bookkeeping error degrades to "all due" — the backoff is only an optimisation.
    """
    from src.database.models import FeedFetchState
    from src.ingest.pipeline import feed_is_due

    try:
        feed_ids = [s.id for s in sources if getattr(s, "rss_url", None)]
        if not feed_ids:
            return sources, 0
        states = {
            st.source_id: st
            for st in session.query(FeedFetchState).filter(
                FeedFetchState.source_id.in_(feed_ids)
            )
        }
        due: list = []
        backed_off = 0
        for s in sources:
            if getattr(s, "rss_url", None) and not feed_is_due(states.get(s.id)):
                backed_off += 1
                continue
            due.append(s)
        return due, backed_off
    except Exception:  # noqa: BLE001 - the backoff filter must never break a pass
        _LOG.debug("feed backoff pre-filter failed; treating all feeds as due", exc_info=True)
        return sources, 0


def select_sources(session, settings: SchedulerSettings):
    """Query of enabled, QUALIFIED sources matching the scheduler's selection criteria.

    Always enabled-only; ALWAYS qualified-only (the admission gate, 0.3 CLOSE GATE
    ruling: "only QUALIFIED sources are scraped" -- a not-yet-qualified or disqualified
    source never joins regular collection; it is picked up instead by the qualification
    ride-along, see src.catalog.qualification.advance_qualification). Optionally narrowed
    by language / source_type (exact) and tags (match ANY, substring). Ordered highest-
    priority first. Used by rss/crawl runs and by the targets-preview endpoint so "what
    will be scraped" is explicit.
    """
    from sqlalchemy import or_

    from src.catalog.qualification import STATUS_QUALIFIED
    from src.database.models import Source

    q = session.query(Source).filter_by(enabled=True, status=STATUS_QUALIFIED)
    if settings.select_languages:
        q = q.filter(Source.language.in_(settings.select_languages))
    if settings.select_source_types:
        q = q.filter(Source.source_type.in_(settings.select_source_types))
    if settings.select_tags:
        q = q.filter(or_(*[Source.tags.ilike(f"%{t}%") for t in settings.select_tags]))
    return q.order_by(Source.priority.asc(), Source.id.asc())


# Small, tight bound for the crawl-SUPPLEMENT'S per-source config -- deliberately much
# smaller than the explicit whole-source mode="crawl" caps (up to 500 pages/depth 6):
# this is a bounded, polite discovery nibble that runs EVERY due pass, not a full crawl.
_CRAWL_SUPPLEMENT_MAX_PAGES = 20
_CRAWL_SUPPLEMENT_MAX_DEPTH = 2


def _select_crawl_candidates(session, settings: SchedulerSettings, limit: int) -> list:
    """Qualified sources due for the §8 crawl-supplement rung this pass, ordered
    FEEDLESS-first (RSS-invisible sources benefit most -- they have no other
    URL-discovery channel yet) then LEAST-RECENTLY-CRAWLED (NULL = never
    crawled by the supplement, sorts first). Reuses select_sources' own
    enabled+qualified+facet filters (cleared of its priority/id order via
    ``order_by(None)`` so this rotation is not swamped by it) -- a rotation
    that covers every qualified source over time, ordering never exclusion."""
    from src.database.models import Source

    if limit <= 0:
        return []
    q = select_sources(session, settings).order_by(None)
    q = q.order_by(
        Source.rss_url.isnot(None),  # feedless (NULL, False=0) sorts first
        Source.last_crawled_at.is_(None).desc(),  # never-crawled (True=1) first
        Source.last_crawled_at.asc(),  # then oldest-crawled first
    )
    return q.limit(limit).all()


def _item_mode_count(session, settings: SchedulerSettings) -> int:
    """How many watched items a wiki/law/markets pass will cover (for the preview
    estimate). With no per-run cap this is the true count; a soft cap clamps it."""
    from src.database.models import LawDocument, MarketExtractionRule, WikiPage

    if settings.mode == "wiki":
        n = session.query(WikiPage).filter_by(watched=True).count()
    elif settings.mode == "law":
        n = session.query(LawDocument).filter_by(watched=True).count()
    elif settings.mode == "markets":
        n = session.query(MarketExtractionRule).filter_by(enabled=True).count()
    else:
        return 0
    cap = settings.max_sources_per_run
    return min(n, cap) if cap and cap > 0 else n


# --- Live run progress (maintainer-ruled 2026-06-10: the activity chip opens -- #
# a detailed collection view). One thread scrapes at a time (the run lock), so a
# module-level, lock-guarded snapshot is enough. Domains only — never full URLs.
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict | None = None


def _progress_set(**fields) -> None:
    global _PROGRESS
    with _PROGRESS_LOCK:
        if fields.get("_clear"):
            _PROGRESS = None
        elif _PROGRESS is None:
            _PROGRESS = dict(fields)
        else:
            _PROGRESS.update(fields)


def current_progress() -> dict | None:
    """A point-in-time copy of the in-flight run's progress (None when idle)."""
    with _PROGRESS_LOCK:
        return dict(_PROGRESS) if _PROGRESS else None


# Coarse PHASE of the in-flight pass, independent of the detailed per-source
# _PROGRESS (which run_scrape_once owns and clears at the end of the scrape).
# This survives the whole pass so the task manager can honestly say WHAT the
# background work is — "collecting articles" vs the post-scrape housekeeping
# (markets/calendars/preflight) that used to run FIRST and look like a stall.
_PHASE_LOCK = threading.Lock()
_PHASE: str | None = None


def _phase_set(phase: str | None) -> None:
    global _PHASE
    with _PHASE_LOCK:
        _PHASE = phase


def current_phase() -> str | None:
    """The current coarse pass phase (e.g. 'collecting'/'background'/'briefing'),
    or None when idle. Backs the task-manager's human label for the collect job."""
    with _PHASE_LOCK:
        return _PHASE


# How many sources the activity-panel preview materialises for its 8 sample
# domains + representative politeness delay. Bounds the per-poll cost: the total
# is a cheap COUNT, only this many rows are decrypted/built into ORM objects.
# Small enough to be fast, large enough that the sampled median delay is stable.
_PLAN_PREVIEW_SAMPLE = int(os.getenv("OO_PLAN_PREVIEW_SAMPLE", "256"))


def plan_preview(session, settings: SchedulerSettings, *, last_result: dict | None) -> dict:
    """What the NEXT pass would do, with an honest duration estimate.

    The estimate is stated arithmetic, not a promise: planned sources × the
    per-source politeness delay × the expected fetches per source (taken from
    the last run's real pages/source when known, else 1 feed fetch each).
    """
    targets: list[str] = []
    # Holds list-of-dict facets PLUS scalar 'sampled'/'note', so the value type is object.
    strata: dict[str, object] = {"languages": [], "tags": []}
    total = 0
    if settings.mode in ("rss", "crawl"):
        base = select_sources(session, settings)
        # Field perf 2026-06-17: /api/scheduler/activity was the #1 endpoint by
        # server time (4244 polls × ~119 ms), because this preview materialised
        # the WHOLE enabled-source set (3000+ rows decrypted through the SQLCipher
        # codec) on every poll. We only need an honest total + 8 preview domains +
        # a representative politeness delay, so: a cheap COUNT for the total, then
        # a BOUNDED sample (never more than the pass will actually run) for the
        # rest. total still drives the estimate, so it stays the true count.
        total = capped(base, settings.max_sources_per_run).count()
        sample_n = min(total, _PLAN_PREVIEW_SAMPLE)
        rows = base.limit(sample_n).all() if sample_n else []
        # Same stratified (language + tag, true-random) ordering the pass uses.
        rows = stratified_interleave(rows)
        targets = [r.domain for r in rows[:8]]
        # Show the ACTUAL strata the pass interleaves by (field test 2026-06-22, #5):
        # not just the claim "stratified by language & tag" but the languages/tags
        # present. Derived from the bounded sample ALREADY fetched (zero extra query —
        # /api/scheduler/activity is the hot poll, never add an unbounded DISTINCT scan),
        # so it is a representative sample of the highest-priority due sources, not the
        # whole catalogue — and the pass RE-RANDOMISES every time, so this is a glimpse
        # of the rotation, never a fixed queue. The "·unknown"/"·untagged" buckets are
        # the same ones stratified_interleave uses (never dropped).
        lang_n: dict[str, int] = {}
        tag_n: dict[str, int] = {}
        for r in rows:
            lang_n[_source_lang(r)] = lang_n.get(_source_lang(r), 0) + 1
            tag_n[_source_tag(r)] = tag_n.get(_source_tag(r), 0) + 1
        strata = {
            "languages": [
                {"key": k, "n": n}
                for k, n in sorted(lang_n.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
            ],
            "tags": [
                {"key": k, "n": n}
                for k, n in sorted(tag_n.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
            ],
            "sampled": len(rows),
            "note": (
                "Languages & tags among the next sources sampled; the pass re-randomises "
                "by language & tag every time (a rotation, not a fixed queue)."
            ),
        }
        delays = [max((r.rate_limit_ms or 1000) / 1000.0, 1.0) for r in rows] or [1.0]
        median_delay = sorted(delays)[len(delays) // 2]
        per_source = 1.0
        if last_result and last_result.get("sources_processed"):
            per_source = max(
                1.0,
                (last_result.get("pages_fetched") or 0) / last_result["sources_processed"],
            )
        if settings.mode == "crawl":
            per_source = max(per_source, min(settings.crawl_max_pages, 5))
        est = round(total * median_delay * per_source)
        method = (
            f"{total} source(s) × ~{median_delay:.1f}s politeness delay × "
            f"~{per_source:.1f} fetch(es) each (from the last run) — an assumption, "
            "not a promise; robots crawl-delays can stretch it."
        )
    else:
        # wiki / law / markets iterate watched items, not sources. With no cap
        # (the default), report the REAL count of items this pass will cover.
        total = _item_mode_count(session, settings)
        est = None
        method = "item-mode pass (wiki/law/markets): duration depends on the remote service."
    return {
        "mode": settings.mode,
        "planned_total": total,
        "next_targets": targets,
        "strata": strata,
        "estimated_seconds": est,
        "estimate_method": method,
    }


def _process_source(source, *, session, fetcher, mode: str, crawl_cfg) -> tuple[dict, int, int]:
    """Scrape ONE source into ``session``; returns (tally, pages_fetched, processed).

    Isolated and fail-safe: one bad source never aborts the pass — its error is
    tallied and reported. Used by both the sequential loop and the parallel
    worker pool; the pool gives each call its OWN session (SQLAlchemy sessions
    are not thread-safe), while the fetcher is shared and per-host-locked.
    """
    from src.ingest.crawl import crawl_source
    from src.ingest.pipeline import ingest_source

    try:
        if mode == "crawl":
            report = crawl_source(session, source, fetcher=fetcher, config=crawl_cfg)
            return report.tally, report.pages_fetched, 1
        if not source.rss_url:
            return {}, 0, 0
        return ingest_source(session, source, fetcher=fetcher), 0, 1
    except Exception:  # noqa: BLE001 - one bad source must not abort the batch
        _LOG.warning("scrape run: source %r failed", getattr(source, "domain", "?"), exc_info=True)
        return {"errors": 1}, 0, 0


def run_scrape_once(session, fetcher, settings: SchedulerSettings) -> dict:
    """Run one ingestion pass over enabled sources and return an aggregated tally.

    In ``rss`` mode each enabled source with a feed is ingested; in ``crawl`` mode
    each enabled source is crawled (bounded by the crawl caps in ``settings``).
    Sources are taken highest-priority first, capped at ``max_sources_per_run``.
    """
    from src.database.models import MarketExtractionRule
    from src.ingest.crawl import CrawlConfig

    started = datetime.now(UTC)

    agg: dict[str, int] = {}
    sources_processed = 0
    pages_fetched = 0

    def _add(tally: dict) -> None:
        for k, v in tally.items():
            if isinstance(v, int):
                agg[k] = agg.get(k, 0) + v

    # Wiki mode tracks watched Wikipedia pages (revisions/diffs/flags), not sources.
    if settings.mode == "wiki":
        from src.wiki.client import WikiClient
        from src.wiki.track import track_watched

        res = track_watched(session, WikiClient(), limit_pages=settings.max_sources_per_run)
        finished = datetime.now(UTC)
        return {
            "mode": "wiki",
            "sources_processed": res["pages"],
            "articles_stored": 0,
            "wiki_new_revisions": res["new_revisions"],
            "wiki_flagged": res["flagged"],
            "pages_fetched": 0,
            "tally": {"new_revisions": res["new_revisions"], "flagged": res["flagged"]},
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 2),
        }

    # Law mode tracks watched legal documents (baseline/diff/flag), not sources.
    if settings.mode == "law":
        from src.law.track import track_watched

        res = track_watched(session, fetcher, limit_documents=settings.max_sources_per_run)
        finished = datetime.now(UTC)
        return {
            "mode": "law",
            "sources_processed": res["documents"],
            "articles_stored": 0,
            "law_changed": res["changed"],
            "law_flagged": res["flagged"],
            "pages_fetched": res["documents"],
            "tally": res,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 2),
        }

    # Markets mode iterates configured extraction rules, not sources.
    if settings.mode == "markets":
        from src.markets.pipeline import import_due_feeds, run_rules

        rules = capped(
            session.query(MarketExtractionRule)
            .filter_by(enabled=True)
            .order_by(MarketExtractionRule.id.asc()),
            settings.max_sources_per_run,
        ).all()
        result = run_rules(session, rules, fetcher=fetcher)
        _add(result["tally"])
        # Background AUTO-LOAD of the curated CSV feeds (commodities + indices),
        # freshness-gated, so the board fills itself and the manual Load/Refresh
        # button is no longer needed (maintainer 2026-06-17). Best-effort.
        feeds = import_due_feeds(session, fetcher=fetcher)
        _add({"feed_points": feeds.get("imported", 0)})
        # Scheduled auto-refresh of tracked official-statistics vintages (ruling #12),
        # freshness- + airplane-gated, best-effort (a stats problem never breaks the pass).
        try:
            from src.stats.subscriptions import refresh_due

            stats_ref = refresh_due(session)
            _add({"stat_vintages": stats_ref.get("stored", 0)})
        except Exception:  # noqa: BLE001 - additive; never fatal to the markets pass
            _LOG.warning("stat-subscription refresh failed; pass continues", exc_info=True)
        finished = datetime.now(UTC)
        return {
            "mode": "markets",
            "sources_processed": len(rules),
            "articles_stored": agg.get("stored", 0),
            "prices_stored": result["prices_stored"],
            "feeds_imported": feeds.get("imported", 0),
            "pages_fetched": 0,
            "tally": agg,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 2),
        }

    sources = capped(select_sources(session, settings), settings.max_sources_per_run).all()
    # Fair ordering: TRUE-RANDOM stratified by LANGUAGE + SOURCE TAG so no
    # source-rich language or topic dominates a pass, and the order differs every
    # pass (maintainer-ruled 2026-06-17, supersedes the per-country round-robin).
    # Per-host politeness is untouched (the fetcher's host lock); this only orders.
    # An opt-in per-country priority ladder (default OFF) lifts chosen countries FIRST
    # under constrained bandwidth without excluding anyone (ordering != exclusion).
    sources = stratified_interleave(
        sources, country_priority=getattr(settings, "country_priority", None) or None
    )

    # Pass-recycling carryover (P0.3 E2): sources the LAST pass boundary
    # deferred run FIRST this pass, in their recorded order — recycling is
    # ordering, never exclusion, so a wound-down pass can never starve a
    # source. A deferred id no longer in the selection simply drops out.
    carry = _consume_deferred()
    if carry:
        rank = {sid: i for i, sid in enumerate(carry)}
        head = sorted((s for s in sources if s.id in rank), key=lambda s: rank[s.id])
        sources = head + [s for s in sources if s.id not in rank]

    # Per-feed de-churn backoff (field log finding F): skip RSS feeds that are
    # within a CAPPED, self-resetting backoff window (a recent 200 served only
    # duplicates). This is an additive pre-filter — it changes only WHICH feeds
    # run THIS pass, never the dispatch below, and never an exclusion: the cap
    # (BACKOFF_CAP_S ~6 h) guarantees every feed is re-checked soon; any new
    # article / 304 / error already cleared the window. Crawl mode has no feed
    # state, so it is untouched. Counted honestly as "backed_off", not skipped
    # silently and not as a duplicate/error.
    backed_off = 0
    if settings.mode == "rss":
        sources, backed_off = _filter_due_feeds(session, sources)
    if backed_off:
        agg["backed_off"] = agg.get("backed_off", 0) + backed_off

    # Optional per-language cadence lever (default OFF; maintainer opt-in). When a
    # target is set, RE-CHECKS of over-represented languages are probabilistically
    # deferred to a later pass — NEVER excluded (a hard freshness floor keeps any
    # cap-stale or never-fetched source). Empty target = the block is skipped =
    # byte-identical to the pure rotation. Additive + fail-open like the backoff.
    if settings.mode == "rss" and settings.language_equilibrium:
        try:
            from src.database.models import FeedFetchState
            from src.scheduler.equilibrium import (
                corpus_language_shares,
                equilibrium_filter,
                language_pace,
            )

            pace = language_pace(
                corpus_language_shares(session),
                settings.language_equilibrium,
                floor=settings.equilibrium_floor,
            )
            if pace:
                feed_ids = [s.id for s in sources if getattr(s, "rss_url", None)]
                states = (
                    {
                        st.source_id: st
                        for st in session.query(FeedFetchState).filter(
                            FeedFetchState.source_id.in_(feed_ids)
                        )
                    }
                    if feed_ids
                    else {}
                )
                sources, deferred = equilibrium_filter(sources, pace=pace, fetch_state=states)
                if deferred:
                    agg["equilibrium_deferred"] = agg.get("equilibrium_deferred", 0) + deferred
        except Exception:  # noqa: BLE001 - the lever must never break a pass
            _LOG.debug("language-equilibrium pre-filter failed; pass proceeds", exc_info=True)

    countries = len({(s.country or "").strip().lower() for s in sources if s.country})

    _progress_set(
        mode=settings.mode,
        total=len(sources),
        done=0,
        current=None,
        pages=0,
        countries=countries,
        ordering="round-robin",
        started_at=started.isoformat(),
    )
    crawl_cfg = (
        CrawlConfig(max_depth=settings.crawl_max_depth, max_pages=settings.crawl_max_pages)
        if settings.mode == "crawl"
        else None
    )
    # The pass-boundary decider (P0.3 E2): when the wall-clock budget or work
    # cap is reached the pass stops ADMITTING new sources; whatever is in
    # flight finishes (politeness untouched) and the remainder is deferred to
    # run first next pass. Checked before each source — never mid-fetch.
    wind = _PassWindDown(budget_s=_pass_budget_s(), max_sources=_pass_max_sources())
    deferred_sources: list = []
    deferred_lock = threading.Lock()
    wind_reasons: dict[str, int] = {}

    def _defer(source, reason: str) -> None:
        with deferred_lock:
            deferred_sources.append(source)
            wind_reasons[reason] = wind_reasons.get(reason, 0) + 1
    # The hard ceiling on concurrent fetches (the governor's upper bound). 1 =
    # the sequential loop (governor off, unchanged behaviour).
    w_max = max(1, getattr(settings, "collect_parallelism", 1) or 1)
    # Parallel collection requires the gated GLOBAL engine: worker threads open
    # their OWN sessions (through the single-writer gate). A caller that passes a
    # session bound to a DIFFERENT engine (e.g. a test's in-memory DB, where
    # ``:memory:`` hands each thread a SEPARATE database) runs sequentially on that
    # same session — correct on any engine, parallel only where it is safe.
    use_pool = w_max > 1 and len(sources) > 1
    if use_pool:
        try:
            from src.database.session import engine as _global_engine

            use_pool = session.get_bind() is _global_engine
        except Exception:  # noqa: BLE001 - any doubt -> the safe sequential path
            use_pool = False
    try:
        if use_pool:
            # Bandwidth-governed parallel FETCH across DIFFERENT hosts (round-robin
            # order already interleaves countries/hosts, so concurrent sources are
            # different hosts → different Tor circuits). The BandwidthGovernor
            # varies how many workers may fetch at once to track the download-rate
            # target, backing off under CPU/memory/writer contention. Each worker
            # gets its OWN DB session AFTER it holds a permit (so a throttled worker
            # holds no connection); writes still serialise through the single-writer
            # gate, and the shared fetcher's per-host lock keeps politeness intact.
            from concurrent.futures import ThreadPoolExecutor, as_completed

            from src.database.session import session_scope
            from src.monitoring.collect_perf import CollectionMonitor
            from src.scheduler.bandwidth import BandwidthGovernor

            governor = BandwidthGovernor(
                mode=getattr(settings, "collect_rate_mode", "target"),
                target_kbps=getattr(settings, "collect_target_kbps", 500),
                w_max=w_max,
            )
            monitor = CollectionMonitor(
                governor=governor,
                pass_id=started.isoformat(timespec="seconds"),
                mode=settings.mode,
                # Per-component memory gauges (P0.3 E1): the fetcher's host
                # caches are per-pass state; their growth rides every sample.
                cache_stats_fn=getattr(fetcher, "cache_stats", None),
            )

            def _worker(source):
                # Pass boundary check BEFORE any permit/session/gate is taken:
                # a wound-down worker holds nothing and returns immediately
                # (the source is deferred, never dropped).
                reason = wind.admit()
                if reason:
                    _defer(source, reason)
                    return {}, 0, 0
                # Acquire a governor permit BEFORE opening a DB session, so a
                # throttled (parked) worker holds no connection or key in memory.
                governor.acquire()
                try:
                    with session_scope() as worker_session:
                        return _process_source(
                            source,
                            session=worker_session,
                            fetcher=fetcher,
                            mode=settings.mode,
                            crawl_cfg=crawl_cfg,
                        )
                finally:
                    governor.release()

            done = 0
            monitor.start()
            try:
                with ThreadPoolExecutor(
                    max_workers=w_max, thread_name_prefix="oo-collect"
                ) as pool:
                    futures = [pool.submit(_worker, s) for s in sources]
                    for fut in as_completed(futures):
                        tally, pages, processed = fut.result()
                        _add(tally)
                        pages_fetched += pages
                        sources_processed += processed
                        done += 1
                        _progress_set(
                            done=done,
                            pages=pages_fetched,
                            active=governor.active,
                            permits=governor.permits,
                        )
            finally:
                summary = monitor.stop(
                    result={
                        "articles_stored": agg.get("stored", 0),
                        "sources_processed": sources_processed,
                        "pages_fetched": pages_fetched,
                    }
                )
                if summary:
                    _LOG.info(
                        "collect perf: bottleneck=%s",
                        summary.get("bottleneck", {}).get("verdict"),
                    )
        else:
            from src.scheduler import memguard as _memguard

            for idx, source in enumerate(sources):
                # The parallel path's monitor feeds the memory guard each tick;
                # the sequential path has no monitor, so poll it directly every
                # few sources (cheap psutil read) — the guard works both ways.
                if idx % 16 == 0:
                    _memguard.memory_guard.poll()
                reason = wind.admit()
                if reason:
                    _defer(source, reason)
                    continue
                _progress_set(current=source.domain, done=idx, pages=pages_fetched)
                tally, pages, processed = _process_source(
                    source, session=session, fetcher=fetcher,
                    mode=settings.mode, crawl_cfg=crawl_cfg,
                )
                _add(tally)
                pages_fetched += pages
                sources_processed += processed
    finally:
        _progress_set(_clear=True)
        # Record deferrals in the FINALLY (skeptic-hardened): even if the pool
        # section raises, whatever was already deferred keeps its run-first
        # claim on the next pass (the exactness invariant: every selected
        # source was either processed or is recorded here, in order).
        if deferred_sources:
            _record_deferred([s.id for s in deferred_sources])

    recycled: str | None = None
    if deferred_sources:
        recycled = max(wind_reasons.items(), key=lambda kv: kv[1])[0]
        _LOG.info(
            "pass wound down (%s): %d source(s) deferred to run first next pass",
            recycled,
            len(deferred_sources),
        )

    finished = datetime.now(UTC)
    out = {
        "mode": settings.mode,
        "sources_processed": sources_processed,
        "articles_stored": agg.get("stored", 0),
        "pages_fetched": pages_fetched,
        "tally": agg,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 2),
    }
    if deferred_sources:
        out["recycled"] = recycled
        out["deferred_next_pass"] = len(deferred_sources)
    return out


# --------------------------------------------------------------------------- #
# S-B / C1+C2 (2026-07-24 throughput brief): the HOUSEKEEPING LANE.
#
# _default_run_once's post-pass tail used to run ~7 network ride-alongs
# SEQUENTIALLY on the pass thread (calendar/markets/law/world-discovery/
# qualification/country-data/hazards), each a real Tor fetch -- measured as a
# large share of the 3-8 min inter-pass gap on BOTH a 2-core and an 8-core
# field machine (duty cycle 48-65%, two 2026-07-23 diagnostics exports).
# _refresh_briefing_async (S4.1) proved the fix for one such ride-along (a
# background thread with its OWN session, non-overlapping via a lock, task-
# manager-visible); this generalizes that pattern to the rest of the serial
# network ride-alongs, so the pass tail becomes "kick the lane, return" and
# pass N+1's collection can start immediately.
#
# The lane opens its OWN session + fetcher (never the pass's -- "never two
# writers on one cursor" for world-discovery/qualification still holds, since
# writes still serialise through the single process-wide writer gate
# regardless of which session/thread initiates them). Deliberately NOT moved
# here: preflight/feed_preflight (first-run only), field-test instrumentation
# (opt-in, off by default), offline discovery (DB-only, no network), the
# ai_layer/langdetect/source-enrichment ride-alongs (LOCAL loopback inference
# or zero-network, not the S-B "network ride-along" target) -- all stay on the
# pass thread, unchanged.
# --------------------------------------------------------------------------- #

# Every kind the lane may run this pass. "crawl" (§8, C3) is the bounded
# crawl-supplement rung -- see _lane_step_crawl / _select_crawl_candidates.
# "backfill" (C15) is a newly-qualified source's sitemap-enumerated HISTORY --
# see _lane_step_backfill / src.ingest.archive_backfill.
_LANE_KINDS = (
    "markets", "hazards", "calendar", "law",
    "world_discovery", "qualification", "country_data", "crawl", "backfill",
)

# The bandwidth PRIORITY LADDER (ruled 2026-06-13): "(1) commodities/markets/
# weather FIRST -- small payloads, cheap, high value; ... (4) recursive
# crawling ONLY with bandwidth headroom (heaviest)". Weights set a priority
# ORDER (ordering != exclusion -- every due kind still runs every invocation;
# see _lane_kind_order's safety net); floors guarantee the discovery/
# qualification/country-data ride-alongs, the crawl rung and the backfill rung
# are never starved. "crawl" and "backfill" both sit at rate=0 (no priority
# order beyond their floor); "backfill" carries the SMALLEST floor of all --
# the ladder's LOWEST rung (C15's "live collection stays first" requirement) --
# so it only ever consumes headroom after every other kind's own turn,
# including "crawl".
_LANE_RATES: dict[str, float] = {
    "markets": 5.0, "hazards": 4.0,
    "calendar": 2.0, "law": 2.0,
    "world_discovery": 1.0, "qualification": 1.0, "country_data": 1.0,
    "crawl": 0.0, "backfill": 0.0,
}
_LANE_FLOORS: dict[str, float] = {
    "markets": 0.0, "hazards": 0.0, "calendar": 0.0, "law": 0.0,
    "world_discovery": 0.2, "qualification": 0.2, "country_data": 0.2,
    "crawl": 0.05, "backfill": 0.02,
}

# Persistent across lane invocations (module-level; the lane's own lock
# guarantees only one invocation is ever live at a time, so no cross-thread
# race on this state) -- the ladder's virtual-time bookkeeping is what gives
# the stride scheduler its starvation-free guarantee ACROSS repeated
# invocations, like the pass-recycling deferred-ids state above.
_LANE_LADDER = KindLadder(rates=_LANE_RATES, floors=_LANE_FLOORS)


def _lane_pending_kinds(settings: SchedulerSettings) -> set[str]:
    """Which housekeeping kinds are DUE this lane invocation, per each
    ride-along's OWN settings toggle/budget -- "budget 0 / toggle off" is a
    kind's off-switch (unchanged from today), never the ladder's job."""
    pending: set[str] = set()
    if settings.mode != "markets":  # markets MODE already ran its own import
        pending.add("markets")
    if getattr(settings, "auto_import_calendars", True):
        pending.add("calendar")
    if getattr(settings, "auto_track_law", True):
        pending.add("law")
    if getattr(settings, "auto_track_signals", True):
        pending.add("hazards")
    if getattr(settings, "world_discovery_per_pass", 0) > 0:
        pending.add("world_discovery")
    if getattr(settings, "qualification_per_pass", 0) > 0:
        pending.add("qualification")
    if getattr(settings, "country_data_per_pass", 0) > 0:
        pending.add("country_data")
    if getattr(settings, "crawl_supplement", True) and getattr(settings, "crawl_per_pass", 0) > 0:
        pending.add("crawl")
    if getattr(settings, "archive_backfill_per_pass", 0) > 0:
        pending.add("backfill")
    return pending


def _lane_kind_order(pending: set[str], *, ladder: KindLadder | None = None) -> list[str]:
    """Order ``pending`` by the ladder's priority (highest-weight first, floors
    breaking ties among the rest). SAFETY NET (deliberate, not an oversight):
    every member of ``pending`` is a kind whose OWN settings toggle/budget just
    said "run me this pass" -- ordering must never become exclusion, so a kind
    the ladder cannot schedule (an unrecognised name, or a genuine 0-weight
    entry) is still appended at the end rather than silently dropped. A kind's
    OFF switch is its settings toggle/budget (checked before it ever reaches
    ``pending`` -- see ``_lane_pending_kinds``), never the ladder."""
    lad = ladder or _LANE_LADDER
    remaining = set(pending)
    order: list[str] = []
    # Bounded: len(remaining) draws must exhaust it; a ladder bug must never spin.
    for _ in range(len(remaining) + 1):
        if not remaining:
            break
        k = lad.next_kind(remaining)
        if k is None:
            break
        order.append(k)
        remaining.discard(k)
    order.extend(sorted(remaining))  # the safety net documented above
    return order


def _lane_step_markets(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.markets.pipeline import import_due_feeds

    feeds = import_due_feeds(session, fetcher=fetcher)
    return {"feed_points": feeds.get("imported", 0)}


def _lane_step_calendar(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.events.feeds import auto_import_due_feeds

    return auto_import_due_feeds(fetcher)


def _lane_step_law(session, fetcher, settings: SchedulerSettings) -> dict:
    """Law auto-track + its AI CHANGE SUMMARIES follow-up (2026-07-24 field-
    feedback Session A §3, ruled). Summarization shares tracking's OWN
    auto_track_law opt-out -- both are now gated ONCE, at
    ``_lane_pending_kinds``, since they were always tied to the same flag
    (collapsing the two separate checks the pre-lane code used into one is
    behavior-identical, not a regression)."""
    from src.law.track import auto_track_due

    out = dict(auto_track_due(session, fetcher))
    try:
        from src.law.summarize import advance_law_summaries

        sum_res = advance_law_summaries(session)
        if sum_res.get("ran"):
            out["law_summarized"] = sum_res.get("stored", 0)
    except Exception:  # noqa: BLE001 - AI summarization must never break law tracking
        _LOG.warning("law auto-summary failed", exc_info=True)
    return out


def _lane_step_hazards(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.hazards.track import auto_snapshot_due

    out: dict = {}
    haz = auto_snapshot_due(fetcher, session=session)
    if haz.get("snapshotted"):
        out["hazards_snapshotted"] = haz["snapshotted"]
    try:
        from src.analytics.weather_signals import auto_refresh_weather_due

        wsig = auto_refresh_weather_due(session)
        if wsig.get("refreshed"):
            out["weather_signals"] = wsig["refreshed"]
    except Exception:  # noqa: BLE001 - never fail the lane on signal refresh
        _LOG.warning("weather signals refresh failed", exc_info=True)
    return out


def _lane_step_world_discovery(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.catalog.discover_job import advance_world_discovery

    return advance_world_discovery(per_pass=settings.world_discovery_per_pass)


def _lane_step_qualification(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.catalog.qualification import advance_qualification
    from src.monitoring import tasks as _bgtasks

    tok = _bgtasks.register(
        "qualification", "qualifying candidate sources",
        detail=f"up to {settings.qualification_per_pass} candidate(s)",
    )
    try:
        return advance_qualification(
            session, fetcher, per_pass=settings.qualification_per_pass
        )
    finally:
        _bgtasks.finish(tok)


def _lane_step_country_data(session, fetcher, settings: SchedulerSettings) -> dict:
    from src.api.governments import advance_country_data

    return advance_country_data(session, per_pass=settings.country_data_per_pass)


def _lane_step_crawl(session, fetcher, settings: SchedulerSettings) -> dict:
    """§8 crawl-by-default (2026-07-24 throughput brief, C3): a bounded crawl
    sub-pass over qualified sources -- feedless-first, least-recently-crawled
    (_select_crawl_candidates). Adds NO new fetch path: every consumer below
    routes through the ONE ``EthicalFetcher`` (robots fail-closed, per-host
    politeness, same-domain-only, dedup). One bad source never aborts the
    rest (mirrors ``_process_source``'s isolation); ``last_crawled_at`` is
    stamped only for sources actually attempted, so a crash mid-batch leaves
    the untouched remainder correctly first-in-line next time.

    C7's consumer (a) -- "new-URL discovery for a qualified source": a
    sitemap is a source's OWN declared page list, more COMPLETE than blind
    on-page link-following (a source's home page never lists everything it
    publishes). When ``src.ingest.sitemap.discover_sitemap_urls`` finds one,
    its declared article URLs are ingested DIRECTLY
    (:func:`~src.ingest.pipeline.ingest_url`, bounded to the same
    ``max_pages`` this rung already uses) instead of falling back to the
    BFS ``crawl_source``; a confirmed sitemap is persisted (consumer c). A
    source with no discoverable sitemap keeps the ORIGINAL BFS crawl
    unchanged -- this rung never regresses a source it previously covered."""
    from src.ingest.crawl import CrawlConfig, crawl_source
    from src.ingest.pipeline import ingest_url
    from src.ingest.sitemap import discover_sitemap_urls, update_source_sitemap_url

    max_pages = min(settings.crawl_max_pages, _CRAWL_SUPPLEMENT_MAX_PAGES)
    cfg = CrawlConfig(
        max_depth=min(settings.crawl_max_depth, _CRAWL_SUPPLEMENT_MAX_DEPTH),
        max_pages=max_pages,
    )
    candidates = _select_crawl_candidates(session, settings, settings.crawl_per_pass)
    sources_crawled = 0
    pages_fetched = 0
    sitemap_urls_ingested = 0
    for source in candidates:
        try:
            sm_report = discover_sitemap_urls(fetcher, source.domain, max_urls=max_pages)
            update_source_sitemap_url(session, source, sm_report)
            if sm_report.urls:
                attempted = 0
                for url in sm_report.urls[:max_pages]:
                    ingest_url(session, source, url, fetcher=fetcher)
                    attempted += 1
                sitemap_urls_ingested += attempted
            else:
                report = crawl_source(session, source, fetcher=fetcher, config=cfg)
                pages_fetched += report.pages_fetched
            source.last_crawled_at = datetime.now(UTC)
            sources_crawled += 1
        except Exception:  # noqa: BLE001 - one source's failure must not skip the rest
            _LOG.warning("crawl supplement: source %r failed", source.domain, exc_info=True)
    return {
        "sources_crawled": sources_crawled,
        "pages_fetched": pages_fetched,
        "sitemap_urls_ingested": sitemap_urls_ingested,
    }


def _lane_step_backfill(session, fetcher, settings: SchedulerSettings) -> dict:
    """C15 (2026-07-24 throughput brief, S-E slice 2): advance one bounded
    slice of the persisted archive-backfill queue -- a newly-qualified
    source's sitemap-enumerated HISTORY. Sources are enqueued automatically on
    qualification success (src.catalog.qualification.evaluate_and_stamp's
    caller); this ride-along only DRAINS the queue, it never enqueues.
    Task-manager visible (mirrors the qualification ride-along's own token)."""
    from src.ingest.archive_backfill import advance_backfill
    from src.monitoring import tasks as _bgtasks

    tok = _bgtasks.register(
        "backfill", "backfilling a newly-qualified source's archive",
        detail=f"up to {settings.archive_backfill_per_pass} page(s)",
    )
    try:
        return advance_backfill(
            session, fetcher, per_pass=settings.archive_backfill_per_pass
        )
    finally:
        _bgtasks.finish(tok)


# Registry (kept separate from _LANE_KINDS so a "reserved, not yet runnable"
# kind can exist in the ladder table with no step to call -- none reserved
# today; every kind in _LANE_KINDS now has a step).
_LANE_STEPS = {
    "markets": _lane_step_markets,
    "calendar": _lane_step_calendar,
    "law": _lane_step_law,
    "hazards": _lane_step_hazards,
    "world_discovery": _lane_step_world_discovery,
    "qualification": _lane_step_qualification,
    "country_data": _lane_step_country_data,
    "crawl": _lane_step_crawl,
    "backfill": _lane_step_backfill,
}


def run_housekeeping_lane(session, fetcher, settings: SchedulerSettings) -> dict:
    """One lane invocation: run every DUE housekeeping kind, ladder-ordered,
    each isolated so one kind's failure never skips the rest (mirrors
    ``_process_source``'s per-source isolation). Stops taking on NEW kinds
    (never interrupts one mid-flight) once the memory guard engages -- the
    same wind-down discipline the pass itself uses (``_PassWindDown``)."""
    from src.scheduler import memguard

    out: dict[str, dict] = {}
    order = _lane_kind_order(_lane_pending_kinds(settings))
    for i, kind in enumerate(order):
        if memguard.memory_guard.engaged:
            out["_paused"] = {"reason": "memory pressure", "remaining": order[i:]}
            break
        step = _LANE_STEPS.get(kind)
        if step is None:
            continue  # a reserved-but-not-yet-runnable kind (e.g. "crawl" pre-C3)
        try:
            out[kind] = step(session, fetcher, settings)
        except Exception:  # noqa: BLE001 - one kind's failure must not skip the rest
            _LOG.warning("housekeeping lane: %s failed", kind, exc_info=True)
            out[kind] = {"error": True}
    return out


class BackgroundScheduler:
    """Daemon-thread scheduler with explicit start/stop and non-overlapping run-now.

    ``run_once_fn`` and ``settings_provider`` are injectable so tests can run the
    state machine with no DB, network, or real waiting. The first run happens
    immediately on start; subsequent runs wait ``interval_minutes`` (interruptibly,
    so :meth:`stop` returns promptly).
    """

    def __init__(self, *, run_once_fn=None, settings_provider=None):
        self._run_once_fn = run_once_fn or self._default_run_once
        self._settings_provider = settings_provider or load_settings
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active = False
        self._started_at: datetime | None = None
        self._last_run: datetime | None = None
        self._next_run: datetime | None = None
        self._last_result: dict | None = None
        self._last_error: str | None = None
        # Inter-pass gap in continuous mode (instance attr so tests can shrink it).
        self._continuous_gap_s = _CONTINUOUS_GAP_S
        # How often a memory pause re-polls the guard (instance attr for tests).
        self._mem_pause_poll_s = 5.0
        # How often, WHILE paused, to actively reclaim memory (gc + malloc_trim +
        # library caches) so a pause caused by allocator retention resumes instead
        # of sticking until restart (instance attr for tests). 0 = every poll.
        self._mem_reclaim_interval_s = _mem_reclaim_interval_s()
        # A10 off-peak maintenance: throttle + last-run monotonic stamp (instance
        # attrs so tests can drive them). 0.0 = due on the first idle window.
        self._maint_interval_s = _maint_interval_s()
        self._last_maint = 0.0
        self._last_maintenance: dict | None = None
        # S4.1 duty-cycle fix (field-feedback 2026-07-23): the whole-corpus
        # briefing recompute runs in its own background thread (see
        # _refresh_briefing_async); this lock makes overlapping refreshes
        # non-overlapping-but-never-queued (a busy refresh means THIS pass's
        # cycle is skipped, not stacked), and the thread ref lets tests wait
        # for it deterministically.
        self._briefing_bg_lock = threading.Lock()
        self._briefing_thread: threading.Thread | None = None
        # S-B/C1 (2026-07-24 throughput brief): the housekeeping lane's own
        # non-overlapping lock + thread ref, same non-overlapping-never-queued
        # shape as the briefing lock above.
        self._lane_lock = threading.Lock()
        self._lane_thread: threading.Thread | None = None
        self._last_lane_result: dict | None = None
        # Session A §4 concurrency-skeptic finding (2026-07-24, HIGH): an exclusive
        # operation (a restore) pausing the CONTINUOUS loop via .stop() left run_now()
        # completely unaware -- run_now() spawns its own _do_run() thread gated ONLY on
        # self._active, never on is_running()/self._thread, so a single manual "Run now"
        # click (or its API) during a restore silently defeated the whole "own the
        # machine" isolation the restore's enlarged cache/worker-count claims to have.
        # This flag is INDEPENDENT of the loop thread's own running state (it must hold
        # even when the loop was already stopped before the restore began, e.g. under
        # airplane mode) -- see hold_exclusive/release_exclusive below.
        self._exclusive_hold = False

    # -- lifecycle --------------------------------------------------------- #

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start the scheduling loop. Returns False if it was already running."""
        if self.is_running():
            return False
        self._stop.clear()
        self._started_at = datetime.now(UTC)
        self._thread = threading.Thread(target=self._loop, name="oo-scheduler", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        """Signal the loop to stop and join it. Returns False if it wasn't running."""
        if not self.is_running():
            return False
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        with self._state_lock:
            self._next_run = None
        return True

    def run_now(self) -> bool:
        """Trigger an immediate one-off run in a worker thread.

        Returns False if a run (scheduled or manual) is already in progress, OR
        an exclusive operation currently holds the machine (see
        :meth:`hold_exclusive` -- a Session A §4 concurrency-skeptic fix,
        2026-07-24: this used to check ONLY ``self._active``, so a manual "Run
        now" during a paused-for-restore window silently spawned a full
        collection pass concurrently with it, defeating the whole point of the
        pause), so runs never overlap and stampede a source.
        """
        # Audit finding 2026-07-17 (L4): read under _state_lock, matching every OTHER
        # instance field it protects -- the real overlap guarantee is _run_lock (a
        # real threading.Lock acquired non-blocking in _do_run), so this quick check
        # was already safe in practice (a bare bool read/write is GIL-atomic and a
        # stale read here at worst spawns a thread that immediately no-ops on the
        # lock), but consistent locking removes the reliance on that implicit fact.
        with self._state_lock:
            if self._active or self._exclusive_hold:
                return False
        threading.Thread(target=self._do_run, name="oo-scrape-now", daemon=True).start()
        return True

    def hold_exclusive(self) -> None:
        """Claim the machine for an exclusive operation (a restore): blocks every
        future :meth:`run_now` call until :meth:`release_exclusive`. Independent
        of the continuous loop's own running state -- must hold even when the
        loop was already stopped (e.g. under airplane mode) before the exclusive
        operation began, since a manual "Run now" would otherwise still compete
        for CPU/the single-writer gate with it regardless of the loop's state."""
        with self._state_lock:
            self._exclusive_hold = True

    def release_exclusive(self) -> None:
        """The other half of :meth:`hold_exclusive` -- always call this in a
        ``finally``, unconditionally, once the exclusive operation is done
        (regardless of whether the continuous loop itself resumed)."""
        with self._state_lock:
            self._exclusive_hold = False

    # -- internals --------------------------------------------------------- #

    def _loop(self) -> None:
        while not self._stop.is_set():
            # RSS memory guard (P0.3 E3): while engaged, PAUSE between passes —
            # loudly (phase + status carry the real numbers), resumably (the
            # guard re-polls and releases itself when memory recovers; stop()
            # still interrupts promptly). Holding here holds NOTHING: no
            # session, no gate, no permit — deadlock-free by construction.
            self._wait_while_memory_paused()
            if self._stop.is_set():
                break
            self._do_run()
            if self._stop.is_set():
                break
            # A10: off-peak keyword maintenance runs HERE, in the idle window right
            # after a pass — collector-idle, mutually exclusive with any run-now
            # (holds _run_lock), throttled off-peak, interruptible by stop(). This
            # replaces the old pass-tail coupling (warm_cache no longer reconciles).
            self._run_off_peak_maintenance()
            if self._stop.is_set():
                break
            settings = self._settings_provider()
            if getattr(settings, "continuous", True):
                # Continuous (the default): passes run back-to-back with only a
                # short, interruptible gap. While the operator is online the
                # corpus fills permanently — "scraping never stops" (maintainer
                # 2026-06-13). Going offline stops the thread (scheduler_stop),
                # so the loop needs no separate online gate.
                gap_s = max(0.0, self._continuous_gap_s)
            else:
                # Legacy cadence: one pass, then idle ``interval_minutes``.
                gap_s = max(1, settings.interval_minutes) * 60
            with self._state_lock:
                self._next_run = datetime.now(UTC) + timedelta(seconds=gap_s)
            self._stop.wait(gap_s)

    def _wait_while_memory_paused(self) -> None:
        """Block (interruptibly) while the memory guard is engaged.

        Re-polls the guard on a short cadence so recovery is noticed within
        seconds; the paused state is visible as phase 'paused-low-memory'
        (rides the collect job + scheduler status). Returns immediately when
        the guard is disabled or healthy.
        """
        import time as _t

        from src.scheduler import memguard

        waited = False
        last_reclaim = _t.monotonic()  # the pass boundary just reclaimed; next at +interval
        while not self._stop.is_set() and memguard.memory_guard.poll():
            if not waited:
                waited = True
                # No pass will start while paused: a stale next_run would
                # otherwise render as a live countdown in the UI (honesty).
                with self._state_lock:
                    self._next_run = None
                _LOG.warning(
                    "collection paused (low memory): %s — resumes when memory "
                    "recovers or on operator action",
                    (memguard.memory_guard.state().get("reason") or "memory pressure"),
                )
            # Re-asserted EVERY iteration: a concurrently finishing run-now
            # pass clears the phase in its finally, which would otherwise
            # leave an hours-long pause looking like idle (skeptic finding).
            _phase_set("paused-low-memory")
            # ACTIVE reclaim while paused (P0.3 follow-up, field 2026-07-09: "scraping
            # stops after a few hours"). The pause otherwise just spins re-polling —
            # so a pause caused by allocator retention (glibc arenas holding freed
            # pages, library caches) NEVER recovers and collection sticks until
            # restart. Periodically hand freed/freeable memory back to the OS so the
            # next poll sees the drop and the guard RESUMES. Holds no lock / session /
            # gate here (deadlock-free), throttled, best-effort. A genuine leak
            # (retained references) still can't be freed — the guard correctly stays
            # engaged, and the diagnostics/perf export pinpoints the growth.
            now = _t.monotonic()
            if now - last_reclaim >= self._mem_reclaim_interval_s:
                last_reclaim = now
                try:
                    from src.scheduler.hygiene import release_pass_state

                    release_pass_state()
                except Exception:  # noqa: BLE001 - reclaim is best-effort, never blocks resume
                    pass
            self._stop.wait(max(0.01, self._mem_pause_poll_s))
        if waited and current_phase() == "paused-low-memory":
            # Guarded clear: never wipe a phase a just-started pass owns.
            _phase_set(None)

    def _do_run(self) -> None:
        # Skip if another run holds the lock (manual + scheduled racing).
        if not self._run_lock.acquire(blocking=False):
            return
        with self._state_lock:
            self._active = True
        started = datetime.now(UTC)
        report: dict = {"started_at": started.isoformat(timespec="seconds")}
        try:
            report["mode"] = self._settings_provider().mode
        except Exception:  # noqa: BLE001 - settings must not block a run
            report["mode"] = "unknown"
        try:
            result = self._run_once_fn()
            with self._state_lock:
                self._last_run = datetime.now(UTC)
                self._last_result = result
                self._last_error = None
            report["ok"] = True
            report["result"] = result
        except Exception as exc:  # noqa: BLE001 - record, never crash the thread
            _LOG.warning("scheduled scrape run failed", exc_info=True)
            with self._state_lock:
                self._last_run = datetime.now(UTC)
                self._last_error = str(exc)
            report["ok"] = False
            report["error"] = str(exc)
        finally:
            # Between-pass memory hygiene (P0.3 E1): release per-pass state at
            # the run boundary — never mid-worker; the pool is joined and the
            # run session closed by the time we get here. Measured + recorded
            # on the run report so the effect is auditable, never guessed.
            from src.scheduler.hygiene import run_pass_hygiene

            hygiene = run_pass_hygiene()
            if hygiene:
                report["hygiene"] = hygiene
            report["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            # One auditable line per run (WP3/RM-06); best-effort by design.
            from src.scheduler.runlog import record_run

            record_run(report)
            _phase_set(None)
            with self._state_lock:
                self._active = False
            self._run_lock.release()

    def _run_off_peak_maintenance(self) -> None:
        """A10: run the budgeted keyword maintenance in the collector-idle window.

        Mutually exclusive with any collect pass — takes ``_run_lock`` NON-BLOCKING
        so a concurrent run-now is never contended (and, if a run-now owns the lock,
        maintenance simply yields this window). While it holds the lock it sets
        ``_active`` + a labelled ``"maintenance"`` phase, so a concurrent
        :meth:`run_now` HONESTLY returns ``False`` ("busy, retry") instead of a false
        ``True`` + a silently-dropped pass, and ``status()`` shows the scheduler busy
        (never idle-while-holding-the-write-gate). The write-gate work is thus never
        concurrent with collection writes — the A10 point. Throttled to
        ``_maint_interval_s`` so it does not fire every 5 s gap, skipped under memory
        pressure, and interruptible (``_stop``). Best-effort; never raises into the loop."""
        import time as _t

        if self._stop.is_set():
            return
        now = _t.monotonic()
        if self._last_maint and now - self._last_maint < self._maint_interval_s:
            return  # off-peak throttle: not due yet
        try:
            from src.scheduler import memguard

            if memguard.memory_guard.engaged:  # property, not a call
                return  # under memory pressure — do not add write-gate work now
        except Exception:  # noqa: BLE001 - guard read must never block maintenance
            pass
        if not self._run_lock.acquire(blocking=False):
            return  # a run-now pass owns the lock — yield this window
        # Mirror _do_run's busy signal: with the lock held but _active False, a
        # concurrent run_now would gate on _active, spawn a pass, fail the lock
        # acquire and silently no-op while replying started:true (skeptic finding).
        # Setting _active + a labelled phase makes run_now honestly return False and
        # status() show the scheduler busy for the (bounded) maintenance window.
        with self._state_lock:
            self._active = True
        _phase_set("maintenance")
        try:
            self._last_maint = now
            from src.scheduler.maintenance import run_idle_maintenance

            result = run_idle_maintenance(should_stop=self._stop.is_set)
            with self._state_lock:
                self._last_maintenance = result
        except Exception:  # noqa: BLE001 - never let maintenance break the loop
            _LOG.warning("off-peak maintenance failed", exc_info=True)
        finally:
            _phase_set(None)
            with self._state_lock:
                self._active = False
            self._run_lock.release()

    def _refresh_briefing_async(self) -> None:
        """S4.1 duty-cycle fix (field-feedback 2026-07-23, two maintainer diagnostics
        exports measuring 65%/48% duty cycle -- 3-8 min inter-pass gaps on BOTH a
        2-core and an 8-core box): ``refresh_briefing`` is a single-core, whole-corpus
        recompute (home-cards alone measured up to ~268s on a 2-core reference box)
        that used to run SYNCHRONOUSLY at the tail of every pass, blocking the very
        next pass's "collecting" phase from starting until it finished -- a large
        share of the measured gap, and one that barely shrinks with more CPU (a
        single-core recompute; the fast box's own gap only improved ~1.4x on 2.7x
        compute). It is READ-MOSTLY (writes only its own file cache + the watch
        evaluation, both already single-writer-gated like every other write in the
        app) so it is handed to its OWN background thread with a FRESH session --
        the caller returns immediately after kicking it off, letting the scheduler
        loop start the next pass's collection concurrently while this finishes.
        Best-effort + NON-OVERLAPPING (never queued): if a previous refresh is still
        running when a later pass finishes, that pass's cycle is skipped outright --
        the corpus grows incrementally between passes, so missing one refresh is
        harmless, the same "occasionally skipped, never stacked" posture the other
        ride-alongs (world-discovery, qualification) already use. Tracked in the task
        manager (kind="briefing") like those ride-alongs, rather than as a scheduler
        phase -- it can now genuinely overlap the next pass's OWN phase.
        """
        if not self._briefing_bg_lock.acquire(blocking=False):
            _LOG.info("background briefing refresh still running; skipping this cycle")
            return

        def _run() -> None:
            from src.database.session import session_scope
            from src.monitoring import tasks as _bgtasks

            tok = _bgtasks.register("briefing", "refreshing the Home briefing")
            try:
                from src.briefing.service import refresh_briefing

                with session_scope() as session:
                    refresh_briefing(session)
            except Exception:  # noqa: BLE001 - a background refresh must never crash the thread
                _LOG.warning("background briefing refresh failed", exc_info=True)
            finally:
                _bgtasks.finish(tok)
                self._briefing_bg_lock.release()

        self._briefing_thread = threading.Thread(
            target=_run, daemon=True, name="oo-briefing-bg"
        )
        self._briefing_thread.start()

    def _kick_housekeeping_lane(self) -> None:
        """S-B (2026-07-24 throughput brief, C1): move the serial network
        ride-alongs (markets/calendar/law/hazards/world-discovery/
        qualification/country-data -- see ``run_housekeeping_lane``) off the
        pass thread, generalizing ``_refresh_briefing_async``'s shape: its OWN
        session + fetcher (never the pass's -- "never two writers on one
        cursor" for world-discovery/qualification still holds, since writes
        still serialise through the single process-wide writer gate
        regardless of which session initiates them), non-overlapping (a lane
        already running means THIS pass's kick is skipped, never queued -- the
        same "occasionally skipped, never stacked" posture the briefing
        refresh already uses -- the corpus/candidates grow incrementally
        between passes, so missing one kick is harmless), task-manager-visible,
        and airplane-aware (refuses up front rather than attempting a lane
        full of individually-refused fetches).
        """
        if not self._lane_lock.acquire(blocking=False):
            _LOG.info("housekeeping lane still running; skipping this cycle's kick")
            return

        def _run() -> None:
            from src.database.session import session_scope
            from src.ingest import kill_switch_active
            from src.monitoring import tasks as _bgtasks
            from src.safety.fetcher import make_fetcher

            tok = _bgtasks.register(
                "housekeeping", "background housekeeping (markets/calendar/law/discovery)"
            )
            try:
                if kill_switch_active():
                    self._last_lane_result = {"skipped": "airplane mode engaged"}
                    return
                settings = self._settings_provider()
                fetcher = make_fetcher()
                with session_scope() as session:
                    self._last_lane_result = run_housekeeping_lane(session, fetcher, settings)
            except Exception:  # noqa: BLE001 - a background lane must never crash the thread
                _LOG.warning("housekeeping lane failed", exc_info=True)
            finally:
                _bgtasks.finish(tok)
                self._lane_lock.release()

        self._lane_thread = threading.Thread(
            target=_run, daemon=True, name="oo-housekeeping-lane"
        )
        self._lane_thread.start()

    def _default_run_once(self) -> dict:

        from src.database.session import session_scope
        from src.safety.fetcher import make_fetcher

        settings = self._settings_provider()
        fetcher = make_fetcher()
        run_started = datetime.now(UTC)
        with session_scope() as session:
            # COLLECT ARTICLES FIRST (maintainer 2026-06-18: "it took 3-5 minutes
            # to get the first article"). The first-run source/feed preflight, the
            # per-pass calendar auto-import and the field-test instrumentation used
            # to run BEFORE the scrape — so over a slow transport (Tor) the operator
            # waited minutes, watching the activity chip sit on a market feed (FRED,
            # the first sampled index) while NO article had landed. The real
            # collection now runs FIRST so articles flow within seconds; all the
            # best-effort housekeeping below piggybacks AFTER it. Robots is enforced
            # LIVE per fetch (EthicalFetcher, fail-closed), so scraping before the
            # preflight LOG is written is safe — the log is instrumentation, not a gate.
            _phase_set("collecting")
            result = run_scrape_once(session, fetcher, settings)
            # Opt-in drop-folder export (WP3/RM-06): write the new-articles
            # delta into the operator's local folder. Best-effort; off when
            # export_dir is empty (the default).
            if settings.export_dir:
                try:
                    from src.scheduler.runlog import export_delta

                    path = export_delta(
                        session, started_at=run_started, export_dir=settings.export_dir
                    )
                    if path:
                        result["delta_export"] = path
                except Exception:  # noqa: BLE001 - never fail the scrape on export
                    _LOG.warning("delta drop-folder export failed", exc_info=True)

            # --- Background housekeeping: best-effort, AFTER the articles, so it
            # never delays the first one. The task manager labels this phase honestly
            # ("background tasks: markets · calendars · checks") so the lingering
            # market/calendar fetches are understood, not mistaken for a stall. ---
            _phase_set("background")
            # First-ever scrape: preflight the enabled sources once (reachability +
            # robots verdicts -> per-source settings + a shareable JSONL log). Done
            # here, not at app boot: boot must stay offline; this run is already
            # going to the network. Best-effort -- never blocks the scrape (now after it).
            try:
                from src.monitoring.preflight import has_run_before, preflight_sources

                if not has_run_before():
                    result_pf = preflight_sources(session, fetcher)
                    _LOG.info("first-run source preflight: %s", result_pf)
            except Exception:  # noqa: BLE001
                _LOG.warning("source preflight failed", exc_info=True)
            # Same contract for the NON-source targets (maintainer-ruled
            # 2026-06-10): robots per feed host + a per-provider sample of the
            # bundled calendar/market feeds, appended to the shareable
            # data/feed_preflight.jsonl. Once, here — never at boot.
            try:
                from src.monitoring import feed_preflight

                if not feed_preflight.has_run_before():
                    result_fpf = feed_preflight.run_feed_preflight(fetcher)
                    _LOG.info("first-run feed preflight: %s", result_fpf)
            except Exception:  # noqa: BLE001
                _LOG.warning("feed preflight failed", exc_info=True)
            # S-B (2026-07-24 throughput brief, C1): calendar auto-import, market
            # auto-load, and law auto-track (+ its AI change-summary follow-up) —
            # each a real Tor fetch — used to run HERE, serially, on the pass
            # thread (measured as a large share of the 3-8 min inter-pass gap on
            # both a 2-core and an 8-core field machine). They now ride the
            # HOUSEKEEPING LANE (see run_housekeeping_lane above): a non-
            # overlapping background thread with its own session/fetcher, so
            # this pass's tail no longer waits on them. Kicked ONCE, here, so it
            # starts as early as possible in the tail (still after the real
            # scrape and the first-run preflights above, so it never delays the
            # first article). Their opt-outs (auto_import_calendars/
            # auto_track_law) are honoured inside the lane's own pending-kinds
            # check (_lane_pending_kinds), not here.
            self._kick_housekeeping_lane()
            # Field-test instrumentation (live-test cycles): exercise every fetch
            # surface once and log verbatim outcomes for the maintainer's debug
            # bundle. OPT-IN since 0.1 (OO_FIELD_TEST=1 enables — a public tag
            # must not auto-instrument by default); see src/monitoring/
            # field_test.py. Runs HERE (the operator's own collect pass), never
            # at boot.
            try:
                from src.monitoring import field_test

                if field_test.enabled():
                    field_test.run_field_test(session, fetcher)
            except Exception:  # noqa: BLE001
                _LOG.warning("field-test instrumentation failed", exc_info=True)
            # Offline source discovery (WP5/RM-19): budgeted, DB-only, and its
            # outcome lands in the run report -- background, never hidden.
            try:
                from src.discovery import run_discovery

                result["discovery"] = run_discovery(
                    session, per_run=settings.discovery_per_run
                )
            except Exception:  # noqa: BLE001 - never fail the scrape on discovery
                _LOG.warning("offline source discovery failed", exc_info=True)
            # S-B (2026-07-24 throughput brief, C1): world-discovery, qualification,
            # and country-data (each a bounded, budget-gated network ride-along —
            # WORLD source-discovery per maintainer ruling 2026-07-15, qualification
            # per the 0.3 CLOSE GATE ruling clause (c), country-data per the
            # 2026-07-24 field-feedback Session A §2 ruling) now ride the
            # HOUSEKEEPING LANE with hazards/calendar/law/markets (see
            # run_housekeeping_lane above + the C1 kick just before the field-test
            # block) instead of running serially here. Every find still stays a
            # DISABLED source for review (automation covers DISCOVERY, never
            # enabling); ongoing refresh of an already-loaded indicator is still the
            # separate stats.subscriptions.refresh_due call in markets mode above,
            # so the two never duplicate work.
            # AUTO-ON-INGEST (opt-in): run every enabled, run_on_ingest custom AI
            # extractor over the most recent articles. Best-effort + bounded; with no
            # auto prompts (the default) it is one empty query, so zero cost. NEVER
            # inline at ingest (a local model in the scrape hot path would stall it) —
            # here, post-pass, off the article path; skip_existing means only NEW
            # articles cost a model call. Results are ai_keyword rows (the AI lens),
            # never the trusted index.
            try:
                from src.ai_layer.auto import run_auto_on_ingest

                _auto = run_auto_on_ingest(session)
                if _auto.get("ran"):
                    result["ai_auto"] = _auto
            except Exception:  # noqa: BLE001 - never let AI extraction break a scrape
                _LOG.warning("auto-on-ingest extraction failed", exc_info=True)
            # AUTO-START language detection (2026-07-24 field-feedback Session A §1, ruled
            # default-ON): a cheap watchdog that (re)starts the CONTINUOUS AI language-
            # detection job whenever it is idle, the local model is available, and unknown-
            # language candidates exist -- opt-out via AppSettings.ai_langdetect_auto. The
            # job itself is loopback Ollama inference (airplane-safe, §7) running on its own
            # thread, resilient to transient outages (retries with backoff) -- this need not
            # fire more than once to drain a whole backlog over many future passes.
            try:
                from src.api.ai import advance_langdetect_auto_start

                _ld = advance_langdetect_auto_start(session)
                if _ld.get("enabled"):
                    result["langdetect_auto"] = _ld
            except Exception:  # noqa: BLE001 - never fail the scrape on the AI-layer watchdog
                _LOG.warning("language-detection auto-start ride-along failed", exc_info=True)
            # Auto source-metadata enrichment (local, zero-network): deduce each
            # source's topic tags from the keywords it actually publishes and union
            # them into Source.tags. Freshness-gated (~daily) so it is usually a
            # no-op; best-effort; opt-out via auto_enrich_sources. This is the
            # "automatic on install" half -- the networked Wikidata source_type pass
            # stays a consented Diagnostics action (it egresses to Wikidata).
            try:
                if getattr(settings, "auto_enrich_sources", True):
                    from src.analytics.source_topics import run_auto_source_enrichment

                    _enr = run_auto_source_enrichment(session)
                    if _enr.get("ran") and _enr.get("sources_updated"):
                        result["source_enrich"] = _enr
                        _LOG.info("source auto-enrichment: %s", _enr)
            except Exception:  # noqa: BLE001 - never fail the scrape on enrichment
                _LOG.warning("source auto-enrichment failed", exc_info=True)
            # S-B (2026-07-24 throughput brief, C1): the hazard snapshot + weather
            # SIGNAL refresh (Wave 4 J; session=session so a freshly-saved snapshot
            # is also ingested as corpus Articles -- zero extra network) now rides
            # the HOUSEKEEPING LANE (see run_housekeeping_lane above) instead of
            # running serially here. Opt-out (auto_track_signals) is honoured inside
            # the lane's own pending-kinds check.
            # Precompute + cache the Home briefing so it loads instantly. S4.1
            # (duty-cycle fix, see _refresh_briefing_async's docstring): this used
            # to run synchronously here, blocking the next pass's collection from
            # starting until the whole-corpus recompute finished. It now kicks off
            # a background thread with its OWN session and returns immediately --
            # the phase stays "background" through to the return (the recompute is
            # tracked as its own task-manager entry, not a scheduler phase, since it
            # can now genuinely outlive this pass).
            self._refresh_briefing_async()
            return result

    # -- introspection ----------------------------------------------------- #

    def status(self) -> dict:
        from src.scheduler import memguard

        s = self._settings_provider()
        # Read outside the state lock (the guard has its own lock; no nesting).
        guard_state = memguard.memory_guard.state()
        with self._state_lock:
            return {
                "running": self.is_running(),
                "active": self._active,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "next_run": self._next_run.isoformat() if self._next_run else None,
                "last_result": self._last_result,
                "last_error": self._last_error,
                "settings": s.to_dict(),
                "progress": current_progress(),
                "phase": current_phase(),
                # Pass recycling honesty (P0.3 E2): how many sources the last
                # pass boundary deferred — they run FIRST next pass.
                "deferred_carryover": deferred_carryover_count(),
                # RSS memory guard (P0.3 E3): the loud paused-low-memory state
                # with the real numbers — never a silent stall.
                "memory_guard": guard_state,
                # A10 off-peak maintenance: the last idle-window keyword-maintenance
                # tally (reconcile + cleanup), so its complete:false disclosure is
                # visible in the scheduler status. None until it first runs.
                "last_maintenance": self._last_maintenance,
            }

    def activity(self, session) -> dict:
        """The collection-activity panel's payload: status + plan + transfer rates."""
        from src.ingest.fetch_verdict import fetch_failed_reasons
        from src.monitoring.activity import activity_monitor
        from src.monitoring.collect_perf import get_latest

        with self._state_lock:
            last = self._last_result
        return {
            **self.status(),
            "plan": plan_preview(session, self._settings_provider(), last_result=last),
            # Break the last pass's fetch_failed count down by reason (Tor-403 vs
            # DNS vs connect vs …) so the number is never a mystery. Reads the flat
            # "ff:<reason>" tally keys; empty when the last pass had no failures.
            "fetch_failed_reasons": fetch_failed_reasons(last),
            "per_host_rates": activity_monitor.per_host_rates(),
            # The app's OWN measured download rate (KiB/s, wall-clock) + the latest
            # bandwidth-governor sample, so the Collect UI can show target vs actual.
            "download_rate_kbps": activity_monitor.download_rate_kbps(),
            "collect_perf": get_latest(),
        }


# Process-wide singleton (created lazily; no thread starts at import).
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def pause_for_exclusive_operation(timeout: float = 10.0) -> bool:
    """Pause background collection for the duration of an exclusive,
    machine-owning operation (field-feedback Session A §4, "import owns the
    machine": a large restore competes for CPU and the write path with any
    in-flight collection pass).

    Returns True iff the CONTINUOUS LOOP was actually running and got
    signalled to stop -- the caller MUST call
    :func:`resume_after_exclusive_operation` with that value afterward (in a
    ``finally``), so a scheduler the user had already left stopped is never
    force-started.

    ALWAYS (regardless of the loop's own state, hence unconditional and
    called first) claims :meth:`BackgroundScheduler.hold_exclusive`, which
    blocks any MANUAL "Run now" for the duration too -- a concurrency-skeptic
    HIGH finding (2026-07-24): ``run_now()`` used to check only whether a run
    was already active, with zero awareness of this pause, so a single manual
    trigger during a restore silently ran a full collection pass concurrently
    with it, defeating the whole point of the pause.

    This is mostly a THROUGHPUT courtesy, never a data-safety requirement for
    the corpus itself (every ORM write through the pooled session is still
    serialised by the single-writer gate regardless of whether collection is
    paused) -- but note that gate does NOT cover the restore's own raw,
    file-level atomic swap (``os.replace`` in ``src/backup/merge.py``), which
    has never been gate-protected (unaffected by this diff, confirmed by the
    crash-mid-stage/data-loss skeptic passes); this pause narrows, but does
    not eliminate, that pre-existing swap-concurrency window --
    :meth:`BackgroundScheduler.stop`'s bounded join means a pass already deep
    in a fetch may still be finishing when this returns.
    """
    get_scheduler().hold_exclusive()
    return get_scheduler().stop(timeout=timeout)


def resume_after_exclusive_operation(
    was_paused: bool, *, retries: int = 19, retry_delay: float = 30.0
) -> None:
    """The other half of :func:`pause_for_exclusive_operation`.

    ALWAYS releases :meth:`BackgroundScheduler.release_exclusive` (in a
    ``finally``, unconditionally) -- a manual "Run now" must work again the
    instant the exclusive operation itself is done, even if the continuous
    loop hasn't actually resumed yet (below).

    ``stop()``'s join is BOUNDED (10 s default) and ``_do_run`` has no
    internal stop-check mid-pass (only between passes, in ``_loop``) — so a
    pass that was already deep in a fetch when ``pause_for_exclusive_
    operation`` was called can still be alive (``is_running()`` True) well
    after ``stop()`` returned. ``start()`` correctly refuses to spawn a
    SECOND thread while the old one is still running — but called only ONCE,
    that leaves a real liveness gap: once the lingering old pass eventually
    finishes on its own, NOTHING would ever call ``start()`` again, silently
    stranding background collection paused indefinitely (a concurrency
    finding from the mandatory skeptic pass, Session A §4).

    So this retries ``start()`` with a bounded backoff — default ~10 minutes
    total (19 retries × 30 s), chosen to comfortably exceed this project's own
    measured worst case for a single blocked write (438 s, see the
    Session-rituals "AUTOFLUSH CAN HAND THE WRITE GATE TO A READ" lesson in
    CLAUDE.md) rather than the too-optimistic 20 s an earlier cut used (a
    concurrency-skeptic LOW finding, 2026-07-24: a short budget made "give up,
    restart manually" the COMMON outcome on Tor-heavy deployments, not a rare
    edge case). This is called from a background job thread, so a few extra
    minutes here costs nothing real. If it genuinely never succeeds (retries
    exhausted), it logs LOUDLY once rather than staying silent, and still
    returns — a caller's own ``finally`` block must never block forever on
    this courtesy call. NOTHING here retries again afterward, so the warning
    never claims a self-heal that does not exist.

    Checked on EVERY attempt: the user's own airplane-mode kill switch always
    wins. If the operator engaged airplane mode of their own accord while
    this operation (or its retry loop) was running, that explicit action must
    never be silently overridden by this best-effort courtesy — bail out
    without starting anything; :func:`~src.api.system.set_network_mode`
    starts the scheduler again the next time THEY choose to go online.
    """
    try:
        if not was_paused:
            return
        from src.ingest import kill_switch_active

        for attempt in range(retries + 1):
            if kill_switch_active():
                return
            if get_scheduler().start():
                return
            if attempt < retries:
                time.sleep(retry_delay)
        _LOG.warning(
            "could not resume background collection after an exclusive operation "
            "-- the previous pass appears to still be running; restart collection "
            "manually from Settings if it does not resume on its own"
        )
    finally:
        get_scheduler().release_exclusive()
