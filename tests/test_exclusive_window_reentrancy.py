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
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)
    monkeypatch.setattr(R, "_EXCL_BASE", False)
    monkeypatch.setattr(R, "_EXCL_PAUSED", False)
    # The kill switch is consulted on resume; keep it off so a resume is attempted.
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    yield s
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    monkeypatch.setattr(R, "_EXCL_DEPTH", 0)


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


# --------------------------------------------------------------------------- #
#  windows that OVERLAP without nesting (a job thread's, a request thread's)
# --------------------------------------------------------------------------- #
def _enter(window):
    """Open a window by hand, so the tests can leave them in any order, as two threads do."""
    window.__enter__()
    return window


def test_a_window_that_began_inside_another_and_ends_after_it_keeps_the_machine_owned_until_it_ends(sched):
    """THE defect (independent read of 5ac155026, B1). An export's window opens first and ends first; an encryption's opened inside it
    and is still running. RED WITHOUT the count: the export's exit restores the value it found on ENTRY (False), so collection
    restarts and ``owns_the_machine()`` is False under the encryption; when that one ends it restores True for good."""
    export = _enter(R.exclusive_window())
    encryption = _enter(R.exclusive_window())
    assert sched.running is False
    export.__exit__(None, None, None)  # the first to enter is the first to leave
    assert R.exclusive_window_open() is True, "the encryption's window still stands"
    assert R.owns_the_machine() is True
    assert sched.starts == 0, "collection is not put back under the encryption"
    assert sched.releases == 0
    encryption.__exit__(None, None, None)
    assert R.exclusive_window_open() is False, "the flag does not stay raised for the rest of the process"
    assert R.owns_the_machine() is False
    assert (sched.starts, sched.releases) == (1, 1), "the last window out resumes what the first one paused, once"
    assert (R._EXCL_DEPTH, R._EXCL_PAUSED) == (0, False)


def test_the_window_that_paused_need_not_be_the_one_that_resumes(sched):
    """The second window found the first open, so it paused nothing; if it leaves last it still carries the resume."""
    first = _enter(R.exclusive_window())
    second = _enter(R.exclusive_window())
    first.__exit__(None, None, None)
    assert sched.starts == 0
    second.__exit__(None, None, None)
    assert sched.starts == 1 and sched.running is True


def test_nested_exits_still_resume_at_the_outermost_only(sched):
    outer = _enter(R.exclusive_window())
    inner = _enter(R.exclusive_window())
    inner.__exit__(None, None, None)
    assert R.exclusive_window_open() is True and sched.starts == 0
    outer.__exit__(None, None, None)
    assert R.exclusive_window_open() is False and sched.starts == 1


def test_overlapping_windows_are_one_run_for_the_work_that_asks_which_run_it_is(sched):
    first = _enter(R.exclusive_window())
    token = R.exclusive_window_token()
    second = _enter(R.exclusive_window())
    assert token and R.exclusive_window_token() == token, "a window opened inside another keeps the identity of the run"
    first.__exit__(None, None, None)
    assert R.exclusive_window_token() == token, "and so does the survivor, after the first has left"
    second.__exit__(None, None, None)
    assert R.exclusive_window_token() == 0
    with R.exclusive_window():
        assert R.exclusive_window_token() > token, "a later run is a new run"


def test_a_flag_raised_by_hand_before_the_first_window_is_what_the_last_window_restores(sched, monkeypatch):
    """Tests raise the flag to stand for an outer run; the window leaves it as it found it, however many of them come and go."""
    monkeypatch.setattr(R, "_EXCL_WINDOW", True)
    token = R._EXCL_TOKEN
    first = _enter(R.exclusive_window())
    second = _enter(R.exclusive_window())
    assert token == R._EXCL_TOKEN, "a window inside a run that was not its own starts no new run"
    first.__exit__(None, None, None)
    second.__exit__(None, None, None)
    assert R.exclusive_window_open() is True
    assert sched.starts == 0, "an outer run that was not ours still owns the resume"


def test_an_exception_in_one_of_two_overlapping_windows_leaves_the_count_right(sched):
    survivor = _enter(R.exclusive_window())
    with pytest.raises(RuntimeError), R.exclusive_window():
        raise RuntimeError("a restore failed")
    assert R.exclusive_window_open() is True and sched.starts == 0
    survivor.__exit__(None, None, None)
    assert R.exclusive_window_open() is False and sched.starts == 1


def test_the_window_that_resumes_passes_its_retry_budget_on(sched, monkeypatch):
    """M1 of the same read: the encryption route is a request handler and must not sit in a 19 x 30 s loop."""
    seen: list[dict] = []
    real = R.resume_after_exclusive_operation
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda was, **kw: seen.append({"was": was, **kw}) or real(was, **kw))
    with R.exclusive_window(resume_retries=0):
        pass
    with R.exclusive_window():
        pass
    assert seen == [{"was": True, "retries": 0}, {"was": True, "retries": 19}]
