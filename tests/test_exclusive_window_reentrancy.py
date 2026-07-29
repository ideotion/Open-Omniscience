"""Collection does not resume between backups: ONE window spans the whole import.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field ruling 2026-07-29 item 10. Each volume restore pauses collection for its own
duration and resumes in a ``finally``, so a 6-backup run paused and RESUMED five times
mid-import — re-opening between every backup the exact race the pause exists to close,
and defeating "import owns the machine" for the majority of the run's wall time.

The fix is reentrancy, not a second mechanism: the import queue takes an OUTER hold and
the per-restore holds nest inside it. These pin both halves — nesting must not re-pause,
and (the load-bearing half) an inner operation finishing must not RESUME.
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
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0, raising=False)
    # The kill switch is consulted on resume; keep it off so a resume is attempted.
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    yield s
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0, raising=False)


def test_a_lone_operation_still_pauses_and_resumes_exactly_once(sched):
    """The pre-existing single-restore behaviour must be byte-identical."""
    was = R.pause_for_exclusive_operation()
    assert was is True
    R.resume_after_exclusive_operation(was)
    assert (sched.stops, sched.starts) == (1, 1)
    assert (sched.holds, sched.releases) == (1, 1)


def test_a_nested_operation_never_pauses_a_second_time(sched):
    outer = R.pause_for_exclusive_operation()
    inner = R.pause_for_exclusive_operation()
    assert outer is True
    assert inner is False, "nothing was paused by the inner call, so it must not claim to"
    assert sched.stops == 1, "one window"
    R.resume_after_exclusive_operation(inner)
    R.resume_after_exclusive_operation(outer)


def test_an_inner_operation_finishing_does_NOT_resume_collection(sched):
    """THE defect. Five inner resumes in a six-backup run put collection back on the
    machine for most of the import."""
    outer = R.pause_for_exclusive_operation()
    for _ in range(5):  # five backups inside one run
        inner = R.pause_for_exclusive_operation()
        R.resume_after_exclusive_operation(inner)
    assert sched.starts == 0, "collection must stay down for the WHOLE run"
    assert sched.releases == 0, "and the manual Run-now hold must stay claimed too"
    R.resume_after_exclusive_operation(outer)
    assert (sched.starts, sched.releases) == (1, 1), "released exactly once, at the end"


def test_the_outermost_resume_is_what_restores_collection(sched):
    outer = R.pause_for_exclusive_operation()
    inner = R.pause_for_exclusive_operation()
    R.resume_after_exclusive_operation(inner)
    assert sched.running is False
    R.resume_after_exclusive_operation(outer)
    assert sched.running is True


def test_a_scheduler_the_user_left_stopped_is_never_force_started(sched):
    """The original contract, unchanged by nesting: was_paused False means "I did not
    stop anything", so nothing gets started."""
    sched.running = False
    was = R.pause_for_exclusive_operation()
    assert was is False
    R.resume_after_exclusive_operation(was)
    assert sched.starts == 0
    assert sched.releases == 1, "the hold is still released — Run now must work again"


def test_the_depth_never_goes_negative_on_an_unbalanced_resume(sched):
    """Defensive: a stray resume must not push the counter below zero, or the NEXT
    genuine pause/resume pair would silently behave as if it were nested."""
    R.resume_after_exclusive_operation(False)
    was = R.pause_for_exclusive_operation()
    R.resume_after_exclusive_operation(was)
    assert sched.starts == 1, "the following real pair still works normally"
