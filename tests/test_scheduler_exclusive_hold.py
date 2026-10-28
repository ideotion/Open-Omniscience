"""An exclusive operation's hold reaches every way collection starts and every pass that is in flight (R367, findings F2 and F5 of the read of #1607).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``pause_for_exclusive_operation`` claims ``hold_exclusive`` and then ``stop()``. Two holes were left:

* F2: ``stop()`` returned before signalling anything when the loop was not running, so a "Run now" pass (the common shape on a machine that
  booted in airplane mode) was never told to wind down and the restore's wait spent its whole bound on it.
* F5: ``start()`` ignored the hold, so the Start button, going online and the unattended start put the loop back in the middle of an import
  although ``run_now()`` was refused.

The pass tests drive the REAL ``_default_run_once`` wiring: ``run_scrape_once`` is replaced by a stand-in that records the ``should_stop`` it was
handed and what it answers while the pass is in flight.
"""

from __future__ import annotations

import contextlib
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


class _PassEnded(Exception):
    """Raised by the stand-in pass so ``_default_run_once`` stops there: nothing after the scrape is under test."""


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


def _scheduler(**kw) -> BackgroundScheduler:
    sch = BackgroundScheduler(settings_provider=_Settings, **kw)
    sch._continuous_gap_s = 0.05
    sch._maint_interval_s = 1e9
    sch._last_maint = time.monotonic()
    return sch


class _Pass:
    """A stand-in for ``run_scrape_once``: parks inside the pass until released, then records what ``should_stop`` answered."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.seen: list[bool] = []

    def __call__(self, session, fetcher, settings, *, should_stop=None):
        self.seen.append(bool(should_stop()))  # on entry
        self.entered.set()
        assert self.release.wait(HANG_GUARD_S), "the test never released the pass"
        self.seen.append(bool(should_stop()))  # after whatever the test did while it was in flight
        raise _PassEnded


@pytest.fixture
def the_pass(monkeypatch) -> _Pass:
    p = _Pass()
    monkeypatch.setattr(runner_mod, "run_scrape_once", p)
    import src.database.session as sess_mod
    import src.safety.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "make_fetcher", lambda *a, **k: object())
    monkeypatch.setattr(sess_mod, "session_scope", contextlib.nullcontext)
    return p


def _wait_idle(sch: BackgroundScheduler) -> None:
    deadline = time.monotonic() + HANG_GUARD_S
    while sch._active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not sch._active, "the pass never ended"


# -- F2 -------------------------------------------------------------------- #


def test_a_run_now_pass_on_a_stopped_loop_is_told_to_stop_when_an_exclusive_operation_pauses_collection(the_pass):
    sch = _scheduler()
    assert sch.is_running() is False
    assert sch.run_now() is True
    assert the_pass.entered.wait(HANG_GUARD_S)

    sch.hold_exclusive()
    sch.stop()  # what pause_for_exclusive_operation does after claiming the hold
    the_pass.release.set()
    _wait_idle(sch)

    assert the_pass.seen == [False, True], "the pass in flight must be told to wind down within one source"


def test_the_next_pass_after_a_signalled_one_is_not_born_stopped(the_pass):
    """The signal belongs to ONE pass: a "Run now" after the exclusive operation must collect, not wind down at its first source."""
    sch = _scheduler()
    sch.run_now()
    assert the_pass.entered.wait(HANG_GUARD_S)
    sch.hold_exclusive()
    sch.stop()
    the_pass.release.set()
    _wait_idle(sch)
    sch.release_exclusive()

    the_pass.entered.clear()
    the_pass.release.clear()
    the_pass.seen.clear()
    assert sch.run_now() is True
    assert the_pass.entered.wait(HANG_GUARD_S)
    the_pass.release.set()
    _wait_idle(sch)

    assert the_pass.seen == [False, False]


def test_a_stop_with_no_pass_in_flight_leaves_nothing_behind(the_pass):
    """Control: ``stop()`` on an idle, stopped scheduler signals nobody, so a later "Run now" is an ordinary pass."""
    sch = _scheduler()
    assert sch.stop() is False
    assert sch.run_now() is True
    assert the_pass.entered.wait(HANG_GUARD_S)
    the_pass.release.set()
    _wait_idle(sch)

    assert the_pass.seen == [False, False]


def test_the_running_loop_still_stops_a_pass_through_its_own_flag(the_pass):
    """Control: the loop's pass keeps being stopped by ``_stop``, which ``stop()`` sets exactly as before."""
    sch = _scheduler()
    assert sch.start() is True
    assert the_pass.entered.wait(HANG_GUARD_S)
    stopper = threading.Thread(target=sch.stop, kwargs={"timeout": HANG_GUARD_S})
    stopper.start()
    deadline = time.monotonic() + HANG_GUARD_S
    while not sch._stop.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    the_pass.release.set()
    stopper.join(timeout=HANG_GUARD_S)
    assert the_pass.seen[-1] is True


# -- F5 -------------------------------------------------------------------- #


def test_start_is_refused_while_an_exclusive_operation_holds_the_machine():
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    sch.hold_exclusive()
    try:
        assert sch.start() is False
        assert sch.is_running() is False
        assert sch._thread is None, "a refused start must not leave a thread behind"
    finally:
        sch.release_exclusive()
    try:
        assert sch.start() is True, "the hold ending is what lets a start through"
    finally:
        sch.stop(timeout=HANG_GUARD_S)


def test_status_says_why_a_start_was_refused():
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    assert sch.status()["exclusive_hold"] is False
    sch.hold_exclusive()
    try:
        assert sch.status()["exclusive_hold"] is True
    finally:
        sch.release_exclusive()


def test_the_resume_that_ends_an_exclusive_operation_still_starts_the_loop(monkeypatch):
    """The refusal must not catch the operation's own resume, which runs while the hold is still the operation's."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    assert sch.start() is True
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
        assert was_paused is True
        assert sch.start() is False, "mid-operation, the loop must stay stopped"
        assert sch.is_running() is False
        runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
        assert sch.is_running() is True
        assert sch.holds_exclusive() is False
    finally:
        sch.stop(timeout=HANG_GUARD_S)


# -- the read of #1617: a refused Start is deferred, not lost; the windows around the hold ------------------------------------------------ #


def test_a_start_refused_during_the_hold_is_honoured_when_the_operation_ends(monkeypatch):
    """The operation began with the loop stopped (airplane mode at boot, the normal case), so ``was_paused`` is False. The operator then presses Start
    or goes online mid-import: that start is refused, and the operation's resume must still start the loop, or the machine ends up online and not
    collecting (``online`` is meant to imply ``collecting``)."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
        assert was_paused is False
        assert sch.start() is False and sch.is_running() is False
        runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
        assert sch.is_running() is True, "the Start pressed during the operation was lost"
        assert sch.holds_exclusive() is False
    finally:
        sch.stop(timeout=HANG_GUARD_S)


def test_a_second_claim_inside_a_hold_does_not_erase_the_first_ones_deferral():
    """The hold is one boolean, so a diagnostics bundle (or any window) that claims it while a standalone restore holds it must not erase the
    Start that was refused during the restore: only a FRESH claim starts with nothing deferred."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    sch.hold_exclusive()
    try:
        assert sch.start() is False
        sch.hold_exclusive()  # a second operation claims it inside the first
        assert sch.status()["start_deferred"] is True
    finally:
        sch.release_exclusive()


def test_a_deferred_start_does_not_outlive_the_operation_it_was_made_during(monkeypatch):
    """A start refused during one hold must not start collection after a LATER operation that nobody asked to start anything during."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        sch.hold_exclusive()
        assert sch.start() is False
        sch.release_exclusive()  # the first operation ended without a resume (an early return)
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
        runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
        assert sch.is_running() is False, "a start refused during an earlier operation was honoured after a later one"
    finally:
        sch.stop(timeout=HANG_GUARD_S)


def test_a_deferred_start_never_overrides_the_operators_airplane_mode(monkeypatch):
    from src.ingest import activate_kill_switch, clear_kill_switch

    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=HANG_GUARD_S)
        assert sch.start() is False
        activate_kill_switch()  # the operator went offline again before the operation ended
        runner_mod.resume_after_exclusive_operation(was_paused, retries=0, retry_delay=0.0)
        assert sch.is_running() is False
    finally:
        clear_kill_switch()
        sch.stop(timeout=HANG_GUARD_S)


def test_a_pass_that_begins_under_the_hold_is_told_to_stop_at_once(the_pass):
    """A "Run now" that passed its check an instant before the hold was claimed reaches ``_do_run`` after ``stop()`` saw no pass: the pass must start
    already stopped, not run unsignalled through the operation."""
    sch = _scheduler()
    sch.hold_exclusive()
    t = threading.Thread(target=sch._do_run)
    t.start()
    assert the_pass.entered.wait(HANG_GUARD_S)
    the_pass.release.set()
    t.join(timeout=HANG_GUARD_S)
    assert the_pass.seen == [True, True]


def test_an_idle_stop_sets_no_pass_signal():
    """Control for ``stop()``'s ``_active`` condition: with no pass in flight there is nothing to signal, and the flag stays down."""
    sch = _scheduler()
    assert sch.stop() is False
    assert sch._pass_stop.is_set() is False


def test_a_hold_claimed_while_the_loop_is_starting_still_stops_it(monkeypatch):
    """``start()`` checks the hold and creates the thread in one lock region: a pause that claims the hold in between would otherwise find no running
    loop (``was_paused`` False) and leave one running for the whole operation."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    real_thread = threading.Thread
    results: dict = {}

    class _RacingThread(real_thread):
        def start(self):
            if self.name == "oo-scheduler":

                def _pause():
                    sch.hold_exclusive()
                    results["stopped"] = sch.stop(timeout=HANG_GUARD_S)

                racer = real_thread(target=_pause)
                racer.start()
                racer.join(timeout=0.3)  # blocked on the lock if start() holds it; finished if it does not
                results["racer_done_early"] = not racer.is_alive()
                results["racer"] = racer
                super().start()
                return
            super().start()

    monkeypatch.setattr(runner_mod.threading, "Thread", _RacingThread)
    try:
        assert sch.start() is True
        results["racer"].join(timeout=HANG_GUARD_S)  # after start() has released its lock
        deadline = time.monotonic() + HANG_GUARD_S
        while sch.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert results["racer_done_early"] is False, "the hold was claimed between start()'s check and its thread"
        assert sch.is_running() is False, "a loop was left running under the hold"
    finally:
        monkeypatch.setattr(runner_mod.threading, "Thread", real_thread)
        sch.release_exclusive()
        sch.stop(timeout=HANG_GUARD_S)


def test_status_says_a_refused_start_is_queued_behind_the_hold_and_that_it_is_consumed():
    """``exclusive_hold`` alone says the hold stands, not that a Start is waiting behind it: ``start_deferred`` is the honest field, and it is false
    again once the resume's ``take_deferred_start()`` has consumed it."""
    sch = _scheduler(run_once_fn=lambda: {"stored": 0})
    assert sch.status()["start_deferred"] is False
    sch.hold_exclusive()
    try:
        assert sch.start() is False
        assert sch.status()["start_deferred"] is True
        assert sch.take_deferred_start() is True
        assert sch.status()["start_deferred"] is False, "consumed by the resume"
        assert sch.take_deferred_start() is False
    finally:
        sch.release_exclusive()
