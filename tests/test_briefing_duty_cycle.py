"""S4.1 duty-cycle fix (field-feedback 2026-07-23): the whole-corpus briefing
recompute must run in its OWN background thread, non-blocking, non-overlapping,
and never crash the scheduler on failure — the point of the fix is to let the
next pass's collection start concurrently with this recompute instead of
waiting for it. See ``BackgroundScheduler._refresh_briefing_async``.

No DB, no network — ``session_scope`` and ``refresh_briefing`` are stubbed.
"""

from __future__ import annotations

import contextlib
import threading

import pytest

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


def test_returns_before_the_refresh_completes(monkeypatch, sched):
    """The whole point of the fix: kicking off the refresh must not block the
    caller while the (potentially slow) recompute runs."""
    _fake_scope_factory(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def _slow_refresh(session):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _slow_refresh)

    sched._refresh_briefing_async()
    # The call above must have returned already (it's synchronous Python, so if
    # we get here at all it did) -- the real assertion is that the refresh is
    # STILL blocked in the background, proving it never ran inline.
    assert started.wait(timeout=2), "the background thread never started"
    assert not release.is_set()  # we haven't released it yet — it's mid-flight

    release.set()
    sched._briefing_thread.join(timeout=5)
    assert not sched._briefing_thread.is_alive()


def test_a_second_call_is_skipped_while_one_is_running(monkeypatch, sched):
    """Non-overlapping, never queued: a busy refresh means the NEXT attempt is
    skipped outright, not stacked behind the first."""
    _fake_scope_factory(monkeypatch)
    calls = []
    release = threading.Event()
    entered = threading.Event()

    def _slow_refresh(session):
        calls.append("run")
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _slow_refresh)

    sched._refresh_briefing_async()
    assert entered.wait(timeout=2)
    first_thread = sched._briefing_thread

    # A second attempt while the first is still in flight must be a no-op.
    sched._refresh_briefing_async()
    assert sched._briefing_thread is first_thread  # no new thread was spawned

    release.set()
    first_thread.join(timeout=5)
    assert calls == ["run"]  # refresh_briefing was invoked exactly once

    # Once the first has fully finished (lock released), a later attempt must
    # be allowed to run again — "never queued" is not "never again".
    calls.clear()
    entered.clear()
    release.clear()
    sched._refresh_briefing_async()
    assert entered.wait(timeout=2)
    release.set()
    sched._briefing_thread.join(timeout=5)
    assert calls == ["run"]


def test_a_raising_refresh_never_crashes_the_thread_and_still_releases_the_lock(
    monkeypatch, sched
):
    _fake_scope_factory(monkeypatch)

    def _boom(session):
        raise RuntimeError("simulated briefing failure")

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _boom)

    sched._refresh_briefing_async()
    sched._briefing_thread.join(timeout=5)
    assert not sched._briefing_thread.is_alive()

    # The lock must be released on a failure too, or every later pass would
    # silently skip the refresh forever.
    assert sched._briefing_bg_lock.acquire(blocking=False)
    sched._briefing_bg_lock.release()


def test_briefing_refresh_is_visible_in_the_task_manager_while_running(monkeypatch, sched):
    _fake_scope_factory(monkeypatch)
    release = threading.Event()
    entered = threading.Event()

    def _slow_refresh(session):
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr("src.briefing.service.refresh_briefing", _slow_refresh)

    from src.monitoring import tasks as bgtasks

    sched._refresh_briefing_async()
    assert entered.wait(timeout=2)
    snap = bgtasks.snapshot()
    assert any(t["kind"] == "briefing" for t in snap), snap

    release.set()
    sched._briefing_thread.join(timeout=5)
    snap_after = bgtasks.snapshot()
    assert not any(t["kind"] == "briefing" for t in snap_after), snap_after
