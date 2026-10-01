"""The disk reserve is sized from the drive; what it PROTECTS is a tail nobody had measured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``max(1 GiB, 2% of the drive)`` protects the writes still in flight while a pass winds down plus
the pass-tail records, which does not scale with the drive. The 2026-09-30 ruling was to leave the
formula alone and MEASURE the tail (the drive's loss between the guard's first refusal and the end
of the pass that was in flight), so the reserve can later be sized from an instance's own tail plus
a stated margin. These tests pin the measurement: when it is taken, when it is not, and that an
unreadable figure is never a recorded zero.
"""

from __future__ import annotations

import pytest

from src.scheduler import runner, storage_guard
from src.scheduler.settings import SchedulerSettings
from src.scheduler.storage_guard import GIB, MIB, StorageGuard


@pytest.fixture(autouse=True)
def _guard_enabled(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def _guard(clock, reading):
    def readings():
        return dict(reading)

    return StorageGuard(clock=clock, readings_fn=readings, drain_fn=lambda: {"busy": 0}, trip_after=2, resume_after=2)


def _trip_disk(g, reading, clock):
    """Two samples under the reserve: the guard first refuses NOW."""
    reading.update(disk_free_bytes=800 * MIB, disk_total_bytes=100 * GIB, corpus_bytes=5 * GIB, wal_bytes=50 * MIB)
    g.poll()
    clock.advance(5)
    g.poll()
    assert g.kind() == "disk"


def test_a_pass_in_flight_when_the_guard_first_refuses_gets_its_tail_measured():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    reading.update(disk_free_bytes=50 * GIB, disk_total_bytes=100 * GIB, corpus_bytes=5 * GIB, wal_bytes=20 * MIB)
    g.poll()
    pass_started = clock()
    clock.advance(10)
    _trip_disk(g, reading, clock)  # first refusal, free 800 MiB
    trip_free = 800 * MIB
    clock.advance(240)
    reading.update(disk_free_bytes=trip_free - 300 * MIB)  # the pass kept writing for 4 minutes
    tail = g.note_pass_ended(pass_started)
    assert tail is not None
    assert tail["drive_free_drop_bytes"] == 300 * MIB
    assert tail["free_at_trip"] == trip_free and tail["free_at_end"] == trip_free - 300 * MIB
    assert tail["seconds"] == 240.0 and tail["kind"] == "disk"
    st = g.state()
    assert st["last_tail"]["drive_free_drop_bytes"] == 300 * MIB
    assert "tails" not in st, "the list rides the bundle, not every poll"
    d = g.state(detail=True)
    assert len(d["tails"]) == 1 and d["max_tail_drive_free_drop_bytes"] == 300 * MIB
    assert "upper bound" in d["method"]


def test_a_pass_that_began_after_the_first_refusal_has_no_tail():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    _trip_disk(g, reading, clock)
    clock.advance(30)
    pass_started = clock()  # the guard was already refusing when this pass started
    clock.advance(60)
    assert g.note_pass_ended(pass_started) is None
    assert g.state()["last_tail"] is None


def test_the_tail_is_measured_once_per_engagement():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    pass_started = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    assert g.note_pass_ended(pass_started) is not None
    assert g.note_pass_ended(pass_started) is None
    assert len(g.state(detail=True)["tails"]) == 1


def test_a_release_clears_the_episode_and_the_next_engagement_is_measured_afresh():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    p1 = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    g.note_pass_ended(p1)
    reading.update(disk_free_bytes=50 * GIB)
    g.poll()
    clock.advance(5)
    g.poll()
    assert not g.engaged
    assert g.note_pass_ended(p1) is None, "nothing engaged: nothing to measure"
    p2 = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    assert g.note_pass_ended(p2) is not None
    assert len(g.state(detail=True)["tails"]) == 2


def test_an_unreadable_figure_is_none_never_a_recorded_zero():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    pass_started = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    reading.update(disk_free_bytes=None)
    tail = g.note_pass_ended(pass_started)
    assert tail is not None and tail["drive_free_drop_bytes"] is None and tail["free_at_end"] is None
    assert g.state(detail=True)["max_tail_drive_free_drop_bytes"] is None


def test_a_drive_that_gained_space_reads_as_zero_loss_not_negative():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    pass_started = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    reading.update(disk_free_bytes=2 * GIB)  # a download elsewhere finished and freed space
    assert g.note_pass_ended(pass_started)["drive_free_drop_bytes"] == 0


def test_a_disabled_guard_measures_nothing(monkeypatch):
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    pass_started = clock()
    clock.advance(5)
    _trip_disk(g, reading, clock)
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert g.note_pass_ended(pass_started) is None


def test_the_tails_are_bounded():
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    for _ in range(storage_guard.TAIL_KEEP + 5):
        p = clock()
        clock.advance(5)
        _trip_disk(g, reading, clock)
        g.note_pass_ended(p)
        reading.update(disk_free_bytes=50 * GIB)
        g.poll()
        clock.advance(5)
        g.poll()
    assert len(g.state(detail=True)["tails"]) == storage_guard.TAIL_KEEP


def test_the_scheduler_measures_the_tail_at_the_end_of_a_pass_that_was_in_flight(monkeypatch):
    clock, reading = Clock(), {}
    g = _guard(clock, reading)
    monkeypatch.setattr(storage_guard, "storage_guard", g)

    def one_pass():
        # the guard first refuses while this pass is running, and the pass keeps writing
        clock.advance(5)
        _trip_disk(g, reading, clock)
        clock.advance(60)
        reading.update(disk_free_bytes=700 * MIB)
        return {"ok": True}

    # the scheduler's monotonic start is the REAL clock; line the injected clock up with it
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock.t)
    sched = runner.BackgroundScheduler(
        run_once_fn=one_pass, settings_provider=lambda: SchedulerSettings(continuous=False)
    )
    sched._do_run()
    tail = g.state()["last_tail"]
    assert tail is not None and tail["drive_free_drop_bytes"] == 100 * MIB


def test_the_runner_calls_the_measure_after_the_pass_tail_not_before():
    import re
    from pathlib import Path

    from tests.js_source_helper import python_function_source

    src = (Path(__file__).resolve().parent.parent / "src" / "scheduler" / "runner.py").read_text(encoding="utf-8")
    body = python_function_source(src, "_do_run")
    at = {k: re.search(re.escape(k), body) for k in ("_tail_journal_trim()", "note_pass_ended(started_mono)", "self._run_lock.release()")}
    assert all(at.values()), at
    assert at["_tail_journal_trim()"].start() < at["note_pass_ended(started_mono)"].start() < at["self._run_lock.release()"].start(), (
        "the tail runs until the record-run line: measure after it, and before the lock is released"
    )
