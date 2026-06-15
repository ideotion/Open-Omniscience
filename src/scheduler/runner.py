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
import random
import threading
from datetime import UTC, datetime, timedelta

from src.database.query import capped
from src.scheduler.settings import SchedulerSettings, load_settings

_LOG = logging.getLogger(__name__)

# Inter-pass gap in CONTINUOUS mode: short enough that passes are effectively
# back-to-back (a real pass takes minutes), long enough to yield CPU and let a
# pathologically fast/empty pass (e.g. every feed answered 304) not hot-spin.
# Interruptible (Event.wait), so stop() still returns promptly.
_CONTINUOUS_GAP_S = 5.0


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


def plan_preview(session, settings: SchedulerSettings, *, last_result: dict | None) -> dict:
    """What the NEXT pass would do, with an honest duration estimate.

    The estimate is stated arithmetic, not a promise: planned sources × the
    per-source politeness delay × the expected fetches per source (taken from
    the last run's real pages/source when known, else 1 feed fetch each).
    """
    targets: list[str] = []
    total = 0
    if settings.mode in ("rss", "crawl"):
        rows = capped(select_sources(session, settings), settings.max_sources_per_run).all()
        total = len(rows)
        # Preview the same per-country round-robin order the pass will use, so
        # "next targets" honestly reflects what runs first (not priority order).
        rows = round_robin_interleave(rows)
        targets = [r.domain for r in rows[:8]]
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
        from src.markets.pipeline import run_rules

        rules = capped(
            session.query(MarketExtractionRule)
            .filter_by(enabled=True)
            .order_by(MarketExtractionRule.id.asc()),
            settings.max_sources_per_run,
        ).all()
        result = run_rules(session, rules, fetcher=fetcher)
        _add(result["tally"])
        finished = datetime.now(UTC)
        return {
            "mode": "markets",
            "sources_processed": len(rules),
            "articles_stored": agg.get("stored", 0),
            "prices_stored": result["prices_stored"],
            "pages_fetched": 0,
            "tally": agg,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_s": round((finished - started).total_seconds(), 2),
        }

    sources = capped(select_sources(session, settings), settings.max_sources_per_run).all()
    # Fair ordering: per-country round-robin so no source-rich country dominates
    # a pass (maintainer 2026-06-11). With continuous passes this realises the
    # ruled "one source per country, then repeat".
    sources = round_robin_interleave(sources)
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
    parallelism = max(1, getattr(settings, "collect_parallelism", 1) or 1)
    try:
        if parallelism > 1:
            # Parallel FETCH across DIFFERENT hosts (round-robin order already
            # interleaves countries/hosts, so concurrent sources are different
            # hosts → different Tor circuits). Each worker gets its OWN DB session;
            # writes still serialise through the single-writer gate, and the shared
            # fetcher's per-host lock keeps politeness intact. Results are
            # aggregated in THIS thread (ex.map yields here), so no aggregation lock.
            from concurrent.futures import ThreadPoolExecutor

            from src.database.session import session_scope

            def _worker(source):
                with session_scope() as worker_session:
                    return _process_source(
                        source,
                        session=worker_session,
                        fetcher=fetcher,
                        mode=settings.mode,
                        crawl_cfg=crawl_cfg,
                    )

            done = 0
            with ThreadPoolExecutor(
                max_workers=parallelism, thread_name_prefix="oo-collect"
            ) as pool:
                for tally, pages, processed in pool.map(_worker, sources):
                    _add(tally)
                    pages_fetched += pages
                    sources_processed += processed
                    done += 1
                    _progress_set(done=done, pages=pages_fetched)
        else:
            for idx, source in enumerate(sources):
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

    finished = datetime.now(UTC)
    return {
        "mode": settings.mode,
        "sources_processed": sources_processed,
        "articles_stored": agg.get("stored", 0),
        "pages_fetched": pages_fetched,
        "tally": agg,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 2),
    }


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
        self._thread.join(timeout=timeout)
        with self._state_lock:
            self._next_run = None
        return True

    def run_now(self) -> bool:
        """Trigger an immediate one-off run in a worker thread.

        Returns False if a run (scheduled or manual) is already in progress, so
        runs never overlap and stampede a source.
        """
        if self._active:
            return False
        threading.Thread(target=self._do_run, name="oo-scrape-now", daemon=True).start()
        return True

    # -- internals --------------------------------------------------------- #

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._do_run()
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

    def _do_run(self) -> None:
        # Skip if another run holds the lock (manual + scheduled racing).
        if not self._run_lock.acquire(blocking=False):
            return
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
            report["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            # One auditable line per run (WP3/RM-06); best-effort by design.
            from src.scheduler.runlog import record_run

            record_run(report)
            self._active = False
            self._run_lock.release()

    def _default_run_once(self) -> dict:

        from src.database.session import session_scope
        from src.safety.fetcher import make_fetcher

        settings = self._settings_provider()
        fetcher = make_fetcher()
        run_started = datetime.now(UTC)
        with session_scope() as session:
            # First-ever scrape: preflight the enabled sources once (reachability +
            # robots verdicts -> per-source settings + a shareable JSONL log). Done
            # here, not at app boot: boot must stay offline; this run is already
            # going to the network. Best-effort -- never blocks the scrape.
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
            # TEMPORARY (0.0.8 live-test cycle): exercise every fetch surface
            # once and log verbatim outcomes for the maintainer's debug bundle.
            # Self-improvement instrumentation only; OO_FIELD_TEST=0 disables;
            # see src/monitoring/field_test.py. Runs HERE (the operator's own
            # collect pass), never at boot.
            try:
                from src.monitoring import field_test

                if field_test.enabled():
                    field_test.run_field_test(session, fetcher)
            except Exception:  # noqa: BLE001
                _LOG.warning("field-test instrumentation failed", exc_info=True)
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
            # Offline source discovery (WP5/RM-19): budgeted, DB-only, and its
            # outcome lands in the run report -- background, never hidden.
            try:
                from src.discovery import run_discovery

                result["discovery"] = run_discovery(
                    session, per_run=settings.discovery_per_run
                )
            except Exception:  # noqa: BLE001 - never fail the scrape on discovery
                _LOG.warning("offline source discovery failed", exc_info=True)
            # Precompute + cache the Home briefing so it loads instantly. Best-effort:
            # a briefing failure must never fail the scrape that just succeeded.
            try:
                from src.briefing.service import refresh_briefing

                refresh_briefing(session)
            except Exception:  # noqa: BLE001 - never let the briefing break a scrape
                _LOG.warning("could not refresh briefing after scrape", exc_info=True)
            return result

    # -- introspection ----------------------------------------------------- #

    def status(self) -> dict:
        s = self._settings_provider()
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
            }

    def activity(self, session) -> dict:
        """The collection-activity panel's payload: status + plan + transfer rates."""
        from src.monitoring.activity import activity_monitor

        with self._state_lock:
            last = self._last_result
        return {
            **self.status(),
            "plan": plan_preview(session, self._settings_provider(), last_result=last),
            "per_host_rates": activity_monitor.per_host_rates(),
        }


# Process-wide singleton (created lazily; no thread starts at import).
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler
