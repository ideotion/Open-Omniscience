"""
S2.5 (b) (2026-09-02 crash analysis): the two whole-corpus tail consumers must
not run at once on a two-core box.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The housekeeping lane and the briefing recompute were each non-overlapping WITH
THEMSELVES and entirely free to run CONCURRENTLY with each other -- and the lane
is always kicked first, early in the tail, so on a busy machine both were live
for most of the gap.

WAITS rather than skips, deliberately: the lane's kick always arrives first, so
skip-on-contention would mean the briefing refresh essentially never ran, and a
permanently stale Home is not an improvement on a slow one. The wait is bounded
so a wedged consumer cannot pin the other's thread forever.

No DB, no network -- ``session_scope``, the lane and ``refresh_briefing`` are
stubbed; what is under test is the SEQUENCING.
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest

from src.scheduler.runner import BackgroundScheduler
from src.scheduler.settings import SchedulerSettings
from tests.wallclock_helpers import HANG_GUARD_S, call_on_thread


@pytest.fixture()
def sched():
    return BackgroundScheduler(settings_provider=lambda: SchedulerSettings())


def _stub_scope(monkeypatch):
    @contextlib.contextmanager
    def _fake_scope():
        yield object()

    monkeypatch.setattr("src.database.session.session_scope", _fake_scope)


def test_the_briefing_refresh_waits_for_the_lane_instead_of_running_beside_it(
    monkeypatch, sched
):
    _stub_scope(monkeypatch)
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())

    live = set()
    overlap: list[str] = []
    lock = threading.Lock()
    lane_running = threading.Event()
    lane_release = threading.Event()

    def _mark(tag):
        with lock:
            if live:
                overlap.append(f"{tag} started while {sorted(live)} was running")
            live.add(tag)

    def _unmark(tag):
        with lock:
            live.discard(tag)

    def _lane(_session, _fetcher, _settings):
        _mark("lane")
        lane_running.set()
        lane_release.wait(10)
        _unmark("lane")
        return {"ok": True}

    def _refresh(_session):
        _mark("briefing")
        time.sleep(0.05)
        _unmark("briefing")

    monkeypatch.setattr("src.scheduler.runner.run_housekeeping_lane", _lane)
    monkeypatch.setattr("src.briefing.service.refresh_briefing", _refresh)

    sched._kick_housekeeping_lane()
    assert lane_running.wait(3), "the lane never started"
    sched._refresh_briefing_async()
    # The refresh thread exists and is BLOCKED on the shared lock, not running.
    time.sleep(0.2)
    with lock:
        assert live == {"lane"}, f"the briefing refresh ran beside the lane: {live}"

    lane_release.set()
    sched._lane_thread.join(HANG_GUARD_S)
    sched._briefing_thread.join(HANG_GUARD_S)
    assert overlap == [], overlap
    # ...and it RAN, rather than being skipped: waiting is the point.
    assert sched._heavy_tail_waits == 0


def test_a_lone_consumer_is_not_delayed(monkeypatch, sched):
    """The negative twin: a serialisation that made an uncontended consumer wait
    would trade a duty-cycle problem for a slower one."""
    _stub_scope(monkeypatch)
    done = threading.Event()
    monkeypatch.setattr("src.briefing.service.refresh_briefing", lambda _s: done.set())

    sched._refresh_briefing_async()
    # The wait for the other consumer is 900 s by default: a refresh that waited for a lock nobody holds is late by that much.
    assert done.wait(HANG_GUARD_S), "an uncontended refresh waited for a lock nobody holds"
    sched._briefing_thread.join(HANG_GUARD_S)


def test_the_wait_is_bounded_and_the_give_up_is_counted(monkeypatch, sched):
    """A wedged consumer must not pin the other's thread forever."""
    monkeypatch.setenv("OO_HEAVY_TAIL_WAIT_S", "0.1")
    sched._heavy_tail_lock.acquire()
    try:
        # An unbounded wait never returns while the lock is held, so the guard is what tells it from the 0.1 s bound.
        came_back, got = call_on_thread(sched._acquire_heavy_tail, "test consumer")
        assert came_back, "the wait for the other consumer was not bounded"
        assert got is False
        assert sched._heavy_tail_waits == 1
    finally:
        sched._heavy_tail_lock.release()
    # ...and once it is free again, the very next caller gets in.
    assert sched._acquire_heavy_tail("test consumer") is True
    sched._heavy_tail_lock.release()


def test_the_wait_asks_the_lock_for_exactly_the_bound_it_was_given(monkeypatch, sched):
    """What the bounded wait ASKS of the lock, read directly: a wait of 3 s for a bound of 0.1 s comes back inside the guard of the test
    above just the same, and a machine that stalls for a second cannot be told from one that waits too long by timing it."""
    monkeypatch.setenv("OO_HEAVY_TAIL_WAIT_S", "0.1")
    asked: list[float] = []

    class _HeldElsewhere:
        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            asked.append(timeout)
            return False

        def release(self) -> None:
            raise AssertionError("released a lock it never got")

    monkeypatch.setattr(sched, "_heavy_tail_lock", _HeldElsewhere())
    assert sched._acquire_heavy_tail("test consumer") is False
    assert asked == [0.1]
    assert sched._heavy_tail_waits == 1


def test_a_lane_that_gives_up_says_so_rather_than_reporting_a_run(monkeypatch, sched):
    """An honest skip, not a silent one: the run report must not read as though
    the lane did its work."""
    monkeypatch.setenv("OO_HEAVY_TAIL_WAIT_S", "0.1")
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())
    monkeypatch.setattr(
        "src.scheduler.runner.run_housekeeping_lane",
        lambda *_a: pytest.fail("the lane ran without the heavy-tail lock"),
    )
    sched._heavy_tail_lock.acquire()
    try:
        sched._kick_housekeeping_lane()
        sched._lane_thread.join(HANG_GUARD_S)
    finally:
        sched._heavy_tail_lock.release()
    assert sched._last_lane_result == {"skipped": "another heavy tail consumer is running"}
