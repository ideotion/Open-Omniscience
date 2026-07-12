"""
S2.2 — A10: off-peak background maintenance is scheduler-owned + collector-idle.

The deadline-budgeted keyword maintenance (counter reconcile + orphan prune +
language reconcile) moved OFF the pass-tail warm_cache and INTO a scheduler-owned
idle-window step (src/scheduler/maintenance.py:run_idle_maintenance, wired in
BackgroundScheduler._run_off_peak_maintenance). These tests pin: it runs the
existing budgeted calls, it is throttled off-peak, it is mutually exclusive with a
collect pass (holds _run_lock), it yields on stop / memory pressure, and it is
decoupled from warm_cache.
"""

from __future__ import annotations

from src.scheduler.runner import BackgroundScheduler


# --------------------------------------------------------------------------- #
# run_idle_maintenance: runs both budgeted calls; yields on stop
# --------------------------------------------------------------------------- #


def test_run_idle_maintenance_runs_both_budgeted_calls(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()
    calls: list[str] = []
    monkeypatch.setattr(
        "src.analytics.store.maybe_reconcile_counters",
        lambda s: calls.append("reconcile") or {"skipped": "fresh"},
    )
    monkeypatch.setattr(
        "src.analytics.store.maybe_cleanup_keywords",
        lambda s, **k: calls.append("cleanup") or {"skipped": "fresh"},
    )
    out = maint_mod.run_idle_maintenance()
    assert calls == ["reconcile", "cleanup"]
    assert out["reconcile"] == {"skipped": "fresh"}
    assert out["cleanup"] == {"skipped": "fresh"}


def test_run_idle_maintenance_yields_on_should_stop_before_and_between(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()
    calls: list[str] = []
    monkeypatch.setattr(
        "src.analytics.store.maybe_reconcile_counters",
        lambda s: calls.append("reconcile") or {"ok": True},
    )
    monkeypatch.setattr(
        "src.analytics.store.maybe_cleanup_keywords",
        lambda s, **k: calls.append("cleanup") or {"ok": True},
    )
    # stop before anything → neither runs
    assert maint_mod.run_idle_maintenance(should_stop=lambda: True) == {"skipped": "stopping"}
    assert calls == []
    # stop AFTER reconcile → cleanup yields (the between-slice yield)
    state = {"n": 0}

    def _stop():
        state["n"] += 1
        return state["n"] > 1  # False on the pre-check, True after reconcile

    out = maint_mod.run_idle_maintenance(should_stop=_stop)
    assert calls == ["reconcile"]
    assert out["cleanup"] == {"skipped": "stopping"}


def test_run_idle_maintenance_never_raises_on_a_failing_call(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.analytics.store.maybe_reconcile_counters", _boom)
    monkeypatch.setattr("src.analytics.store.maybe_cleanup_keywords", _boom)
    out = maint_mod.run_idle_maintenance()  # must not raise
    assert out["reconcile"] == {"skipped": "error"}
    assert out["cleanup"] == {"skipped": "error"}


# --------------------------------------------------------------------------- #
# The scheduler hook: idle-gated, throttled, mutually exclusive, yields
# --------------------------------------------------------------------------- #


def _recorder(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "src.scheduler.maintenance.run_idle_maintenance",
        lambda **k: calls.append(k) or {"ran": True},
    )
    return calls


def test_scheduler_runs_maintenance_in_the_idle_window(monkeypatch):
    calls = _recorder(monkeypatch)
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    sched._run_off_peak_maintenance()
    assert len(calls) == 1
    assert sched._last_maintenance == {"ran": True}


def test_maintenance_is_throttled_by_the_min_interval(monkeypatch):
    calls = _recorder(monkeypatch)
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 10_000.0  # a long off-peak interval
    sched._run_off_peak_maintenance()  # first is due
    sched._run_off_peak_maintenance()  # immediate second is throttled
    assert len(calls) == 1


def test_maintenance_yields_when_a_pass_holds_the_run_lock(monkeypatch):
    calls = _recorder(monkeypatch)
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    assert sched._run_lock.acquire(blocking=False)  # a "run-now pass" owns it
    try:
        sched._run_off_peak_maintenance()
    finally:
        sched._run_lock.release()
    assert calls == []  # yielded — never concurrent with a pass


def test_maintenance_skipped_when_stopping(monkeypatch):
    calls = _recorder(monkeypatch)
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    sched._stop.set()
    sched._run_off_peak_maintenance()
    assert calls == []


def test_maintenance_skipped_under_memory_pressure(monkeypatch):
    calls = _recorder(monkeypatch)
    from src.scheduler import memguard

    # engaged is a read-only property backed by _engaged (read under a lock); set
    # the backing attr so the property returns True. monkeypatch auto-restores it.
    monkeypatch.setattr(memguard.memory_guard, "_engaged", True)
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    sched._run_off_peak_maintenance()
    assert calls == []


def test_maintenance_sets_active_so_run_now_is_honest(monkeypatch):
    """Skeptic finding (2026-07-12): while maintenance holds _run_lock but _active is
    False, a concurrent run_now gates on _active, spawns a pass, fails the lock acquire
    and silently no-ops while replying started:true. The fix sets _active + a labelled
    phase for the window, so run_now honestly returns False and status shows busy."""
    from src.scheduler.runner import current_phase

    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    seen: dict = {}

    def _rec(**k):
        seen["active_during"] = sched._active
        seen["phase_during"] = current_phase()
        seen["run_now_during"] = sched.run_now()  # must be False (busy), not a silent True
        return {"ran": True}

    monkeypatch.setattr("src.scheduler.maintenance.run_idle_maintenance", _rec)
    sched._run_off_peak_maintenance()
    assert seen["active_during"] is True
    assert seen["phase_during"] == "maintenance"
    assert seen["run_now_during"] is False  # honest busy, never a silently-dropped run
    assert sched._active is False  # reset after the window
    assert current_phase() is None


def test_maintenance_releases_the_run_lock_even_on_error(monkeypatch):
    monkeypatch.setattr(
        "src.scheduler.maintenance.run_idle_maintenance",
        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    sched = BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: _S())
    sched._maint_interval_s = 0.0
    sched._run_off_peak_maintenance()  # must not raise
    # the lock is free again (a subsequent pass can run)
    assert sched._run_lock.acquire(blocking=False)
    sched._run_lock.release()


# --------------------------------------------------------------------------- #
# Decoupling guard: warm_cache no longer runs the keyword maintenance
# --------------------------------------------------------------------------- #


def test_scheduler_loop_wires_off_peak_maintenance():
    """The idle-window hook must actually be CALLED from the loop (a wiring guard:
    it composes the call, never asserts it side-by-side)."""
    import inspect

    from src.scheduler import runner

    loop_src = inspect.getsource(runner.BackgroundScheduler._loop)
    assert "_run_off_peak_maintenance()" in loop_src
    # And the method delegates to the scheduler-owned maintenance module.
    method_src = inspect.getsource(runner.BackgroundScheduler._run_off_peak_maintenance)
    assert "run_idle_maintenance" in method_src


def test_warm_cache_no_longer_runs_keyword_maintenance():
    """A10 decoupling: the pass-tail warm_cache keeps cache-warming but must NOT
    call the keyword maintenance any more (it is scheduler-owned now)."""
    import inspect

    from src.api import insights

    src = inspect.getsource(insights.warm_cache)
    assert "maybe_reconcile_counters" not in src
    assert "maybe_cleanup_keywords" not in src


class _S:
    """A minimal settings object for the injectable scheduler."""

    continuous = True
    interval_minutes = 60
    mode = "rss"

    def to_dict(self):
        return {"continuous": self.continuous, "interval_minutes": self.interval_minutes}
