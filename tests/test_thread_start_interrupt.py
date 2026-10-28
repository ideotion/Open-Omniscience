"""A ``Thread.start()`` that is interrupted AFTER the OS thread exists is not read as 'the thread never ran'.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

CPython 3.13's ``Thread.start()`` catches only ``Exception`` around creating the OS thread ("can't start new thread" is a
``RuntimeError``), then waits ``self._started.wait()`` for the thread to report in. An interrupt (a ``BaseException``) during that wait
escapes with the thread created and about to run, ``ident`` still None and ``is_alive()`` False (measured on 3.13.17: ``ident`` set 0.1 s
later). A handler that reads the escape as 'the thread never ran' and gives its record back therefore leaves a live thread nobody holds:
``BackgroundJob.start()`` marked the job 'error' so a second ``start()`` ran a second worker of the same kind, and
``DamageRegistry._single_flight`` dropped the key so the next call for it started a second thread. Both now act on an ``Exception`` only
(the same correction as ``BackgroundScheduler.start()`` and ``_watch_for_resume``, tests/test_scheduler_start_failure_state.py).
``BackgroundScheduler._start_detached`` was already ``except Exception``; it is pinned here so it stays so.
"""

from __future__ import annotations

import threading

import pytest

from src.database.damage import DamageRegistry
from src.jobs.background import BackgroundJob
from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S, wait_until

_KEY = ("sweep-key",)


def _start_fails(monkeypatch, name_prefix, how):
    """``never``: ``start`` raises before the thread exists (an out-of-threads process). ``interrupted``: the OS thread is created, then an
    interrupt lands while ``start`` waits for it to report in (CPython 3.13's ``self._started.wait()``)."""
    real = threading.Thread.start

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    def start(self):
        if not self.name.startswith(name_prefix):
            return real(self)
        if how == "interrupted":
            self._started.wait = interrupt
            return real(self)
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", start)


class _Workers:
    """A worker that holds until released and counts how many run at once."""

    def __init__(self):
        self.release = threading.Event()
        self.running = 0
        self.peak = 0
        self._lock = threading.Lock()

    def work(self, *args, **kwargs):
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            self.release.wait(HANG_GUARD_S)
        finally:
            with self._lock:
                self.running -= 1


# -- BackgroundJob.start ---------------------------------------------------- #


def test_a_job_whose_thread_was_created_before_an_interrupt_stays_running(monkeypatch):
    w = _Workers()
    job = BackgroundJob("sweep-interrupt", "sweep", w.work)
    _start_fails(monkeypatch, "bgjob-sweep-interrupt", "interrupted")
    try:
        with pytest.raises(KeyboardInterrupt):
            job.start()
        assert wait_until(lambda: w.running == 1), "the worker never ran, so the premise of this test (a live thread with ident None) did not hold"
        assert job.status()["state"] == "running", "a job with a live worker was marked as failed to start"
        with pytest.raises(RuntimeError, match="already running"):
            job.start()
        assert w.peak == 1, "a second worker of the same kind ran beside the first"
    finally:
        w.release.set()
        job.join()


def test_a_job_whose_thread_could_not_be_created_is_marked_failed_and_can_start_again(monkeypatch):
    w = _Workers()
    w.release.set()
    job = BackgroundJob("sweep-never", "sweep", w.work)
    _start_fails(monkeypatch, "bgjob-sweep-never", "never")
    with pytest.raises(RuntimeError, match="can't start new thread"):
        job.start()
    assert job.status()["state"] == "error" and job._thread is None
    monkeypatch.undo()
    job.start()
    job.join()
    assert job.status()["state"] != "error"


# -- DamageRegistry._single_flight ------------------------------------------ #


def test_a_damage_job_created_before_an_interrupt_keeps_its_key(monkeypatch):
    w = _Workers()
    reg = DamageRegistry()
    _start_fails(monkeypatch, "oo-damage-record", "interrupted")
    try:
        with pytest.raises(KeyboardInterrupt):
            reg._single_flight(_KEY, w.work)
        assert wait_until(lambda: w.running == 1), "the job never ran, so the premise of this test (a live thread with ident None) did not hold"
        assert _KEY in reg._jobs, "the key of a live job was dropped"
        reg._single_flight(_KEY, w.work)  # finds the live job and counts itself instead of starting another
        assert w.peak == 1, "a second thread ran for the same key"
        assert reg._pending.get(_KEY) == 1
    finally:
        w.release.set()
        assert wait_until(lambda: _KEY not in reg._jobs)


def test_a_damage_job_whose_thread_could_not_be_created_leaves_no_key(monkeypatch):
    reg = DamageRegistry()
    _start_fails(monkeypatch, "oo-damage-record", "never")
    with pytest.raises(RuntimeError, match="can't start new thread"):
        reg._single_flight(_KEY, lambda: None)
    assert _KEY not in reg._jobs


# -- BackgroundScheduler._start_detached (already Exception-only: pinned) -- #


def test_a_detached_launch_interrupted_after_its_thread_exists_leaves_the_lock_to_that_thread(monkeypatch):
    """The thread's own ``finally`` releases the lock; releasing it here as well would raise ``release unlocked lock`` in that thread."""
    lock = threading.Lock()
    lock.acquire()
    done = threading.Event()
    errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", errors.append)

    def run():
        try:
            done.wait(HANG_GUARD_S)
        finally:
            lock.release()

    thread = threading.Thread(target=run, name="oo-sweep-detached", daemon=True)
    _start_fails(monkeypatch, "oo-sweep-detached", "interrupted")
    try:
        with pytest.raises(KeyboardInterrupt):
            BackgroundScheduler._start_detached(thread, lock, "sweep launch")
        assert lock.locked(), "the launch released a lock that the live thread still owns"
    finally:
        done.set()
        assert wait_until(lambda: not lock.locked())
    thread.join(HANG_GUARD_S)
    assert errors == [], f"the thread died on a double release: {errors}"
