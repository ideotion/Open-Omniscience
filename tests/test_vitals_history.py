"""The vitals history (2026-10-06, R119): memory, drive, database and log counts over days.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Driven with INJECTED clocks and readings, and asserted from the document the member serves and the
file the next boot reads -- never from a sleep. The negative space is the point: a reading that
could not be taken is null and never 0, a gap shows as a gap and is never filled, the minutes
before a kill are not claimed, and the log counter can neither deadlock logging nor stall on the
history's own lock.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest

from src.monitoring import vitals_history as v

HOUR0 = 1_699_999_200  # an exact hour boundary (a multiple of 3600), and so of 300 and 60
COL = {name: i for i, name in enumerate(v.COLUMNS)}


@pytest.fixture
def hist(monkeypatch, tmp_path):
    """An isolated data dir, the recorder reset, readings under the test's control."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    box: dict[str, dict[str, float]] = {"fast": {}, "slow": {}}
    monkeypatch.setattr(v, "_fast_readings", lambda: dict(box["fast"]))
    monkeypatch.setattr(v, "_slow_readings", lambda _now: dict(box["slow"]))
    monkeypatch.setattr(v, "_busiest", lambda _avail: [])
    v.start()
    yield box
    v.reset_for_tests()


def _ticks(box, start: int, seconds: int, *, step: int = 5, **fast: float) -> None:
    box["fast"] = dict(fast)
    for t in range(start, start + seconds, step):
        v.tick(now=float(t))


def _member(**kw):
    return v.diagnostics_member(**kw)


def test_a_bucket_holds_its_ticks_with_min_mean_and_max(hist):
    _ticks(hist, HOUR0, 300, rss=1000.0, avail=2000.0, swap=10.0, threads=40.0, blocks=500.0)
    hist["fast"] = {"rss": 1300.0, "avail": 1700.0, "swap": 30.0, "threads": 44.0, "blocks": 900.0}
    v.tick(now=float(HOUR0 + 300))  # the first tick of the next bucket closes the first one
    fine = _member()["fine"]
    first = fine[0]
    assert first[COL["t"]] == HOUR0 and first[COL["n"]] == 60
    assert (first[COL["rss_min"]], first[COL["rss_mean"]], first[COL["rss_max"]]) == (1000, 1000, 1000)
    assert first[COL["swap_max"]] == 10 and first[COL["threads_max"]] == 40 and first[COL["blocks_k_max"]] == 500
    # the open bucket is served as the last row, with its own single tick
    assert fine[-1][COL["t"]] == HOUR0 + 300 and fine[-1][COL["n"]] == 1
    assert fine[-1][COL["rss_max"]] == 1300


def test_mean_min_and_max_are_taken_across_different_readings(hist):
    for i, (rss, swap, threads, blocks) in enumerate(
        ((1000.0, 5.0, 40.0, 500.0), (1200.0, 30.0, 44.0, 900.0), (1100.0, 10.0, 41.0, 700.0))
    ):
        hist["fast"] = {"rss": rss, "avail": 3000.0 - rss, "swap": swap, "threads": threads, "blocks": blocks}
        v.tick(now=float(HOUR0 + 5 * i))
    row = _member()["fine"][-1]
    assert (row[COL["rss_min"]], row[COL["rss_mean"]], row[COL["rss_max"]]) == (1000, 1100, 1200)
    assert (row[COL["avail_min"]], row[COL["avail_mean"]], row[COL["avail_max"]]) == (1800, 1900, 2000)
    # the three that keep ONE extreme keep the PEAK, not the last and not the lowest
    assert (row[COL["swap_max"]], row[COL["threads_max"]], row[COL["blocks_k_max"]]) == (30, 44, 900)


def test_a_reading_that_could_not_be_taken_is_null_never_zero(hist):
    _ticks(hist, HOUR0, 60, rss=800.0)  # no avail, no swap, no drive
    row = _member()["fine"][-1]
    assert row[COL["rss_max"]] == 800
    for name in ("avail_min", "avail_mean", "avail_max", "swap_max", "drive_free_min", "db_max", "wal_max"):
        assert row[COL[name]] is None, name


def test_the_slow_readings_ride_every_row_of_their_interval(hist):
    hist["slow"] = {"drive_free": 5000.0, "db": 700.0, "wal": 1190.0, "columnar": 0.4}
    _ticks(hist, HOUR0, 30, rss=500.0)
    hist["slow"] = {"drive_free": 4800.0, "db": 710.0, "wal": 400.0, "columnar": 0.4}
    _ticks(hist, HOUR0 + 30, 30, rss=500.0)
    row = _member()["fine"][-1]
    assert row[COL["drive_free_min"]] == 4800  # the LOWEST free space of the bucket
    assert row[COL["db_max"]] == 710
    assert row[COL["wal_max"]] == 1190  # the LARGEST log of the bucket, not the last
    assert row[COL["columnar_max"]] == 0  # 0.4 MB rounds to a whole megabyte; the column says so


def test_the_hourly_row_is_the_merge_of_its_five_minute_buckets(hist):
    for k, rss in enumerate((1000.0, 2000.0, 3000.0)):
        _ticks(hist, HOUR0 + 300 * k, 300, rss=rss, avail=4000.0 - rss)
    # a tick in the next hour closes the third bucket and the hour
    _ticks(hist, HOUR0 + 3600, 5, rss=500.0)
    coarse = _member()["coarse"]
    first = coarse[0]
    assert first[COL["t"]] == HOUR0 and first[COL["n"]] == 180
    assert first[COL["rss_min"]] == 1000 and first[COL["rss_max"]] == 3000
    assert first[COL["rss_mean"]] == 2000  # weighted by ticks: three equal buckets
    assert first[COL["avail_min"]] == 1000 and first[COL["avail_max"]] == 3000


def test_the_hourly_mean_is_weighted_by_ticks_not_by_buckets(hist):
    _ticks(hist, HOUR0, 300, rss=1000.0)  # 60 ticks
    _ticks(hist, HOUR0 + 300, 5, rss=4000.0)  # 1 tick, in the next bucket of the same hour
    _ticks(hist, HOUR0 + 3600, 5, rss=0.0 + 100.0)  # next hour closes the first
    first = _member()["coarse"][0]
    assert first[COL["n"]] == 61
    assert first[COL["rss_mean"]] == round((60 * 1000 + 4000) / 61)


def test_retention_keeps_the_newest_rows_of_each_table(hist):
    hist["fast"] = {"rss": 100.0}
    for k in range(v.FINE_KEEP + 40):
        v.tick(now=float(HOUR0 + v.FINE_S * k))
    # one more bucket closes the last
    v.tick(now=float(HOUR0 + v.FINE_S * (v.FINE_KEEP + 41)))
    m = _member(max_bytes=10_000_000)
    assert len(v._FINE) == v.FINE_KEEP
    assert m["fine"][0][COL["t"]] == v._FINE[0][0] and m["fine"][-1][COL["t"]] == HOUR0 + v.FINE_S * (v.FINE_KEEP + 41)
    assert v._FINE[-1][0] == HOUR0 + v.FINE_S * (v.FINE_KEEP + 39)  # the newest CLOSED bucket kept


def test_a_gap_is_shown_as_a_gap_and_nothing_is_filled(hist):
    _ticks(hist, HOUR0, 600, rss=900.0)
    _ticks(hist, HOUR0 + 600 + 1800, 600, rss=900.0)  # the process was away for 30 minutes
    m = _member()
    times = [r[COL["t"]] for r in m["fine"]]
    assert all(t not in times for t in range(HOUR0 + 600, HOUR0 + 2400, 300))  # no invented rows
    assert m["gaps"] == [
        {
            "from": v._iso(HOUR0 + 600),
            "to": v._iso(HOUR0 + 2400),
            "seconds": 1800,
        }
    ]


def test_a_clock_that_steps_back_never_reorders_the_rows(hist):
    _ticks(hist, HOUR0 + 600, 300, rss=500.0)
    v.tick(now=float(HOUR0))  # an hour-ish earlier by the wall clock
    m = _member()
    times = [r[COL["t"]] for r in m["fine"]]
    assert times == sorted(times) and len(times) == len(set(times))
    assert m["clock_stepped_back"] == 1


def test_a_restart_resumes_the_open_bucket_and_counts_no_tick_twice(hist, monkeypatch):
    _ticks(hist, HOUR0, 450, rss=1000.0)  # one closed bucket (60) and 30 ticks of an open one
    v.flush()
    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: dict(hist["fast"]))
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    monkeypatch.setattr(v, "_busiest", lambda _avail: [])
    v.start()
    _ticks(hist, HOUR0 + 450, 150, rss=2000.0)  # the same open bucket continues, at another reading
    m = _member()
    assert [r[COL["t"]] for r in m["fine"]] == [HOUR0, HOUR0 + 300]
    assert [r[COL["n"]] for r in m["fine"]] == [60, 60]  # 30 stored + 30 new ticks = one full bucket
    assert m["fine"][1][COL["rss_mean"]] == 1500  # 30 ticks at 1000 and 30 at 2000: weighted by ticks
    assert m["fine"][1][COL["rss_min"]] == 1000 and m["fine"][1][COL["rss_max"]] == 2000
    # the hourly row holds each tick once: 60 closed + 60 in the (still open) second bucket
    assert m["coarse"][-1][COL["n"]] == 120
    assert m["coarse"][-1][COL["rss_mean"]] == 1250  # (60 x 1000 + 30 x 1000 + 30 x 2000) / 120
    assert len(m["session_starts"]) == 2


def test_a_restart_keeps_the_previous_sessions_last_minutes_apart(hist, monkeypatch):
    monkeypatch.setattr(v, "_busiest", lambda _avail: [{"thread": "oo-wiki-drain", "cpu_s": 40.0, "frames": ["a.py:1 f"]}])
    _ticks(hist, HOUR0, 300, rss=1000.0)
    v.flush()
    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 1.0})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    v.start()
    m = _member()
    prev = m["previous_session"]
    assert prev["last_flush_at"] and prev["minutes"]
    assert prev["minutes"][-1]["busiest"][0]["thread"] == "oo-wiki-drain"
    assert m["minutes"] == []  # this session's own minutes start empty


def test_a_damaged_or_foreign_file_starts_a_fresh_history(hist):
    v.reset_for_tests()
    path = v._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for payload in ("{not json", json.dumps({"schema": "somebody-else", "fine": [[1] * 15]}), "[]"):
        path.write_text(payload, encoding="utf-8")
        v.reset_for_tests()
        v.start()
        assert _member()["fine"] == [] and _member()["recording"] is True
    v.reset_for_tests()
    path.write_text(json.dumps({"schema": v.SCHEMA, "fine": [[1, 2, 3], "x"], "coarse": None}), encoding="utf-8")
    v.start()  # rows of the wrong layout are dropped, not crashed on
    assert _member()["fine"] == []


def test_a_member_that_is_not_recording_reads_the_file_and_says_so(hist):
    _ticks(hist, HOUR0, 300, rss=1000.0)
    v.flush()
    v.reset_for_tests()  # no start(): the liveness thread is off in this process
    m = _member()
    assert m["recording"] is False and m["fine"] and m["fine"][0][COL["t"]] == HOUR0
    assert m["cost"] == {}


def test_nothing_is_recorded_before_start(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    v.tick(now=float(HOUR0))
    v.flush()
    assert not v._path().exists()
    assert _member()["fine"] == [] and _member()["recording"] is False


# --------------------------------------------------------------------------- #
#  The log counter
# --------------------------------------------------------------------------- #
def _emit(name: str, levelno: int, times: int = 1) -> None:
    assert v._HANDLER is not None
    for _ in range(times):
        v._HANDLER.emit(logging.LogRecord(name, levelno, "f.py", 1, "m", None, None))


def test_log_lines_are_counted_per_hour_by_logger_and_level(hist):
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.ingest.fetch", logging.WARNING, 12)
    _emit("src.ingest.fetch", logging.ERROR)
    _emit("src.wiki.drain", logging.INFO, 3)
    _ticks(hist, HOUR0 + 3600, 5, rss=1.0)  # the next hour closes the first
    row = _member()["logs"][0]
    assert row["t"] == HOUR0 and row["lines"] == 16
    assert row["by"] == {"src.ingest.fetch": "e1w12", "src.wiki.drain": "i3"}


def test_the_busiest_loggers_are_named_and_the_rest_summed(hist):
    _ticks(hist, HOUR0, 30, rss=1.0)
    for i in range(v.LOG_LOGGERS_PER_HOUR + 4):
        _emit(f"src.mod{i:02d}", logging.WARNING, 100 - i)
    _emit("src.quiet.a", logging.ERROR)  # one error outranks any number of warnings
    _ticks(hist, HOUR0 + 3600, 5, rss=1.0)
    row = _member()["logs"][0]
    assert len(row["by"]) == v.LOG_LOGGERS_PER_HOUR
    assert "src.quiet.a" in row["by"] and "src.mod00" in row["by"] and "src.mod11" not in row["by"]
    assert row["other_loggers"] == 5 and row["other"].startswith("w")
    assert row["lines"] == sum(100 - i for i in range(v.LOG_LOGGERS_PER_HOUR + 4)) + 1


def test_level_letters_follow_the_numeric_level(hist):
    _ticks(hist, HOUR0, 5, rss=1.0)
    for name, lvl in (("a", 10), ("b", 20), ("c", 30), ("d", 40), ("e", 50), ("f", 25), ("g", 35)):
        _emit(name, lvl)
    _ticks(hist, HOUR0 + 3600, 5, rss=1.0)
    by = _member()["logs"][0]["by"]
    assert by == {"e": "c1", "d": "e1", "g": "w1", "c": "w1", "f": "i1", "b": "i1", "a": "d1"}


def test_distinct_logger_names_are_capped_so_the_table_cannot_grow_without_bound(hist):
    _ticks(hist, HOUR0, 5, rss=1.0)
    for i in range(v._LOG_NAMES_CAP + 50):
        _emit(f"per.request.{i}", logging.WARNING)
    with v._LOG_LOCK:
        names = {n for n, _ in v._HOUR_LOGS}
    assert len(names) <= v._LOG_NAMES_CAP + 1  # the cap, plus the one "other" bucket
    assert ("other", "w") in v._HOUR_LOGS


def test_an_open_hour_survives_a_restart_as_one_row(hist, monkeypatch):
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.x", logging.WARNING, 12)
    v.flush()
    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 1.0})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    v.start()
    _emit("src.x", logging.WARNING, 11)
    v.tick(now=float(HOUR0 + 60))
    v.tick(now=float(HOUR0 + 3600))
    rows = [r for r in _member()["logs"] if r["t"] == HOUR0]
    assert len(rows) == 1 and rows[0]["by"] == {"src.x": "w23"}  # 12 stored + 11 new: counts of two digits survive


def test_the_counter_is_on_the_root_logger_and_comes_back_when_removed(hist):
    root = logging.getLogger()
    assert v._HANDLER in root.handlers
    root.removeHandler(v._HANDLER)
    v.tick(now=float(HOUR0))
    assert v._HANDLER in root.handlers


def test_the_log_counter_never_waits_on_the_history_lock(hist):
    """``logging`` calls emit with the handler's lock held; the history's main lock is held while rows
    fold. If emit took that lock, a thread logging while another folds a row could deadlock with it."""
    done = threading.Event()

    def log_one() -> None:
        _emit("src.deadlock", logging.WARNING)
        done.set()

    with v._LOCK:
        t = threading.Thread(target=log_one)
        t.start()
        assert done.wait(2.0), "emit blocked on the history's main lock"
    t.join(2.0)


def test_the_thread_sample_is_taken_without_the_history_lock(hist, monkeypatch):
    """The minute's thread sample can take 0.3-0.6 s under a GIL-holding burst; while it runs, every
    thread that logs would queue behind the lock if it were held."""
    seen: dict[str, bool] = {}

    def probe(_avail):
        got: list[bool] = []

        def try_lock() -> None:
            ok = v._LOCK.acquire(timeout=1.0)
            got.append(ok)
            if ok:
                v._LOCK.release()

        t = threading.Thread(target=try_lock)
        t.start()
        t.join(2.0)
        seen["free"] = bool(got and got[0])
        return []

    monkeypatch.setattr(v, "_busiest", probe)
    _ticks(hist, HOUR0, 65, rss=1.0)  # a tick crosses the minute and closes it
    assert seen.get("free") is True


# --------------------------------------------------------------------------- #
#  The minutes
# --------------------------------------------------------------------------- #
def test_a_minute_row_names_the_busiest_threads_and_their_cpu_between_snapshots(monkeypatch, tmp_path):
    from src.monitoring import session_hwm

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    snaps = iter(
        [
            [{"tid": 1, "name": "oo-a", "cpu_s": 10.0, "stack": ["x.py:1 f", "y.py:2 g", "z.py:3 h"]},
             {"tid": 2, "name": "oo-b", "cpu_s": 5.0, "stack": ["q.py:1 q"]},
             {"tid": 3, "name": "oo-idle", "waiting": True, "stack": ["threading.py:1 wait"]}],
            [{"tid": 1, "name": "oo-a", "cpu_s": 12.0, "stack": ["x.py:9 f", "y.py:2 g", "z.py:3 h"]},
             {"tid": 2, "name": "oo-b", "cpu_s": 45.0, "stack": ["q.py:7 q"]},
             {"tid": 3, "name": "oo-idle", "waiting": True, "stack": ["threading.py:1 wait"]}],
        ]
    )
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: next(snaps))
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 700.0, "avail": 3000.0})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    v.start()
    try:
        v.tick(now=float(HOUR0))
        v.tick(now=float(HOUR0 + 60))  # closes minute 0: the FIRST snapshot (no baseline yet)
        v.tick(now=float(HOUR0 + 120))  # closes minute 1: the second, a minute of CPU later
        minutes = _member()["minutes"]
    finally:
        v.reset_for_tests()
    assert minutes[0]["busiest"] == []  # nothing to take a difference against yet: no invented ranking
    second = minutes[1]["busiest"]
    assert [b["thread"] for b in second] == ["oo-b", "oo-a"]  # the waiting thread is not "busy"
    assert second[0]["cpu_s"] == 40.0 and second[1]["cpu_s"] == 2.0
    assert second[0]["frames"] == ["q.py:7 q"] and second[1]["frames"] == ["x.py:9 f", "y.py:2 g"]


def test_the_thread_sample_is_skipped_while_memory_is_short(monkeypatch, tmp_path):
    from src.monitoring import session_hwm

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    calls: list[int] = []
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: calls.append(1) or [])
    monkeypatch.setattr(session_hwm, "_pressure_line_mb", lambda total: 600.0)
    import psutil

    class _VM:
        total = 4096 * 1024 * 1024

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())
    assert v._busiest(300.0) is None  # below the line: session_pressure.json already records the threads
    assert calls == []
    assert v._busiest(2000.0) == []  # above it: the sample is taken
    assert calls == [1]


def test_the_minute_table_keeps_the_last_sixty(hist):
    hist["fast"] = {"rss": 1.0}
    for k in range(75):
        v.tick(now=float(HOUR0 + 60 * k))
    minutes = _member()["minutes"]
    assert len(minutes) == v.MINUTE_KEEP
    assert minutes[-1]["t"] == HOUR0 + 60 * 73 and minutes[0]["t"] == HOUR0 + 60 * 14


# --------------------------------------------------------------------------- #
#  Honesty and the budget
# --------------------------------------------------------------------------- #
def test_the_member_does_not_claim_the_minutes_before_a_kill(hist):
    _ticks(hist, HOUR0, 60, rss=1.0)
    v.flush()
    m = _member()
    assert m["tail_in"]["member"] is None and "only record" in m["tail_in"]["why"]
    assert "before a kill are not claimed" in m["caveat"]
    assert m["last_flush_at"] and isinstance(m["last_flush_age_s"], int)
    v.TAIL_IN = {"member": "contention.json", "why": "its 15-second snapshot"}
    try:
        assert _member()["tail_in"] == {"member": "contention.json", "why": "its 15-second snapshot"}
    finally:
        v.TAIL_IN = None


def test_the_member_is_held_to_its_budget_by_dropping_the_oldest_rows(hist):
    hist["fast"] = {"rss": 123.0, "avail": 456.0, "swap": 7.0, "threads": 40.0, "blocks": 99.0}
    for k in range(400):
        v.tick(now=float(HOUR0 + v.FINE_S * k))
    full = _member(max_bytes=10_000_000)
    small = _member(max_bytes=20_000)
    assert len(json.dumps(small, separators=(",", ":"))) <= 20_000
    assert small["dropped_oldest_rows"]["fine"] > 0 and "20000" in small["dropped_why"]
    assert small["fine"][-1] == full["fine"][-1]  # the NEWEST row stays
    assert small["fine"][0][0] > full["fine"][0][0]  # the oldest went
    assert "dropped_oldest_rows" not in full


def test_a_budget_too_small_for_one_row_still_serves_the_newest_row_of_each_table(hist):
    _ticks(hist, HOUR0, 600, rss=1.0)
    m = _member(max_bytes=10)
    assert len(m["fine"]) == 1 and m["fine"][0][0] == m["fine"][-1][0]


def test_the_default_member_for_a_full_history_fits_its_budget(hist, monkeypatch):
    """The whole retention, with a busy logger set: the budget must not cut the 48 hours the member
    exists to show (measured 166 KB raw against a 200 KB budget)."""
    hist["fast"] = {"rss": 1234.0, "avail": 2345.0, "swap": 120.0, "threads": 48.0, "blocks": 23456.0}
    hist["slow"] = {"drive_free": 20000.0, "db": 1700.0, "wal": 180.0, "columnar": 90.0}
    monkeypatch.setattr(
        v, "_busiest",
        lambda _a: [{"thread": f"oo-worker-{i}", "cpu_s": 33.3, "frames": ["src/ingest/fetch_pipeline.py:812 fetch_one", "src/ingest/rss_reader.py:410 parse_entry"]} for i in range(3)],
    )
    names = [f"src.module{i:02d}.sub" for i in range(25)]
    for k in range(v.COARSE_KEEP * 12 + 30):
        if k % 12 == 0:
            for n in names:
                _emit(n, logging.WARNING, 3)
                _emit(n, logging.ERROR)
        v.tick(now=float(HOUR0 + v.FINE_S * k))
    m = _member()
    assert "dropped_oldest_rows" not in m, m.get("dropped_oldest_rows")
    assert len(json.dumps(m, separators=(",", ":"))) <= v.MEMBER_BUDGET_BYTES
    assert len(m["fine"]) >= v.FINE_KEEP - 1 and len(m["coarse"]) >= v.COARSE_KEEP - 1


def test_a_failing_reading_never_raises_into_the_tick_and_the_member_still_serves(hist, monkeypatch):
    def boom():
        raise RuntimeError("psutil fell over")

    monkeypatch.setattr(v, "_fast_readings", boom)
    v.tick(now=float(HOUR0))  # no exception
    assert _member()["recording"] is True


def test_a_flush_that_cannot_write_never_raises(hist, monkeypatch):
    _ticks(hist, HOUR0, 30, rss=1.0)
    monkeypatch.setattr(v.os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")))
    v.flush()  # no exception
    assert _member()["fine"]  # and the in-memory history is intact


def test_the_flush_is_atomic_and_throttled_to_the_interval(hist, monkeypatch):
    path = v._path()
    replaced: list[tuple[str, str]] = []
    real_replace = v.os.replace
    monkeypatch.setattr(v.os, "replace", lambda a, b: replaced.append((str(a), str(b))) or real_replace(a, b))
    v.tick(now=float(HOUR0))  # the first tick writes the file: a new session is on disk at once
    assert replaced == [(str(path.with_suffix(".json.tmp")), str(path))]  # written aside, then swapped in
    assert path.exists() and not path.with_suffix(".json.tmp").exists()
    first = path.stat().st_mtime_ns
    writes: list[int] = []
    real = v.flush
    monkeypatch.setattr(v, "flush", lambda: writes.append(1) or real())
    for k in range(1, 50):
        v.tick(now=float(HOUR0 + 5 * k))
    assert writes == []  # 245 s of ticks: under FLUSH_S, so no write
    assert path.stat().st_mtime_ns == first
    v._LAST_FLUSH = time.monotonic() - v.FLUSH_S - 1  # the interval has passed
    v.tick(now=float(HOUR0 + 300))
    assert writes == [1]


def test_nothing_in_the_member_is_an_article_an_address_or_a_term(hist):
    """Counts, sizes and times: the only strings are timestamps, thread names, code locations and
    logger names -- all identifiers of the app's own code."""
    hist["fast"] = {"rss": 1.0}
    _ticks(hist, HOUR0, 300, rss=1.0)
    _emit("src.demo", logging.WARNING)
    blob = json.dumps(_member())
    assert "http" not in blob and "://" not in blob and "@" not in blob


def test_the_row_survives_a_round_trip_through_an_accumulator(hist):
    _ticks(hist, HOUR0, 300, rss=1000.0, avail=2000.0, swap=5.0, threads=40.0, blocks=9.0)
    v.tick(now=float(HOUR0 + 300))
    row = v._FINE[0]
    assert v._from_row(row).row(row[0]) == row


# --------------------------------------------------------------------------- #
#  The real readings (the tests above inject theirs)
# --------------------------------------------------------------------------- #
def test_the_fast_readings_are_in_the_units_the_columns_say(monkeypatch):
    import psutil

    v.reset_for_tests()
    got = v._fast_readings()
    own = psutil.Process().memory_info().rss / (1024 * 1024)
    assert 0.5 * own < got["rss"] < 2.0 * own  # megabytes, not kilobytes or bytes
    assert 0 < got["avail"] <= psutil.virtual_memory().total / (1024 * 1024)
    assert got["threads"] >= 1 and got["swap"] >= 0
    import sys

    assert abs(got["blocks"] * 1000 - sys.getallocatedblocks()) < 200_000  # thousands of blocks


def test_without_psutil_the_history_keeps_what_needs_none(monkeypatch):
    import sys

    v.reset_for_tests()
    monkeypatch.setitem(sys.modules, "psutil", None)  # an import of it now raises ImportError
    got = v._fast_readings()
    assert "rss" not in got and "avail" not in got and "swap" not in got  # absent, never zero
    assert got["threads"] >= 1 and "blocks" in got


def test_the_slow_readings_are_sizes_in_megabytes_and_the_lowest_free_space(monkeypatch, tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(base))
    v.reset_for_tests()
    (base / "open_omniscience.db").write_bytes(b"\0" * (3 * 1024 * 1024))
    (base / "open_omniscience.db-wal").write_bytes(b"\0" * (7 * 1024 * 1024))
    (base / "analytics.duckdb").write_bytes(b"\0" * (11 * 1024 * 1024))

    class _Usage:
        free = 5 * 1024 * 1024 * 1024

    monkeypatch.setattr(v.shutil, "disk_usage", lambda _p: _Usage())
    got = v._slow_readings(1000.0)
    assert got == {"drive_free": 5120.0, "db": 3.0, "wal": 7.0, "columnar": 11.0}


def test_a_file_that_is_not_there_is_absent_not_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    got = v._slow_readings(1000.0)
    assert "db" not in got and "wal" not in got and "columnar" not in got
    assert "drive_free" in got  # the drive itself can always be read


def test_the_slow_readings_are_taken_once_a_minute_and_repeated_between(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    calls: list[int] = []

    class _Usage:
        free = 1024 * 1024

    monkeypatch.setattr(v.shutil, "disk_usage", lambda _p: calls.append(1) or _Usage())
    first = v._slow_readings(100.0)
    again = v._slow_readings(100.0 + v.SLOW_S - 1)
    assert calls == [1] and again is first  # inside the interval: the same reading, no system call
    v._slow_readings(100.0 + v.SLOW_S)
    assert calls == [1, 1]


def test_the_session_starts_are_kept_to_the_newest_thirty(hist):
    for _ in range(v.SESSIONS_KEEP + 5):
        v.flush()
        v.reset_for_tests()
        v.start()
    assert len(_member()["session_starts"]) == v.SESSIONS_KEEP


def test_the_previous_sessions_tail_is_its_last_thirty_minutes(hist, monkeypatch):
    hist["fast"] = {"rss": 1.0}
    for k in range(50):
        v.tick(now=float(HOUR0 + 60 * k))
    v.flush()
    last_t = v._MINUTES[-1]["t"]
    v.reset_for_tests()
    v.start()
    prev = _member()["previous_session"]["minutes"]
    assert len(prev) == v.PREVIOUS_TAIL_KEEP and prev[-1]["t"] == last_t
