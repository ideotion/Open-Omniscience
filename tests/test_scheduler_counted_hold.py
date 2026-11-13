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


def _bundle_inside(sch: BackgroundScheduler) -> None:
    """A diagnostics bundle's window, opened and closed while the restore runs (request-handler shape: no retry loop)."""
    assert runner_mod.exclusive_window_open() is False, "the restore's bare pause must not be visible as a window (the premise of the trace)"
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0) as was_paused:
        assert was_paused is False  # the restore already stopped everything
        assert sch.holds_exclusive() is True


def test_a_window_that_ends_inside_a_standalone_restore_leaves_the_restore_holding_the_machine(sch):
    was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)  # the restore, loop stopped (airplane mode at boot)
    assert was_paused is False
    _bundle_inside(sch)
    assert sch.holds_exclusive() is True, "the bundle's resume released the restore's hold"
    assert sch.status()["exclusive_hold"] is True
    assert sch.status()["exclusive_holds"] == 1
    assert sch.run_now() is False, "Run now was accepted in the middle of the restore"
    assert sch.start() is False, "a Start put the loop back in the middle of the restore"
    assert sch.is_running() is False
    runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)  # the restore ends
    assert sch.holds_exclusive() is False
    assert sch.status()["exclusive_holds"] == 0


def test_a_start_refused_during_the_restore_waits_for_the_restore_not_the_bundle(sch):
    was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
    assert sch.start() is False  # the operator presses Start mid-restore: deferred
    _bundle_inside(sch)
    assert sch.is_running() is False, "the bundle's resume consumed the restore's deferred start and started the loop mid-restore"
    assert sch.status()["start_deferred"] is True, "the deferred start was lost at the bundle's end"
    runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
    assert sch.is_running() is True, "the Start pressed during the restore was never honoured"
    assert sch.holds_exclusive() is False


def test_a_start_refused_during_the_bundle_is_handed_to_the_restore(sch):
    was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
    assert runner_mod.exclusive_window_open() is False
    with runner_mod.exclusive_window(timeout=HANG_GUARD_S, resume_retries=0):
        assert sch.start() is False  # pressed during the bundle, which runs inside the restore
    assert sch.is_running() is False
    assert sch.status()["start_deferred"] is True
    runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
    assert sch.is_running() is True


def test_an_unmatched_release_is_harmless_and_the_count_never_goes_negative(sch):
    sch.release_exclusive()
    assert sch.status()["exclusive_holds"] == 0
    sch.hold_exclusive()
    assert sch.holds_exclusive() is True, "an earlier unmatched release must not swallow a later claim"
    sch.release_exclusive()
    assert sch.holds_exclusive() is False


def test_a_resume_without_a_deferral_hook_on_the_scheduler_behaves_as_before(monkeypatch):
    """A scheduler with no ``defer_start`` (a test double, an older object) is never treated as held by another operation."""

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
