"""
S4.3 (2026-09-02 crash analysis): WAL bytes in every collector sample.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app had exactly one WAL series -- the hourly ``wal_bytes`` gauge -- and it is
recorded inside idle maintenance, which ``BackgroundScheduler`` returns early from
whenever the memory guard is engaged. So the instrument was blind on precisely the
machine whose WAL matters: the one already starving.

The reader half needs its own care. ``pool_watch.checked_out()`` returns an empty
list both when nothing is checked out AND when the listeners were never attached,
and those are opposite facts -- an unattached instrument would otherwise publish
"no reader is pinning the WAL" forever, which is the reading a checkpoint
diagnosis turns on.
"""

from __future__ import annotations

import pytest

from src.monitoring.collect_perf import CollectionMonitor


@pytest.fixture(autouse=True)
def _clean_pool_watch():
    from src.database import pool_watch

    pool_watch._reset_for_tests()
    yield
    pool_watch._reset_for_tests()


def test_the_hourly_gauge_is_skipped_under_pressure_which_is_why_this_exists():
    """The premise, asserted rather than assumed: the scheduler really does return
    before running idle maintenance when the guard is engaged."""
    import inspect

    from src.scheduler.runner import BackgroundScheduler

    src = inspect.getsource(BackgroundScheduler._run_off_peak_maintenance)
    assert "memory_guard.engaged" in src
    # The early return is what makes the hourly series blind; if this stops being a
    # return, the per-sample reading is redundant rather than load-bearing.
    head = src.split("memory_guard.engaged", 1)[1][:120]
    assert "return" in head, "the guard no longer short-circuits idle maintenance"


def test_every_sample_carries_the_wal_bytes_reading(monkeypatch):
    from src.database import snapshots

    monkeypatch.setattr(snapshots, "wal_bytes", lambda: 4096)
    g = CollectionMonitor._wal_gauges()
    assert g["bytes"] == 4096


def test_an_absent_wal_file_is_a_real_zero_not_a_gap(monkeypatch):
    """A store with nothing to replay measured 0 bytes. That is a measurement."""
    from src.database import snapshots

    monkeypatch.setattr(snapshots, "wal_bytes", lambda: 0)
    assert CollectionMonitor._wal_gauges()["bytes"] == 0


def test_an_unmeasurable_backend_is_none_never_zero(monkeypatch):
    """The other direction: on an in-memory or non-SQLite backend there is no WAL to
    measure, and a recorded 0 there would read as an empty WAL."""
    from src.database import snapshots

    monkeypatch.setattr(snapshots, "wal_bytes", lambda: None)
    assert CollectionMonitor._wal_gauges()["bytes"] is None


def test_a_gauge_fault_never_aborts_the_tick(monkeypatch):
    from src.database import snapshots

    def _boom():
        raise RuntimeError("cannot stat")

    monkeypatch.setattr(snapshots, "wal_bytes", _boom)
    g = CollectionMonitor._wal_gauges()
    assert g["bytes"] is None  # omitted, and the sample still exists


def test_the_oldest_checkout_is_named_so_a_pinned_wal_has_a_candidate(monkeypatch):
    from src.database import pool_watch

    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(
        pool_watch,
        "checked_out",
        lambda: [{"thread": "collect-3", "age_s": 812.5}, {"thread": "main", "age_s": 0.2}],
    )
    r = CollectionMonitor._wal_gauges()["readers"]
    assert r["n"] == 2
    assert r["oldest_age_s"] == 812.5
    assert r["oldest_thread"] == "collect-3"


def test_an_idle_pool_reports_zero_readers_with_no_age(monkeypatch):
    """Genuinely nothing checked out: n is the measurement, and the age is None
    because there is no reader to age -- not because it could not be read."""
    from src.database import pool_watch

    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(pool_watch, "checked_out", lambda: [])
    r = CollectionMonitor._wal_gauges()["readers"]
    assert r["n"] == 0
    assert r["oldest_age_s"] is None


def test_an_unattached_instrument_is_not_reported_as_an_idle_pool(monkeypatch):
    """The discriminating case. Both states return an empty list from
    checked_out(), so without is_registered() a never-registered pool would
    publish n=0 -- a clean bill of health from an instrument that is not running."""
    from src.database import pool_watch

    monkeypatch.setattr(pool_watch, "is_registered", lambda: False)
    monkeypatch.setattr(pool_watch, "checked_out", lambda: [])
    r = CollectionMonitor._wal_gauges()["readers"]
    assert r == {"instrument": "unattached"}
    assert "n" not in r, "an unattached instrument published a reader count"


def test_a_real_tick_writes_the_wal_reading_into_the_sample(tmp_path, monkeypatch):
    """The wiring, not the helper. Every test above calls ``_wal_gauges()``
    directly, and a mutation that deleted its USE from the sample dict reddened
    none of them -- the recorded unguarded-wiring defect. Recording the figure in
    every sample IS this slice, so the sample is what must be asserted."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database import snapshots
    from src.monitoring.collect_perf import recent_samples
    from src.scheduler.bandwidth import BandwidthGovernor

    monkeypatch.setattr(snapshots, "wal_bytes", lambda: 8192)
    mon = CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=2),
        pass_id="wal-sample-test",
        mode="rss",
        rate_fn=lambda: 100.0,
        vitals_fn=lambda: {"cpu_sys_pct": 5.0, "cpu_proc_pct": 5.0,
                           "mem_avail_mb": 4000.0, "rss_mb": 100.0},
        writer_stats_fn=lambda: {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0},
    )
    mon._tick()

    mine = [s for s in recent_samples() if s.get("pass_id") == "wal-sample-test"]
    assert mine, "the tick recorded no sample at all — nothing was measured"
    wal = mine[-1].get("wal")
    assert wal is not None, "the sample carries no WAL reading, which is the whole slice"
    assert wal["bytes"] == 8192
    assert "readers" in wal


def test_is_registered_reports_false_before_it_is_attached():
    """The discriminating case, and the reason the first version of this guard was
    worthless: session.py registers at import, so by the time any test runs the
    flag is already True and "register, then assert True" passes for a constant.
    The unattached direction is the one the reading depends on, so the flag is
    driven both ways and restored."""
    from sqlalchemy import create_engine

    from src.database import pool_watch

    saved = pool_watch._REGISTERED
    try:
        pool_watch._REGISTERED = False
        assert pool_watch.is_registered() is False, (
            "is_registered() cannot report an unattached instrument, so an "
            "unwatched pool publishes a reader count of zero"
        )
        eng = create_engine("sqlite://")
        assert pool_watch.register(eng) is True
        assert pool_watch.is_registered() is True
    finally:
        pool_watch._REGISTERED = saved
