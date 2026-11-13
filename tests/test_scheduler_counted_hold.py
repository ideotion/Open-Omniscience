"""The scheduler's exclusive hold is COUNTED: an operation that ends inside another's hold ends only its own claim (R383).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The trace (OPEN_QUEUE 2026-10-27 item 23, reproduced by the keyword lane): a standalone restore claims the hold through the bare
``pause_for_exclusive_operation``, which ``exclusive_window_open()`` cannot see; a diagnostics bundle then opens ``exclusive_window()``
inside it, claims the hold a second time, and on its exit its resume released the hold. With one boolean that lowered the RESTORE's hold
too, and "Run now" or a Start put collection back on the machine in the middle of the restore. Each test here fails on the boolean.
"""

from __future__ import annotations

import threading
import time

import pytest

import src.scheduler.runner as runner_mod
from src.scheduler.runner import BackgroundScheduler
from tests.wallclock_helpers import HANG_GUARD_S, quiet_pass_tail


class _Settings:
    continuous = True
    interval_minutes = 1
    mode = "rss"

    def to_dict(self) -> dict:
        return {"continuous": True, "interval_minutes": 1, "mode": "rss"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    quiet_pass_tail(monkeypatch)
    monkeypatch.setattr(runner_mod, "RESUME_POLL_S", 0.01)
    runner_mod.cancel_pending_resume()
    yield
    runner_mod.cancel_pending_resume()
    for t in [t for t in threading.enumerate() if t.name == "oo-resume-watch"]:
        t.join(timeout=5)


@pytest.fixture
def sch(monkeypatch) -> BackgroundScheduler:
    s = BackgroundScheduler(settings_provider=_Settings, run_once_fn=lambda: {"stored": 0})
    s._continuous_gap_s = 0.05
    s._maint_interval_s = 1e9
    s._last_maint = time.monotonic()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: s)
    yield s
    s.stop(timeout=HANG_GUARD_S)


def _restore_pause(claim: list[bool]) -> bool:
    """A standalone restore's pause, as ``src/backup/volume_job.py`` takes it: the bare pause, its claim kept by the caller."""
    return runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S, claim=claim)


def _restore_resume(was_paused: bool, claim: list[bool]) -> None:
    runner_mod.resume_after_exclusive_operation(was_paused, claim=claim, retries=0, retry_delay=0.0)


def _bundle_inside(sch: BackgroundScheduler) -> None:
    """A diagnostics bundle's window, opened and closed while the restore runs (request-handler shape: no retry loop)."""
    assert runner_mod.exclusive_window_open() is False, "the restore's bare pause must not be visible as a window (the premise of the trace)"
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0) as was_paused:
        assert was_paused is False  # the restore already stopped everything
        assert sch.holds_exclusive() is True


def test_a_window_that_ends_inside_a_standalone_restore_leaves_the_restore_holding_the_machine(sch):
    claim: list[bool] = []
    was_paused = _restore_pause(claim)  # loop stopped (airplane mode at boot)
    assert was_paused is False and claim == [True]
    _bundle_inside(sch)
    assert sch.holds_exclusive() is True, "the bundle's resume released the restore's hold"
    assert sch.status()["exclusive_holds"] == 1
    assert sch.run_now() is False, "Run now was accepted in the middle of the restore"
    assert sch.start() is False, "a Start put the loop back in the middle of the restore"
    assert sch.is_running() is False
    _restore_resume(was_paused, claim)  # the restore ends
    assert sch.holds_exclusive() is False and claim == []
    assert sch.status()["exclusive_holds"] == 0


def test_a_start_refused_during_the_restore_waits_for_the_restore_not_the_bundle(sch):
    claim: list[bool] = []
    was_paused = _restore_pause(claim)
    assert sch.start() is False  # the operator presses Start mid-restore: deferred
    _bundle_inside(sch)
    assert sch.is_running() is False, "the bundle's resume consumed the restore's deferred start and started the loop mid-restore"
    assert sch.status()["start_deferred"] is True, "the deferred start was lost at the bundle's end"
    _restore_resume(was_paused, claim)
    assert sch.is_running() is True, "the Start pressed during the restore was never honoured"
    assert sch.holds_exclusive() is False


def test_a_start_refused_during_the_bundle_is_handed_to_the_restore(sch):
    claim: list[bool] = []
    was_paused = _restore_pause(claim)
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        assert sch.start() is False  # pressed during the bundle, which runs inside the restore
    assert sch.is_running() is False
    assert sch.status()["start_deferred"] is True
    _restore_resume(was_paused, claim)
    assert sch.is_running() is True


def test_a_restore_that_ends_while_a_window_is_open_releases_its_own_claim(sch):
    """The reverse order (the read of 2f3fbef1, blocker 1): the bundle outlives the restore. The restore's claim must still be released by
    the restore, or the count stays at 1 for the life of the process and every Start is refused."""
    claim: list[bool] = []
    was_paused = _restore_pause(claim)
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        assert sch.status()["exclusive_holds"] == 2
        _restore_resume(was_paused, claim)  # the restore ends first
        assert sch.status()["exclusive_holds"] == 1, "the restore did not release its claim inside the window"
        assert sch.start() is False, "the bundle still holds the machine"
    assert sch.status()["exclusive_holds"] == 0, "a claim leaked: Start stays refused until the process restarts"
    assert sch.holds_exclusive() is False
    assert sch.is_running() is True, "the Start refused inside the bundle was never honoured"
    sch.stop(timeout=HANG_GUARD_S)
    assert sch.start() is True, "a Start pressed after both operations did nothing"


def test_a_loop_the_restore_stopped_is_started_by_the_bundle_that_outlives_it(sch):
    assert sch.start() is True  # collecting when the restore begins
    claim: list[bool] = []
    was_paused = _restore_pause(claim)
    assert was_paused is True
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        _restore_resume(was_paused, claim)
        assert sch.is_running() is False, "collection came back while the bundle still owned the machine"
    assert sch.is_running() is True, "the collector the restore stopped was never put back"
    assert sch.status()["exclusive_holds"] == 0


def test_two_operations_that_end_together_never_strand_a_start(sch):
    """The read's should-fix 2: R1 stopped the loop, R2 found it stopped; their resumes interleave. Whatever the order of the releases, the
    LAST one out starts the loop R1 stopped, and nothing is left deferred at a count of zero."""
    for first_out in ("R1", "R2"):
        assert sch.start() is True
        c1: list[bool] = []
        c2: list[bool] = []
        w1 = _restore_pause(c1)
        w2 = _restore_pause(c2)
        assert (w1, w2) == (True, False)
        order = [(w1, c1), (w2, c2)] if first_out == "R1" else [(w2, c2), (w1, c1)]
        _restore_resume(*order[0])
        assert sch.is_running() is False and sch.holds_exclusive() is True
        _restore_resume(*order[1])
        assert sch.status()["exclusive_holds"] == 0
        assert sch.is_running() is True, f"the loop R1 stopped stayed stopped ({first_out} out first)"
        assert sch.status()["start_deferred"] is False, "a deferred start was stranded at a count of zero"
        sch.stop(timeout=HANG_GUARD_S)


def test_the_release_and_the_deferred_start_are_one_step(sch):
    """``release_exclusive`` answers (hold_ended, start_wanted) itself, so no caller reads the deferral apart from the release."""
    sch.hold_exclusive()
    sch.hold_exclusive()
    assert sch.start() is False  # deferred
    assert sch.release_exclusive() == (False, False)  # another claim stands: nothing to start, the deferral stays
    assert sch.status()["start_deferred"] is True
    assert sch.release_exclusive() == (True, True)  # the last claim: the deferral is taken with it
    assert sch.status()["start_deferred"] is False
    sch.hold_exclusive()
    assert sch.release_exclusive(hand_over_start=True) == (True, False)  # the last claim: a hand-over has no one to go to
    sch.hold_exclusive()
    sch.hold_exclusive()
    assert sch.release_exclusive(hand_over_start=True) == (False, False)
    assert sch.status()["start_deferred"] is True, "the loop this operation stopped was not queued behind the other holder"
    sch.release_exclusive()


def test_a_restore_begun_inside_a_window_keeps_the_machine_when_the_window_ends_first(sch):
    """The reverse order (security reads A and B of B3): a window (an export, a bundle) is open, a volume restore starts inside it and the
    window ends first. The restore's pause takes its OWN claim, so the window's last exit cannot start collection under the restore; the
    restore's resume releases exactly that claim, and a third operation's claim is never ended by it."""
    assert sch.start() is True
    inner: list[bool] = []
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        inner_paused = _restore_pause(inner)
        assert inner == [True], "a pause inside a window must take its own claim"
        assert inner_paused is False, "the window already stopped the loop: this pause stopped nothing"
    # the window has ended; the restore is still running
    assert sch.holds_exclusive() is True, "the window's exit ended the restore's hold"
    assert sch.is_running() is False and sch.run_now() is False and sch.start() is False, "collection came back under the restore"
    other: list[bool] = []
    _restore_pause(other)  # a third operation holds the machine now
    _restore_resume(inner_paused, inner)
    assert sch.holds_exclusive() is True, "a resume released a claim it never took"
    _restore_resume(False, other)
    assert sch.holds_exclusive() is False
    assert sch.is_running() is True, "the start refused during the restore was never made"


def test_a_window_that_read_another_as_open_still_claims_and_makes_the_start_at_its_exit(sch, monkeypatch):
    """Security read B of B3 and the delta reads: a window that read ``already`` while another was closing used to run with no claim (Start
    and Run now accepted for its whole body) and, when a restore that stopped the loop ended inside it, dropped that restore's start at its
    exit. Every window now pauses, so it holds a claim of its own, and the start is made when it ends."""
    assert sch.start() is True
    restore: list[bool] = []
    was_paused = _restore_pause(restore)
    assert was_paused is True
    # window B reads ``already`` as True although no window is open any more (the race at its entry)
    monkeypatch.setattr(runner_mod, "exclusive_window_open", lambda: True)
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        monkeypatch.setattr(runner_mod, "exclusive_window_open", lambda: runner_mod._EXCL_WINDOW)
        _restore_resume(was_paused, restore)  # the restore ends inside B
        assert sch.holds_exclusive() is True, "the window ran without a claim of its own"
        assert sch.is_running() is False and sch.run_now() is False, "collection came back inside the window"
    assert sch.holds_exclusive() is False
    assert sch.is_running() is True, "the start the restore left was dropped at the window's exit"


def test_a_window_that_ends_between_a_pause_and_its_window_read_never_leaves_the_loop_running_under_the_pause(sch, monkeypatch):
    """Security read of B3 delta 3, S1 (reproduced on 5c7d518d): the pause read the window as open, then the last window ended, released its
    claim, found the hold free and started collection; only then did the pause take its claim, return False and run its whole operation
    with the continuous loop running. The window now ends AT the pause's read, the latest point it can: the claim is already taken, so the
    window's start is deferred behind it and made by the pause's own release."""
    assert sch.start() is True
    window = runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0)
    window.__enter__()
    assert sch.is_running() is False
    real_open = runner_mod.exclusive_window_open

    def the_window_ends_now() -> bool:
        seen = real_open()
        monkeypatch.setattr(runner_mod, "exclusive_window_open", real_open)
        window.__exit__(None, None, None)  # the last window out, between the read and whatever the pause does next
        return seen

    monkeypatch.setattr(runner_mod, "exclusive_window_open", the_window_ends_now)
    restore: list[bool] = []
    was_paused = _restore_pause(restore)
    assert restore == [True]
    assert sch.is_running() is False, "collection was started under the pause: the window ended between its read and its claim"
    assert sch.holds_exclusive() is True and sch.run_now() is False
    _restore_resume(was_paused, restore)
    assert sch.holds_exclusive() is False
    assert sch.is_running() is True, "the start the window deferred behind the pause was never made"


def test_a_pause_and_resume_that_keep_no_list_inside_a_window_leave_no_claim(sch):
    """The delta read's should-fix: a caller from before R383 (no claim list) pausing and resuming inside a window must not leave the hold
    standing for the life of the process."""
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
        runner_mod.resume_after_exclusive_operation(paused, retries=0, retry_delay=0.0)
        assert sch.status()["exclusive_holds"] == 1, "only the window's own claim stands"
    assert sch.status()["exclusive_holds"] == 0


def test_an_unmatched_release_never_goes_below_zero_and_a_later_claim_still_holds(sch):
    sch.release_exclusive()
    sch.hold_exclusive()
    assert sch.holds_exclusive() is True, "an earlier unmatched release must not swallow a later claim"
    assert sch.run_now() is False and sch.start() is False
    sch.release_exclusive()
    assert sch.holds_exclusive() is False
    assert sch.start() is True


def test_a_second_resume_with_the_same_claim_releases_nothing(sch):
    claim: list[bool] = []
    was_paused = _restore_pause(claim)
    other: list[bool] = []
    _restore_pause(other)
    _restore_resume(was_paused, claim)
    _restore_resume(was_paused, claim)  # a caller that resumes twice owns nothing the second time
    assert sch.holds_exclusive() is True, "a repeated resume ended another operation's claim"
    _restore_resume(False, other)
    assert sch.holds_exclusive() is False


def test_a_resume_on_a_scheduler_double_without_the_counted_api_behaves_as_before(monkeypatch):
    """A stand-in with the pre-R383 shape (``release_exclusive()`` answers nothing) is read the old way: deferral, then release, then start."""

    class _Bare:
        def __init__(self):
            self.started = 0
            self.released = 0

        def take_deferred_start(self):
            return False

        def release_exclusive(self):
            self.released += 1

        def start(self):
            self.started += 1
            return True

    bare = _Bare()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: bare)
    runner_mod.resume_after_exclusive_operation(True, retries=0, retry_delay=0.0)
    assert (bare.released, bare.started) == (1, 1)


def test_the_volume_restore_takes_its_claim_right_before_the_try_that_gives_it_back():
    """Security read of B3 delta 3, S2: the volume restore took its claim, then computed its stage plan, then entered the ``try`` whose
    ``finally`` resumes. A raise in between stranded the claim, and a counted hold keeps it for the life of the process. Read from source:
    after the pause, the next statement is that ``try``."""
    import ast
    from pathlib import Path

    src = Path(runner_mod.__file__).resolve().parents[1] / "backup" / "volume_job.py"
    tree = ast.parse(src.read_text("utf-8"))
    found = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body):
            if isinstance(stmt, ast.Try) and not stmt.finalbody and "claim=hold_claim" in ast.unparse(stmt.body[0]):
                after = body[i + 1]
                found.append(isinstance(after, ast.Try) and "resume_after_exclusive_operation" in ast.unparse(after.finalbody))
    assert found == [True], found
