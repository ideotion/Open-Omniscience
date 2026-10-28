"""A pass-tail thread that cannot be started does not leave its non-overlap lock held for the life of the process.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_refresh_briefing_async`` and ``_kick_housekeeping_lane`` take a non-blocking lock, build a thread whose ``_run`` releases it in a
``finally``, and start the thread. ``Thread.start()`` raises ``RuntimeError`` ("can't start new thread") before the target runs when
the process is out of threads, so that ``finally`` never ran: every later pass skipped the launch as "still running" and
``whole_corpus_work_running()`` read true until the process ended (found by the read of #1629; ``service._ensure_background_refresh``
already handled the same case, the scheduler's two launches did not).
"""

from __future__ import annotations

import threading

import pytest

from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S, wait_until

_LAUNCHES = [
    ("_refresh_briefing_async", "oo-briefing-bg", "_briefing_bg_lock"),
    ("_kick_housekeeping_lane", "oo-housekeeping-lane", "_lane_lock"),
]


class _Settings:
    continuous = True
    interval_minutes = 1
    mode = "rss"

    def to_dict(self):
        return {}


@pytest.fixture()
def sched(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    return BackgroundScheduler(settings_provider=_Settings)


def _no_work(monkeypatch):
    """What the launched thread would do is not under test: it ends at once."""
    monkeypatch.setattr("src.briefing.service.refresh_briefing", lambda session: {"kept_reason": "test"})
    monkeypatch.setattr("src.scheduler.runner.run_housekeeping_lane", lambda session, fetcher, settings: {})
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: object())


def _real_start_except(monkeypatch, name, how, *, times=None):
    """Patch ``Thread.start`` for the one named thread: ``how`` is ``never`` (raises before the thread runs, as an out-of-threads
    process does) or ``after`` (the thread really starts and then ``start`` raises anyway). ``times`` limits how many starts fail."""
    real = threading.Thread.start
    failed = [0]

    def start(self):
        if self.name != name or (times is not None and failed[0] >= times):
            return real(self)
        failed[0] += 1
        if how == "after":
            real(self)
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", start)


@pytest.mark.parametrize(("method", "name", "lock"), _LAUNCHES)
def test_a_thread_that_cannot_start_frees_the_lock_and_the_pass_goes_on(sched, monkeypatch, method, name, lock):
    _real_start_except(monkeypatch, name, "never")
    getattr(sched, method)()  # never raises into the pass tail
    assert not getattr(sched, lock).locked(), "the lock stayed held: every later pass would skip this launch"
    assert not sched.whole_corpus_work_running()


@pytest.mark.parametrize(("method", "name", "lock"), _LAUNCHES)
def test_the_next_launch_after_a_failed_start_runs(sched, monkeypatch, method, name, lock):
    _no_work(monkeypatch)
    _real_start_except(monkeypatch, name, "never", times=1)
    getattr(sched, method)()
    getattr(sched, method)()  # a skipped launch ("still running") would never start a thread at all
    assert wait_until(lambda: not getattr(sched, lock).locked(), guard_s=HANG_GUARD_S), "the second launch never ran to its release"


@pytest.mark.parametrize(("method", "name", "lock"), _LAUNCHES)
def test_a_thread_that_did_start_releases_for_itself_once(sched, monkeypatch, method, name, lock):
    """``start`` raising AFTER the target ran (exotic, but it is the case that tells a release-unconditionally fix from the right one): the
    thread's own ``finally`` releases, and a second release here would raise in the thread."""
    _no_work(monkeypatch)
    _real_start_except(monkeypatch, name, "after")
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", thread_errors.append)
    getattr(sched, method)()
    assert wait_until(lambda: not getattr(sched, lock).locked(), guard_s=HANG_GUARD_S)
    thread = getattr(sched, "_briefing_thread" if "briefing" in method else "_lane_thread")
    thread.join(HANG_GUARD_S)
    assert thread_errors == [], f"the thread died on a double release: {thread_errors}"
