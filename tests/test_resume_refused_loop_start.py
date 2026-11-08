"""A scheduler loop thread that cannot start does not turn a FINISHED exclusive operation into an error.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WAL's measured probe (2026-11-01, main 6ac8ae7, injected failure): with ``Thread.start()`` refusing the ``oo-scheduler`` thread, a finished
``POST /api/system/encrypt-db`` answered 500 (the store WAS encrypted and the plaintext snapshot is on disk, but the response that reports
both was replaced) and a finished ``GET /api/diagnostics/all`` answered 500 after building the whole bundle. Cause: ``exclusive_window``'s
``finally`` calls ``resume_after_exclusive_operation``, which called ``_start_or_stand_down`` with no handler, and ``start()`` re-raises.
Every operation that runs in the window (restore volumes, the import queue, stream backup, repair) shared that exit.
"""

from __future__ import annotations

import logging

import pytest

import src.scheduler.runner as R

WORDS = "the-words-of-the-refusal"


class _Sched:
    def __init__(self, refuse: int = 1, exc: BaseException | None = None) -> None:
        self.running = True
        self.releases = 0
        self.starts = 0
        self.refuse = refuse
        self.exc = exc or RuntimeError(WORDS)

    def hold_exclusive(self) -> None:
        pass

    def release_exclusive(self) -> None:
        self.releases += 1

    def stop(self, timeout: float = 10.0) -> bool:
        was, self.running = self.running, False
        return was

    def take_deferred_start(self) -> bool:
        return False

    def start(self) -> bool:
        self.starts += 1
        if self.starts <= self.refuse:
            raise self.exc
        self.running = True
        return True


def _watchers_gone(secs: float = 10.0) -> None:
    """Wait for every resume-watcher thread to leave (the watchers here poll every 10 ms, so this is a moment). Without it the next test
    file starts while a retired watcher is still in its last sleep, and a test that asserts "no watcher thread" fails on it."""
    import threading
    import time

    end = time.monotonic() + secs
    while time.monotonic() < end and any(t.name == "oo-resume-watch" for t in threading.enumerate()):
        time.sleep(0.005)


@pytest.fixture()
def sched(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    s = _Sched()
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "RESUME_POLL_S", 0.01)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    R.cancel_pending_resume()
    yield s
    R.cancel_pending_resume()
    _watchers_gone()  # a retired watcher leaves at its next look: do not hand a live one to the next test file
    monkeypatch.undo()


def _wait(cond, secs: float = 10.0) -> bool:
    import time

    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_a_refused_loop_start_does_not_raise_out_of_the_window_and_a_watcher_takes_over(sched, caplog):
    caplog.set_level(logging.DEBUG, logger=R._LOG.name)
    with R.exclusive_window() as was:
        assert was is True
    # the window exited normally: the operation's own result is not replaced by the refusal
    assert sched.releases == 1, "the exclusive hold was released"
    assert R.resume_pending() is not None or sched.running, "a watcher was started (or it already resumed)"
    assert _wait(lambda: sched.running and R.resume_pending() is None), "the watcher did not resume collection"
    said = [r for r in caplog.records if "could not start background collection" in r.getMessage()]
    assert len(said) == 1 and said[0].levelno == logging.WARNING and "RuntimeError" in said[0].getMessage()


def test_the_words_of_the_refusal_stay_out_of_the_log(sched, caplog):
    caplog.set_level(logging.DEBUG, logger=R._LOG.name)
    with R.exclusive_window():
        pass
    assert WORDS not in caplog.text
    assert all(r.exc_info is None for r in caplog.records if "could not start background collection" in r.getMessage())


def test_when_the_watcher_cannot_start_either_it_says_so_and_still_does_not_raise(sched, monkeypatch, caplog):
    def refuse(*a, **k):
        raise RuntimeError("no thread for the watcher")

    monkeypatch.setattr(R, "_watch_for_resume", refuse)
    caplog.set_level(logging.DEBUG, logger=R._LOG.name)
    with R.exclusive_window():
        pass
    assert sched.releases == 1 and sched.running is False
    assert "nothing is waiting to" in caplog.text and "collection stays stopped" in caplog.text


def test_an_interrupt_in_the_start_is_not_swallowed_and_the_hold_is_still_released(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    s = _Sched(exc=KeyboardInterrupt())
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    with pytest.raises(KeyboardInterrupt), R.exclusive_window():
        pass
    assert s.releases == 1, "the finally still gave the hold back"


def test_a_start_that_works_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    s = _Sched(refuse=0)
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    with R.exclusive_window():
        pass
    assert (s.starts, s.releases) == (1, 1) and R.resume_pending() is None
