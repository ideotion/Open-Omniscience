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
    monkeypatch.setattr(v, "_busiest", lambda _avail: ([], None))
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
    monkeypatch.setattr(v, "_busiest", lambda _avail: ([], None))
    v.start(now=float(HOUR0 + 450))
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
    monkeypatch.setattr(
        v, "_busiest", lambda _avail: ([{"thread": "oo-wiki-drain", "cpu_s": 40.0, "over_s": 60, "frames": ["a.py:1 f"]}], None)
    )
    _ticks(hist, HOUR0, 300, rss=1000.0)
    v.flush()
    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 1.0})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    v.start(now=float(HOUR0 + 300))
    m = _member()
    (prev,) = m["previous_sessions"]
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
        counted = set(v._HOUR_LOG_NAMES)
    assert len(counted) == v._LOG_NAMES_CAP  # the cap holds for the names that are counted
    assert len(names) == v._LOG_NAMES_CAP + 1  # plus the one overflow bucket, which is not a logger's name
    assert v._HOUR_LOGS[(v._OVERFLOW, "w")] == 50


def test_an_open_hour_survives_a_restart_as_one_row(hist, monkeypatch):
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.x", logging.WARNING, 12)
    v.flush()
    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 1.0})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    v.start(now=float(HOUR0 + 40))
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
        return [], None

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
    # nothing to take a difference against yet: null with the reason, never [] standing for "none was busy"
    assert minutes[0]["busiest"] is None and "first reading of this session" in minutes[0]["busiest_why"]
    second = minutes[1]["busiest"]
    assert "busiest_why" not in minutes[1]
    assert [b["thread"] for b in second] == ["oo-b", "oo-a"]  # the waiting thread is not "busy"
    assert second[0]["cpu_s"] == 40.0 and second[1]["cpu_s"] == 2.0
    assert isinstance(second[0]["over_s"], int) and second[0]["over_s"] >= 0  # the real gap between two calls: a machine's speed
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
    rows, why = v._busiest(300.0)  # below the line: session_pressure.json already records the threads
    assert rows is None and "session_pressure.json" in why
    assert calls == []
    rows, why = v._busiest(2000.0)  # above it: the sample is taken (here no thread has a CPU figure at all)
    assert rows is None and "CPU figure" in why
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
    # and the member does not claim it met a budget it could not meet
    assert m["over_budget_bytes"] > 10 and "could not be held to 10 bytes" in m["dropped_why"]
    assert "over_budget_bytes" not in _member()


_BUSY_THREADS = [
    {
        "thread": f"oo-worker-{i}", "cpu_s": 33.3, "over_s": 60,
        "frames": ["src/ingest/fetch_pipeline.py:812 fetch_one", "src/ingest/rss_reader.py:410 parse_entry"],
    }
    for i in range(3)
]


def _full_history_with_three_tails(hist, monkeypatch, names):
    """The whole retention (48 h of five-minute rows, 14 d of hourly rows, 60 minutes, 7 d of log
    counts for ``names``) AND the tails of the three sessions before this one, each of the
    ``PREVIOUS_TAIL_KEEP`` minutes a tail holds, every minute naming its three busiest threads: the
    heaviest member the recorder can build, and the one the budget is sized against."""
    hist["fast"] = {"rss": 1234.0, "avail": 2345.0, "swap": 120.0, "threads": 48.0, "blocks": 23456.0}
    hist["slow"] = {"drive_free": 20000.0, "db": 1700.0, "wal": 180.0, "columnar": 90.0}
    monkeypatch.setattr(v, "_busiest", lambda _a: ([dict(t) for t in _BUSY_THREADS], None))
    last = 0
    for k in range(v.COARSE_KEEP * 12 + 30):
        if k % 12 == 0:
            for n in names:
                _emit(n, logging.WARNING, 3)
                _emit(n, logging.ERROR)
        last = HOUR0 + v.FINE_S * k
        v.tick(now=float(last))
    for session in range(v.PREVIOUS_SESSIONS_KEEP + 1):  # three that ended, and this one
        base = last + 10_000 * (session + 1)
        for k in range(v.PREVIOUS_TAIL_KEEP + 5):
            v.tick(now=float(base + 60 * k))
        if session < v.PREVIOUS_SESSIONS_KEEP:
            _restart(float(base + 60 * (v.PREVIOUS_TAIL_KEEP + 6)))
    return _member()


@pytest.mark.parametrize(
    "names",
    [
        [f"src.module{i:02d}.sub" for i in range(25)],
        # longer, deeper logger names: the same member with about 2.5 times the log table
        [f"src.ingest.collectors.regional_feed_reader.module{i:02d}.parser" for i in range(25)],
    ],
    ids=["typical-names", "long-names"],
)
def test_the_heaviest_member_fits_its_budget_with_three_previous_tails_and_cuts_nothing(hist, monkeypatch, names):
    """The budget must not cut the 48 hours the member exists to show, nor the tails that say how the
    last sessions died. Measured here (raw JSON): about 158 KB for the history alone, about 212 KB with
    the three tails, about 241 KB with long logger names; ``MEMBER_BUDGET_BYTES`` is sized above the
    last of these, and this test is the check that it stays so."""
    m = _full_history_with_three_tails(hist, monkeypatch, names)
    size = len(json.dumps(m, separators=(",", ":")))
    assert "dropped_oldest_rows" not in m, (size, m.get("dropped_oldest_rows"))
    assert size <= v.MEMBER_BUDGET_BYTES, size
    assert len(m["fine"]) >= v.FINE_KEEP - 1 and len(m["coarse"]) >= v.COARSE_KEEP - 1
    tails = m["previous_sessions"]
    assert len(tails) == v.PREVIOUS_SESSIONS_KEEP
    assert all(len(t["minutes"]) == v.PREVIOUS_TAIL_KEEP for t in tails)


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
    assert "threads" not in got and "swap" not in got  # read once a minute, with the slow group
    slow = v._count_readings()
    assert slow["threads"] >= 1 and slow["swap"] >= 0
    import sys

    assert abs(got["blocks"] * 1000 - sys.getallocatedblocks()) < 200_000  # thousands of blocks


def test_the_count_readings_are_the_kernels_numbers_in_megabytes_and_threads(monkeypatch):
    import psutil

    v.reset_for_tests()

    class _Swap:
        used = 7 * 1024 * 1024

    class _Proc:
        def num_threads(self):
            return 23

    monkeypatch.setattr(psutil, "swap_memory", lambda: _Swap())
    monkeypatch.setattr(v, "_process", lambda: _Proc())
    assert v._count_readings() == {"threads": 23.0, "swap": 7.0}  # swap in megabytes, threads as a count


def test_without_psutil_the_history_keeps_what_needs_none(monkeypatch):
    import sys

    v.reset_for_tests()
    monkeypatch.setitem(sys.modules, "psutil", None)  # an import of it now raises ImportError
    got = v._fast_readings()
    assert "rss" not in got and "avail" not in got  # absent, never zero
    assert "blocks" in got
    counts = v._count_readings()
    assert "swap" not in counts  # absent, never zero
    assert counts["threads"] == float(threading.active_count())  # Python's own count stands in


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
    monkeypatch.setattr(v, "_count_readings", lambda: {"threads": 41.0, "swap": 12.5})
    got = v._slow_readings(1000.0)
    assert got == {
        "threads": 41.0, "swap": 12.5, "drive_free": 5120.0, "db": 3.0, "wal": 7.0, "columnar": 11.0,
    }


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
    v.start(now=float(HOUR0 + 3000))
    prev = _member()["previous_sessions"][-1]["minutes"]
    assert len(prev) == v.PREVIOUS_TAIL_KEEP and prev[-1]["t"] == last_t


# --------------------------------------------------------------------------- #
#  The Opus read of the first version (2026-10-06): each test names the finding it pins
# --------------------------------------------------------------------------- #
def _restart(now: float) -> None:
    """What a new process does: nothing in memory, the file on disk, ``start`` again."""
    v.flush()
    v.reset_for_tests()
    v.start(now=now)


def test_a_re_entered_emit_does_not_deadlock_its_own_thread(hist, monkeypatch, request):
    """B1. The cyclic collector and Python-level signal handlers run between any two bytecodes, so a
    finalizer that logs (SQLAlchemy's pool does) re-enters ``emit`` on the thread that is inside it.
    A plain lock makes that thread wait for itself while it holds the handler's own lock, and every
    other thread that logs then waits behind it. The test's own lock stands in for the module's, of
    the same kind, so a regression fails here rather than hanging every later test."""
    monkeypatch.setattr(v, "_LOG_LOCK", type(v._LOG_LOCK)())
    # a regression leaves a thread holding that private lock; put the module's own back before the
    # recorder's teardown asks for it, or the failure becomes a hang
    request.addfinalizer(monkeypatch.undo)

    class _Names(set):
        reentered = False

        def add(self, item):
            if not _Names.reentered:
                _Names.reentered = True
                _emit("src.finalizer", logging.ERROR)  # a log call made from inside the locked section
            super().add(item)

    monkeypatch.setattr(v, "_HOUR_LOG_NAMES", _Names())
    done = threading.Event()

    def log_it() -> None:
        _emit("src.outer", logging.WARNING)
        done.set()

    t = threading.Thread(target=log_it, daemon=True)
    t.start()
    assert done.wait(3.0), "emit waited for itself"
    assert v._HOUR_LOGS[("src.outer", "w")] == 1 and v._HOUR_LOGS[("src.finalizer", "e")] == 1


def test_two_restarts_inside_one_hour_lose_no_log_count_and_name_no_logger_other(hist):
    """S2. The open hour is kept as raw (logger, level, count) triples. Kept as its display row, the
    quiet loggers' sum came back as a logger NAMED "other" and a real logger of that name was
    overwritten by it, so a crash loop (several restarts an hour) lost lines."""
    _ticks(hist, HOUR0, 30, rss=1.0)
    for i in range(12):
        _emit(f"src.l{i:02d}", logging.WARNING, 10)
    _emit("other", logging.WARNING, 3)  # a logger that really is called "other"
    _restart(float(HOUR0 + 100))
    _restart(float(HOUR0 + 200))
    v.tick(now=float(HOUR0 + 3600))
    (row,) = [r for r in _member()["logs"] if r["t"] == HOUR0]
    assert row["lines"] == 123
    assert len(row["by"]) == v.LOG_LOGGERS_PER_HOUR and "other" not in row["by"]
    assert row["other"] == "w43" and row["other_loggers"] == 5  # l08..l11 and "other": five loggers, 43 lines


def test_a_restored_hour_that_is_over_is_closed_at_start_so_boot_lines_are_not_dated_into_it(hist):
    """S1. The first tick used to close the restored hour, five seconds after the counter was attached,
    so the rest of the boot was added to a row of an hour that ended while the process was down."""
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.old", logging.WARNING, 3)
    later = HOUR0 + 20 * 3600
    _restart(float(later))
    _emit("src.boot", logging.WARNING, 40)  # the rest of the boot, before the first tick
    v.tick(now=float(later + 5))
    v.tick(now=float(later + 3600))
    rows = {r["t"]: r for r in _member()["logs"]}
    assert rows[HOUR0]["by"] == {"src.old": "w3"} and rows[HOUR0]["lines"] == 3
    assert rows[later]["by"] == {"src.boot": "w40"}


def test_the_name_cap_still_holds_after_a_restart(hist):
    _ticks(hist, HOUR0, 30, rss=1.0)
    for i in range(v._LOG_NAMES_CAP):
        _emit(f"n{i}", logging.WARNING)
    _restart(float(HOUR0 + 100))
    _emit("one.more", logging.WARNING)
    assert (v._OVERFLOW, "w") in v._HOUR_LOGS and ("one.more", "w") not in v._HOUR_LOGS


def test_the_open_log_hour_is_in_the_member_of_a_process_that_is_not_recording(hist):
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.x", logging.WARNING, 4)
    v.flush()
    v.reset_for_tests()  # no start(): the liveness thread is off in this process
    m = _member()
    assert m["recording"] is False
    assert m["logs"][-1]["open"] is True and m["logs"][-1]["by"] == {"src.x": "w4"}


def test_stored_log_counts_of_the_wrong_shape_are_dropped():
    raw = [["a", "w", 2], ["b", "x", 1], ["c", "w", 0], ["d", "e", "3"], "junk", ["e", "w"], [1, "w", 2], ["a", "w", 3]]
    assert v._counts_from_triples(raw) == {("a", "w"): 5}  # two valid lines for one key add up
    assert v._counts_from_triples(None) == {} and v._counts_from_triples("x") == {}


def test_a_log_counter_overflow_line_count_is_named_and_is_not_a_logger(hist):
    _ticks(hist, HOUR0, 5, rss=1.0)
    for i in range(v._LOG_NAMES_CAP + 7):
        _emit(f"per.request.{i}", logging.WARNING)
    v.tick(now=float(HOUR0 + 3600))
    row = _member()["logs"][0]
    assert row["past_name_cap"] == 7 and v._OVERFLOW not in row["by"]
    assert row["lines"] == v._LOG_NAMES_CAP + 7
    # the overflow lines are summed with the quiet loggers' lines, not dropped from the row
    assert row["other"] == f"w{v._LOG_NAMES_CAP - v.LOG_LOGGERS_PER_HOUR + 7}"
    assert row["other_loggers"] == v._LOG_NAMES_CAP - v.LOG_LOGGERS_PER_HOUR


# --- the previous sessions' tails (S4) -------------------------------------------------------------
def _run_minutes(box, start: int, minutes: int) -> None:
    box["fast"] = {"rss": 1.0}
    for k in range(minutes):
        v.tick(now=float(start + 60 * k))


def test_the_previous_sessions_tail_survives_one_more_restart(hist):
    """S4. Session B held A's last minutes only in memory, and its first flush wrote ``minutes: []`` over
    them; killed too, the minutes before the first crash were gone."""
    _run_minutes(hist, HOUR0, 40)
    a_end = v._MINUTES[-1]["t"]
    _restart(float(HOUR0 + 4000))  # B starts...
    v.tick(now=float(HOUR0 + 4000))  # ...ticks once (and so flushes at once)...
    _restart(float(HOUR0 + 4100))  # ...and is killed within its first minute: C starts
    (tail,) = _member()["previous_sessions"]
    assert tail["minutes"][-1]["t"] == a_end
    v.flush()
    v.reset_for_tests()  # and a process that does not record shows it as well
    (tail,) = _member()["previous_sessions"]
    assert tail["minutes"][-1]["t"] == a_end


def test_short_sessions_do_not_push_out_the_tail_of_the_one_that_ran_long(hist):
    _run_minutes(hist, HOUR0, 40)
    a_end = v._MINUTES[-1]["t"]
    for k in range(6):  # a crash loop: every session dies within its first minute
        _restart(float(HOUR0 + 4000 + 100 * k))
        v.tick(now=float(HOUR0 + 4000 + 100 * k))
    tails = _member()["previous_sessions"]
    assert len(tails) == 1 and tails[0]["minutes"][-1]["t"] == a_end
    assert all(p["minutes"] for p in v._PREVIOUS)  # a session that wrote no minute adds no tail, not even an empty one


def test_the_tails_of_the_last_three_sessions_that_wrote_minutes_are_kept(hist):
    ends = []
    for k in range(5):
        _run_minutes(hist, HOUR0 + 10_000 * k, v.PREVIOUS_TAIL_MIN + 4)  # long enough to be a tail worth keeping
        ends.append(v._MINUTES[-1]["t"])
        _restart(float(HOUR0 + 10_000 * k + 5000))
    tails = _member()["previous_sessions"]
    assert [t["minutes"][-1]["t"] for t in tails] == ends[-v.PREVIOUS_SESSIONS_KEEP:]


def _ends_of_tails() -> list[int]:
    return [t["minutes"][-1]["t"] for t in _member()["previous_sessions"]]


def _session(box, start: int, rows: int) -> int:
    """A session that leaves ``rows`` minute rows in the file, ended by a restart; the time its last row is at."""
    _run_minutes(box, start, rows + 1)  # the last minute is still open at the end
    end = v._MINUTES[-1]["t"]
    assert len(v._MINUTES) == rows
    _restart(float(start + 60 * (rows + 3)))
    return end


def test_a_tail_of_four_minutes_is_short_and_one_of_five_is_not(hist):
    """N1. The file is written at a session's first tick and then every five minutes, so a session needs
    about five minutes to leave a tail worth keeping over one that ran long: the line is five rows."""
    assert v.PREVIOUS_TAIL_MIN == 5
    long1, long2, long3 = (_session(hist, HOUR0 + 10_000 * k, 30) for k in range(3))
    assert _ends_of_tails() == [long1, long2, long3]
    _session(hist, HOUR0 + 40_000, v.PREVIOUS_TAIL_MIN - 1)  # four rows: short, evicted at once
    assert _ends_of_tails() == [long1, long2, long3]
    five = _session(hist, HOUR0 + 50_000, v.PREVIOUS_TAIL_MIN)  # five rows: not short, the oldest long one goes
    assert _ends_of_tails() == [long2, long3, five]


def test_a_crash_loop_of_short_sessions_keeps_the_tail_of_the_session_that_ran_long(hist):
    """N1. Each of these sessions lived long enough to write a few minutes (three rows) and not five."""
    long_end = _session(hist, HOUR0, 30)
    shorts = [_session(hist, HOUR0 + 10_000 * (k + 1), 3) for k in range(6)]
    assert _ends_of_tails() == [long_end, shorts[-2], shorts[-1]]  # the newest two short ones, never the long one's place


def test_short_tails_are_evicted_oldest_first_and_a_long_one_only_when_none_is_short(hist):
    short1 = _session(hist, HOUR0, 2)
    long1 = _session(hist, HOUR0 + 10_000, 30)
    short2 = _session(hist, HOUR0 + 20_000, 2)
    assert _ends_of_tails() == [short1, long1, short2]
    short3 = _session(hist, HOUR0 + 30_000, 2)  # four tails: the OLDEST short one goes
    assert _ends_of_tails() == [long1, short2, short3]
    long2 = _session(hist, HOUR0 + 40_000, 30)  # the oldest of the two short ones goes
    assert _ends_of_tails() == [long1, short3, long2]


# --- which threads were busy (S3) --------------------------------------------------------------------
@pytest.fixture
def threads(monkeypatch, tmp_path):
    from src.monitoring import session_hwm

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    box: dict[str, list] = {"snap": []}
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [dict(e) for e in box["snap"]])
    yield box
    v.reset_for_tests()


def _t(tid: int, cpu: float | None, name: str = "oo-w") -> dict:
    entry: dict = {"tid": tid, "name": name, "stack": ["x.py:1 f"]}
    if cpu is None:
        entry["waiting"] = True
    else:
        entry["cpu_s"] = cpu
    return entry


def test_the_cpu_after_a_memory_short_stretch_is_not_charged_to_one_minute(threads, monkeypatch):
    """S3a. A thread burning 55 s a minute through ten minutes of short memory was reported as 605 s in
    one minute: the skipped minutes kept their old baseline."""
    import psutil

    from src.monitoring import session_hwm

    class _VM:
        total = 4096 * 1024 * 1024

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())
    monkeypatch.setattr(session_hwm, "_pressure_line_mb", lambda total: 600.0)
    threads["snap"] = [_t(1, 0.0)]
    assert v._busiest(2000.0, now=0.0)[0] is None  # the first reading: a baseline, nothing to compare
    for minute in range(1, 11):  # memory is short: no sample at all
        rows, why = v._busiest(100.0, now=60.0 * minute)
        assert rows is None and "memory was short" in why
    threads["snap"] = [_t(1, 605.0)]
    rows, why = v._busiest(2000.0, now=660.0)  # memory is back; the baseline is ten minutes old
    assert rows is None and "earlier reading" in why  # not used: it would charge ten minutes to one
    threads["snap"] = [_t(1, 660.0)]
    (row,) = v._busiest(2000.0, now=720.0)[0]
    assert row["cpu_s"] == 55.0 and row["over_s"] == 60


def test_a_thread_that_was_waiting_at_one_reading_keeps_its_earlier_baseline(threads):
    """S3b. A pool worker parked in its queue at the sample instant has no CPU figure that minute; its
    last one is carried, and the span the difference covers is said."""
    threads["snap"] = [_t(1, 10.0)]
    assert v._busiest(None, now=0.0)[0] is None
    threads["snap"] = [_t(1, None)]  # waiting at the second reading
    assert v._busiest(None, now=60.0)[0] is None
    threads["snap"] = [_t(1, 68.0)]
    (row,) = v._busiest(None, now=120.0)[0]
    assert row["cpu_s"] == 58.0 and row["over_s"] == 120  # two minutes of work, and it says two minutes


def test_a_thread_with_no_earlier_reading_is_not_named_and_a_gone_thread_is_forgotten(threads):
    threads["snap"] = [_t(1, 5.0)]
    v._busiest(None, now=0.0)
    threads["snap"] = [_t(1, 6.0), _t(2, 50.0)]  # thread 2 is new: it has nothing to be compared with
    rows, _ = v._busiest(None, now=60.0)
    assert [r["thread"] for r in rows] == ["oo-w"] and rows[0]["cpu_s"] == 1.0
    threads["snap"] = [_t(2, 52.0)]  # thread 1 is gone
    v._busiest(None, now=120.0)
    assert 1 not in v._LAST_CPU and v._LAST_CPU[2][0] == 52.0


def test_threads_compared_with_none_burning_is_an_empty_list_not_null(threads):
    threads["snap"] = [_t(1, 5.0)]
    v._busiest(None, now=0.0)
    rows, why = v._busiest(None, now=60.0)  # compared, unchanged: that IS the fact "none was busy"
    assert rows == [] and why is None


def test_the_real_thread_strings_reach_the_member_with_no_path_address_or_term(monkeypatch, tmp_path):
    """S8. The one way real strings (thread names, frames) reach the member is the thread sample, and the
    other privacy test never took it (it mocked it away): this takes the real one."""
    import os

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    stop = threading.Event()

    def burn() -> None:
        while not stop.is_set():
            sum(range(20_000))

    worker = threading.Thread(target=burn, name="oo-privacy-probe", daemon=True)
    worker.start()
    rows = None
    try:
        v._busiest(None)  # the baseline
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not rows:
            time.sleep(0.25)
            rows, _why = v._busiest(None)
    finally:
        stop.set()
        worker.join(2.0)
    if not rows:
        pytest.skip("the kernel's per-thread CPU times are not readable here")
    blob = json.dumps(rows)
    for forbidden in (str(tmp_path), os.path.expanduser("~"), "site-packages", "/usr/lib", "://", "@"):
        assert forbidden not in blob, forbidden
    assert all(len(r["frames"]) <= 2 for r in rows)


# --- clock steps (S7) ---------------------------------------------------------------------------------
def test_a_held_clock_step_counts_one_step_however_many_ticks_it_lasts(hist):
    """S7. ``clock_stepped_back`` counted ticks spent behind (719 for one step)."""
    _ticks(hist, HOUR0 + 600, 300, rss=500.0)  # the open bucket is HOUR0 + 600
    for k in range(20):  # the clock is five minutes behind: inside what a hold bounds
        v.tick(now=float(HOUR0 + 300 + 5 * k))
    m = _member()
    assert m["clock_stepped_back"] == 1 and len(m["clock_steps"]) == 1
    # measured from the clock's own last reading (the last tick, 895 s), not from the bucket's start
    assert m["clock_steps"][0] == {"at": v._iso(HOUR0 + 300), "was": v._iso(HOUR0 + 895), "back_s": 595}
    times = [r[COL["t"]] for r in m["fine"]]
    assert times == sorted(times) and len(times) == len(set(times))
    v.tick(now=float(HOUR0 + 1200))  # the clock catches up, and a second step back is a second step
    v.tick(now=float(HOUR0 + 1000))
    assert _member()["clock_stepped_back"] == 2


def test_a_big_clock_step_back_closes_what_is_open_instead_of_piling_an_hour_into_one_bucket(hist):
    """S7. One step back of an hour gave one five-minute row of 721 ticks, no minute row and no log hour
    closing for that hour, and a file written while the clock was ahead pinned every tick until then."""
    _ticks(hist, HOUR0 + 7200, 300, rss=500.0)  # 60 ticks
    _emit("src.before", logging.WARNING, 5)
    _ticks(hist, HOUR0, 300, rss=900.0)  # the clock is now two hours behind
    m = _member()
    assert [r[COL["n"]] for r in m["fine"]] == [60, 60]  # never more than a bucket holds
    assert [r[COL["t"]] for r in m["fine"]] == [HOUR0 + 7200, HOUR0]  # in the order written, at the clock's time
    assert [r[COL["t"]] for r in m["coarse"]] == [HOUR0 + 7200, HOUR0]
    assert m["clock_stepped_back"] == 1
    assert m["clock_steps"] == [{"at": v._iso(HOUR0), "was": v._iso(HOUR0 + 7495), "back_s": 7495}]
    assert all(r["n"] == 12 for r in m["minutes"]) and len(m["minutes"]) == 9  # a minute holds 12 ticks, always
    closed = [r for r in m["logs"] if r["t"] == HOUR0 + 7200]
    assert closed and "open" not in closed[0] and closed[0]["lines"] == 5  # that hour closed, with its lines


def test_a_file_written_while_the_clock_was_ahead_does_not_pin_this_session(hist):
    _ticks(hist, HOUR0 + 86_400, 60, rss=1.0)  # a day ahead
    _restart(float(HOUR0))
    _ticks(hist, HOUR0, 600, rss=2.0)
    m = _member()
    assert [r[COL["n"]] for r in m["fine"]] == [12, 60, 60]  # the restored bucket as it stood, then two new ones
    assert [r[COL["t"]] for r in m["fine"]] == [HOUR0 + 86_400, HOUR0, HOUR0 + 300]
    assert m["clock_stepped_back"] == 1


def test_the_minute_table_never_repeats_or_reorders_when_the_clock_steps_back_a_little(hist):
    for t in (600, 660, 720, 650, 655, 780, 840):
        v.tick(now=float(HOUR0 + t))
    times = [r["t"] for r in _member()["minutes"]]
    assert times == sorted(set(times)) and len(times) >= 3


# --- the rest of the survivors and the nits ------------------------------------------------------------
def test_a_minute_row_reports_the_peak_memory_and_the_lowest_available_of_its_minute(hist):
    for i, (rss, avail, swap, threads_) in enumerate(((1000.0, 3000.0, 5.0, 40.0), (1400.0, 2500.0, 9.0, 47.0), (1200.0, 2800.0, 7.0, 44.0))):
        hist["fast"] = {"rss": rss, "avail": avail, "swap": swap, "threads": threads_}
        v.tick(now=float(HOUR0 + 5 * i))
    hist["fast"] = {"rss": 1.0}
    v.tick(now=float(HOUR0 + 60))  # closes the minute
    (row,) = [r for r in _member()["minutes"] if r["t"] == HOUR0]
    assert (row["n"], row["rss_max"], row["avail_min"], row["swap_max"], row["threads_max"]) == (3, 1400, 2500, 9, 47)


def test_a_gap_of_three_buckets_is_a_gap_and_one_missing_bucket_is_not(hist):
    _ticks(hist, HOUR0, 300, rss=1.0)
    _ticks(hist, HOUR0 + 600, 300, rss=1.0)  # one bucket missing between: the rows are two buckets apart
    _ticks(hist, HOUR0 + 1500, 300, rss=1.0)  # two missing: three buckets apart
    assert [g["from"] for g in _member()["gaps"]] == [v._iso(HOUR0 + 900)]


def test_a_failed_flush_is_retried_in_a_minute_not_on_every_tick(hist, monkeypatch):
    attempts: list[int] = []

    def full(*_a, **_k):
        attempts.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(v.os, "replace", full)
    for k in range(10):
        v.tick(now=float(HOUR0 + 5 * k))
    assert len(attempts) == 1 and _member()["errors"]["flush_failures"] == 1
    remaining = v.FLUSH_S - (time.monotonic() - v._LAST_FLUSH)
    assert v.FLUSH_RETRY_S - 2 < remaining <= v.FLUSH_RETRY_S  # the next try is a retry interval away
    v._LAST_FLUSH -= v.FLUSH_RETRY_S + 1  # that interval passes
    v.tick(now=float(HOUR0 + 60))
    assert len(attempts) == 2


def test_a_data_drive_that_vanishes_reads_absent_not_its_last_value(monkeypatch, tmp_path):
    """S5. ``data_dir()`` raises when the marked data drive is unplugged; the drive and size columns kept
    repeating their last value (a vanished drive read as 19 GB free) and the tick was lost."""
    base = tmp_path / "data"
    base.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(base))
    (base / "open_omniscience.db").write_bytes(b"\0" * (2 * 1024 * 1024))
    v.reset_for_tests()
    first = v._slow_readings(1000.0)
    assert first["db"] == 2.0 and "drive_free" in first

    def gone():
        raise RuntimeError("the data drive is not there")

    monkeypatch.setattr(v, "data_dir", gone)
    again = v._slow_readings(1000.0 + v.SLOW_S)  # no exception, and nothing carried over
    assert "db" not in again and "drive_free" not in again and again["threads"] >= 1
    assert v._LAST_SLOW == 1000.0 + v.SLOW_S  # retried in a minute, not on every tick


def test_the_costs_say_cpu_and_wall_apart(monkeypatch):
    """S6. The wall time of a tick under busy threads is the interpreter lock's queue, not the work: the
    member said 532 ms where the CPU was 1 ms, which is the mistake the lessons entry records."""

    real_time, real_monotonic = time.time, time.monotonic

    class _Clock:
        cpu = 0.0
        wall = 0.0
        time = staticmethod(real_time)
        monotonic = staticmethod(real_monotonic)

        def thread_time(self):
            self.cpu += 0.001
            return self.cpu

        def perf_counter(self):
            self.wall += 0.05
            return self.wall

    v.reset_for_tests()
    monkeypatch.setattr(v, "time", _Clock())
    v._note_cost("tick", 0.0, 0.0)
    assert v._COST["tick_cpu_ms_last"] == 1.0 and v._COST["tick_wall_ms_last"] == 50.0
    v._note_cost("tick", 0.0, 0.0)  # a second reading of the same kind: the maximum is kept apart
    assert v._COST["tick_wall_ms_max"] == 100.0 and v._COST["tick_cpu_ms_max"] == 2.0 and v._COST["tick_wall_ms_last"] == 100.0


def test_the_member_carries_both_cost_kinds_and_says_what_they_mean(hist):
    _ticks(hist, HOUR0, 30, rss=1.0)
    v.flush()
    m = _member()
    for key in ("tick_cpu_ms_last", "tick_wall_ms_last", "tick_cpu_ms_max", "flush_cpu_ms_last", "flush_wall_ms_last"):
        assert key in m["cost"], key
    assert "tick_ms_last" not in m["cost"]
    assert "waiting for the interpreter" in m["cost_note"]


def test_the_state_document_takes_the_main_lock_before_the_log_lock(hist, monkeypatch):
    """N5. ``tick`` takes ``_LOCK`` then ``_LOG_LOCK``; a document built the other way round could show the
    old hour's counts twice when a tick closed the hour between the two."""
    held: list[bool] = []

    class _Spy:
        def __enter__(self):
            held.append(v._LOCK._is_owned())

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(v, "_LOG_LOCK", _Spy())
    v._state_doc()
    assert held == [True]


# --- failures show in the vitals themselves; the cuts and caps that had no test ------------------------
def test_a_failed_flush_is_counted_and_named_in_the_member_without_a_path(hist, monkeypatch):
    """A failing disk used to show only in a debug log. The reason is kept, the message (which names a
    path under the data folder) is not."""

    def full(*_a, **_k):
        raise OSError(28, "No space left on device", "/home/someone/Open-Omniscience/data/diagnostics/x.tmp")

    monkeypatch.setattr(v.os, "replace", full)
    _ticks(hist, HOUR0, 10, rss=1.0)
    errors = _member()["errors"]
    assert errors["flush_failures"] == 1
    assert errors["last_flush_error"]["error"] == "OSError: No space left on device"
    assert "someone" not in json.dumps(_member()) and "x.tmp" not in json.dumps(_member())
    assert _member()["errors"].get("tick_failures") is None  # a failed write is not a failed tick


def test_a_failed_tick_is_counted_by_type_only(hist, monkeypatch):
    def boom():
        raise RuntimeError("psutil fell over at /private/place")

    monkeypatch.setattr(v, "_fast_readings", boom)
    v.tick(now=float(HOUR0))
    v.tick(now=float(HOUR0 + 5))
    errors = _member()["errors"]
    assert errors["tick_failures"] == 2 and errors["last_tick_error"]["error"] == "RuntimeError"
    assert "private" not in json.dumps(_member())
    v.reset_for_tests()
    assert _member()["errors"] == {}


def test_the_hourly_table_keeps_its_newest_336_rows(hist):
    hist["fast"] = {"rss": 1.0}
    for k in range(v.COARSE_KEEP + 25):
        v.tick(now=float(HOUR0 + v.COARSE_S * k))
    assert len(v._COARSE) == v.COARSE_KEEP
    # an hour closes when the bucket AFTER its last one closes, so hour 358 is the newest closed of 361
    assert v._COARSE[-1][0] == HOUR0 + v.COARSE_S * (v.COARSE_KEEP + 22)
    assert v._COARSE[0][0] == HOUR0 + v.COARSE_S * 23  # 359 closed, the oldest 23 went


def test_the_log_table_keeps_its_newest_168_hours(hist):
    _ticks(hist, HOUR0, 5, rss=1.0)
    for k in range(v.LOG_KEEP + 12):
        _emit("src.x", logging.WARNING)
        v.tick(now=float(HOUR0 + v.COARSE_S * (k + 1)))
    assert len(v._LOGS) == v.LOG_KEEP
    assert v._LOGS[-1]["t"] == HOUR0 + v.COARSE_S * (v.LOG_KEEP + 11)
    assert v._LOGS[0]["t"] == HOUR0 + v.COARSE_S * 12


def test_only_the_newest_fifty_gaps_are_listed(hist):
    hist["fast"] = {"rss": 1.0}
    for k in range(v.GAPS_KEEP + 20):  # a row every three buckets: a gap between each pair
        v.tick(now=float(HOUR0 + 3 * v.FINE_S * k))
    gaps = _member(max_bytes=10_000_000)["gaps"]
    assert len(gaps) == v.GAPS_KEEP
    last_row = HOUR0 + 3 * v.FINE_S * (v.GAPS_KEEP + 19)
    assert gaps[-1]["to"] == v._iso(last_row)  # the newest gap is the one kept


def test_a_minute_names_at_most_three_threads_the_busiest_first(threads):
    threads["snap"] = [_t(i, 0.0, f"oo-{i}") for i in range(1, 6)]
    v._busiest(None, now=0.0)
    threads["snap"] = [_t(i, float(i * 10), f"oo-{i}") for i in range(1, 6)]
    rows, _ = v._busiest(None, now=60.0)
    assert [r["thread"] for r in rows] == ["oo-5", "oo-4", "oo-3"] and len(rows) == v.BUSIEST_THREADS


def test_the_slow_group_rides_the_tick_once_a_minute(monkeypatch, tmp_path):
    """The tick takes the drive, the sizes, the thread count and the swap from the slow group at
    most once a minute and repeats them between: 24 ticks over two minutes make two reads."""
    base = tmp_path / "data"
    base.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(base))
    (base / "open_omniscience.db").write_bytes(b"\0" * (4 * 1024 * 1024))
    v.reset_for_tests()
    reads: list[int] = []

    class _Usage:
        free = 9 * 1024 * 1024

    monkeypatch.setattr(v.shutil, "disk_usage", lambda _p: reads.append(1) or _Usage())
    monkeypatch.setattr(v, "_fast_readings", lambda: {"rss": 1.0})
    monkeypatch.setattr(v, "_busiest", lambda _avail: ([], None))
    real_time, real_perf, real_cpu = time.time, time.perf_counter, time.thread_time
    clock = [1000.0]

    class _Clock:
        time = staticmethod(real_time)
        perf_counter = staticmethod(real_perf)
        thread_time = staticmethod(real_cpu)

        @staticmethod
        def monotonic():
            return clock[0]

    monkeypatch.setattr(v, "time", _Clock())
    v.start(now=float(HOUR0))
    try:
        for k in range(24):
            clock[0] = 1000.0 + 5 * k
            v.tick(now=float(HOUR0 + 5 * k))
        row = _member()["fine"][-1]
    finally:
        v.reset_for_tests()
    assert len(reads) == 2  # at 1000 s and at 1060 s of the monotonic clock
    assert row[COL["db_max"]] == 4 and row[COL["drive_free_min"]] == 9 and row[COL["threads_max"]] is not None


# --------------------------------------------------------------------------- #
#  The coordinator's check of the second head (2026-10-06)
# --------------------------------------------------------------------------- #
def _fine_times() -> list[int]:
    return [r[COL["t"]] for r in _member()["fine"]]


@pytest.mark.parametrize("phase", [0, 295])
@pytest.mark.parametrize(("back", "rebased"), [(600, False), (601, True)])
def test_the_hold_edge_is_exact_and_does_not_depend_on_where_in_the_bucket_the_last_tick_fell(hist, phase, back, rebased):
    """S2. A step back that leaves the clock 600 s behind the open bucket's start is held, and one
    second more starts a new history; the bucket's start is bucket-aligned, so the second at which the
    last tick fell (the first or the last tick of the bucket) changes nothing, and ``back_s`` says the
    real step from the last tick. The literals are the point: a constant moved to 900 or 3,600 s fails."""
    assert v.CLOCK_HOLD_S == 600
    t0 = HOUR0 + 3600  # the open bucket's start
    v.tick(now=float(t0 + phase), mono=1000.0)
    v.tick(now=float(t0 - back), mono=1005.0)
    m = _member()
    (step,) = m["clock_steps"]
    assert step["back_s"] == back + phase and step["was"] == v._iso(t0 + phase) and "kept_open" not in step
    if rebased:
        assert _fine_times() == [t0, t0 - 900]  # closed, and a new bucket at the clock's own time
        assert [r[COL["n"]] for r in m["fine"]] == [1, 1]
    else:
        assert _fine_times() == [t0] and m["fine"][0][COL["n"]] == 2  # both ticks in the one open bucket


def test_the_worst_held_step_pins_at_most_the_ticks_the_constant_says(hist):
    """S2. The last tick at the end of its bucket and a step to the edge: the open bucket holds its own
    60 ticks and every tick until the clock is past the bucket again, which is the bound the constant
    states ((CLOCK_HOLD_S + 2 * FINE_S) / 5) and not the 180 an earlier comment claimed."""
    t0 = HOUR0 + 3600
    for t in range(t0, t0 + 300, 5):
        v.tick(now=float(t))
    for t in range(t0 - 600, t0 + 300, 5):
        v.tick(now=float(t))
    (row,) = _member()["fine"]
    assert row[COL["n"]] == (v.CLOCK_HOLD_S + 2 * v.FINE_S) // 5 == 240


def test_a_clock_that_keeps_flapping_starts_a_new_history_at_most_once_per_interval(hist):
    """S2. Every second tick lands two hours behind the one before; with a rebase on each, the fine table
    gained a row per tick and pushed the 48 hours out within a couple of hours."""
    ahead, behind = HOUR0 + 100_000, HOUR0 + 100_000 - 7200
    mono = 5000.0
    for _ in range(100):  # 200 ticks, 1,000 s of the monotonic clock
        v.tick(now=float(ahead), mono=mono)
        mono += 5
        v.tick(now=float(behind), mono=mono)
        mono += 5
    m = _member()
    allowed = int(1000 // v.REBASE_MIN_GAP_S) + 1
    assert len(m["fine"]) <= 2 * allowed + 2, len(m["fine"])  # not 200
    steps = m["clock_steps"]
    assert len(steps) <= v.CLOCK_STEPS_KEEP
    assert sum(1 for s in steps if "kept_open" not in s) <= allowed
    assert any(s.get("kept_open") is True for s in steps)
    # the rows are still in the order they were written and none holds more than a bucket plus the hold
    assert all(r[COL["n"]] <= (v.CLOCK_HOLD_S + v.FINE_S) // 5 * 2 for r in m["fine"])


def test_a_big_step_after_the_interval_starts_a_new_history_again(hist):
    t0 = HOUR0 + 100_000
    v.tick(now=float(t0), mono=5000.0)
    v.tick(now=float(t0 - 7200), mono=5005.0)  # a new history
    v.tick(now=float(t0 + 100), mono=5010.0)
    v.tick(now=float(t0 - 7200), mono=5020.0)  # too soon: held
    v.tick(now=float(t0 - 7200), mono=5005.0 + v.REBASE_MIN_GAP_S)  # the interval has passed: a new history
    steps = _member()["clock_steps"]
    assert ["kept_open" in s for s in steps] == [False, True, False]


def test_a_platform_with_no_thread_clock_still_records_and_reports_its_cpu_cost_as_null(hist, monkeypatch):
    """S4. ``time.thread_time`` raises where the platform has no per-thread clock; it used to fail every
    tick before the reading was taken, so the recorder recorded nothing at all."""
    def no_clock():
        raise OSError("no per-thread CPU clock")

    monkeypatch.setattr(time, "thread_time", no_clock)
    _ticks(hist, HOUR0, 600, rss=5.0)
    v.flush()
    m = _member()
    assert m["errors"] == {} and [r[COL["n"]] for r in m["fine"]] == [60, 60]
    cost = m["cost"]
    assert cost["tick_cpu_ms_last"] is None and "tick_cpu_ms_max" not in cost
    assert cost["flush_cpu_ms_last"] is None and cost["tick_wall_ms_last"] >= 0


def test_a_file_of_another_layout_is_not_trusted(hist):
    """N3. The layout changed in development (raw log triples, tails, clock steps); a file of the first
    layout is read as no history, and the member names the layout it writes."""
    _ticks(hist, HOUR0, 600, rss=1.0)
    v.flush()
    doc = json.loads(v._path().read_text(encoding="utf-8"))
    assert doc["schema"] == v.SCHEMA == _member()["schema"] != "oo-vitals-1"
    doc["schema"] = "oo-vitals-1"
    v._path().write_text(json.dumps(doc), encoding="utf-8")
    v.reset_for_tests()
    v.start(now=float(HOUR0 + 7200))
    m = _member()
    assert m["fine"] == [] and "previous_sessions" not in m


def _tail(n: int) -> dict:
    return {"last_flush_at": "2026-10-06T00:00:00Z", "minutes": [{"t": i, "n": 12, "rss_max": 1234} for i in range(n)]}


def _enc(value) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def test_the_earlier_tails_are_the_last_table_cut_and_the_shortest_tail_goes_first():
    """S1. The tails say how the last sessions died and they are small: the history's tables give up rows
    first, and only a member whose every other table is down to its newest row gives up a tail."""
    def member() -> dict:
        return {
            "fine": [[1000 + i, 60, 1234] for i in range(80)],
            "coarse": [[i, 600, 1234] for i in range(10)],
            "logs": [], "minutes": [],
            "previous_sessions": [_tail(30), _tail(20), _tail(30)],
        }

    full = _enc(member())
    cut_fine = v._fit(member(), full - 200)
    assert set(cut_fine["dropped_oldest_rows"]) <= {"fine", "coarse"}
    assert [len(t["minutes"]) for t in cut_fine["previous_sessions"]] == [30, 20, 30]  # no tail went
    floor = member()
    floor["fine"], floor["coarse"] = floor["fine"][-1:], floor["coarse"][-1:]
    # two long tails and the notes that say what was cut (about 200 bytes), and not the 20-row tail (about 700)
    only_long_ones = _enc({**floor, "previous_sessions": [_tail(30), _tail(30)]}) + 300
    tight = v._fit(member(), only_long_ones)
    assert len(tight["fine"]) == 1 and len(tight["coarse"]) == 1
    assert [len(t["minutes"]) for t in tight["previous_sessions"]] == [30, 30]  # the 20-row one went, not the oldest
    assert tight["dropped_oldest_rows"]["previous_sessions"] == 1 and "shortest went first" in tight["dropped_why"]
    assert "over_budget_bytes" not in tight
    one = v._fit(member(), 10)  # nothing fits: every table to its newest row, and the newest tail stays
    assert len(one["previous_sessions"]) == 1 and one["previous_sessions"][0]["minutes"] == _tail(30)["minutes"]
    assert "over_budget_bytes" in one


# --------------------------------------------------------------------------- #
#  The Opus read of the second head (2026-10-06): each test names the finding it pins
# --------------------------------------------------------------------------- #
def test_a_finalizer_that_logs_while_the_state_is_written_fails_neither_the_flush_nor_the_member(hist, monkeypatch):
    """Opus 2. The counts were walked in Python under the re-entrant lock, so a line logged from inside
    the walk (a finalizer, as in B1) added a key to the dictionary being iterated: 'dictionary changed
    size', a failed flush or a member with ``available: false``. The copy is C-level and the walk is
    over the copy."""
    _ticks(hist, HOUR0, 30, rss=1.0)
    for i in range(5):
        _emit(f"src.l{i}", logging.WARNING)
    real_sorted = sorted
    fired: list[int] = []

    def sorted_with_a_late_log(iterable, **kw):
        def walk():
            for i, item in enumerate(iterable):
                if i == 2:
                    fired.append(1)
                    _emit("src.logged.from.the.walk", logging.ERROR)  # a NEW key, while the walk is under way
                yield item
        return real_sorted(walk(), **kw)

    monkeypatch.setattr(v, "sorted", sorted_with_a_late_log, raising=False)
    doc = v._state_doc()
    assert fired and len(doc["open_logs_counts"]) == 5  # the document is the copy; the late line is in the next one
    assert v._HOUR_LOGS[("src.logged.from.the.walk", "e")] == 1
    fired.clear()
    assert _member()["available"] is True and v._ERRORS.get("flush_failures") is None


def test_the_lines_of_a_boot_that_ends_before_its_first_tick_are_dated_and_kept(hist, monkeypatch):
    """Opus 4. A start closes a restored hour that is over and sets the open hour to none; a session that
    ended before its first tick then wrote ``open_logs_t: 0``, and the next start dropped its counts: the
    failing boots of a crash loop were exactly the ones that recorded nothing."""
    later = HOUR0 + 5 * 3600
    monkeypatch.setattr(time, "time", lambda: float(later + 7))
    _emit("src.boot", logging.ERROR, 7)  # logged by the fixture's session, which never ticks
    assert v._HOUR_LOGS_T == 0
    _restart(float(later + 20))  # flushed (dated now) and started again in the same hour
    assert v._HOUR_LOGS[("src.boot", "e")] == 7 and later == v._HOUR_LOGS_T
    m = _member()
    assert [(r["t"], r["lines"]) for r in m["logs"]] == [(later, 7)]


@pytest.mark.parametrize(
    ("figures", "memory_snapshots", "earlier", "now", "expect"),
    [
        ([], None, None, 0.0, "CPU figure"),  # nothing running: an idle process, not "the first minute"
        ([("a", 5.0)], None, "none", 0.0, "first reading of this session"),
        ([("a", 6.0)], None, "old", 400.0, "more than 150 s old"),  # a held minute, or memory was short
        ([("b", 6.0)], None, "other", 60.0, "new or waiting"),  # every thread with a figure is new
    ],
    ids=["idle", "first", "stale", "new-threads"],
)
def test_a_minute_with_no_comparison_says_which_of_four_facts_it_is(threads, figures, memory_snapshots, earlier, now, expect):
    """Opus 3. An idle app and a clock hold both read 'the first minute, or the first after memory was
    short', a cause that did not happen, every minute of an idle night."""
    if earlier in ("old", "other"):
        threads["snap"] = [_t(1, 5.0, "a")]
        v._busiest(None, now=0.0)
    threads["snap"] = [{**_t(i + 1, cpu, name)} for i, (name, cpu) in enumerate(figures)] if figures else [_t(1, None)]
    if earlier == "other":
        threads["snap"] = [_t(9, 6.0, "b")]
    rows, why = v._busiest(None, now=now)
    assert rows is None and expect in why


def test_a_gap_next_to_a_recorded_clock_step_says_so_and_a_plain_gap_does_not(hist):
    """Opus 6. A rebase and the clock's return forward read as time the process was down."""
    _ticks(hist, HOUR0 + 7200, 300, rss=1.0)
    _ticks(hist, HOUR0, 300, rss=1.0)  # the clock steps two hours back: a recorded step
    _ticks(hist, HOUR0 + 7500, 300, rss=1.0)  # ...and the correction forward, which is not recorded
    gaps = _member()["gaps"]
    assert gaps and gaps[-1].get("clock_step") is True
    v.reset_for_tests()
    v._path().unlink(missing_ok=True)  # a history of its own: nothing recorded a step
    v.start()
    _ticks(hist, HOUR0, 300, rss=1.0)
    _ticks(hist, HOUR0 + 3000, 300, rss=1.0)  # a plain stop, no step
    (gap,) = _member()["gaps"]
    assert "clock_step" not in gap and gap["seconds"] > 0


def test_a_hold_a_rebase_and_a_small_step_straight_after_are_three_steps(hist):
    """Opus nit 2. A rebase left the hold flag set, so the small step that followed was not counted."""
    t = HOUR0 + 100_000
    v.tick(now=float(t), mono=100.0)
    v.tick(now=float(t - 300), mono=105.0)  # small: held, step 1
    v.tick(now=float(t - 8000), mono=500.0)  # big, and the interval has passed: a new history, step 2
    v.tick(now=float(t - 8400), mono=505.0)  # small, straight after: step 3
    assert _member()["clock_stepped_back"] == 3


def test_the_clock_steps_survive_a_restart_and_are_trimmed_to_their_limit(hist):
    """Opus 7 (M36, M18)."""
    t = HOUR0 + 100_000
    for k in range(v.CLOCK_STEPS_KEEP + 5):  # held steps: forward 1,000 s, then back 400 s (past a bucket edge)
        v.tick(now=float(t + 1000 * k), mono=5000.0 + k)
        v.tick(now=float(t + 1000 * k - 400), mono=5000.0 + k + 0.5)
    m = _member()
    assert m["clock_stepped_back"] == v.CLOCK_STEPS_KEEP + 5 and len(m["clock_steps"]) == v.CLOCK_STEPS_KEEP
    before = m["clock_steps"]
    _restart(float(t + 10 ** 6))
    again = _member()
    assert again["clock_steps"] == before and again["clock_stepped_back"] == m["clock_stepped_back"]


def test_a_rebase_dates_the_lines_after_the_step_into_the_new_hour(hist):
    """Opus 7 (M31). The log hour was kept open across a rebase, so the lines after the step were counted
    into an hour two hours ahead, which stayed open until the clock caught up."""
    t = HOUR0 + 7200
    v.tick(now=float(t), mono=100.0)
    _emit("src.before", logging.WARNING, 5)
    v.tick(now=float(HOUR0 + 60), mono=1000.0)  # two hours back: a new history
    _emit("src.after", logging.WARNING, 4)
    rows = {r["t"]: r for r in _member()["logs"]}
    assert rows[t]["lines"] == 5 and "open" not in rows[t]  # closed at the step, with only its own lines
    assert rows[HOUR0]["by"] == {"src.after": "w4"} and rows[HOUR0]["open"] is True


def test_the_name_cap_counts_real_names_after_a_restart_not_the_overflow_bucket(hist):
    """Opus 7 (M9)."""
    _ticks(hist, HOUR0, 30, rss=1.0)
    for i in range(v._LOG_NAMES_CAP + 3):
        _emit(f"n{i}", logging.WARNING)
    assert (v._OVERFLOW, "w") in v._HOUR_LOGS
    _restart(float(HOUR0 + 100))
    assert v._OVERFLOW not in v._HOUR_LOG_NAMES and len(v._HOUR_LOG_NAMES) == v._LOG_NAMES_CAP


def test_a_restored_hour_exactly_one_hour_behind_the_clock_is_closed_at_start(hist):
    """Opus 7 (M11): the hour is over as soon as the clock is in the next one."""
    _ticks(hist, HOUR0, 30, rss=1.0)
    _emit("src.old", logging.WARNING, 3)
    _restart(float(HOUR0 + 3600 + 30))
    assert v._HOUR_LOGS == {} and [r["t"] for r in v._LOGS] == [HOUR0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("previous_sessions", None), ("previous_sessions", 5), ("previous_sessions", [{"minutes": None}]),
        ("clock_steps", None), ("clock_steps", 3), ("open_logs_counts", 7), ("open_logs_t", "soon"),
        ("open_logs_t", [1]), ("minutes", None), ("logs", None), ("session_starts", None),
        ("clock_stepped_back", "x"), ("open_fine", 5), ("open_coarse", "x"), ("coarse", 4),
    ],
)
def test_one_wrong_typed_field_costs_that_field_and_never_the_history(hist, field, value):
    """Opus nit 4. One bad field in an otherwise valid file discarded the 14 days and the next flush wrote
    the empty history over them."""
    _ticks(hist, HOUR0, 900, rss=77.0)
    _emit("src.x", logging.WARNING, 2)
    v.flush()
    doc = json.loads(v._path().read_text(encoding="utf-8"))
    doc[field] = value
    v._path().write_text(json.dumps(doc), encoding="utf-8")
    kept = len(doc["fine"])
    v.reset_for_tests()
    assert _member()["recording"] is False  # the reader that does not record shows it too
    v.start(now=float(HOUR0 + 1000))
    m = _member()
    assert m["available"] is True and len(m["fine"]) >= kept and m["fine"][0][COL["rss_max"]] == 77


def test_the_notes_a_cut_adds_are_part_of_what_the_budget_measures():
    """Opus nit 3. ``dropped_oldest_rows`` and ``dropped_why`` were added after the size check, so the
    member could weigh up to 118 bytes more than the number it said it was held to."""
    for budget in range(2000, 2600, 7):
        member = {"fine": [[1000 + i, 60, 1234, 5678] for i in range(400)], "coarse": [], "logs": [], "minutes": []}
        out = v._fit(member, budget)
        assert _enc(out) <= budget or "over_budget_bytes" in out, budget
