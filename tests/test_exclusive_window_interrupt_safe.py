"""An interrupt delivered while ``exclusive_window`` is taking the machine does not leave the scheduler held (R171).

The window paused the scheduler (``hold_exclusive``, then ``stop``) BEFORE its ``try``, so a KeyboardInterrupt landing between that and the
``try`` skipped the resume and the scheduler stayed held. ``scripts/run_scale_bench.py`` is the one CLI that reaches it on a main thread
(tests/test_contextmanager_acquire_before_try.py is the scan that found the shape). Deterministic here: the pause is replaced by one that does
its work and then raises, as an interrupt after the stop would.

The stated limit: an interrupt before the pause has REPORTED leaves ``was_paused`` False, so the hold is released and the loop is not started
(the window cannot tell whether the stop happened); an interrupt after it reported resumes collection as usual.
"""

from __future__ import annotations

import pytest

import src.scheduler.runner as R


class _Sched:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.held = False
        self.starts = 0
        self.releases = 0

    def hold_exclusive(self) -> None:
        self.held = True

    def release_exclusive(self) -> None:
        self.held = False
        self.releases += 1

    def stop(self, timeout: float = 10.0) -> bool:
        was, self.running = self.running, False
        return was

    def start(self) -> bool:
        self.starts += 1
        self.running = True
        return True


class _InterruptOnFirstExit:
    def __init__(self) -> None:
        self.fired = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self.fired:
            self.fired = True
            raise KeyboardInterrupt
        return False


@pytest.fixture()
def sched(monkeypatch):
    s = _Sched()
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    # the window's own bookkeeping, so a window left standing by a regression cannot leak into the next test (or the rest of the run)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    return s


def test_an_interrupt_inside_the_pause_does_not_leave_the_scheduler_held(sched, monkeypatch):
    def pause_then_interrupt(timeout: float = 10.0) -> bool:
        sched.hold_exclusive()
        sched.stop()
        raise KeyboardInterrupt  # the pause stopped the loop and never reported it

    monkeypatch.setattr(R, "pause_for_exclusive_operation", pause_then_interrupt)
    with pytest.raises(KeyboardInterrupt), R.exclusive_window():
        pytest.fail("the body must not run")
    assert not sched.held, "the scheduler stayed held for good"
    assert sched.releases == 1 and not R.exclusive_window_open()
    assert sched.starts == 0  # the stated limit: the pause had not reported


def test_an_interrupt_after_the_pause_reported_resumes_collection(sched, monkeypatch):
    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(R, "_EXCL_LOCK", lock)
    monkeypatch.setattr(R, "exclusive_window_open", lambda: False)  # its own use of the lock must not spend the one interrupt
    with pytest.raises(KeyboardInterrupt), R.exclusive_window():
        pytest.fail("the body must not run")
    assert lock.fired
    assert not sched.held and sched.running and sched.starts == 1


def test_a_window_that_pauses_normally_still_resumes_once(sched):
    with R.exclusive_window() as was_paused:
        assert was_paused is True and sched.held
    assert not sched.held and sched.running and sched.starts == 1


class _InterruptOnFirstEnter:
    """The window's lock, wrapped: the first ``with`` raises an interrupt before the lock is taken, as one delivered just ahead of the count."""

    def __init__(self, real, before=None) -> None:
        self.real, self.fired, self.before = real, False, before

    def __enter__(self):
        if not self.fired:
            self.fired = True
            if self.before is not None:
                self.before()  # whatever happens on another thread just ahead of the interrupt
            raise KeyboardInterrupt
        return self.real.__enter__()

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)


def test_an_inner_window_interrupted_before_it_counted_leaves_the_outer_one_standing(sched, monkeypatch):
    with R.exclusive_window() as outer_paused:
        assert outer_paused is True and R._EXCL_DEPTH == 1
        real = R._EXCL_LOCK
        real_open = R.exclusive_window_open
        monkeypatch.setattr(R, "_EXCL_LOCK", _InterruptOnFirstEnter(real))
        monkeypatch.setattr(R, "exclusive_window_open", lambda: True)  # its own use of the lock must not spend the one interrupt
        with pytest.raises(KeyboardInterrupt), R.exclusive_window():
            pytest.fail("the body must not run")
        monkeypatch.setattr(R, "_EXCL_LOCK", real)
        monkeypatch.setattr(R, "exclusive_window_open", real_open)
        # The inner window never counted, so it gives nothing back: the outer window's depth, flag and hold are as they were.
        assert R._EXCL_DEPTH == 1 and R.exclusive_window_open() and sched.held and sched.starts == 0
    assert not sched.held and sched.running and sched.starts == 1 and not R.exclusive_window_open()


def test_an_inner_window_that_never_counted_gives_nothing_back_when_the_outer_one_left_first(sched, monkeypatch):
    outer = R.exclusive_window()
    assert outer.__enter__() is True
    real = R._EXCL_LOCK
    monkeypatch.setattr(R, "_EXCL_LOCK", _InterruptOnFirstEnter(real, before=lambda: outer.__exit__(None, None, None)))
    real_open, seen = R.exclusive_window_open, []

    def open_once_for_the_inner_window() -> bool:
        if not seen:
            seen.append(1)
            return True  # the inner window saw the outer one standing; everything after reads the real flag
        return real_open()

    monkeypatch.setattr(R, "exclusive_window_open", open_once_for_the_inner_window)
    with pytest.raises(KeyboardInterrupt), R.exclusive_window():
        pytest.fail("the body must not run")
    # The outer window left (and gave the scheduler back) before the inner one's ``finally`` ran; the inner one owns nothing, so it does not give it back again.
    assert sched.releases == 1 and sched.starts == 1 and sched.running and not sched.held
    assert R._EXCL_DEPTH == 0
