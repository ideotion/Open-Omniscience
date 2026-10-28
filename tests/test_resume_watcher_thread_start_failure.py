"""A pending-resume watcher that cannot be started does not leave a resume claimed that nothing is waiting on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_watch_for_resume`` publishes ``_RESUME_PENDING`` (what the Schedule tab and ``status()["resume_pending"]`` show as "collection starts
again the moment that pass exits") and then starts the ``oo-resume-watch`` thread. ``Thread.start()`` raises ``RuntimeError`` ("can't
start new thread") before the target runs when the process is out of threads, so the claim stayed for the life of the process with no
watcher behind it, and the error escaped ``resume_after_exclusive_operation`` into the finally of the backup or restore that called it
(the same shape as ``tests/test_scheduler_detached_thread_start_failure.py``, which closed it for the pass tail's two threads).
"""

from __future__ import annotations

import logging
import threading

import pytest

from src.scheduler import runner

_NAME = "oo-resume-watch"


class _Sched:
    _thread = None

    def __init__(self):
        self.released = 0

    def start(self):
        return False

    def holds_exclusive(self):
        return False

    def take_deferred_start(self):
        return False

    def release_exclusive(self):
        self.released += 1


def _refuse_start(monkeypatch, *, newer_watcher_takes_over=False):
    real = threading.Thread.start

    def start(self):
        if self.name != _NAME:
            return real(self)
        if newer_watcher_takes_over:  # another watcher was published between the claim and the failed start
            with runner._RESUME_LOCK:
                runner._RESUME_GEN += 1
                runner._RESUME_PENDING = {"since": "newer", "waiting_for": None, "basis": "newer watcher"}
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", start)


def _watchers():
    return [t for t in threading.enumerate() if t.name == _NAME]


def test_a_watcher_that_cannot_start_retracts_its_claim(monkeypatch):
    _refuse_start(monkeypatch)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        runner._watch_for_resume(_Sched(), poll_s=0.01)
    assert runner.resume_pending() is None, "a resume is shown as pending with no watcher behind it"
    assert not _watchers()


def test_a_newer_watchers_claim_is_not_retracted(monkeypatch):
    _refuse_start(monkeypatch, newer_watcher_takes_over=True)
    with pytest.raises(RuntimeError):
        runner._watch_for_resume(_Sched(), poll_s=0.01)
    pending = runner.resume_pending()
    assert pending is not None and pending["basis"] == "newer watcher"


def test_the_failure_does_not_escape_the_resume_into_the_operations_finally(monkeypatch, caplog):
    sched = _Sched()
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(runner, "exclusive_window_open", lambda: False)
    monkeypatch.setattr(runner, "_start_or_stand_down", lambda retries, retry_delay: False)
    _refuse_start(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=runner._LOG.name):
        runner.resume_after_exclusive_operation(True, retries=1, retry_delay=0)  # does not raise
    assert sched.released == 1, "the hold was not given back"
    assert runner.resume_pending() is None
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "watcher thread could not be started" in said
    assert "resumes on its own" not in said, "the log promised a resume that nothing will make"
