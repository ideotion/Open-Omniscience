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
    monkeypatch.setattr("src.discovery.run_discovery",
                        lambda s, per_run: calls.append("discovery") or {})

    def _briefing(session):
        calls.append("briefing")
        phases_at["briefing"] = current_phase()

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _briefing)

    sched = BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    sched._default_run_once()
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
    assert phases_at["briefing"] == "briefing"
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
