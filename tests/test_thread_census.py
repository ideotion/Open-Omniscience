"""The native thread census: kernel threads Python did not start, by kernel name, within a stated byte budget."""

from __future__ import annotations

import json
import os
import threading

import pytest

from src.monitoring import session_hwm as hwm

linux_only = pytest.mark.skipif(not os.path.isdir("/proc/self/task"), reason="needs /proc/self/task")


@pytest.fixture(autouse=True)
def _reset():
    hwm.reset_for_tests()
    yield
    hwm.reset_for_tests()


def _fake_proc(tmp_path, comms, monkeypatch):
    """A /proc/self/task with one directory per thread: tid -> comm."""
    for tid, comm in comms.items():
        d = tmp_path / str(tid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
    monkeypatch.setattr(hwm, "_CENSUS_TASKS", str(tmp_path))


class _T:
    def __init__(self, native_id):
        self.native_id = native_id


@linux_only
def test_real_process_counts_add_up():
    got = hwm.thread_census()
    assert got["os_threads"] >= got["python_threads"] >= 1
    assert set(got) == {"os_threads", "python_threads", "non_python", "other_comms"}


def test_python_threads_are_excluded_and_their_names_are_never_read(tmp_path, monkeypatch):
    _fake_proc(tmp_path, {10: "oo-osm-secretco", 11: "duckdb", 12: "duckdb", 13: "OMP worker"}, monkeypatch)
    monkeypatch.setattr(threading, "enumerate", lambda: [_T(10)])
    got = hwm.thread_census()
    assert got["os_threads"] == 4 and got["python_threads"] == 1
    assert got["non_python"] == {"duckdb": 2, "OMP worker": 1}
    assert "oo-osm-secretco" not in json.dumps(got)


def test_python_thread_name_never_reaches_the_record_real_thread():
    ready, done = threading.Event(), threading.Event()
    t = threading.Thread(target=lambda: (ready.set(), done.wait(5)), name="oo-osm-NEVERSHOWN")
    t.start()
    ready.wait(5)
    try:
        assert "NEVERSHOWN" not in json.dumps(hwm.thread_census())
    finally:
        done.set()
        t.join()


def test_unavailable_carries_a_reason_never_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(hwm, "_CENSUS_TASKS", str(tmp_path / "nope"))
    assert hwm.thread_census() == {"unavailable": "no /proc/self/task on this system"}


def test_a_thread_that_ended_between_listing_and_read_is_skipped(tmp_path, monkeypatch):
    _fake_proc(tmp_path, {20: "duckdb"}, monkeypatch)
    (tmp_path / "21").mkdir()  # listed, no comm file: it ended
    monkeypatch.setattr(threading, "enumerate", lambda: [])
    got = hwm.thread_census()
    assert got["non_python"] == {"duckdb": 1}


def test_worst_case_member_fits_the_budget_by_construction(tmp_path, monkeypatch):
    comms = {1000 + i: f"{chr(97 + i % 26)}{i:013d}zz"[:15] for i in range(300)}
    _fake_proc(tmp_path, comms, monkeypatch)
    monkeypatch.setattr(threading, "enumerate", lambda: [])
    got = hwm.thread_census()
    assert len(json.dumps({hwm._CENSUS_KEY: got}, separators=(",", ":"))) <= hwm.CENSUS_BYTES
    assert got["other_comms"] > 0 and got["other_comms"] + len(got["non_python"]) == 300


def test_most_numerous_names_are_kept_first(tmp_path, monkeypatch):
    comms = dict.fromkeys(range(1, 6), "pool") | {50: "lone"}
    _fake_proc(tmp_path, comms, monkeypatch)
    monkeypatch.setattr(threading, "enumerate", lambda: [])
    got = hwm.thread_census()
    assert list(got["non_python"]) == ["pool", "lone"] and got["non_python"]["pool"] == 5


def test_observe_records_it_at_most_once_per_interval(monkeypatch):
    calls = []
    monkeypatch.setattr(hwm, "thread_census", lambda: calls.append(1) or {"os_threads": 3, "python_threads": 2, "non_python": {}, "other_comms": 0})
    hwm.observe(may_snapshot_threads=True)
    hwm.observe(may_snapshot_threads=True)
    assert len(calls) == 1 and hwm.current()["last_thread_census"]["os_threads"] == 3
    hwm.observe()  # not the liveness thread: never takes one
    hwm.reset_for_tests()
    hwm.observe()
    assert len(calls) == 1 and "last_thread_census" not in hwm.current()
