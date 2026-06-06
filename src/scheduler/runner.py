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
import threading
from datetime import UTC, datetime, timedelta

from src.scheduler.settings import SchedulerSettings, load_settings

_LOG = logging.getLogger(__name__)


def run_scrape_once(session, fetcher, settings: SchedulerSettings) -> dict:
    """Run one ingestion pass over enabled sources and return an aggregated tally.

    In ``rss`` mode each enabled source with a feed is ingested; in ``crawl`` mode
    each enabled source is crawled (bounded by the crawl caps in ``settings``).
    Sources are taken highest-priority first, capped at ``max_sources_per_run``.
    """
    from src.database.models import MarketExtractionRule, Source
    from src.ingest.crawl import CrawlConfig, crawl_source
    from src.ingest.pipeline import ingest_source

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

    # Markets mode iterates configured extraction rules, not sources.
    if settings.mode == "markets":
        from src.markets.pipeline import run_rules

        rules = (
            session.query(MarketExtractionRule)
            .filter_by(enabled=True)
            .order_by(MarketExtractionRule.id.asc())
            .limit(settings.max_sources_per_run)
            .all()
        )
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

    sources = (
        session.query(Source)
        .filter_by(enabled=True)
        .order_by(Source.priority.asc(), Source.id.asc())
        .limit(settings.max_sources_per_run)
        .all()
    )

    for source in sources:
        try:
            if settings.mode == "crawl":
                report = crawl_source(
                    session, source, fetcher=fetcher,
                    config=CrawlConfig(
                        max_depth=settings.crawl_max_depth,
                        max_pages=settings.crawl_max_pages,
                    ),
                )
                _add(report.tally)
                pages_fetched += report.pages_fetched
                sources_processed += 1
            else:  # rss
                if not source.rss_url:
                    continue
                tally = ingest_source(session, source, fetcher=fetcher)
                _add(tally)
                sources_processed += 1
        except Exception:  # noqa: BLE001 - one bad source must not abort the batch
            _LOG.warning("scrape run: source %r failed", source.domain, exc_info=True)
            agg["errors"] = agg.get("errors", 0) + 1

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
            interval_s = max(1, self._settings_provider().interval_minutes) * 60
            with self._state_lock:
                self._next_run = datetime.now(UTC) + timedelta(seconds=interval_s)
            self._stop.wait(interval_s)

    def _do_run(self) -> None:
        # Skip if another run holds the lock (manual + scheduled racing).
        if not self._run_lock.acquire(blocking=False):
            return
        self._active = True
        try:
            result = self._run_once_fn()
            with self._state_lock:
                self._last_run = datetime.now(UTC)
                self._last_result = result
                self._last_error = None
        except Exception as exc:  # noqa: BLE001 - record, never crash the thread
            _LOG.warning("scheduled scrape run failed", exc_info=True)
            with self._state_lock:
                self._last_run = datetime.now(UTC)
                self._last_error = str(exc)
        finally:
            self._active = False
            self._run_lock.release()

    def _default_run_once(self) -> dict:
        import os

        from src.database.session import session_scope
        from src.ingest import EthicalFetcher

        settings = self._settings_provider()
        fetcher = EthicalFetcher(
            min_interval_s=float(os.getenv("OO_FETCH_MIN_INTERVAL", "1.0")),
            timeout=float(os.getenv("OO_FETCH_TIMEOUT", "30")),
        )
        with session_scope() as session:
            return run_scrape_once(session, fetcher, settings)

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
            }


# Process-wide singleton (created lazily; no thread starts at import).
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler
