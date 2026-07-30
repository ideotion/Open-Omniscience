"""Collection does not resume between backups: ONE window spans the whole import.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ruling 2026-07-29 item 10. Each volume restore pauses collection for its own
duration and resumes in a ``finally``, so a 6-backup run paused and RESUMED five times
mid-import — re-opening between every backup the exact race the pause exists to close,
and defeating "import owns the machine" for the majority of the run's wall time.

THE MECHANISM MATTERS, and the first cut got it wrong. A nesting COUNTER passes the
happy-path tests and is quietly broken: it self-corrects only under perfect pairing, so
a single unbalanced pause anywhere leaves it elevated forever and every later pause
becomes a silent no-op — collection would keep running through every subsequent import
with nothing reporting it. The macOS portability lane caught exactly that (a test that
pauses an already-stopped scheduler and never resumes it poisoned three later tests).

So the window is an explicitly OWNED flag: ``exclusive_window`` is the sole writer,
setting and restoring it in its own try/finally, and the two standalone functions only
read it. The imbalance case is pinned below, not just the nesting case.
"""

from __future__ import annotations

import pytest

import src.scheduler.runner as R


class _FakeScheduler:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.holds = 0
        self.releases = 0
        self.stops = 0
        self.starts = 0

    def hold_exclusive(self) -> None:
        self.holds += 1

    def release_exclusive(self) -> None:
        self.releases += 1

    def stop(self, timeout: float = 10.0) -> bool:
        self.stops += 1
        was, self.running = self.running, False
        return was

    def start(self) -> bool:
        self.starts += 1
        self.running = True
        return True


@pytest.fixture()
def sched(monkeypatch):
    s = _FakeScheduler()
    monkeypatch.setattr(R, "get_scheduler", lambda: s)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    # The kill switch is consulted on resume; keep it off so a resume is attempted.
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    yield s
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)


# --------------------------------------------------------------------------- #
#  the pre-existing single-operation behaviour is untouched
# --------------------------------------------------------------------------- #
def test_a_lone_operation_still_pauses_and_resumes_exactly_once(sched):
    was = R.pause_for_exclusive_operation()
    assert was is True
    R.resume_after_exclusive_operation(was)
    assert (sched.stops, sched.starts) == (1, 1)
    assert (sched.holds, sched.releases) == (1, 1)


def test_a_scheduler_the_user_left_stopped_is_never_force_started(sched):
    """The original contract, unchanged: was_paused False means "I did not stop
    anything", so nothing gets started."""
    sched.running = False
    was = R.pause_for_exclusive_operation()
    assert was is False
    R.resume_after_exclusive_operation(was)
    assert sched.starts == 0
    assert sched.releases == 1, "the hold is still released — Run now must work again"


# --------------------------------------------------------------------------- #
#  the window
# --------------------------------------------------------------------------- #
def test_the_window_pauses_on_entry_and_resumes_on_exit(sched):
    with R.exclusive_window() as was:
        assert was is True
        assert sched.running is False
    assert sched.running is True
    assert (sched.stops, sched.starts) == (1, 1)


def test_an_operation_inside_the_window_does_NOT_resume_collection(sched):
    """THE defect. Five inner resumes in a six-backup run put collection back on the
    machine for most of the import."""
    with R.exclusive_window():
        for _ in range(5):  # five backups inside one run
            inner = R.pause_for_exclusive_operation()
            assert inner is False, "nothing was paused by the inner call"
            R.resume_after_exclusive_operation(inner)
        assert sched.starts == 0, "collection must stay down for the WHOLE run"
        assert sched.releases == 0, "and the manual Run-now hold must stay claimed"
    assert (sched.starts, sched.releases) == (1, 1), "released once, at the end"


def test_the_window_survives_an_exception_inside_it(sched):
    with pytest.raises(RuntimeError), R.exclusive_window():
        raise RuntimeError("a backup failed")
    assert sched.running is True, "a failed import must not strand collection paused"


def test_nested_windows_only_resume_at_the_outermost(sched):
    with R.exclusive_window():
        with R.exclusive_window():
            assert sched.running is False
        assert sched.starts == 0, "an inner window must not resume"
    assert sched.starts == 1


# --------------------------------------------------------------------------- #
#  imbalance-proofing — the property a counter did NOT have
# --------------------------------------------------------------------------- #
def test_an_unbalanced_pause_does_not_disable_every_later_pause(sched):
    """THE macOS-lane failure, reduced. Under the counter design this one unbalanced
    call left the depth at 1 forever, so the NEXT pause read as "nested" and silently
    stopped nothing — collection kept running through every later import.

    The failure mode is silent, which is what makes it worth a test: nothing raises,
    the pause simply stops working."""
    sched.running = False
    R.pause_for_exclusive_operation()  # deliberately never resumed
    sched.running = True

    was = R.pause_for_exclusive_operation()
    assert was is True, "a later pause must still genuinely pause"
    assert sched.running is False
    R.resume_after_exclusive_operation(was)
    assert sched.running is True


def test_an_unbalanced_resume_does_not_disable_the_next_window(sched):
    R.resume_after_exclusive_operation(False)  # a stray resume
    with R.exclusive_window() as was:
        assert was is True
        assert sched.running is False
    assert sched.running is True


def test_the_window_flag_is_readable_and_correct(sched):
    assert R.exclusive_window_open() is False
    with R.exclusive_window():
        assert R.exclusive_window_open() is True
    assert R.exclusive_window_open() is False
