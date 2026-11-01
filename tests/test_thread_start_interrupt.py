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

import logging
import threading

import pytest

from src.database import writer
from src.database.damage import DamageRegistry
from src.jobs.background import BackgroundJob
from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S, wait_until

_KEY = ("sweep-key",)
_REAL_START = threading.Thread.start


def _start_fails(monkeypatch, name_prefix, how):
    """``never``: ``start`` raises before the thread exists (an out-of-threads process). ``interrupted``: the OS thread is created, then an
    interrupt lands while ``start`` waits for it to report in (CPython 3.13's ``self._started.wait()``)."""
    real = _REAL_START

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


def _start_works_again(monkeypatch):
    """Only ``Thread.start`` is put back: ``monkeypatch.undo()`` would also undo the fixtures' other patches."""
    monkeypatch.setattr(threading.Thread, "start", _REAL_START)


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
    _start_works_again(monkeypatch)
    job.start()
    job.join()
    assert job.status()["state"] != "error"


# -- BackgroundJob.start: the refused start is in the log, once, with none of the exception's words -- #

_LOGGER = "jobs.background"


def _did_not_start(caplog):
    return [r for r in caplog.records if r.name == _LOGGER and "did not start" in r.getMessage()]


def test_a_job_whose_thread_could_not_be_created_is_logged_once_as_a_warning_with_the_jobs_own_error_text(monkeypatch, caplog):
    """Every caller of every job kind shares this one line: the routes that map the refusal to an answer used to carry a line each, and most
    carried none. It says what the job's own ``error`` field says, which is the class and a fixed note."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    w = _Workers()
    job = BackgroundJob("sweep-logged", "sweep", w.work)
    _start_fails(monkeypatch, "bgjob-sweep-logged", "never")
    with pytest.raises(RuntimeError, match="can't start new thread"):
        job.start()
    lines = _did_not_start(caplog)
    assert len(lines) == 1, "the refused start must be logged exactly once"
    assert lines[0].levelno == logging.WARNING
    assert lines[0].getMessage() == f"background job sweep-logged did not start: {job.status()['error']}"
    assert job.status()["error"] == "RuntimeError: could not start the worker thread"


def test_the_refused_start_log_carries_none_of_the_exceptions_words(monkeypatch, caplog):
    """A start's keyword arguments can hold a passphrase or a mailbox password and this point has not read the job's secrets, so the
    class and the fixed note are all it writes: whatever the exception says stays out of the log."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER)

    def start(self):
        raise RuntimeError("can't start new thread (passphrase=hunter2 mailbox_password=correct-horse)")

    monkeypatch.setattr(threading.Thread, "start", start)
    job = BackgroundJob("sweep-quiet", "sweep", _Workers().work)
    with pytest.raises(RuntimeError):
        job.start(passphrase="hunter2", mailbox_password="correct-horse")
    assert len(_did_not_start(caplog)) == 1
    assert "hunter2" not in caplog.text and "correct-horse" not in caplog.text and "passphrase" not in caplog.text
    assert "hunter2" not in repr(job.status()) and "correct-horse" not in repr(job.status())


def test_a_start_that_finds_a_run_in_flight_logs_no_refused_start(monkeypatch, caplog):
    """The 'already running' refusal is a different fact (the caller reads the live status) and is not a failed thread start."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = _Workers()
    job = BackgroundJob("sweep-busy", "sweep", w.work)
    try:
        job.start()
        assert wait_until(lambda: w.running == 1)
        with pytest.raises(RuntimeError, match="already running"):
            job.start()
        assert _did_not_start(caplog) == []
    finally:
        w.release.set()
        job.join()


def test_an_interrupt_during_start_logs_no_refused_start(monkeypatch, caplog):
    """An interrupt leaves a live worker thread behind and the job running; saying it 'did not start' would be false."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    w = _Workers()
    job = BackgroundJob("sweep-interrupt-log", "sweep", w.work)
    _start_fails(monkeypatch, "bgjob-sweep-interrupt-log", "interrupted")
    try:
        with pytest.raises(KeyboardInterrupt):
            job.start()
        assert wait_until(lambda: w.running == 1)
        assert _did_not_start(caplog) == []
    finally:
        w.release.set()
        job.join()


def test_a_start_that_is_refused_still_raises_when_the_log_cannot_be_written(monkeypatch):
    """The line is best effort: a handler that raises must not replace the refusal the caller maps to its answer."""
    job = BackgroundJob("sweep-broken-log", "sweep", _Workers().work)
    _start_fails(monkeypatch, "bgjob-sweep-broken-log", "never")

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.jobs.background._LOG.warning", broken)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        job.start()
    assert job.status()["state"] == "error" and job._thread is None


def test_the_refusal_the_caller_catches_is_the_very_exception_the_thread_raised_with_its_chain_as_it_was(monkeypatch):
    """The callers map the refusal to an answer (and some read its type): the wrapper that writes the line re-raises the original object,
    never a copy of it, and leaves ``__context__`` and ``__cause__`` as a plain re-raise leaves them, whether or not the caller was
    already handling another exception."""
    raised: list[RuntimeError] = []

    def start(self):
        err = RuntimeError("can't start new thread")
        raised.append(err)
        raise err

    monkeypatch.setattr(threading.Thread, "start", start)
    job = BackgroundJob("sweep-identity", "sweep", _Workers().work)
    with pytest.raises(RuntimeError) as plain:
        job.start()
    assert plain.value is raised[0]
    assert plain.value.__context__ is None and plain.value.__cause__ is None and not plain.value.__suppress_context__

    outer = ValueError("the caller was handling this")
    with pytest.raises(RuntimeError) as nested:
        try:
            raise outer
        except ValueError:
            job.start()
    assert nested.value is raised[1] and nested.value is not raised[0]
    assert nested.value.__context__ is outer and nested.value.__cause__ is None and not nested.value.__suppress_context__


def test_the_job_lock_is_not_held_while_the_refused_start_is_written(monkeypatch):
    """A log handler can block (a full pipe, a slow disk). ``status()`` readers wait on the job's lock, so the line is written after it is
    released: a handler that is stuck must not stop the task manager reading the job."""
    entered, release = threading.Event(), threading.Event()

    class Stuck(logging.Handler):
        def emit(self, record):
            if "did not start" in record.getMessage():
                entered.set()
                release.wait(2 * HANG_GUARD_S)  # outlasts the reader's guard below, so a reader held by the lock fails instead of being let go

    logger = logging.getLogger(_LOGGER)
    handler = Stuck(level=logging.WARNING)
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    job = BackgroundJob("sweep-stuck-log", "sweep", _Workers().work)
    _start_fails(monkeypatch, "bgjob-sweep-stuck-log", "never")
    raised: list[BaseException] = []

    def starter():
        try:
            job.start()
        except RuntimeError as exc:
            raised.append(exc)

    t = threading.Thread(target=starter, name="starter-stuck-log", daemon=True)
    seen: list[dict] = []
    reader = threading.Thread(target=lambda: seen.append(job.status()), name="reader-stuck-log", daemon=True)
    try:
        t.start()
        assert entered.wait(HANG_GUARD_S), "the refused start was never written"
        reader.start()
        assert wait_until(lambda: bool(seen)), "status() waited on the job lock while the log handler was stuck"
        assert seen[0]["state"] == "error"
    finally:
        release.set()
        t.join(HANG_GUARD_S)
        reader.join(HANG_GUARD_S)
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert len(raised) == 1


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


# -- writer.start_write_gate_watchdog --------------------------------------- #


def _watchdogs():
    return [t for t in threading.enumerate() if t.name == "oo-write-gate-watchdog"]


@pytest.fixture()
def watchdog(monkeypatch):
    """The process may already run the real watchdog (the first gate acquisition of any earlier test arms it): only the ones started here
    are counted."""
    hold = threading.Event()
    before = set(_watchdogs())
    monkeypatch.setattr(writer, "_WATCHDOG_STARTED", False)
    monkeypatch.setattr(writer, "_watchdog_loop", lambda stop: hold.wait(HANG_GUARD_S))
    monkeypatch.delenv("OO_WRITE_GATE_WATCHDOG", raising=False)

    def mine():
        return [t for t in _watchdogs() if t not in before]

    yield mine
    hold.set()
    assert wait_until(lambda: not mine())


def test_a_watchdog_created_before_an_interrupt_is_not_started_twice(monkeypatch, watchdog):
    _start_fails(monkeypatch, "oo-write-gate-watchdog", "interrupted")
    with pytest.raises(KeyboardInterrupt):
        writer.start_write_gate_watchdog()
    assert wait_until(lambda: len(watchdog()) == 1), "the watchdog never ran, so the premise of this test (a live thread with ident None) did not hold"
    _start_works_again(monkeypatch)  # the next call is an ordinary one
    assert writer.start_write_gate_watchdog() is False, "a second watchdog was started beside the live one"
    assert len(watchdog()) == 1


def test_a_watchdog_that_could_not_be_created_can_be_started_again(monkeypatch, watchdog):
    _start_fails(monkeypatch, "oo-write-gate-watchdog", "never")
    with pytest.raises(RuntimeError, match="can't start new thread"):
        writer.start_write_gate_watchdog()
    assert not watchdog()
    _start_works_again(monkeypatch)
    assert writer.start_write_gate_watchdog() is True
