"""A yielded maintenance window is counted, not silent (C6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. `storage_composition` reported "31 hourly samples" over a
SIXTEEN-DAY window -- about 1.9 a day where hourly would be ~384 -- with visible holes in
`wal_history.series`, including one of five days.

THE RECORDER WAS NEVER BROKEN. `record_stat_snapshots` buckets by hour and refuses a
duplicate bucket correctly. It simply was not CALLED: it rides the scheduler's off-peak
maintenance window, and `_run_off_peak_maintenance` returns early in four places -- while
stopping, while throttled, under memory pressure, and when a collect pass owns the run
lock. Every one of those returned in SILENCE.

That last case is the one that explains the field gap: a continuously-collecting machine
holds the run lock essentially always, so the window is yielded over and over. And a
dropped sample that leaves no trace is indistinguishable from an hour in which nothing
happened -- which is why nothing in the bundle could explain the holes.

So the misses are counted BY REASON. The label is fixed too: "hourly" now reads
"at most hourly" wherever it was stating a guarantee the lane cannot make.
"""

from __future__ import annotations

import pathlib

import pytest

from src.scheduler.runner import BackgroundScheduler


@pytest.fixture()
def sched(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return BackgroundScheduler()


def test_a_throttled_window_is_counted_not_silent(sched, monkeypatch):
    """The commonest skip. It fires on most scheduler iterations by design, so it must
    be cheap -- but it must not be invisible."""
    import time as _t

    sched._last_maint = _t.monotonic()          # just ran -> not due
    sched._maint_interval_s = 3600.0
    sched._run_off_peak_maintenance()

    assert sched.status()["maintenance_skips"] == {"throttled": 1}


def test_a_window_yielded_to_a_collect_pass_names_that_reason(sched, monkeypatch):
    """THE FIELD MECHANISM: a continuously-collecting machine holds the run lock, so the
    snapshot recorder's window is yielded again and again. The reason must be nameable,
    because "the series has a five-day hole" and "the collector never let go of the lock
    for five days" are the same fact and only one of them is actionable."""
    sched._last_maint = 0.0                     # due
    assert sched._run_lock.acquire(blocking=False)
    try:
        sched._run_off_peak_maintenance()
    finally:
        sched._run_lock.release()

    skips = sched.status()["maintenance_skips"]
    assert skips == {"collect_pass_owns_lock": 1}


def test_memory_pressure_is_its_own_reason(sched, monkeypatch):
    """Kept apart from the others: "we were out of memory" and "the collector was busy"
    call for different remedies, so one counter for both would answer neither."""
    from src.scheduler import memguard

    sched._last_maint = 0.0
    monkeypatch.setattr(type(memguard.memory_guard), "engaged", property(lambda self: True))
    sched._run_off_peak_maintenance()

    assert sched.status()["maintenance_skips"] == {"memory_pressure": 1}


def test_skips_accumulate_per_reason(sched):
    """Counts, so a reader can see WHICH pressure dominated a window of missing samples,
    not merely that something did."""
    import time as _t

    sched._maint_interval_s = 3600.0
    for _ in range(3):
        sched._last_maint = _t.monotonic()
        sched._run_off_peak_maintenance()

    assert sched.status()["maintenance_skips"]["throttled"] == 3


def test_a_fresh_scheduler_reports_no_skips_rather_than_a_fabricated_zero_history(sched):
    """Process-scoped and never persisted: after a restart these honestly read EMPTY.
    An empty dict says "this process has yielded nothing yet"; it must not be dressed up
    as a run with zero problems."""
    assert sched.status()["maintenance_skips"] == {}


def test_the_hourly_claim_no_longer_reads_as_a_guarantee():
    """The label half. The lane cannot promise hourly -- it is opportunistic -- so the
    surfaces that stated it flatly now say "at most". Pinned so the honest wording is not
    quietly reverted to the flat claim the field measurements contradict."""
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    soak = (root / "monitoring" / "soak_window.py").read_text(encoding="utf-8")

    assert "AT-MOST-hourly snapshot with infinite retention" in soak
    assert "AT MOST one per hour" in soak
    # ...and it points the reader at what explains a gap.
    assert "maintenance_skips" in soak
    # The flat claim is gone from the places that were stating it as a property.
    assert "an hourly snapshot with infinite retention" not in soak
    assert "no hourly snapshot has been recorded" not in soak
