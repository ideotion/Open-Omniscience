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
    """Query of enabled sources matching the scheduler's selection criteria.

    Always enabled-only; optionally narrowed by language / source_type (exact) and
    tags (match ANY, substring). Ordered highest-priority first. Used by rss/crawl
    runs and by the targets-preview endpoint so "what will be scraped" is explicit.
    """
    from sqlalchemy import or_

    from src.database.models import Source

    q = session.query(Source).filter_by(enabled=True)
    if settings.select_languages:
        q = q.filter(Source.language.in_(settings.select_languages))
    if settings.select_source_types:
        q = q.filter(Source.source_type.in_(settings.select_source_types))
    if settings.select_tags:
        q = q.filter(or_(*[Source.tags.ilike(f"%{t}%") for t in settings.select_tags]))
    return q.order_by(Source.priority.asc(), Source.id.asc())


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

        Returns False if a run (scheduled or manual) is already in progress, so
        runs never overlap and stampede a source.
        """
        # Audit finding 2026-07-17 (L4): read under _state_lock, matching every OTHER
        # instance field it protects -- the real overlap guarantee is _run_lock (a
        # real threading.Lock acquired non-blocking in _do_run), so this quick check
        # was already safe in practice (a bare bool read/write is GIL-atomic and a
        # stale read here at worst spawns a thread that immediately no-ops on the
        # lock), but consistent locking removes the reliance on that implicit fact.
        with self._state_lock:
            if self._active:
                return False
        threading.Thread(target=self._do_run, name="oo-scrape-now", daemon=True).start()
        return True

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
            # Calendar auto-import (ruled 2026-06-15 "auto-import everything"): a
            # BOUNDED, polite batch of bundled calendar feeds per pass, round-robin
            # by least-recently-imported so over time every feed is covered without
            # hammering. Best-effort; gated to online (this pass already is) + the
            # kill switch via the shared fetcher; opt-out via auto_import_calendars.
            try:
                if getattr(settings, "auto_import_calendars", True):
                    from src.events.feeds import auto_import_due_feeds

                    result_ai = auto_import_due_feeds(fetcher)
                    if result_ai["picked"]:
                        _LOG.info("calendar auto-import: %s", result_ai)
            except Exception:  # noqa: BLE001 - never fail the scrape on auto-import
                _LOG.warning("calendar auto-import failed", exc_info=True)
            # Market data auto-load (maintainer 2026-06-17 "markets load automatically
            # in the background"): the curated commodity/index CSV feeds. Previously
            # this only ran in markets MODE, but the default continuous mode is rss,
            # so a normal user never collected any price points (field log 2026-06-18:
            # price_points = 0). It is freshness-gated (daily/monthly cadence) so it is
            # usually a no-op, and small + cheap (the bandwidth-ladder's first tier).
            # Skip when already in markets mode (run_scrape_once did it there).
            try:
                if settings.mode != "markets":
                    from src.markets.pipeline import import_due_feeds

                    feeds = import_due_feeds(session, fetcher=fetcher)
                    if feeds.get("imported"):
                        result["feed_points"] = feeds.get("imported", 0)
                        _LOG.info("market auto-load: %s price points", feeds.get("imported"))
            except Exception:  # noqa: BLE001 - never fail the scrape on market auto-load
                _LOG.warning("market auto-load failed", exc_info=True)
            # Law auto-track (field test 2026-06-22, #18: the World-law tab was empty
            # because legal documents are only tracked in mode=="law", never in the
            # default rss pass). A BOUNDED, freshness-gated, round-robin batch per pass
            # (like the calendar/markets auto-load) so watched legal documents build
            # baselines + surface changes over time WITHOUT hammering legal sites
            # (politeness/robots/kill-switch ride the shared fetcher). Best-effort;
            # opt-out via auto_track_law.
            try:
                if getattr(settings, "auto_track_law", True):
                    from src.law.track import auto_track_due

                    law_res = auto_track_due(session, fetcher)
                    if law_res.get("documents"):
                        result["law_tracked"] = law_res.get("documents", 0)
                        _LOG.info("law auto-track: %s", law_res)
            except Exception:  # noqa: BLE001 - never fail the scrape on law auto-track
                _LOG.warning("law auto-track failed", exc_info=True)
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
            # WORLD source-discovery ride-along (maintainer ruled 2026-07-15: source
            # discovery should be "background and automated"): advance the persisted
            # world-discovery cursor a few countries per online pass, through the
            # same guarded transport as the pass. Every find stays a DISABLED source
            # for review — automation covers DISCOVERY, never enabling. It opens its
            # OWN per-country sessions (never this pass's), skips honestly when the
            # budget is 0 / the manual job runs / the world is complete, and is
            # best-effort: a failure never breaks a scrape.
            try:
                from src.catalog.discover_job import advance_world_discovery

                _wd = advance_world_discovery(per_pass=settings.world_discovery_per_pass)
                if _wd.get("enabled"):
                    result["world_discovery"] = _wd
            except Exception:  # noqa: BLE001 - never fail the scrape on discovery
                _LOG.warning("world source-discovery ride-along failed", exc_info=True)
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
            # Hazard + weather SIGNAL refresh (Wave 4 J): the severity-tiered alert layer
            # (src/analytics/alerts.py) reads a LOCAL hazard snapshot, and the weather SIGNAL
            # store feeds /api/signals/weather-signals -- both were only ever populated by an
            # explicit manual POST, so in a normal continuous run they stayed empty. This
            # freshness-gated, best-effort pass keeps them current, like the markets/law
            # auto-track: the consented hazard snapshot fetches the open USGS/GDACS feeds
            # through the shared guarded fetcher (kill-switch/robots/proxy; refused under
            # airplane mode -> no socket), and the weather signals are derived LOCALLY from
            # the corpus (no network). Opt-out via auto_track_signals.
            try:
                if getattr(settings, "auto_track_signals", True):
                    from src.hazards.track import auto_snapshot_due

                    haz = auto_snapshot_due(fetcher)
                    if haz.get("snapshotted"):
                        result["hazards_snapshotted"] = haz["snapshotted"]
                        _LOG.info("hazard snapshot: %s", haz)

                    from src.analytics.weather_signals import auto_refresh_weather_due

                    wsig = auto_refresh_weather_due(session)
                    if wsig.get("refreshed"):
                        result["weather_signals"] = wsig["refreshed"]
                        _LOG.info("weather signals refresh: %s", wsig)
            except Exception:  # noqa: BLE001 - never fail the scrape on signal refresh
                _LOG.warning("hazard/weather signal refresh failed", exc_info=True)
            # Precompute + cache the Home briefing so it loads instantly. Best-effort:
            # a briefing failure must never fail the scrape that just succeeded.
            _phase_set("briefing")
            try:
                from src.briefing.service import refresh_briefing

                refresh_briefing(session)
            except Exception:  # noqa: BLE001 - never let the briefing break a scrape
                _LOG.warning("could not refresh briefing after scrape", exc_info=True)
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
