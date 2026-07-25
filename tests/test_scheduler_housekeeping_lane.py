"""S-B duty-cycle fix, part 2 (2026-07-24 throughput brief, C1): the serial
post-pass network ride-alongs (markets/calendar/law/hazards/world-discovery/
qualification/country-data) must run in their OWN background thread, non-
overlapping, task-manager-visible, and never crash the scheduler on failure —
mirrors tests/test_briefing_duty_cycle.py's coverage of the same shape for the
briefing refresh (S4.1).

No DB, no network — session_scope/make_fetcher/kill_switch_active and each
individual ride-along step are stubbed.
"""

from __future__ import annotations

import contextlib
import threading

import pytest

import src.scheduler.runner as runner
from src.scheduler.runner import BackgroundScheduler
from src.scheduler.settings import SchedulerSettings


@pytest.fixture()
def sched():
    return BackgroundScheduler(settings_provider=lambda: SchedulerSettings())


def _fake_scope_factory(monkeypatch):
    @contextlib.contextmanager
    def _fake_scope():
        yield object()

    monkeypatch.setattr("src.database.session.session_scope", _fake_scope)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    # The ladder is a MODULE-LEVEL singleton in production (its virtual-time
    # bookkeeping is meant to persist across real pass invocations -- see C2).
    # Reset it to a FRESH instance per test so ordering assertions below are
    # deterministic and never coupled to another test's call history.
    monkeypatch.setattr(
        runner, "_LANE_LADDER", runner.KindLadder(rates=runner._LANE_RATES, floors=runner._LANE_FLOORS)
    )


def test_returns_before_all_kinds_complete(monkeypatch, sched):
    """The whole point of the fix: kicking off the lane must not block the
    caller while the (potentially slow, Tor-fetching) ride-alongs run."""
    _fake_scope_factory(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def _slow_step(session, fetcher, settings):
        started.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setitem(runner._LANE_STEPS, "calendar", _slow_step)

    sched._kick_housekeeping_lane()
    # The call above already returned (synchronous Python) -- the real
    # assertion is that the step is STILL blocked in the background.
    assert started.wait(timeout=2), "the background thread never started"
    assert not release.is_set()

    release.set()
    sched._lane_thread.join(timeout=5)
    assert not sched._lane_thread.is_alive()


def test_a_second_kick_is_skipped_while_one_is_running(monkeypatch, sched):
    """Non-overlapping, never queued: a busy lane means the NEXT kick is
    skipped outright, not stacked behind the first."""
    _fake_scope_factory(monkeypatch)
    calls = []
    release = threading.Event()
    entered = threading.Event()

    def _slow_step(session, fetcher, settings):
        calls.append("run")
        entered.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setitem(runner._LANE_STEPS, "calendar", _slow_step)

    sched._kick_housekeeping_lane()
    assert entered.wait(timeout=2)
    first_thread = sched._lane_thread

    sched._kick_housekeeping_lane()
    assert sched._lane_thread is first_thread  # no new thread was spawned

    release.set()
    first_thread.join(timeout=5)
    assert calls == ["run"]

    # Once the first has fully finished (lock released), a later kick must be
    # allowed to run again -- "never queued" is not "never again".
    calls.clear()
    entered.clear()
    release.clear()
    sched._kick_housekeeping_lane()
    assert entered.wait(timeout=2)
    release.set()
    sched._lane_thread.join(timeout=5)
    assert calls == ["run"]


def test_a_raising_step_never_crashes_the_thread_and_releases_the_lock(monkeypatch, sched):
    _fake_scope_factory(monkeypatch)

    def _boom(session, fetcher, settings):
        raise RuntimeError("simulated calendar failure")

    monkeypatch.setitem(runner._LANE_STEPS, "calendar", _boom)

    sched._kick_housekeeping_lane()
    sched._lane_thread.join(timeout=5)
    assert not sched._lane_thread.is_alive()

    # The lock must be released on a failure too, or every later pass would
    # silently skip the lane forever.
    assert sched._lane_lock.acquire(blocking=False)
    sched._lane_lock.release()


def test_one_kind_failing_does_not_skip_the_rest(monkeypatch, sched):
    """Mirrors _process_source's per-source isolation: one ride-along's
    exception must not prevent the OTHERS from running this same invocation."""
    _fake_scope_factory(monkeypatch)
    ran = []

    def _boom(session, fetcher, settings):
        raise RuntimeError("boom")

    def _ok(session, fetcher, settings):
        ran.append("ok")
        return {"ran": True}

    for kind in ("markets", "hazards", "law", "world_discovery", "qualification", "country_data"):
        monkeypatch.setitem(runner._LANE_STEPS, kind, _ok)
    monkeypatch.setitem(runner._LANE_STEPS, "calendar", _boom)

    sched._kick_housekeeping_lane()
    sched._lane_thread.join(timeout=5)

    assert len(ran) == 6, ran
    result = sched._last_lane_result
    assert result["calendar"] == {"error": True}
    for kind in ("markets", "hazards", "law", "world_discovery", "qualification", "country_data"):
        assert result[kind] == {"ran": True}


def test_lane_is_visible_in_the_task_manager_while_running(monkeypatch, sched):
    _fake_scope_factory(monkeypatch)
    release = threading.Event()
    entered = threading.Event()

    def _slow_step(session, fetcher, settings):
        entered.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setitem(runner._LANE_STEPS, "calendar", _slow_step)

    from src.monitoring import tasks as bgtasks

    sched._kick_housekeeping_lane()
    assert entered.wait(timeout=2)
    snap = bgtasks.snapshot()
    assert any(t["kind"] == "housekeeping" for t in snap), snap

    release.set()
    sched._lane_thread.join(timeout=5)
    snap_after = bgtasks.snapshot()
    assert not any(t["kind"] == "housekeeping" for t in snap_after), snap_after


def test_airplane_mode_skips_the_whole_lane_without_attempting_a_step(monkeypatch, sched):
    """Airplane-aware: refuses up front rather than attempting a lane full of
    individually-refused fetches (every per-kind step would otherwise still be
    invoked pointlessly against a fake session/fetcher)."""
    import contextlib as _ctx

    @_ctx.contextmanager
    def _fake_scope():
        yield object()

    monkeypatch.setattr("src.database.session.session_scope", _fake_scope)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    calls = []
    for kind in runner._LANE_STEPS:
        monkeypatch.setitem(
            runner._LANE_STEPS, kind, lambda s, f, st, k=kind: calls.append(k) or {}
        )

    sched._kick_housekeeping_lane()
    sched._lane_thread.join(timeout=5)

    assert calls == [], "no step should run while the kill switch is engaged"
    assert sched._last_lane_result == {"skipped": "airplane mode engaged"}


def test_memory_guard_stops_taking_new_kinds_never_interrupts_one_mid_flight(monkeypatch, sched):
    """run_housekeeping_lane's own wind-down: once the memory guard engages it
    must stop STARTING new kinds, but never abort one already mid-flight."""
    _fake_scope_factory(monkeypatch)

    class _FakeGuard:
        engaged = False

        def reset(self, *, reason: str = "") -> None:
            """No-op -- satisfies the autouse conftest teardown fixture
            (_memory_guard_not_leaked), which unconditionally calls
            memory_guard.reset(...) after every test regardless of whether
            THIS test replaced the singleton with a fake."""
            self.engaged = False

    guard = _FakeGuard()
    monkeypatch.setattr("src.scheduler.memguard.memory_guard", guard)

    started = threading.Event()
    finish_ok = threading.Event()

    def _first(session, fetcher, settings):
        started.set()
        # Engage the guard WHILE this kind is mid-flight -- it must still be
        # allowed to finish (never interrupted).
        guard.engaged = True
        finish_ok.wait(timeout=5)
        return {"ran": True}

    def _second(session, fetcher, settings):
        raise AssertionError("a new kind must never start once the guard is engaged")

    # markets has the highest weight so it runs first (ties broken by weight
    # descending on a fresh ladder); everything else must never be reached.
    monkeypatch.setitem(runner._LANE_STEPS, "markets", _first)
    for kind in ("calendar", "law", "hazards", "world_discovery", "qualification", "country_data"):
        monkeypatch.setitem(runner._LANE_STEPS, kind, _second)

    sched._kick_housekeeping_lane()
    assert started.wait(timeout=2)
    finish_ok.set()
    sched._lane_thread.join(timeout=5)

    result = sched._last_lane_result
    assert result["markets"] == {"ran": True}  # the in-flight kind finished
    assert "_paused" in result
    assert result["_paused"]["reason"] == "memory pressure"
