"""``status()`` names the guard that is DOWN when nothing is left to resume collection.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

After an exclusive operation (encrypt, diagnostics bundle, restore, repair ...) the resume tries ``start()``, then hands over to the
pending-resume watcher (``resume_pending``). When the OS refused the loop thread AND the watcher thread, the only trace was a WARNING in a
log: the Schedule tab read as an idle collector, and nothing would ever start it again (autostart off) until the operator pressed Start.
``status()["resume_abandoned"]`` says so, in the same payload the Schedule tab already polls: when, which class refused each thread (never
its words: the operation may have held a passphrase) and what to do. None whenever collection runs or a watcher is waiting.
"""

from __future__ import annotations

import pytest

import src.scheduler.runner as R

WORDS = "the-words-of-the-refusal"


class _Sched:
    def __init__(self, refuse: int = 100) -> None:
        self.running = True
        self.releases = 0
        self.starts = 0
        self.refuse = refuse

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
            raise RuntimeError(WORDS)
        self.running = True
        return True


def _refuse_watcher(*a, **k):
    raise OSError("no thread for the watcher " + WORDS)


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


def _status() -> dict:
    from src.scheduler.settings import SchedulerSettings

    return R.BackgroundScheduler(settings_provider=lambda: SchedulerSettings()).status()


def test_nothing_is_reported_when_nothing_went_wrong(sched):
    assert R.resume_abandoned() is None
    assert _status()["resume_abandoned"] is None


def test_a_resume_with_no_loop_and_no_watcher_is_named_in_status_by_the_class_of_each_refusal(sched, monkeypatch):
    monkeypatch.setattr(R, "_watch_for_resume", _refuse_watcher)
    with R.exclusive_window():
        pass
    assert sched.releases == 1 and sched.running is False
    got = R.resume_abandoned()
    assert got is not None
    assert got["start_error"] == "RuntimeError" and got["watcher_error"] == "OSError"
    assert got["since"] and "Start" in got["basis"]
    assert _status()["resume_abandoned"] == got
    assert WORDS not in repr(got), "the words of a refusal can carry a passphrase: the class only"


def test_a_watcher_that_is_waiting_is_pending_not_abandoned(sched):
    with R.exclusive_window():
        pass
    assert R.resume_abandoned() is None, "a watcher took over: resume_pending says so, nothing is abandoned"


def test_a_new_resume_that_works_retires_the_old_record(sched, monkeypatch):
    monkeypatch.setattr(R, "_watch_for_resume", _refuse_watcher)
    with R.exclusive_window():
        pass
    assert R.resume_abandoned() is not None
    sched.refuse = 0  # the next start works
    sched.running = True  # the operator had started collection again before the next operation
    with R.exclusive_window():
        pass
    assert sched.running is True
    assert R.resume_abandoned() is None


def test_the_operator_starting_collection_retires_the_record(sched, monkeypatch):
    monkeypatch.setattr(R, "_watch_for_resume", _refuse_watcher)
    with R.exclusive_window():
        pass
    assert R.resume_abandoned() is not None
    monkeypatch.setattr(R, "_ensure_storage_supervisor", lambda: None)
    monkeypatch.setattr(R.BackgroundScheduler, "_loop_recorded", lambda self: None)
    from src.scheduler.settings import SchedulerSettings

    real = R.BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    assert real.start() is True
    real._thread.join(2)
    assert R.resume_abandoned() is None, "a started loop is the end of the abandonment"
    assert real.status()["resume_abandoned"] is None


def test_a_shutdown_clears_the_record(sched, monkeypatch):
    monkeypatch.setattr(R, "_watch_for_resume", _refuse_watcher)
    with R.exclusive_window():
        pass
    R.cancel_pending_resume()
    assert R.resume_abandoned() is None



def test_a_later_resume_whose_watcher_starts_retires_the_old_record(sched, monkeypatch):
    """Pending and abandoned must never be reported together: the watcher of the later resume is waiting."""
    real_watch = R._watch_for_resume
    monkeypatch.setattr(R, "_watch_for_resume", _refuse_watcher)
    with R.exclusive_window():
        pass
    assert R.resume_abandoned() is not None
    monkeypatch.setattr(R, "_watch_for_resume", real_watch)
    sched.running = True  # collection was running again before the next operation
    with R.exclusive_window():
        pass
    assert R.resume_pending() is not None, "the later resume handed over to a watcher"
    assert R.resume_abandoned() is None
