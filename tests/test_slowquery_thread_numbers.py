"""A slow statement's record says what the executing thread did, so a wait can be told from work.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: ``SAVEPOINT`` averaged 36.5 s and ``INSERT INTO articles`` 35.0 s, and the log (wall time only) could
not say whether the thread worked or waited. Each record now carries ``cpu_ms`` and the thread's ``nvcsw``/``nivcsw``/
``majflt``/``inblock`` deltas. These tests run the REAL listeners on a real engine with a statement that sleeps and one that burns
CPU, inside the sqlite call, and read what the record says of each.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine, event

from src.monitoring import slowquery, thread_usage

RECORD_KEYS = {"at", "duration_ms", "sql", "cpu_ms", "nvcsw", "nivcsw", "majflt", "inblock"}


def _burn(seconds: float) -> int:
    """Hold the CPU for ``seconds`` of THIS THREAD's CPU time, inside the sqlite call."""
    t0 = time.thread_time()
    while time.thread_time() - t0 < seconds:
        pass
    return 1


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_SLOW_QUERY_MS", "50")
    monkeypatch.setattr(slowquery, "_installed", False)
    slowquery._RING.clear()
    slowquery._AGG.clear()
    eng = create_engine(f"sqlite:///{tmp_path / 'slow.db'}")

    @event.listens_for(eng, "connect")
    def _functions(dbapi, _record):
        dbapi.create_function("pause", 1, lambda s: time.sleep(s) or 1)
        dbapi.create_function("burn", 1, _burn)

    slowquery.install(eng)
    yield eng
    eng.dispose()
    slowquery._RING.clear()
    slowquery._AGG.clear()


def _run(engine, sql):
    with engine.connect() as conn:
        conn.exec_driver_sql(sql).fetchall()
    return slowquery.recent(10)[-1]


@pytest.mark.skipif(thread_usage.RUSAGE_THREAD is None, reason="the OS gives no per-thread counters")
def test_a_wait_has_little_cpu_and_a_voluntary_switch_and_work_has_cpu(engine):
    waited = _run(engine, "SELECT pause(0.25)")
    worked = _run(engine, "SELECT burn(0.25)")
    assert waited["duration_ms"] >= 240 and worked["duration_ms"] >= 240
    # the thread waited: almost no CPU over a quarter second of wall time, and it gave the CPU up (a sleep is a voluntary switch)
    assert waited["cpu_ms"] < 100, waited
    assert waited["nvcsw"] >= 1, waited
    # the thread worked: ``burn`` holds a quarter second of THIS THREAD's CPU, so its figure is at least that however loaded the
    # machine is (a busy runner stretches the wall time, never the thread's own CPU time)
    assert worked["cpu_ms"] >= 240, worked


@pytest.mark.skipif(thread_usage.RUSAGE_THREAD is None, reason="the OS gives no per-thread counters")
def test_the_counters_are_the_executing_threads_not_the_processs(engine):
    """Another thread switching a hundred times during the statement must not appear in the statement's record: the record's
    interval is nested in the same thread's outer interval, so its count cannot exceed the outer one unless it counted the process."""
    import resource
    import threading

    stop = threading.Event()

    def chatter():
        while not stop.is_set():
            time.sleep(0.001)

    other = threading.Thread(target=chatter)
    other.start()
    try:
        outer0 = resource.getrusage(resource.RUSAGE_THREAD).ru_nvcsw
        rec = _run(engine, "SELECT pause(0.3)")
        outer1 = resource.getrusage(resource.RUSAGE_THREAD).ru_nvcsw
    finally:
        stop.set()
        other.join()
    assert rec["nvcsw"] <= outer1 - outer0, (rec, outer1 - outer0)


def test_the_record_carries_numbers_only_never_a_value_or_a_second_statement(engine):
    rec = _run(engine, "SELECT pause(0.1)")
    if thread_usage.RUSAGE_THREAD is not None:
        assert set(rec) == RECORD_KEYS, set(rec)
    assert all(isinstance(rec[k], (int, float)) for k in rec if k not in ("at", "sql")), rec
    assert "0.1" not in rec["sql"], "the bound value is stripped as before"


def test_a_figure_the_os_cannot_give_is_absent_never_zero(engine, monkeypatch):
    monkeypatch.setattr(thread_usage, "RUSAGE_THREAD", None)
    rec = _run(engine, "SELECT pause(0.1)")
    assert "cpu_ms" in rec and not ({"nvcsw", "nivcsw", "majflt", "inblock"} & set(rec)), rec

    def no_clock():
        raise OSError("no per-thread clock")

    monkeypatch.setattr(thread_usage.time, "thread_time", no_clock)
    rec = _run(engine, "SELECT pause(0.1)")
    assert "cpu_ms" not in rec, "a clock that cannot be read is no figure, not 0.0"
    assert rec["duration_ms"] >= 90, "the wall time is unaffected"


def test_a_statement_under_the_threshold_leaves_no_record(engine):
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1").fetchall()
    assert slowquery.recent(10) == []


def test_the_aggregate_sums_the_figures_over_the_calls_that_had_them_and_counts_them():
    slowquery._RING.clear()
    slowquery._AGG.clear()
    sql = "SELECT * FROM keywords WHERE id = 7"
    slowquery._record(sql, 1000.0, {"cpu_ms": 100.0, "nvcsw": 4, "nivcsw": 1, "majflt": 0, "inblock": 8})
    slowquery._record(sql, 500.0)  # a call the OS gave nothing for, BETWEEN the two that had figures
    slowquery._record(sql, 3000.0, {"cpu_ms": 200.0, "nvcsw": 6, "nivcsw": 2, "majflt": 3, "inblock": 0})
    (row,) = slowquery._by_total()
    assert row["count"] == 3 and row["total_ms"] == 4500.0
    assert row["measured"] == 2 and row["measured_ms"] == 4000.0, "the 500 ms call is not averaged in as a 0"
    assert row["cpu_ms"] == 300.0 and row["nvcsw"] == 10 and row["nivcsw"] == 3 and row["majflt"] == 3 and row["inblock"] == 8
    slowquery._AGG.clear()
    slowquery._RING.clear()
    slowquery._record(sql, 700.0)
    (row,) = slowquery._by_total()
    assert "measured" not in row and "cpu_ms" not in row, "a shape with no measured call carries none of the figures"
    slowquery._AGG.clear()
    slowquery._RING.clear()


def test_a_sample_that_fails_never_reaches_the_statement(engine, monkeypatch):
    """The listener runs before every statement of every thread: a sample that raises must cost the figure, not the statement."""

    def boom():
        raise OSError("clock")

    monkeypatch.setattr(thread_usage.time, "thread_time", boom)
    if thread_usage._resource is not None:
        monkeypatch.setattr(thread_usage._resource, "getrusage", lambda *_a: (_ for _ in ()).throw(OSError("rusage")))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT pause(0.1)").fetchall() == [(1,)]
    rec = slowquery.recent(10)[-1]
    assert "cpu_ms" not in rec and "nvcsw" not in rec and rec["duration_ms"] >= 90


def test_a_sample_from_the_future_is_clamped_to_zero_never_shown_negative():
    """A sample taken on ANOTHER thread (a mistake of a caller) can be ahead of this thread's counters; the difference is clamped."""
    out = thread_usage.since((1e12, (10**12,) * 4))
    assert out.get("cpu_ms") == 0.0
    if thread_usage.RUSAGE_THREAD is not None:
        assert all(out[name] == 0 for name in thread_usage.COUNTS), out
