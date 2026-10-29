"""A maintenance guard that cannot be READ refuses the window and is named, and two best-effort handlers say what they dropped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``BackgroundScheduler._run_off_peak_maintenance`` read four guards (memory, storage, a damaged corpus file, the check after an unexpected
stop) in ONE ``try`` that ended in ``except Exception: pass``. A guard that raised was therefore read as "clear" and the window went
on to vacuum, clean up and checkpoint, with nothing logged: the guards that exist to keep that work off a damaged file and a full
drive failed OPEN, and a failure of the first one skipped the three after it. Each guard is now read on its own; one that cannot be
read refuses the window (skip reason ``guard_unreadable``) and the log names it.

``_tail_journal_trim`` and the reclaim in the memory pause ended in a bare ``pass``; their siblings log at DEBUG (R386).
"""

from __future__ import annotations

import logging

import pytest

from src.scheduler import maintenance, memguard, storage_guard
from src.scheduler import runner as R
from src.scheduler.runner import BackgroundScheduler


@pytest.fixture()
def sched(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    s = BackgroundScheduler()
    s._last_maint = 0.0  # due
    return s


@pytest.fixture()
def ran(monkeypatch):
    """What the window did if it got past the guards: ``run_idle_maintenance`` is replaced by a recorder."""
    calls: list[object] = []

    def run(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(maintenance, "run_idle_maintenance", run)
    return calls


def _boom():
    raise RuntimeError("guard read broke")


# (name in the log, the reader the window calls)
_GUARDS = {
    "memory": "_maint_memory_refusal",
    "storage": "_maint_storage_refusal",
    "database damage": "_maint_damage_refusal",
    "database check": "_maint_check_refusal",
}


@pytest.mark.parametrize("guard", list(_GUARDS))
def test_a_guard_that_cannot_be_read_refuses_the_window_and_is_named(sched, ran, monkeypatch, caplog, guard):
    monkeypatch.setattr(R, _GUARDS[guard], _boom)
    with caplog.at_level(logging.DEBUG, logger=R._LOG.name):
        assert sched._run_off_peak_maintenance() is False
    assert ran == [], "maintenance ran although a guard could not be read"
    assert sched.status()["maintenance_skips"] == {"guard_unreadable": 1}
    said = " ".join(r.getMessage() for r in caplog.records)
    assert f"the {guard} guard could not be read" in said and "guard read broke" in said
    assert not sched._run_lock.locked() and not sched._active


def test_an_unreadable_first_guard_does_not_hide_a_hit_by_a_later_one(sched, ran, monkeypatch):
    """Before, the memory guard raising skipped the damage guard's read entirely; the window refuses and the counter says it was a read
    that failed, not that the file was found damaged."""
    monkeypatch.setattr(R, "_maint_memory_refusal", _boom)
    monkeypatch.setattr(R, "_maint_damage_refusal", lambda: "database_damage")
    assert sched._run_off_peak_maintenance() is False
    assert ran == []
    assert sched.status()["maintenance_skips"] == {"guard_unreadable": 1}


def test_readable_guards_still_let_the_window_run(sched, ran, monkeypatch):
    for fn in _GUARDS.values():
        monkeypatch.setattr(R, fn, lambda: None)
    assert sched._run_off_peak_maintenance() is True
    assert len(ran) == 1
    assert sched.status()["maintenance_skips"] == {}


def test_each_guard_still_refuses_with_its_own_reason(sched, ran, monkeypatch):
    for fn in _GUARDS.values():
        monkeypatch.setattr(R, fn, lambda: None)
    for guard, reason in (("_maint_storage_refusal", "storage_pressure"), ("_maint_check_refusal", "database_check")):
        monkeypatch.setattr(R, guard, lambda reason=reason: reason)
        assert sched._run_off_peak_maintenance() is False
        monkeypatch.setattr(R, guard, lambda: None)
    assert ran == []
    assert sched.status()["maintenance_skips"] == {"storage_pressure": 1, "database_check": 1}


def test_the_real_readers_read_the_live_guards(sched, ran, monkeypatch):
    """The readers are what the window calls: a storage guard that is enabled and engaged refuses with ``storage_pressure``."""
    guard = storage_guard.storage_guard
    monkeypatch.setattr(type(guard), "enabled", lambda self: True)
    monkeypatch.setattr(type(guard), "engaged", property(lambda self: True))
    assert R._maint_storage_refusal() == "storage_pressure"
    monkeypatch.setattr(type(memguard.memory_guard), "engaged", property(lambda self: True))
    assert R._maint_memory_refusal() == "memory_pressure"


# -- the two handlers that dropped their exception (R386) -------------------- #


def test_a_pass_journal_that_cannot_be_trimmed_says_so(monkeypatch, caplog):
    monkeypatch.setattr("src.scheduler.pass_journal.trim", _boom)
    with caplog.at_level(logging.DEBUG, logger=R._LOG.name):
        R._tail_journal_trim()  # never raises: housekeeping
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "pass journal could not be trimmed" in said and "guard read broke" in said


def test_a_memory_pause_reclaim_that_fails_says_so_and_the_pause_still_ends(sched, monkeypatch, caplog):
    guard = memguard.MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0, trip_after=1, resume_after=1, readings_fn=lambda: {})
    polls = [0]

    def poll():
        polls[0] += 1
        return polls[0] <= 2  # engaged twice, then recovered

    monkeypatch.setattr(guard, "poll", poll)
    monkeypatch.setattr(guard, "state", lambda: {})
    monkeypatch.setattr(memguard, "memory_guard", guard)
    monkeypatch.setattr("src.scheduler.hygiene.release_pass_state", _boom)
    sched._mem_reclaim_interval_s = 0.0
    sched._mem_pause_poll_s = 0.01
    with caplog.at_level(logging.DEBUG, logger=R._LOG.name):
        sched._wait_while_memory_paused()
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "memory-pause reclaim failed" in said and "guard read broke" in said
    assert polls[0] >= 3, "the pause did not run to its end"
