"""A scheduler loop that cannot be started leaves ``status()`` saying when it LAST started, not a start that never happened.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``BackgroundScheduler.start()`` stamped ``_started_at`` and stored the new thread in ``_thread`` BEFORE ``Thread.start()``. That call
raises ``RuntimeError`` ("can't start new thread") before the target runs when the process is out of threads, so a failed start left a
``started_at`` in ``status()`` for a loop that never ran, and ``_thread`` pointing at a thread that was never started (found in the read
of #1638, stated there as cosmetic). The state is now recorded once the OS thread exists, and also when ``start()`` raises AFTER it
exists, because that thread owns the loop and an unrecorded live loop would be started a second time.
"""

from __future__ import annotations

import threading

import pytest

from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S


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
    monkeypatch.setattr("src.scheduler.runner._ensure_storage_supervisor", lambda: None)
    s = BackgroundScheduler(settings_provider=_Settings)
    s._loop = lambda: None  # what the loop would do is not under test: it ends at once
    return s


def _fail_start(monkeypatch, how, *, times=None):
    """``never``: ``start`` raises before the thread runs (an out-of-threads process). ``after``: the thread really starts, then ``start``
    raises anyway. ``times`` limits how many starts fail."""
    real = threading.Thread.start
    failed = [0]

    def start(self):
        if self.name != "oo-scheduler" or (times is not None and failed[0] >= times):
            return real(self)
        failed[0] += 1
        if how == "after":
            real(self)
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", start)


def test_a_failed_start_records_no_start(sched, monkeypatch):
    _fail_start(monkeypatch, "never")
    with pytest.raises(RuntimeError):
        sched.start()
    assert sched.status()["started_at"] is None, "status() claims a start that never happened"
    assert sched._thread is None, "a thread that was never started is held as the loop"
    assert not sched.is_running()


def test_a_failed_start_keeps_the_previous_start(sched, monkeypatch):
    """The honest value after a failed second start is the first start's, not the failed attempt's."""
    assert sched.start()
    sched._thread.join(HANG_GUARD_S)
    first = sched.status()["started_at"]
    assert first is not None
    first_thread = sched._thread
    _fail_start(monkeypatch, "never")
    with pytest.raises(RuntimeError):
        sched.start()
    assert sched.status()["started_at"] == first
    assert sched._thread is first_thread


def test_the_next_start_after_a_failed_one_starts(sched, monkeypatch):
    _fail_start(monkeypatch, "never", times=1)
    with pytest.raises(RuntimeError):
        sched.start()
    assert sched.start()
    sched._thread.join(HANG_GUARD_S)
    assert sched.status()["started_at"] is not None


def test_a_thread_that_did_start_is_recorded_even_if_start_raised(sched, monkeypatch):
    """``start`` raising AFTER the OS thread exists (exotic, and the case that tells recording-only-on-success from the right fix): the
    thread owns the loop, so it is the one recorded."""
    _fail_start(monkeypatch, "after")
    with pytest.raises(RuntimeError):
        sched.start()
    assert sched._thread is not None and sched._thread.ident is not None
    assert sched.status()["started_at"] is not None
    sched._thread.join(HANG_GUARD_S)
