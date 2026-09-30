"""The off-peak maintenance window also runs while the scheduler loop does not.

Field bundle 2026-09-30: ``auto_cleanup.last_run`` and ``auto_incremental_vacuum.last_run``
were both null on an instance with 7.9 M mention-less keyword rows. The window had exactly
one caller -- the collection loop -- and an offline instance never starts it.
"""

from __future__ import annotations

import pathlib

import pytest

from src.scheduler import offline_maintenance as om
from src.scheduler.runner import BackgroundScheduler

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def sched(monkeypatch):
    s = BackgroundScheduler()
    monkeypatch.setattr("src.scheduler.runner.owns_the_machine", lambda: False)
    monkeypatch.setattr(
        "src.analytics.reindex_job.get_reindex_manager",
        lambda: type("M", (), {"status": staticmethod(lambda: {"state": "idle"})})(),
    )
    monkeypatch.setattr("src.jobs.background.all_job_statuses", lambda: [])
    return s


def _record_runs(monkeypatch):
    calls: list[int] = []

    def fake(*, should_stop=None):
        calls.append(1)
        return {"cleanup": {"skipped": "fresh"}}

    monkeypatch.setattr("src.scheduler.maintenance.run_idle_maintenance", fake)
    return calls


def test_a_stopped_scheduler_still_gets_its_maintenance_window(sched, monkeypatch):
    calls = _record_runs(monkeypatch)
    # The loop was stopped for good: _stop is set, which the loop's own call reads as
    # "stopping" -- the timer must not inherit that.
    sched._stop.set()
    assert om.tick(sched) == "ran"
    assert calls == [1]
    assert sched.status()["maintenance_skips"] == {}


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ("loop", "offline_loop_owns_window"),
        ("exclusive", "offline_exclusive_operation"),
        ("reindex", "offline_reindex_running"),
        ("writer", "offline_writer_job_running"),
    ],
)
def test_it_yields_to_whatever_already_owns_the_machine(sched, monkeypatch, patch, reason):
    calls = _record_runs(monkeypatch)
    if patch == "loop":
        monkeypatch.setattr(sched, "is_running", lambda: True)
    elif patch == "exclusive":
        monkeypatch.setattr("src.scheduler.runner.owns_the_machine", lambda: True)
    elif patch == "reindex":
        monkeypatch.setattr(
            "src.analytics.reindex_job.get_reindex_manager",
            lambda: type("M", (), {"status": staticmethod(lambda: {"state": "running"})})(),
        )
    else:
        monkeypatch.setattr(
            "src.jobs.background.all_job_statuses",
            lambda: [{"running": True, "is_writer": True}],
        )
    assert om.tick(sched) == reason
    assert calls == []
    # Recorded, not silent: the diagnostics read the skip counters.
    assert sched.status()["maintenance_skips"] == {reason: 1}


def test_the_scheduler_loops_own_stop_flag_is_unchanged(sched, monkeypatch):
    calls = _record_runs(monkeypatch)
    sched._stop.set()
    sched._run_off_peak_maintenance()  # no should_stop: the loop's own call
    assert calls == []
    assert sched.status()["maintenance_skips"] == {"stopping": 1}


def test_declined_by_the_environment(monkeypatch):
    monkeypatch.setenv("OO_OFFLINE_MAINTENANCE", "0")
    assert om.start() is False


def test_interval_has_a_floor(monkeypatch):
    monkeypatch.setenv("OO_OFFLINE_MAINT_INTERVAL_S", "1")
    assert om.interval_s() == 60.0
    monkeypatch.setenv("OO_OFFLINE_MAINT_INTERVAL_S", "junk")
    assert om.interval_s() == 300.0


def test_boot_upkeep_starts_it_inside_the_no_scheduler_gate():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    call = src.index("_start_offline_maintenance()")
    gate = src.rindex('if os.getenv("OO_NO_SCHEDULER", "0") != "1":', 0, call)
    # Same block as the airplane engage: tests and headless setups never get a thread.
    assert "install_airplane_socket_guard()" in src[gate:call]


def _fake_continuation(monkeypatch, sched, incomplete_for: int):
    """A cleanup whose prune reports ``complete: false`` for the first N passes."""
    state = {"left": incomplete_for, "passes": 0}
    monkeypatch.setattr(om, "prune_incomplete", lambda: state["left"] > 0)

    def fake(*, should_stop=None):
        state["passes"] += 1
        state["left"] -= 1
        return {"cleanup": {"prune": {"complete": state["left"] <= 0}}}

    monkeypatch.setattr("src.scheduler.maintenance.run_cleanup_continuation", fake)
    monkeypatch.setattr(om, "_MIN_REST_S", 0.0)
    return state


def test_an_unfinished_prune_runs_back_to_back_without_the_interval_throttle(sched, monkeypatch):
    _record_runs(monkeypatch)
    state = _fake_continuation(monkeypatch, sched, incomplete_for=3)
    assert om.tick(sched) == "ran"
    # The window itself ran once, then the sweep continued until it reported complete --
    # all inside one tick, although the scheduler's own throttle (300 s) is still closed.
    assert state["passes"] == 3
    assert sched._last_maint  # the throttle stamp belongs to the FULL window only


def test_the_continuation_stops_at_the_first_yield_reason(sched, monkeypatch):
    _record_runs(monkeypatch)
    state = _fake_continuation(monkeypatch, sched, incomplete_for=50)
    real_yield = om.yield_reason
    seen = {"n": 0}

    def yield_after_two(s):
        seen["n"] += 1
        return real_yield(s) if seen["n"] <= 3 else "offline_reindex_running"

    monkeypatch.setattr(om, "yield_reason", yield_after_two)
    assert om.tick(sched) == "ran"
    assert state["passes"] == 2  # tick's own check, then 2 passes, then the yield
    assert sched.status()["maintenance_skips"].get("offline_reindex_running") == 1


def test_the_rest_between_passes_is_sized_from_the_pass_itself(sched, monkeypatch):
    _record_runs(monkeypatch)
    _fake_continuation(monkeypatch, sched, incomplete_for=2)
    monkeypatch.setattr(om, "_MIN_REST_S", 1.0)
    waits: list[float] = []
    monkeypatch.setattr(om._STOP, "wait", lambda t=None: waits.append(t) or False)
    # Per pass: the timer's start, the scheduler's own read, the timer's end -- a 40 s pass,
    # then a 1 s pass. Past the script the clock stays put.
    script = [0.0, 0.0, 40.0, 40.0, 40.0, 41.0]
    monkeypatch.setattr("time.monotonic", lambda: script.pop(0) if script else 41.0)
    assert om._continue_prune(sched, lambda: False) == 2
    assert waits == [pytest.approx(10.0), 1.0]  # 25 % of 40 s; floored at the minimum


def test_the_continuation_helper_runs_only_the_cleanup(monkeypatch):
    from src.scheduler import maintenance

    calls: list[str] = []
    monkeypatch.setattr(
        "src.analytics.store.maybe_cleanup_keywords",
        lambda session: calls.append("cleanup") or {"skipped": "fresh"},
    )
    monkeypatch.setattr("src.database.session.session_scope", _null_scope)
    assert maintenance.run_cleanup_continuation() == {"cleanup": {"skipped": "fresh"}}
    assert calls == ["cleanup"]
    assert maintenance.run_cleanup_continuation(should_stop=lambda: True) == {"skipped": "stopping"}


def _null_scope():
    import contextlib

    @contextlib.contextmanager
    def _cm():
        yield object()

    return _cm()
