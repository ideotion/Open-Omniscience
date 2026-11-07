"""A retired pending-resume watcher leaves at once, not at the end of its 30 s poll.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/conftest.py`` retires the process-global watcher at every test's teardown with ``cancel_pending_resume()``, which bumps the
generation. The watcher used to wait ``time.sleep(RESUME_POLL_S)`` (30 s) BEFORE it looked at the generation, so a test that handed off to a
default-poll watcher left a live ``oo-resume-watch`` thread for up to 30 s, and the next test that asserts "no watcher is running"
(``tests/test_resume_watcher_thread_start_failure.py``) failed whenever the runner was fast enough to reach it inside that window. The wait is
now an Event that every bump of the generation sets.
"""

from __future__ import annotations

import threading

from src.scheduler import runner
from tests.wallclock_helpers import HANG_GUARD_S, wait_until

_NAME = "oo-resume-watch"


class _Sched:
    _thread = None

    def start(self):
        return False

    def holds_exclusive(self):
        return False


def _watchers():
    return [t for t in threading.enumerate() if t.name == _NAME]


def test_a_cancelled_watcher_on_the_default_poll_leaves_at_once():
    assert runner.RESUME_POLL_S >= 30.0, "the default poll is the long one this test is about"
    t = runner._watch_for_resume(_Sched())  # the default poll, as resume_after_exclusive_operation starts it
    try:
        assert t.is_alive()
        runner.cancel_pending_resume()
        t.join(HANG_GUARD_S)
        assert not t.is_alive(), "a retired watcher stayed asleep for the rest of its poll"
        assert wait_until(lambda: not _watchers())
    finally:
        runner.cancel_pending_resume()


def test_a_newer_watcher_retires_the_older_one_at_once():
    first = runner._watch_for_resume(_Sched())
    second = None
    try:
        second = runner._watch_for_resume(_Sched())
        first.join(HANG_GUARD_S)
        assert not first.is_alive(), "the older watcher outlived the one that replaced it"
        assert second.is_alive(), "the newer watcher owns the claim and keeps running"
        assert runner.resume_pending() is not None
    finally:
        runner.cancel_pending_resume()
        if second is not None:
            second.join(HANG_GUARD_S)
            assert not second.is_alive()


def test_a_watcher_with_no_event_still_waits_by_the_clock(monkeypatch):
    """The direct call without the event (older callers and tests) keeps the old behaviour: sleep, then look at the generation."""
    seen = []
    monkeypatch.setattr(runner.time, "sleep", lambda s: seen.append(s))
    with runner._RESUME_LOCK:
        gen = runner._RESUME_GEN + 1
        runner._RESUME_GEN = gen
    runner._RESUME_GEN += 1  # retired before it looks: it returns after its one wait
    runner._resume_watch(_Sched(), None, gen, 0.5)
    assert seen == [0.5]
