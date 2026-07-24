"""pause_for_exclusive_operation / resume_after_exclusive_operation
(field-feedback Session A §4, "import owns the machine").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A THROUGHPUT courtesy, never a correctness requirement -- these tests pin
the one property that actually matters: a pause never force-starts a
scheduler the user had already left stopped (resume is conditioned on the
PAUSE call's own return value, never unconditional).
"""

from __future__ import annotations

import pytest

from src.scheduler.runner import BackgroundScheduler


class _FakeSettings:
    def __init__(self):
        self.continuous = True
        self.interval_minutes = 1
        self.mode = "rss"

    def to_dict(self) -> dict:
        return {"continuous": True, "interval_minutes": 1, "mode": "rss"}


@pytest.fixture(autouse=True)
def _isolate_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def _running_scheduler() -> BackgroundScheduler:
    def run_once():
        return {"stored": 0}

    sch = BackgroundScheduler(run_once_fn=run_once, settings_provider=lambda: _FakeSettings())
    sch._continuous_gap_s = 0.05
    assert sch.start() is True
    return sch


def test_pause_stops_a_running_scheduler_and_reports_it_was_running(monkeypatch):
    import src.scheduler.runner as runner_mod

    sch = _running_scheduler()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=5.0)
        assert was_paused is True
        assert sch.is_running() is False
    finally:
        if sch.is_running():
            sch.stop()


def test_pause_on_an_already_stopped_scheduler_reports_false(monkeypatch):
    import src.scheduler.runner as runner_mod

    sch = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    assert sch.is_running() is False
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)

    was_paused = runner_mod.pause_for_exclusive_operation()
    assert was_paused is False  # honest: there was nothing to pause


def test_resume_only_restarts_when_the_pause_actually_stopped_it(monkeypatch):
    """THE load-bearing property: resume_after_exclusive_operation(False) must
    NEVER start a scheduler the user had deliberately left stopped -- only a
    pause call that itself reports True may be followed by a resume."""
    import src.scheduler.runner as runner_mod

    sch = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    assert sch.is_running() is False

    runner_mod.resume_after_exclusive_operation(False)  # "was_paused=False"
    assert sch.is_running() is False, "a False pause result must never force-start collection"


def test_pause_then_resume_round_trips_back_to_running(monkeypatch):
    import src.scheduler.runner as runner_mod

    sch = _running_scheduler()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=5.0)
        assert sch.is_running() is False
        runner_mod.resume_after_exclusive_operation(was_paused)
        assert sch.is_running() is True
    finally:
        if sch.is_running():
            sch.stop()


def test_resume_after_a_genuine_pause_survives_a_finally_block_pattern(monkeypatch):
    """Mirrors the real call site's shape (volume_job.py): pause, do work,
    resume in a finally -- even when the 'work' raises, resume still runs."""
    import src.scheduler.runner as runner_mod

    sch = _running_scheduler()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    was_paused = False
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=5.0)
        assert sch.is_running() is False
        raise RuntimeError("simulated restore failure")
    except RuntimeError:
        pass
    finally:
        runner_mod.resume_after_exclusive_operation(was_paused)
    assert sch.is_running() is True
    sch.stop()


class _FakeSchedulerFlaky:
    """start() reports False (still running / can't start) a fixed number of
    times, then succeeds -- simulates the real race: BackgroundScheduler.stop's
    JOIN is bounded (10s) but ``_do_run`` has no internal stop-check mid-pass,
    so a pass that was already deep in a fetch can still be alive well after
    ``pause_for_exclusive_operation`` returned."""

    def __init__(self, flaky_for: int) -> None:
        self.flaky_for = flaky_for
        self.calls = 0
        self.release_calls = 0

    def start(self) -> bool:
        self.calls += 1
        return self.calls > self.flaky_for

    def release_exclusive(self) -> None:
        self.release_calls += 1


def test_resume_retries_when_the_old_pass_is_still_finishing(monkeypatch):
    """A concurrency finding from the mandatory skeptic pass (Session A §4):
    start() correctly refuses a second thread while the old one lingers, so a
    single un-retried call would silently strand collection paused forever
    once that lingering pass eventually exits on its own. Retry must recover."""
    import src.scheduler.runner as runner_mod

    fake = _FakeSchedulerFlaky(flaky_for=2)
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: fake)

    runner_mod.resume_after_exclusive_operation(True, retries=4, retry_delay=0.0)
    assert fake.calls == 3  # 2 failed attempts, then the one that succeeded


def test_resume_gives_up_after_exhausting_retries_without_raising(monkeypatch):
    """If the old pass never dies (retries exhausted), this must still return
    normally -- a caller's finally block must never block/raise forever on a
    best-effort courtesy -- and it must say so loudly rather than pretend
    success or silently vanish. Asserted directly on ``_LOG.warning`` (never
    on ``caplog``/the process-wide root-logger handler set): a real-app
    ``TestClient(app)`` boot elsewhere in the same pytest session can leave
    an extra root handler behind, which made a caplog-based assertion here
    order-dependent on which test files ran first -- this is the same
    "TestClient IS a heavyweight, global-state fixture" hazard this project
    already tracks for other surfaces."""
    import src.scheduler.runner as runner_mod

    fake = _FakeSchedulerFlaky(flaky_for=999)  # never succeeds
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: fake)
    warnings: list[str] = []
    monkeypatch.setattr(runner_mod._LOG, "warning", lambda msg, *a, **k: warnings.append(msg))

    runner_mod.resume_after_exclusive_operation(True, retries=2, retry_delay=0.0)
    assert fake.calls == 3  # attempts 0, 1, 2 (retries=2 -> 3 total tries)
    assert any("could not resume" in w for w in warnings)
    # ALWAYS released, even on the give-up path -- a manual "Run now" must work
    # again the instant this function returns, regardless of retry outcome.
    assert fake.release_calls == 1


def test_resume_never_overrides_the_users_own_airplane_mode(monkeypatch):
    """If the operator engages airplane mode of their own accord while this
    operation (or its retry loop) is running, that explicit choice must never
    be silently overridden by a background courtesy call -- start() must
    never even be ATTEMPTED while the kill switch is engaged."""
    import src.scheduler.runner as runner_mod
    from src.ingest import activate_kill_switch

    fake = _FakeSchedulerFlaky(flaky_for=999)
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: fake)

    activate_kill_switch()  # the conftest autouse fixture clears it after this test
    runner_mod.resume_after_exclusive_operation(True, retries=4, retry_delay=0.0)
    assert fake.calls == 0, "start() must never be attempted while airplane mode is engaged"


def test_resume_bails_out_mid_retry_if_airplane_mode_engages_partway_through(monkeypatch):
    """The narrower race: the operator flips airplane mode ON in the WINDOW
    between two retry attempts (not before the first). The very next attempt
    must see it and stop trying, never force a start afterward."""
    import src.scheduler.runner as runner_mod
    from src.ingest import activate_kill_switch

    class _FlipsKillSwitchOnSecondCall:
        def __init__(self) -> None:
            self.calls = 0

        def start(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                activate_kill_switch()  # the user acted between our attempts
            return False  # never actually succeeds -- proves it stopped trying, not that it won

        def release_exclusive(self) -> None:
            pass

    fake = _FlipsKillSwitchOnSecondCall()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: fake)

    runner_mod.resume_after_exclusive_operation(True, retries=4, retry_delay=0.0)
    assert fake.calls == 1, "must stop retrying the instant airplane mode is seen engaged"


# --------------------------------------------------------------------------- #
#  hold_exclusive / release_exclusive -- the HIGH concurrency-skeptic fix
#  (2026-07-24): run_now() used to check ONLY self._active, with zero
#  awareness of a restore's pause, so a single manual "Run now" click during a
#  restore silently ran a full collection pass concurrently with it -- fully
#  defeating the "own the machine" isolation. These tests pin the fix at both
#  the BackgroundScheduler unit level and the pause/resume wiring level.
# --------------------------------------------------------------------------- #


def test_run_now_is_blocked_while_the_machine_is_held_exclusively():
    # A fresh instance (never run_now'd/started) has a deterministic, race-free
    # _active=False -- run_now() itself spawns an async thread, so this test
    # never triggers a first real run and then races its own background
    # completion; each assertion below is checked purely against the
    # synchronous, lock-guarded state run_now()/hold_exclusive() touch.
    sch = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    assert sch._active is False

    sch.hold_exclusive()
    assert sch.run_now() is False, "a manual run must be refused while an exclusive op holds the machine"

    sch.release_exclusive()
    assert sch.run_now() is True, "run_now must work again the instant the hold is released"


def test_hold_exclusive_is_independent_of_the_loop_thread_state():
    """The hold must block run_now() even when the continuous loop was
    already stopped BEFORE the exclusive operation began (e.g. under
    airplane mode) -- a manual "Run now" would still compete for CPU/the
    single-writer gate with the restore regardless of the loop's own state."""
    sch = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    assert sch.is_running() is False

    sch.hold_exclusive()
    assert sch.run_now() is False
    sch.release_exclusive()
    assert sch.run_now() is True


def test_pause_claims_the_exclusive_hold_before_stopping_the_loop(monkeypatch):
    """pause_for_exclusive_operation() must claim the hold UNCONDITIONALLY --
    even when there is nothing running to stop (was_paused == False) -- so a
    manual "Run now" is blocked for the operation's whole duration regardless
    of the loop's prior state."""
    import src.scheduler.runner as runner_mod

    sch = BackgroundScheduler(run_once_fn=lambda: {"stored": 0}, settings_provider=lambda: _FakeSettings())
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    assert sch.is_running() is False

    was_paused = runner_mod.pause_for_exclusive_operation()
    assert was_paused is False  # nothing was running to stop
    assert sch.run_now() is False, "the hold must still be claimed even when was_paused is False"

    runner_mod.resume_after_exclusive_operation(was_paused)
    assert sch.run_now() is True, "resume must release the hold even on the was_paused=False path"


def test_resume_releases_the_hold_even_when_retries_are_exhausted(monkeypatch):
    """The hold must be released the instant the exclusive operation itself is
    done, regardless of whether the continuous loop successfully resumed --
    manual runs must not stay blocked just because the old pass hasn't died."""
    import src.scheduler.runner as runner_mod

    fake = _FakeSchedulerFlaky(flaky_for=999)  # start() never succeeds
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: fake)

    runner_mod.resume_after_exclusive_operation(True, retries=1, retry_delay=0.0)
    assert fake.release_calls == 1


def test_pause_then_resume_round_trip_releases_the_hold(monkeypatch):
    """End-to-end proof against the REAL scheduler class (not a fake): a
    manual run is blocked for the exclusive operation's whole duration, and
    the hold itself is genuinely released on resume (checked directly via
    hold_exclusive/release_exclusive, not via the resumed loop's OWN _active
    flag -- whether the freshly-restarted loop has claimed _active yet is an
    unrelated race against its background thread, not this fix's concern)."""
    import src.scheduler.runner as runner_mod

    sch = _running_scheduler()
    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: sch)
    try:
        was_paused = runner_mod.pause_for_exclusive_operation(timeout=5.0)
        assert sch.run_now() is False, "blocked for the whole duration of the exclusive operation"
        runner_mod.resume_after_exclusive_operation(was_paused)
        assert sch.is_running() is True
        assert sch._exclusive_hold is False, "the hold itself must be released by resume"
    finally:
        if sch.is_running():
            sch.stop()
