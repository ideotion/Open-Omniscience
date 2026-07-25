"""Time-to-first-article: a collection pass must scrape ARTICLES before the
best-effort housekeeping (maintainer 2026-06-18 — "it took 3-5 minutes to get
the first article" because the first-run source/feed preflight, calendar import
and field-test ran BEFORE the scrape and were slow over Tor).

These drive _default_run_once with everything network/DB stubbed, recording the
ORDER of the key steps and the coarse PHASE the task manager surfaces. No DB, no
network.
"""

from __future__ import annotations

import contextlib

import pytest

import src.scheduler.runner as runner
from src.scheduler.runner import BackgroundScheduler, current_phase
from src.scheduler.settings import SchedulerSettings


@pytest.fixture()
def order(monkeypatch):
    calls: list[str] = []
    phases_at: dict[str, str | None] = {}

    # Stub the heavy/networked collaborators _default_run_once reaches for.
    @contextlib.contextmanager
    def _fake_scope():
        yield object()

    monkeypatch.setattr("src.database.session.session_scope", _fake_scope)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())

    def _scrape(session, fetcher, settings):
        calls.append("scrape")
        phases_at["scrape"] = current_phase()
        return {"ok": True, "tally": {}}

    monkeypatch.setattr(runner, "run_scrape_once", _scrape)

    def _preflight(session, fetcher):
        calls.append("preflight")
        phases_at["preflight"] = current_phase()
        return {}

    monkeypatch.setattr("src.monitoring.preflight.has_run_before", lambda: False)
    monkeypatch.setattr("src.monitoring.preflight.preflight_sources", _preflight)
    monkeypatch.setattr("src.monitoring.feed_preflight.has_run_before", lambda: True)
    monkeypatch.setattr("src.events.feeds.auto_import_due_feeds",
                        lambda f: calls.append("calendars") or {"picked": []})
    monkeypatch.setattr("src.monitoring.field_test.enabled", lambda: False)
    monkeypatch.setattr("src.markets.pipeline.import_due_feeds",
                        lambda s, fetcher=None, now=None: calls.append("markets") or {"imported": 0})
    monkeypatch.setattr("src.discovery.run_discovery",
                        lambda s, per_run: calls.append("discovery") or {})

    def _briefing(session):
        calls.append("briefing")
        phases_at["briefing"] = current_phase()

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _briefing)

    sched = BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    sched._default_run_once()
    # S4.1 (duty-cycle fix): the briefing recompute now runs in its own
    # background thread (see _refresh_briefing_async) instead of inline —
    # join it so the ordering/phase assertions below stay deterministic.
    if sched._briefing_thread is not None:
        sched._briefing_thread.join(timeout=5)
    # S-B (2026-07-24 throughput brief, C1): calendar/markets/law/hazards/
    # world-discovery/qualification/country-data now ride the housekeeping
    # lane's OWN background thread (see run_housekeeping_lane) instead of
    # running inline — join it too, for the same determinism reason.
    if sched._lane_thread is not None:
        sched._lane_thread.join(timeout=5)
    return calls, phases_at


def test_scrape_runs_before_first_run_preflight(order):
    calls, _ = order
    assert "scrape" in calls and "preflight" in calls
    assert calls.index("scrape") < calls.index("preflight"), calls
    # And before the calendar import + discovery too (all the slow housekeeping).
    assert calls.index("scrape") < calls.index("calendars"), calls


def test_phase_is_collecting_during_scrape_then_cleared(order):
    _, phases_at = order
    assert phases_at["scrape"] == "collecting"
    assert phases_at["preflight"] == "background"
    # S4.1 (duty-cycle fix): the briefing recompute now runs concurrently in its
    # own background thread (tracked as its own task-manager entry, kind=
    # "briefing" — see test_briefing_duty_cycle.py) rather than as its own
    # scheduler phase, so the pass's OWN phase stays "background" right through
    # to when it kicks the refresh off.
    assert phases_at["briefing"] == "background"
    # Idle once the pass returns (set None in _do_run; _default_run_once leaves it
    # to the caller, so we only assert it was the right phase at briefing time).


def test_collect_job_label_reflects_phase(monkeypatch):
    # The task-manager job is labelled by phase so the user sees WHAT it's doing.
    import src.api.jobs as jobs

    class _Sched:
        def status(self):
            return {"running": True, "active": True, "phase": "background", "next_run": None}

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Sched())
    job = jobs._collect_job()
    assert job is not None
    assert "background tasks" in job["label"]
    assert job["phase"] == "background"


def test_market_feeds_autoload_in_default_rss_pass_after_scrape(order):
    """Field log 2026-06-18: price_points = 0 because the curated commodity/index
    feeds only imported in markets MODE, while the default continuous mode is rss.
    They must now ride the default pass's housekeeping (freshness-gated), AFTER the
    articles (time-to-first-article).

    S-B (2026-07-24 throughput brief, C1) amendment: markets now runs inside the
    housekeeping LANE's own background thread rather than inline on the pass
    thread, and the briefing refresh (S4.1) already runs in a SEPARATE background
    thread — the two are independent, concurrent background tasks with NO
    guaranteed relative order (that is the whole point of C1: the serial tail no
    longer serializes them against each other). So "markets before briefing" is no
    longer asserted; only "after the real scrape" still holds, since both
    background kicks happen strictly after the synchronous scrape returns."""
    calls, _ = order
    assert "markets" in calls and "briefing" in calls, calls
    assert calls.index("scrape") < calls.index("markets"), calls
