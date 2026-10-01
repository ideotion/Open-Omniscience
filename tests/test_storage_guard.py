"""The storage guard: pause collection loudly before a pinned WAL or a full drive.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics of 16 instances (2026-09-30, ranks 1, 2, 6): the corpus ``-wal`` reached 18.7
to 42.9 GB on six machines against a 64 MiB resting limit, the data drive filled on three, and
one machine logged no successful pass for 35 hours (every pass failing on the same full drive).
``src/scheduler/storage_guard.py`` is the stop. These tests pin its ladder the way
``test_memory_guard.py`` pins the memory guard's -- injected readings, a fake clock, nothing
sampled from the machine running the suite -- plus one end-to-end case against a REAL SQLite
file with a real pinned reader, because the whole design is a claim about what SQLite does.
"""

from __future__ import annotations

import errno
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError, PendingRollbackError

from src.database import pool_watch
from src.scheduler import runner, storage_guard
from src.scheduler.settings import SchedulerSettings
from src.scheduler.storage_guard import (
    DRAIN_EVERY_S,
    ERROR_HOLD_S,
    GIB,
    MIB,
    OVERRIDE_FLOOR_MIN_BYTES,
    StorageGuard,
    disk_reserve_bytes,
    is_disk_full,
    override_floor_bytes,
    wal_high_bytes,
)
from tests.js_source_helper import python_function_source


@pytest.fixture(autouse=True)
def _guard_enabled_for_these_tests(monkeypatch):
    """conftest.py switches the guard off for the suite; this file is its own, and feeds it
    injected readings, never the real drive."""
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def _guard(clock=None, **kw):
    kw.setdefault("trip_after", 2)
    kw.setdefault("resume_after", 2)
    return StorageGuard(clock=clock or Clock(), **kw)


#: A machine with a 10 GiB corpus on a 500 GiB drive: wal_high = 1 GiB, reserve = 10 GB.
_CORPUS = 10 * GIB
_TOTAL = 500 * GIB
_FREE_OK = 300 * GIB


def _feed(g, *, wal=0, free=_FREE_OK, corpus=_CORPUS, total=_TOTAL, n=1):
    for _ in range(n):
        g.observe(wal_bytes=wal, corpus_bytes=corpus, disk_free_bytes=free, disk_total_bytes=total)
    return g


# --------------------------------------------------------------------------- #
#  sizing: each number is derived from the machine and says what it protects
# --------------------------------------------------------------------------- #
def test_wal_high_is_a_tenth_of_the_corpus_between_the_floor_and_the_ceiling(monkeypatch):
    monkeypatch.delenv("OO_WAL_HIGH_MB", raising=False)
    # the field's measured range: corpus 6.7 to 42.4 GB, free 18.8 to 449.8 GB
    assert wal_high_bytes(6_700_000_000, 18_800_000_000) == 670_000_000  # 10% of corpus
    assert wal_high_bytes(42_400_000_000, 449_800_000_000) == 2 * GIB  # the ceiling
    assert wal_high_bytes(1 * MIB, 500 * GIB) == 512 * MIB  # the floor: healthy bursts
    assert wal_high_bytes(200 * GIB, 5000 * GIB) == 2 * GIB


def test_wal_high_never_takes_more_than_a_tenth_of_what_is_left_on_the_drive(monkeypatch):
    monkeypatch.delenv("OO_WAL_HIGH_MB", raising=False)
    assert wal_high_bytes(40 * GIB, 8 * GIB) == int(8 * GIB * 0.10)
    assert wal_high_bytes(40 * GIB, 12 * GIB) == int(12 * GIB * 0.10)
    # ...but never below the absolute minimum, so a tiny drive cannot make a healthy WAL fire
    assert wal_high_bytes(40 * GIB, 100 * MIB) == 128 * MIB


def test_unreadable_figures_fall_back_to_the_floor_not_to_zero(monkeypatch):
    monkeypatch.delenv("OO_WAL_HIGH_MB", raising=False)
    assert wal_high_bytes(None, None) == 512 * MIB
    assert disk_reserve_bytes(None) == 1 * GIB


def test_disk_reserve_is_the_larger_of_a_gib_and_two_percent_of_the_drive(monkeypatch):
    monkeypatch.delenv("OO_DISK_RESERVE_MB", raising=False)
    assert disk_reserve_bytes(20 * GIB) == 1 * GIB
    assert disk_reserve_bytes(500 * GIB) == int(500 * GIB * 0.02)


def test_the_two_operator_overrides_win(monkeypatch):
    monkeypatch.setenv("OO_WAL_HIGH_MB", "300")
    monkeypatch.setenv("OO_DISK_RESERVE_MB", "2048")
    assert wal_high_bytes(40 * GIB, 500 * GIB) == 300 * MIB
    assert disk_reserve_bytes(500 * GIB) == 2048 * MIB
    monkeypatch.setenv("OO_WAL_HIGH_MB", "garbage")
    assert wal_high_bytes(6_700_000_000, 500 * GIB) == 670_000_000


# --------------------------------------------------------------------------- #
#  is_disk_full: every shape the failure arrives in
# --------------------------------------------------------------------------- #
def test_is_disk_full_recognises_each_shape_and_nothing_else():
    assert is_disk_full(OSError(errno.ENOSPC, "No space left on device"))
    assert is_disk_full(sqlite3.OperationalError("database or disk is full"))
    wrapped = OperationalError("INSERT ...", {}, sqlite3.OperationalError("database or disk is full"))
    assert is_disk_full(wrapped)
    # the PendingRollbackError every later statement raises carries the ORIGINAL in its text
    pend = PendingRollbackError(
        "This Session's transaction has been rolled back due to a previous exception during "
        "flush. Original exception was: (sqlite3.OperationalError) database or disk is full"
    )
    assert is_disk_full(pend)
    try:
        try:
            raise sqlite3.OperationalError("database or disk is full")
        except sqlite3.OperationalError as inner:
            raise RuntimeError("pass failed") from inner
    except RuntimeError as outer:
        assert is_disk_full(outer), "the cause chain is walked"
    assert not is_disk_full(sqlite3.OperationalError("database is locked"))
    assert not is_disk_full(ValueError("boom"))
    assert not is_disk_full(None)


def test_a_real_sqlite_full_error_is_recognised(tmp_path):
    """Not a string we made up: SQLite's own SQLITE_FULL, forced with max_page_count."""
    c = sqlite3.connect(tmp_path / "full.db")
    c.execute("CREATE TABLE t(b BLOB)")
    c.execute("PRAGMA max_page_count=8")
    with pytest.raises(sqlite3.OperationalError) as ei:
        for _ in range(200):
            c.execute("INSERT INTO t VALUES (?)", (b"x" * 4000,))
    c.close()
    assert is_disk_full(ei.value), str(ei.value)


# --------------------------------------------------------------------------- #
#  the latches
# --------------------------------------------------------------------------- #
def test_one_brushed_sample_never_pauses_collection():
    g = _feed(_guard(), wal=2 * GIB)
    assert g.admit() is None
    _feed(g, wal=0)
    _feed(g, wal=2 * GIB)
    assert g.admit() is None, "an over-limit sample followed by a healthy one resets the count"


def test_the_wal_latch_trips_after_consecutive_samples_and_resumes_with_margin():
    g = _feed(_guard(), wal=2 * GIB, n=2)
    assert g.admit() == "wal" and g.phase() == "paused-wal-pinned" and g.engaged
    # just under the limit is NOT recovery: resume needs half of it (a reset is zero)
    _feed(g, wal=int(0.9 * GIB), n=5)
    assert g.engaged, "hysteresis: a WAL hovering under the limit must not flap"
    _feed(g, wal=int(0.4 * GIB), n=2)
    assert g.admit() is None and g.phase() is None


def test_the_disk_latch_trips_below_the_reserve_and_resumes_at_one_and_a_half_times():
    reserve = int(_TOTAL * 0.02)
    g = _feed(_guard(), free=reserve - MIB, n=2)
    assert g.admit() == "disk" and g.phase() == "paused-low-disk"
    _feed(g, free=int(reserve * 1.2), n=6)
    assert g.engaged, "between the reserve and 1.5x the reserve the pause holds"
    _feed(g, free=int(reserve * 1.6), n=2)
    assert not g.engaged


def test_disk_is_the_more_severe_kind_and_both_latches_release_independently():
    reserve = int(_TOTAL * 0.02)
    g = _feed(_guard(), wal=2 * GIB, free=reserve - MIB, n=2)
    assert g.kind() == "disk"
    assert g.state()["kinds"] == ["disk", "wal"]
    _feed(g, wal=2 * GIB, free=_FREE_OK, n=2)  # disk recovers, WAL still pinned
    assert g.kind() == "wal"


def test_a_missing_reading_counts_for_nothing_in_either_direction():
    g = _guard()
    for _ in range(5):
        g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert not g.engaged, "an unreadable figure never trips the guard"
    _feed(g, wal=2 * GIB, n=2)
    assert g.engaged
    for _ in range(5):
        g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert g.engaged, "and never reads as recovery either"
    assert g.state()["readings_available"] is False


def test_the_guard_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    g = _feed(_guard(), wal=50 * GIB, free=0, n=5)
    assert g.admit() is None and g.phase() is None
    g.note_disk_full("x")
    assert g.admit() is None


def test_episode_accounting_counts_engagements_time_and_the_peak():
    clock = Clock()
    g = _feed(_guard(clock), wal=2 * GIB, n=2)
    clock.advance(30)
    _feed(g, wal=3 * GIB)
    clock.advance(30)
    _feed(g, wal=0, n=2)
    st = g.state()
    assert st["engaged"] is False and st["engagements"] == 1
    assert st["total_engaged_s"] == pytest.approx(60.0, abs=1.0)
    g2 = _feed(_guard(clock), wal=2 * GIB, n=2)
    _feed(g2, wal=3 * GIB)
    assert g2.state()["peak_wal_bytes_while_engaged"] == 3 * GIB


# --------------------------------------------------------------------------- #
#  a write that FAILED for want of space
# --------------------------------------------------------------------------- #
def test_a_disk_full_error_latches_at_once_and_holds_even_when_free_looks_healthy():
    clock = Clock()
    g = _guard(clock)
    _feed(g, free=_FREE_OK)
    assert g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass") is True
    assert g.kind() == "disk", "no waiting for the next sample"
    st = g.state()
    assert st["disk_full_events"] == 1 and st["last_disk_full"]["disk_free_bytes"] == _FREE_OK
    # a quota can refuse writes while statvfs says "free": healthy samples inside the hold
    # do not release, so collection cannot flap at pass cadence
    _feed(g, free=_FREE_OK, n=5)
    assert g.engaged
    clock.advance(ERROR_HOLD_S + 1)
    _feed(g, free=_FREE_OK, n=2)
    assert not g.engaged


def test_an_unrelated_error_is_not_a_full_drive():
    g = _guard()
    assert g.note_error(ValueError("nope"), "collect pass") is False
    assert not g.engaged


def test_the_engine_error_hook_latches_the_guard_on_a_real_sqlite_full(tmp_path):
    """The hook in ``src/database/session.py`` closes the gap between the failed write and the
    supervisor's next sample. Driven with SQLite's own SQLITE_FULL on a throwaway engine."""
    import src.database.session as session_mod

    eng = create_engine(f"sqlite:///{tmp_path / 'f.db'}", future=True)
    event.listen(eng, "handle_error", session_mod._storage_guard_on_disk_full)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(b BLOB)")
        c.exec_driver_sql("PRAGMA max_page_count=8")
    with pytest.raises(OperationalError), eng.begin() as c:
        for _ in range(200):
            c.exec_driver_sql("INSERT INTO t VALUES (?)", (b"x" * 4000,))
    eng.dispose()
    assert storage_guard.storage_guard.kind() == "disk"
    assert storage_guard.storage_guard.state()["disk_full_events"] >= 1


def test_the_error_hook_ignores_other_errors(tmp_path):
    import src.database.session as session_mod

    eng = create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True)
    event.listen(eng, "handle_error", session_mod._storage_guard_on_disk_full)
    with pytest.raises(OperationalError), eng.connect() as c:
        c.exec_driver_sql("SELECT * FROM no_such_table")
    eng.dispose()
    assert storage_guard.storage_guard.kind() is None


def test_reset_is_a_retry_not_an_override():
    g = _feed(_guard(), wal=2 * GIB, n=2)
    assert g.engaged
    g.reset(reason="operator")
    assert not g.engaged
    _feed(g, wal=2 * GIB)
    assert not g.engaged, "a single fresh sample is not yet a trip"
    _feed(g, wal=2 * GIB)
    assert g.engaged, "the still-pinned WAL re-engages after fresh over-limit samples"


# --------------------------------------------------------------------------- #
#  the drain and the pin report
# --------------------------------------------------------------------------- #
def test_the_drain_runs_only_while_engaged_and_at_most_every_ten_seconds():
    clock = Clock()
    calls = []

    def drain():
        calls.append(clock())
        return {"busy": 0, "wal_bytes_before": 5, "wal_bytes_after": 0}

    g = _guard(clock, drain_fn=drain)
    assert g.drain_if_due() is None and calls == [], "nothing to drain while healthy"
    _feed(g, wal=2 * GIB, n=2)
    assert g.drain_if_due() is not None
    assert g.drain_if_due() is None, "rate limited"
    clock.advance(DRAIN_EVERY_S + 0.1)
    assert g.drain_if_due() is not None
    assert len(calls) == 2
    assert g.state()["drains"] == 2 and g.state()["last_drain"]["busy"] == 0


def test_a_busy_drain_names_the_holders_at_most_once_a_minute(monkeypatch):
    clock = Clock()
    reports = []
    monkeypatch.setattr(
        storage_guard,
        "_pin_report",
        lambda drain: reports.append(drain) or {"holders": [], "instrument": "attached"},
    )
    g = _guard(clock, drain_fn=lambda: {"busy": 1, "wal_bytes_before": 9, "wal_bytes_after": 9})
    _feed(g, wal=2 * GIB, n=2)
    for _ in range(4):
        g.drain_if_due()
        clock.advance(DRAIN_EVERY_S + 0.1)
    assert len(reports) == 1, "four busy drains inside a minute produce ONE report"
    clock.advance(storage_guard.PIN_REPORT_EVERY_S)
    g.drain_if_due()
    assert len(reports) == 2
    assert g.state(detail=True)["last_pin_report"] is not None


def test_a_gate_busy_skip_is_reported_as_pinned_not_as_success():
    g = _guard(drain_fn=lambda: {"skipped": "gate busy", "detail": "x", "waited_s": 30.0})
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    assert g.state()["last_drain"]["skipped"] == "gate busy"
    assert g.state()["last_drain"]["busy"] is None


def test_a_drain_that_raises_never_kills_the_supervisor():
    def boom():
        raise RuntimeError("no")

    g = _guard(drain_fn=boom)
    _feed(g, wal=2 * GIB, n=2)
    assert g.drain_if_due() is None
    assert g.state()["last_drain"]["ran"] is False


def test_the_drain_never_runs_while_an_exclusive_operation_owns_the_machine(monkeypatch):
    """An import or a restore owns the machine: a drain opens connections to the live corpus
    and must not do so between a restore's dispose and its file swap. Nothing is stamped, so the
    drain runs at once when the operation ends."""
    calls = []
    g = _guard(drain_fn=lambda: calls.append(1) or {"busy": 0})
    _feed(g, wal=2 * GIB, n=2)
    monkeypatch.setattr(runner, "owns_the_machine", lambda: True)
    assert g.drain_if_due() is None and calls == []
    monkeypatch.setattr(runner, "owns_the_machine", lambda: False)
    assert g.drain_if_due() is not None and calls == [1]


def test_the_drain_holds_a_corpus_lease_so_a_restore_waits_for_it():
    from src.database.corpus_lease import active_leases

    seen = []
    g = _guard(drain_fn=lambda: seen.append(active_leases()) or {"busy": 0})
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    assert seen == [["storage-guard-drain"]]
    assert active_leases() == [], "and it lets go"


def test_a_drive_only_pause_drains_only_a_log_big_enough_to_give_space_back():
    """Below the smallest log the guard itself calls large, a reset frees next to nothing and
    logs a record every ten seconds onto a nearly full drive."""
    clock = Clock()
    calls = []
    g = _guard(clock, drain_fn=lambda: calls.append(1) or {"busy": 0})
    _feed(g, free=MIB, wal=MIB, n=2)
    assert g.kind() == "disk" and g.drain_if_due() is None and calls == []
    clock.advance(DRAIN_EVERY_S + 1)
    _feed(g, free=MIB, wal=storage_guard.WAL_ABSOLUTE_MIN_BYTES, n=1)
    assert g.drain_if_due() is not None and calls == [1]


def test_with_the_checkpoint_switched_off_the_drain_says_so(monkeypatch):
    """OO_WAL_CHECKPOINT=0 makes the drain a no-op by the operator's own switch: the state says
    so, instead of reading as a drain that failed."""
    monkeypatch.setenv("OO_WAL_CHECKPOINT", "0")
    g = _guard(drain_fn=lambda: None)
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    assert g.state()["last_drain"]["checkpoint_disabled"] is True
    monkeypatch.delenv("OO_WAL_CHECKPOINT")
    g2 = _guard(drain_fn=lambda: None)
    _feed(g2, wal=2 * GIB, n=2)
    g2.drain_if_due()
    assert g2.state()["last_drain"]["checkpoint_disabled"] is False


def test_a_gate_busy_skip_and_a_busy_truncate_are_logged_as_different_facts(caplog, monkeypatch):
    monkeypatch.setattr(storage_guard, "_pin_report", lambda d: {"holders": [], "instrument": "attached"})
    caplog.set_level("WARNING", logger="scheduler.storage_guard")
    g = _guard(drain_fn=lambda: {"busy": 1, "skipped": None})
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    assert "TRUNCATE is busy" in caplog.text and "write gate stayed busy" not in caplog.text
    caplog.clear()
    g = _guard(drain_fn=lambda: {"skipped": "gate busy", "detail": "x", "waited_s": 30.0})
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    assert "write gate stayed busy" in caplog.text and "TRUNCATE is busy" not in caplog.text


def test_the_pin_report_names_at_most_the_stated_holders_with_the_stated_stack_depth(monkeypatch):
    rows = [{"ident": 100 + i, "thread": f"t{i}", "age_s": 100.0 - i} for i in range(12)]
    asked = {}

    def stacks_for(idents, *, depth=12):
        asked["idents"], asked["depth"] = list(idents), depth
        return {i: ["frame"] for i in idents}

    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(pool_watch, "checked_out", lambda: rows)
    monkeypatch.setattr(pool_watch, "stacks_for", stacks_for)
    rep = storage_guard._pin_report({"busy": 1})
    assert rep["checkouts"] == 12
    assert len(rep["holders"]) == storage_guard.PIN_HOLDERS_MAX
    assert asked["depth"] == storage_guard.PIN_STACK_DEPTH
    assert [h["thread"] for h in rep["holders"]] == ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7"]


def test_a_disk_full_error_is_logged_even_when_the_wal_latch_is_already_engaged(caplog):
    caplog.set_level("WARNING", logger="scheduler.storage_guard")
    g = _feed(_guard(), wal=2 * GIB, n=2)
    assert g.kind() == "wal"
    caplog.clear()
    g.note_disk_full("database or disk is full")
    assert "a write failed for want of space" in caplog.text
    assert g.state()["kinds"] == ["disk", "wal"]


def test_a_disabled_guard_takes_no_reading_at_all(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    reads = []
    g = _guard(readings_fn=lambda: reads.append(1) or {})
    assert g.poll() is False
    g.poll_and_drain_unsupervised()
    assert reads == [], "OO_STORAGE_GUARD=0 means no stat, no glob and no statvfs either"


# --------------------------------------------------------------------------- #
#  what the state says (plain words, numbers apart, a stated method)
# --------------------------------------------------------------------------- #
def test_the_state_carries_frames_and_numbers_apart_and_says_it_resumes_by_itself():
    g = _feed(_guard(), wal=2 * GIB, n=2)
    st = g.state()
    (note,) = st["notes"]
    assert note["kind"] == "wal" and note["frame"] == storage_guard.FRAME_WAL
    assert set(note["vars"]) == {"size", "limit"} and note["vars"]["size"] == 2 * GIB
    assert "resumes by itself" in st["reason"]
    assert "{size}" not in st["reason"], "the English reason is rendered; the frame is not"
    assert "no table is read" in st["method"].lower()
    assert "history" not in st, "the six-hour history rides the bundle, never the polled payload"
    assert len(g.state(detail=True)["history"]) == 1


def test_the_polled_state_omits_the_pin_report_and_the_bundle_carries_it(monkeypatch):
    monkeypatch.setattr(
        storage_guard, "_pin_report", lambda d: {"holders": [{"thread": "x", "age_s": 1.0, "stack": ["a"]}]}
    )
    g = _guard(drain_fn=lambda: {"busy": 1})
    _feed(g, wal=2 * GIB, n=2)
    g.drain_if_due()
    polled = g.state()
    assert "last_pin_report" not in polled and polled["has_pin_report"] is True
    assert g.state(detail=True)["last_pin_report"]["holders"][0]["thread"] == "x"


def test_a_full_disk_write_error_on_a_drive_with_room_gets_its_own_sentence():
    """A quota can refuse writes while the free figure is healthy: "only 300 GB is free" about
    a healthy 300 GB would contradict itself and hide the real release rule (a hold, then
    healthy samples)."""
    g = _feed(_guard(), free=_FREE_OK)
    g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass")
    (note,) = g.state()["notes"]
    assert note["kind"] == "disk" and note["frame"] == storage_guard.FRAME_DISK_ERROR
    assert "short hold" in note["frame"] and "{resume}" not in note["frame"]
    g2 = _feed(_guard(), free=MIB, n=2)  # a measured shortage keeps the plain frame
    assert g2.state()["notes"][0]["frame"] == storage_guard.FRAME_DISK


def test_an_error_before_the_first_sample_still_renders_a_sentence():
    g = _guard()
    g.note_disk_full("database or disk is full")
    st = g.state()
    assert st["engaged"] and st["reason"] and "{free}" not in st["reason"]
    assert "?" in st["reason"], "an unmeasured figure reads '?', never a fabricated number"


def test_sizes_read_the_same_in_the_log_and_on_the_page():
    """The page writes binary steps with MB/GB labels; a log line that said 2.1 GB for the same
    figure would read as two different limits."""
    assert storage_guard._size_text(2 * GIB) == "2.0 GB"
    assert storage_guard._size_text(512 * MIB) == "512 MB"
    assert storage_guard._size_text(1536 * MIB) == "1.5 GB"
    assert storage_guard._size_text(None) == "?"
    assert storage_guard._size_text(0) == "0 B"


def test_a_healthy_guard_says_nothing_is_wrong():
    st = _feed(_guard()).state()
    assert st["engaged"] is False and st["notes"] == [] and st["reason"] is None
    assert st["thresholds"]["wal_high_bytes"] == wal_high_bytes(_CORPUS, _FREE_OK)


def test_history_is_one_sample_a_minute():
    clock = Clock()
    g = _guard(clock)
    for _ in range(10):
        _feed(g)
        clock.advance(10)
    assert len(g.state(detail=True)["history"]) == 2


# --------------------------------------------------------------------------- #
#  the consumers: pass wind-down, the loop, the lane, off-peak maintenance
# --------------------------------------------------------------------------- #
def _engaged(kind="wal"):
    """An engaged guard whose own readings keep saying so (the loop polls it itself when no
    supervisor runs); ``g.fake`` is the mutable reading a test flips to healthy."""
    fake = {"wal_bytes": 2 * GIB if kind == "wal" else 0, "disk_free_bytes": _FREE_OK if kind == "wal" else MIB}

    def readings():
        return {"corpus_bytes": _CORPUS, "disk_total_bytes": _TOTAL, "lane_wal_bytes": {}, **fake}

    g = _guard(readings_fn=readings, drain_fn=lambda: {"busy": 1, "skipped": None})
    g.fake = fake
    g.poll()
    g.poll()
    assert g.engaged
    return g


def test_the_pass_wind_down_refuses_new_sources_with_a_named_reason(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("wal"))
    wind = runner._PassWindDown(budget_s=0, max_sources=0)
    assert wind.admit() == "storage_wal"
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("disk"))
    assert wind.admit() == "storage_disk"


def test_an_explicit_stop_outranks_the_storage_reason(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("wal"))
    wind = runner._PassWindDown(budget_s=0, max_sources=0, should_stop=lambda: True)
    assert wind.admit() == "stopping"


def test_the_storage_reason_has_no_forward_progress_floor(monkeypatch):
    """Unlike a budget wind-down, the FIRST source is not admitted either: one more source on
    a full drive is the failure this exists to stop."""
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("disk"))
    wind = runner._PassWindDown(budget_s=3600, max_sources=10)
    assert wind.admit() == "storage_disk"


def test_a_healthy_guard_admits(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _guard())
    wind = runner._PassWindDown(budget_s=3600, max_sources=10)
    assert wind.admit() is None


def test_the_loop_pauses_in_a_named_phase_and_resumes_by_itself(monkeypatch):
    g = _engaged("wal")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    runs = {"n": 0}
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: runs.__setitem__("n", runs["n"] + 1) or {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._continuous_gap_s = 0.01
    sched._storage_pause_poll_s = 0.02
    assert sched.start()
    try:
        deadline = time.monotonic() + 5.0
        while runner.current_phase() != "paused-wal-pinned" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runner.current_phase() == "paused-wal-pinned"
        assert runs["n"] == 0
        st = sched.status()
        assert st["storage_guard"]["engaged"] is True
        assert st["storage_guard"]["phase"] == "paused-wal-pinned"
        assert st["next_run"] is None, "no stale countdown while paused"
        g.reset(reason="test")
        deadline = time.monotonic() + 5.0
        while runs["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runs["n"] >= 1, "collection resumed without a restart"
    finally:
        sched.stop()


def test_the_loop_releases_the_latch_itself_when_no_supervisor_runs(monkeypatch):
    """The supervisor is what normally releases the latch. With the scheduler started over the
    API after an ``OO_NO_SCHEDULER=1`` boot there is none, and a loop that only waited would
    wait for ever: the loop takes the readings itself."""
    monkeypatch.setattr(storage_guard, "_THREAD", None)
    assert storage_guard.supervisor_running() is False
    g = _engaged("wal")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    runs = {"n": 0}
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: runs.__setitem__("n", runs["n"] + 1) or {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._continuous_gap_s = 0.01
    sched._storage_pause_poll_s = 0.02
    assert sched.start()
    try:
        deadline = time.monotonic() + 5.0
        while runner.current_phase() != "paused-wal-pinned" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runner.current_phase() == "paused-wal-pinned"
        time.sleep(0.2)
        assert runs["n"] == 0, "still over the limit: still paused"
        g.fake["wal_bytes"] = 0  # the log reset; nothing but the loop is looking
        deadline = time.monotonic() + 5.0
        while runs["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runs["n"] >= 1, "the pause outlived the condition that caused it"
        assert g.engaged is False
    finally:
        sched.stop()


def test_stop_interrupts_a_storage_pause_promptly(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("disk"))
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._storage_pause_poll_s = 30.0  # only stop() can end this wait in time
    assert sched.start()
    deadline = time.monotonic() + 5.0
    while runner.current_phase() != "paused-low-disk" and time.monotonic() < deadline:
        time.sleep(0.02)
    t0 = time.monotonic()
    sched.stop(timeout=5.0)
    assert time.monotonic() - t0 < 3.0
    assert not sched.is_running()


def test_a_pass_that_dies_of_a_full_drive_latches_the_guard():
    g = storage_guard.storage_guard

    def failing():
        raise sqlite3.OperationalError("database or disk is full")

    sched = runner.BackgroundScheduler(
        run_once_fn=failing, settings_provider=lambda: SchedulerSettings(continuous=False)
    )
    sched._do_run()
    assert g.kind() == "disk"
    assert "disk is full" in (sched.status()["last_error"] or "")


def test_off_peak_maintenance_yields_while_the_guard_is_engaged(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("wal"))
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings()
    )
    assert sched._run_off_peak_maintenance() is False
    assert sched.status()["maintenance_skips"].get("storage_pressure") == 1


def test_the_housekeeping_lane_takes_on_no_new_kind_while_engaged(monkeypatch):
    monkeypatch.setattr(storage_guard, "storage_guard", _engaged("disk"))
    monkeypatch.setattr(runner, "_lane_pending_kinds", lambda settings: ["markets", "calendar"])
    monkeypatch.setattr("src.ingest.fetch_release.wrap_fetcher", lambda f, s: f)
    out = runner.run_housekeeping_lane(object(), object(), SchedulerSettings())
    assert out["_paused"]["reason"].startswith("storage")
    assert {k for k in out if k != "_paused"} == set(), "no kind ran"


def test_the_resume_endpoint_is_wired_and_really_overrides(monkeypatch):
    from src.api.scheduler import router, storage_guard_resume

    assert "/api/scheduler/storage-guard/resume" in {getattr(r, "path", None) for r in router.routes}
    g = _engaged("wal")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    payload = storage_guard_resume()
    # R112: the button FORCES collection on while the limit still holds -- the latch is the
    # truth about the condition and stays engaged; what changes is whether work may start
    assert payload["storage_guard_override"] == {"engaged": True, "overridden": True, "refused": None}
    assert g.engaged is True and g.admit() is None
    assert payload["storage_guard"]["engaged"] is True and payload["storage_guard"]["overridden"] is True


def test_the_resume_endpoint_answers_a_refusal_with_its_sentence(monkeypatch):
    from src.api.scheduler import storage_guard_resume

    g = _engaged("disk")  # free = 1 MiB: already below the floor
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    payload = storage_guard_resume()
    o = payload["storage_guard_override"]
    assert o["overridden"] is False and o["refused"]["kind"] == "floor"
    assert o["refused"]["frame"] == storage_guard.FRAME_OVERRIDE_STOPPED
    assert g.admit() == "disk", "a refusal changes nothing"


def test_start_and_run_now_release_the_latch_as_a_retry(monkeypatch):
    import src.api.scheduler as api_sched

    g = _engaged("wal")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    fake = type("S", (), {"start": lambda self: True, "run_now": lambda self: True})()
    monkeypatch.setattr(api_sched, "get_scheduler", lambda: fake)
    monkeypatch.setattr(api_sched, "_status_payload", lambda: {})
    api_sched.scheduler_start()
    assert not g.engaged
    g2 = _engaged("disk")
    monkeypatch.setattr(storage_guard, "storage_guard", g2)
    api_sched.scheduler_run_now()
    assert not g2.engaged


# --------------------------------------------------------------------------- #
#  the operator's override (R112, question 18 = a): "Resume anyway" really overrides
# --------------------------------------------------------------------------- #
def _overridable(*, wal=2 * GIB, free=100 * GIB, kind="wal", clock=None):
    """An engaged guard whose own readings (what ``override()`` re-reads at the click) are the
    mutable ``g.fake``; ``free`` and ``wal`` are what the drive and the log look like."""
    fake = {"wal_bytes": wal, "disk_free_bytes": free}

    def readings():
        return {"corpus_bytes": _CORPUS, "disk_total_bytes": _TOTAL, "lane_wal_bytes": {}, **fake}

    g = _guard(clock, readings_fn=readings, drain_fn=lambda: {"busy": 1, "skipped": None})
    g.fake = fake
    g.poll()
    g.poll()
    assert g.engaged and g.kind() == kind
    return g


def test_the_override_floor_is_the_logs_own_size_never_below_128_mib():
    assert OVERRIDE_FLOOR_MIN_BYTES == 128 * MIB
    assert override_floor_bytes(None) == 128 * MIB
    assert override_floor_bytes(5 * MIB) == 128 * MIB, "a small log still needs room for a commit"
    assert override_floor_bytes(3 * GIB) == 3 * GIB, "a checkpoint may need the log's size again"


def test_an_override_lets_collection_run_while_the_limit_still_holds():
    g = _overridable()
    r = g.override(reason="test")
    assert r == {"engaged": True, "overridden": True, "refused": None}
    # the condition is still true and still reported as such ...
    assert g.engaged is True and g.kind() == "wal"
    # ... but nothing waits on it: a pass starts, and the loop does not pause
    assert g.admit() is None
    st = g.state()
    assert st["engaged"] is True and st["overridden"] is True and st["phase"] is None
    assert st["override"]["floor_bytes"] == 2 * GIB and st["overrides"] == 1
    assert st["kinds"] == ["override-wal"], "the notice says the override is on, not 'paused'"
    note = st["notes"][0]
    assert note["frame"] == storage_guard.FRAME_OVERRIDE_WAL
    assert note["vars"] == {"size": 2 * GIB, "limit": g.state()["thresholds"]["wal_high_bytes"], "floor": 2 * GIB}


def test_an_override_on_a_nearly_full_drive_names_the_floor_and_the_free_space():
    g = _overridable(wal=100 * MIB, free=1 * GIB, kind="disk")  # reserve is 10 GB, free 1 GiB
    r = g.override(reason="test")
    assert r["overridden"] is True
    st = g.state()
    assert st["kinds"] == ["override-disk"] and st["phase"] is None
    assert st["notes"][0]["vars"]["free"] == 1 * GIB
    assert st["notes"][0]["vars"]["floor"] == 128 * MIB


def test_an_override_ends_by_itself_when_the_cause_clears_and_the_guard_is_armed_again():
    g = _overridable()
    g.override(reason="test")
    # the reader let go: the log resets, both samples healthy
    g.fake["wal_bytes"] = 0
    g.poll()
    g.poll()
    assert g.engaged is False and g.state()["overridden"] is False and g.admit() is None
    assert g.state()["override"] is None
    # armed again: a new over-limit stretch pauses normally, with no override left over
    g.fake["wal_bytes"] = 2 * GIB
    g.poll()
    g.poll()
    assert g.engaged and g.admit() == "wal"
    assert g.state()["overridden"] is False


def test_an_override_is_withdrawn_when_free_space_falls_to_the_logs_size():
    # a 20 GiB log on a drive whose reserve is 10 GiB: the floor (the log's size) is the limit
    # that bites first, so the override ends on its own terms rather than by the disk latch
    g = _overridable(wal=20 * GIB, free=100 * GIB)
    g.override(reason="test")
    g.fake["disk_free_bytes"] = 20 * GIB + 1
    g.poll()
    assert g.admit() is None, "still above the floor"
    g.fake["disk_free_bytes"] = 20 * GIB  # at the floor: the log could no longer be written back
    g.poll()
    assert g.admit() == "wal", "collection pauses again by itself"
    st = g.state()
    assert st["overridden"] is False
    assert st["kinds"] == ["override-withdrawn", "wal"], "the sentence says WHY it stopped, then the pause"
    withdrawn = st["notes"][0]
    assert withdrawn["frame"] == storage_guard.FRAME_OVERRIDE_STOPPED
    assert withdrawn["vars"] == {"free": 20 * GIB, "floor": 20 * GIB}


def test_the_disk_reserve_latch_can_join_an_override_but_the_floor_still_ends_it():
    """While overridden for the log, free space also falls under the drive's reserve: the disk
    latch trips as usual, the notice names both, and the floor is still what stops collection."""
    g = _overridable(wal=2 * GIB, free=100 * GIB)  # reserve 10 GiB, floor 2 GiB
    g.override(reason="test")
    g.fake["disk_free_bytes"] = 5 * GIB
    g.poll()
    g.poll()
    assert g.state()["kinds"] == ["override-disk", "override-wal"]
    assert g.admit() is None
    g.fake["disk_free_bytes"] = 2 * GIB
    g.poll()
    assert g.admit() == "disk", "now both latches pause it"
    assert g.state()["kinds"][0] == "override-withdrawn"


def test_the_floor_never_falls_when_a_reading_is_missing():
    g = _overridable(wal=20 * GIB, free=100 * GIB)
    g.override(reason="test")
    g.fake["wal_bytes"] = None  # the size could not be read: the last real size still sets the floor
    g.fake["disk_free_bytes"] = 15 * GIB
    g.poll()
    assert g.admit() == "wal", "free space below the log's last known size ends it"


def test_a_small_log_still_leaves_128_mib_for_a_commit():
    g = _overridable(wal=1 * MIB, free=1 * GIB, kind="disk")
    g.override(reason="test")
    g.fake["disk_free_bytes"] = 129 * MIB
    g.poll()
    assert g.admit() is None
    g.fake["disk_free_bytes"] = 128 * MIB
    g.poll()
    assert g.admit() == "disk"


def test_an_override_is_refused_when_free_space_is_already_at_the_floor():
    g = _overridable(wal=20 * GIB, free=20 * GIB)
    r = g.override(reason="test")
    assert r["overridden"] is False and r["refused"]["kind"] == "floor"
    assert r["refused"]["vars"] == {"free": 20 * GIB, "floor": 20 * GIB}
    assert g.admit() == "wal", "nothing changed"
    assert g.state()["overrides"] == 0


def test_an_override_is_refused_when_free_space_cannot_be_read():
    g = _overridable()
    g.fake["disk_free_bytes"] = None
    r = g.override(reason="test")
    assert r["overridden"] is False and r["refused"]["kind"] == "unreadable"
    assert g.admit() == "wal"


def test_an_override_is_refused_while_a_write_has_just_failed_for_want_of_space():
    clock = Clock()
    g = _overridable(clock=clock)
    g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass")
    r = g.override(reason="test")
    assert r["overridden"] is False and r["refused"]["kind"] == "held"
    assert r["refused"]["frame"] == storage_guard.FRAME_OVERRIDE_HELD
    assert g.admit() == "disk", "a drive that refuses writes cannot be forced"
    clock.advance(ERROR_HOLD_S + 1)
    g.poll()
    g.poll()
    # the hold is over and the drive reads healthy: the disk latch releases by itself, the log
    # is still over its limit, and the button works again
    assert g.kind() == "wal"
    assert g.override(reason="test")["overridden"] is True


def test_a_write_that_fails_for_want_of_space_ends_an_override_at_once():
    g = _overridable()
    g.override(reason="test")
    assert g.admit() is None
    assert g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass") is True
    assert g.admit() == "disk", "no waiting for the next sample"
    st = g.state()
    assert st["overridden"] is False and "override-wal" not in st["kinds"]
    assert g.override(reason="test")["refused"]["kind"] == "held"


def test_an_override_with_nothing_engaged_is_not_recorded():
    g = _guard()
    r = g.override(reason="test")
    assert r == {"engaged": False, "overridden": False, "refused": None}
    # a latch that trips later is paused normally, not pre-overridden
    _feed(g, wal=2 * GIB, n=2)
    assert g.admit() == "wal"


def test_the_start_and_run_now_retry_ends_an_override_it_does_not_extend_one():
    g = _overridable()
    g.override(reason="test")
    g.reset(reason="operator started collection")
    assert g.engaged is False and g.state()["overridden"] is False
    g.poll()
    g.poll()
    assert g.admit() == "wal", "a retry that finds the limit still exceeded pauses again"


def test_an_override_does_not_stop_the_drain_and_the_drain_ends_the_cause():
    clock = Clock()
    calls = []
    g = _overridable(clock=clock)
    g._drain = lambda: calls.append(clock()) or {"busy": 0, "wal_bytes_before": 2 * GIB, "wal_bytes_after": 0}
    g.override(reason="test")
    assert g.drain_if_due() is not None and len(calls) == 1, "the log still gets reset the moment it can"


def test_off_peak_maintenance_still_yields_under_an_override(monkeypatch):
    """Collection is forced on; the maintenance writes are not (they append to the file the
    guard is bounding, and nobody asked for them)."""
    g = _overridable()
    g.override(reason="test")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings()
    )
    assert sched._run_off_peak_maintenance() is False
    assert sched.status()["maintenance_skips"].get("storage_pressure") == 1


def test_the_pass_wind_down_and_the_loop_do_not_pause_under_an_override(monkeypatch):
    g = _overridable()
    g.override(reason="test")
    monkeypatch.setattr(storage_guard, "storage_guard", g)
    assert runner._PassWindDown(budget_s=0, max_sources=0).admit() is None
    runs = {"n": 0}
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: runs.__setitem__("n", runs["n"] + 1) or {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._continuous_gap_s = 0.01
    sched._storage_pause_poll_s = 0.02
    assert sched.start()
    try:
        deadline = time.monotonic() + 5.0
        while runs["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runs["n"] >= 1, "collection ran while the limit was still exceeded"
        assert runner.current_phase() != "paused-wal-pinned"
    finally:
        sched.stop()


def test_an_override_and_its_withdrawal_are_logged_with_the_numbers(caplog):
    g = _overridable(wal=20 * GIB, free=100 * GIB)
    with caplog.at_level("WARNING", logger=storage_guard._LOG.name):
        g.override(reason="operator resumed via the API")
        g.fake["disk_free_bytes"] = 15 * GIB
        g.poll()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "STORAGE GUARD OVERRIDDEN (operator resumed via the API)" in text
    assert "WAL 20 GB, free 100 GB" in text.replace(".0 GB", " GB")
    assert "STORAGE GUARD OVERRIDE WITHDRAWN" in text and "15" in text


def test_the_polled_state_says_what_bounds_an_override():
    g = _overridable()
    st = g.state()
    assert st["thresholds"]["override_floor_bytes"] == 2 * GIB
    assert "Resume anyway" in st["method"] and "128 MiB" in st["method"]
    assert st["overridden"] is False and st["override"] is None and st["overrides"] == 0


# --------------------------------------------------------------------------- #
#  end to end against a REAL SQLite file: a pinned reader, the guard, the drain, the release
# --------------------------------------------------------------------------- #
def test_a_real_pinned_reader_engages_the_guard_is_named_and_released_when_it_ends(
    tmp_path, monkeypatch
):
    """The premise of the whole design, exercised through the repo's own checkpoint call.

    A pooled connection holds an open SELECT cursor (a snapshot), writers grow the WAL past a
    tiny limit, the guard engages, its drain reports TRUNCATE busy and NAMES the holder with a
    stack, the reader ends, the next drain resets the file to zero, and the guard releases.
    """
    from src.scheduler.hygiene import checkpoint_wal

    monkeypatch.setenv("OO_WAL_HIGH_MB", "1")
    db = tmp_path / "real.db"
    eng = create_engine(f"sqlite:///{db}", future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA wal_autocheckpoint=0")
        cur.close()

    pool_watch.register(eng)
    wal = Path(str(db) + "-wal")
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")

    def burst():
        with eng.begin() as c:
            c.exec_driver_sql(
                "INSERT INTO t(b) VALUES " + ",".join(["(zeroblob(3000))"] * 256)
            )

    burst()
    reader = eng.connect()
    held = reader.exec_driver_sql("SELECT id FROM t")
    held.fetchone()  # an open cursor: the snapshot is held, in_transaction would say False
    for _ in range(3):
        burst()
    assert wal.stat().st_size > 1 * MIB

    clock = Clock()

    def readings():
        return {
            "wal_bytes": wal.stat().st_size if wal.exists() else 0,
            "corpus_bytes": db.stat().st_size,
            "disk_free_bytes": 300 * GIB,
            "disk_total_bytes": 500 * GIB,
            "lane_wal_bytes": {},
        }

    g = StorageGuard(
        readings_fn=readings,
        drain_fn=lambda: checkpoint_wal(engine=eng, force=True),
        trip_after=1,
        resume_after=1,
        clock=clock,
    )
    assert g.poll() is True and g.kind() == "wal"
    rec = g.drain_if_due()
    assert rec is not None and rec["busy"] == 1, "TRUNCATE is busy while the cursor is open"
    assert wal.stat().st_size > 1 * MIB, "and the file was not reset"
    rep = g.state(detail=True)["last_pin_report"]
    assert rep["instrument"] == "attached"
    (holder, *_rest) = rep["holders"]
    assert holder["thread"] == threading.current_thread().name
    assert any("test_a_real_pinned_reader" in line for line in holder["stack"]), holder["stack"]
    assert g.poll() is True, "still pinned, still paused"

    held.close()
    reader.close()
    clock.advance(DRAIN_EVERY_S + 1)
    rec2 = g.drain_if_due()
    assert rec2 is not None and rec2["busy"] == 0
    assert (wal.stat().st_size if wal.exists() else 0) == 0
    assert g.poll() is False and g.kind() is None, "released by itself once the log reset"
    eng.dispose()


# --------------------------------------------------------------------------- #
#  what rides the existing surfaces
# --------------------------------------------------------------------------- #
def test_the_hourly_disk_gauge_is_registered_in_mib_and_unmeasurable_is_a_hole(monkeypatch):
    from src.database.snapshots import _GAUGE_METRICS, ALL_METRICS

    assert "disk_free_mib" in _GAUGE_METRICS
    assert "disk_free_mib" not in ALL_METRICS, "diagnostics material, like wal_bytes"
    monkeypatch.setattr(storage_guard, "read_storage", lambda: {"disk_free_bytes": 5 * GIB + 123})
    assert _GAUGE_METRICS["disk_free_mib"](None) == 5 * 1024
    monkeypatch.setattr(storage_guard, "read_storage", lambda: {"disk_free_bytes": None})
    assert _GAUGE_METRICS["disk_free_mib"](None) is None, "never a recorded 0 (it would read as full)"


def test_the_reader_snapshot_lists_every_holder_not_only_the_oldest(tmp_path):
    from src.scheduler.hygiene import _reader_snapshot

    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True)
    pool_watch.register(eng)
    a, b = eng.connect(), eng.connect()
    try:
        snap = _reader_snapshot()
        # The registry is process-wide: a daemon's own checkout may be listed too.
        assert snap["n"] >= 2 and len(snap["holders"]) >= 2
        assert set(snap["holders"][0]) == {"thread", "age_s"}
        assert snap["oldest_thread"] == snap["holders"][0]["thread"]
    finally:
        a.close()
        b.close()
        eng.dispose()


def test_storage_composition_carries_the_guard_block(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base
    from src.monitoring.storage import storage_composition

    eng = create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    try:
        out = storage_composition(s)
    finally:
        s.close()
        eng.dispose()
    blk = out["storage_guard"]
    assert blk["enabled"] is True and "history" in blk and "method" in blk


def test_the_real_reading_reports_unreadable_figures_as_none_not_zero(monkeypatch):
    """``read_storage`` off SQLite (or with no engine file) degrades to None everywhere."""
    import src.database.session as session_mod

    class _Url:
        def get_backend_name(self):
            return "postgresql"

    class _Eng:
        url = _Url()

    monkeypatch.setattr(session_mod, "engine", _Eng())
    r = storage_guard.read_storage()
    assert r["wal_bytes"] is None and r["disk_free_bytes"] is None


# --------------------------------------------------------------------------- #
#  the wiring cannot silently go missing
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_node(tree, name):
    import ast

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no def of {name!r}")


def _call_lines(node, name):
    import ast

    return [
        c.lineno
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name
    ]


def test_boot_starts_the_supervisor_inside_the_scheduler_gate():
    """The call of the imported ``start`` must sit INSIDE the ``if`` whose test is the
    OO_NO_SCHEDULER gate, in the upkeep that run_deferred_startup calls. A parser walk, not a
    text search: dedenting the block out of the gate, or keeping the import and deleting the
    call, would each pass a find/rfind pair and fail this."""
    import ast

    main = _src("src/api/main.py")
    assert "_run_startup_upkeep()" in python_function_source(main, "run_deferred_startup")
    tree = ast.parse(main)
    upkeep = _function_node(tree, "_run_startup_upkeep")
    gates = [
        n
        for n in ast.walk(upkeep)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "os.getenv('OO_NO_SCHEDULER', '0') != '1'"
    ]
    assert gates, "the OO_NO_SCHEDULER gate moved -- re-anchor this test"
    inside = []
    for gate in gates:
        imported = {
            a.asname or a.name
            for n in ast.walk(gate)
            if isinstance(n, ast.ImportFrom) and n.module == "src.scheduler.storage_guard"
            for a in n.names
            if a.name == "start"
        }
        inside += [name for name in imported if _call_lines(gate, name)]
    assert inside, (
        "the supervisor must start after unlock (run_deferred_startup) and stay behind "
        "OO_NO_SCHEDULER, like the offline-maintenance timer it sits beside"
    )


def test_shutdown_stops_the_supervisor_before_the_engine_is_disposed():
    """A drain in flight (an engaged guard) must not overlap ``dispose_engine``."""
    import ast

    life = _function_node(ast.parse(_src("src/api/main.py")), "lifespan")
    stop_at = _call_lines(life, "_stop_storage_guard")
    assert stop_at, "the lifespan never stops the storage guard's supervisor"
    assert max(_call_lines(life, "_stop_offline_maintenance")) < min(stop_at) < min(_call_lines(life, "dispose_engine"))


def test_the_supervisor_can_be_stopped_and_started_again_and_leaves_one_live_thread(monkeypatch):
    monkeypatch.setattr(storage_guard, "POLL_EVERY_S", 0.05)
    monkeypatch.setattr(storage_guard, "_THREAD", None)
    monkeypatch.setattr(storage_guard, "_STOP", threading.Event())
    try:
        assert storage_guard.start() is True
        assert storage_guard.supervisor_running() is True
        assert storage_guard.start() is False, "idempotent while running"
        first = storage_guard._THREAD
        storage_guard.stop()
        assert storage_guard.supervisor_running() is False
        assert storage_guard.start() is True, "a start right after a stop must not be refused"
        assert storage_guard.supervisor_running() is True
        first.join(timeout=2.0)
        assert not first.is_alive(), "the old thread exits on its own event; the clear never revives it"
        live = [t for t in threading.enumerate() if t.name == "oo-storage-guard" and t.is_alive()]
        assert len(live) == 1
    finally:
        storage_guard.stop()


def test_the_guard_being_off_starts_no_supervisor(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    monkeypatch.setattr(storage_guard, "_THREAD", None)
    assert storage_guard.start() is False
    assert storage_guard._THREAD is None


def test_wait_if_engaged_ends_by_itself_when_no_supervisor_runs(monkeypatch):
    """A caller that waits (the keyword boot recompute will) must not wait for ever when the
    supervisor never started: it takes the readings and the drain itself."""
    monkeypatch.setattr(storage_guard, "_THREAD", None)
    g = _engaged("wal")
    waiter = threading.Thread(target=g.wait_if_engaged, kwargs={"poll_s": 0.02}, daemon=True)
    waiter.start()
    time.sleep(0.15)
    assert waiter.is_alive(), "still over the limit: still waiting"
    g.fake["wal_bytes"] = 0
    waiter.join(timeout=5.0)
    assert not waiter.is_alive(), "the wait outlived the condition that caused it"


def test_the_runner_consults_the_guard_at_every_point_the_memory_guard_is_consulted():
    src = _src("src/scheduler/runner.py")
    assert src.count("storage_guard.storage_guard.admit()") >= 2  # wind-down, lane
    # off-peak maintenance asks the LATCH, not admit(): an operator's override lets collection
    # run, it does not ask for the maintenance writes (R112)
    assert "storage_guard.storage_guard.enabled() and storage_guard.storage_guard.engaged" in src
    assert "_wait_while_storage_paused" in src and "note_error(exc" in src
    assert '"storage_guard": storage_state' in src


def test_the_engine_hook_and_the_read_engine_registration_exist():
    from src.database import session

    assert event.contains(session.engine, "handle_error", session._storage_guard_on_disk_full), (
        "the global engine must carry the full-disk listener (a substring check would pass "
        "with the decorator removed)"
    )
    assert "_pool_watch.register(eng)" in _src("src/database/read_snapshot.py")


# --------------------------------------------------------------------------- #
#  the follow-ups from the coordinator's check of #1279 (P1, P3, P6, P7, P8, P9, P11)
# --------------------------------------------------------------------------- #
def test_no_sentence_the_guard_sends_tells_the_user_to_do_anything():
    """P1: the app works as is. The disk frames used to end with an imperative; they now say
    what would bring the end sooner."""
    frames = [
        storage_guard.FRAME_WAL,
        storage_guard.FRAME_DISK,
        storage_guard.FRAME_DISK_ERROR,
        storage_guard.FRAME_OVERRIDE_WAL,
        storage_guard.FRAME_OVERRIDE_DISK,
        storage_guard.FRAME_OVERRIDE_STOPPED,
        storage_guard.FRAME_OVERRIDE_HELD,
        storage_guard.FRAME_OVERRIDE_UNREADABLE,
    ]
    for f in frames:
        assert "Free some space" not in f and "move the data folder" not in f, f
    # the plain-words rule: the first thing a reader meets is "working file", not log jargon
    assert "working file (its write-ahead log)" in storage_guard.FRAME_WAL
    assert "once writes succeed" not in storage_guard.FRAME_DISK_ERROR, "release does not attempt a write"


def test_the_reserve_has_one_stated_reason_everywhere_it_is_said():
    """P3: 1 GiB for the writes still in flight plus 2% of the drive as room for everything
    else writing to it -- the same two-part reason in the docstring, the hover and the method."""
    doc = storage_guard.__doc__ or ""
    assert "1 GiB for the writes still in flight" in doc and "2% of the drive as room for everything" in doc
    method = _guard().state()["method"]
    assert "1 GiB for the writes still in flight" in method and "2% of the drive as room" in method
    for page in ("src/static/app-core.js", "src/static/taskmanager.js"):
        assert "1 GB for the writes still in flight plus 2% of the drive as room for everything else" in _src(page)


def test_the_stack_depth_is_one_number_in_the_report_and_the_on_demand_capture():
    """P11: pool_watch's default and the guard's report depth are the same twelve."""
    assert pool_watch.STACK_DEPTH == storage_guard.PIN_STACK_DEPTH


def test_a_long_pin_logs_one_warning_an_episode_and_one_when_the_holders_change(caplog):
    """P6: one WARNING a minute for a day-long pin would replace the 2,000-record error ring."""
    clock = Clock()
    holders = [[{"thread": "worker-1", "age_s": 400.0}]]

    def drain():
        return {"busy": 1, "wal_bytes_before": 3 * GIB, "wal_bytes_after": 3 * GIB}

    g = _guard(clock, drain_fn=drain)
    _feed(g, wal=3 * GIB, n=2)

    import src.scheduler.storage_guard as sg

    real = sg._pin_report
    sg._pin_report = lambda rec: {"holders": holders[0], "n": len(holders[0])}
    try:
        with caplog.at_level("INFO", logger=sg._LOG.name):
            for _ in range(4):
                clock.advance(storage_guard.PIN_REPORT_EVERY_S + 1)
                assert g.drain_if_due() is not None
            levels = [r.levelname for r in caplog.records if "TRUNCATE is busy" in r.getMessage()]
            assert levels == ["WARNING", "INFO", "INFO", "INFO"], levels
            holders[0] = [{"thread": "worker-2", "age_s": 10.0}]  # a different holder: say so again
            clock.advance(storage_guard.PIN_REPORT_EVERY_S + 1)
            g.drain_if_due()
            levels = [r.levelname for r in caplog.records if "TRUNCATE is busy" in r.getMessage()]
            assert levels[-1] == "WARNING"
            # a released and re-engaged guard is a new episode: its first report is a WARNING again
            g.fake = None
            _feed(g, wal=0, n=2)
            assert not g.engaged
            _feed(g, wal=3 * GIB, n=2)
            clock.advance(storage_guard.PIN_REPORT_EVERY_S + 1)
            g.drain_if_due()
            levels = [r.levelname for r in caplog.records if "TRUNCATE is busy" in r.getMessage()]
            assert levels[-1] == "WARNING"
    finally:
        sg._pin_report = real


def test_the_drain_is_paced_from_when_it_ended_not_from_when_it_began():
    """P9: a drain that queued 30 s on the write gate must not be followed 5 s later by the next."""
    clock = Clock()
    starts = []

    def slow_drain():
        starts.append(clock())
        clock.advance(30.0)  # the bounded wait on a busy write gate
        return {"busy": 0, "skipped": "gate busy"}

    g = _guard(clock, drain_fn=slow_drain)
    _feed(g, wal=2 * GIB, n=2)
    assert g.drain_if_due() is not None
    clock.advance(DRAIN_EVERY_S - 1)
    assert g.drain_if_due() is None, "ten seconds after it ENDED has not passed"
    clock.advance(2)
    assert g.drain_if_due() is not None
    assert len(starts) == 2


def test_a_write_error_latch_whose_hold_lapsed_with_free_space_unreadable_releases_as_a_retry():
    """P7: nothing could ever confirm recovery by measurement (a PostgreSQL install reads no
    free space), so the latch must not outlive its hold for ever; another failed write
    re-latches it at once."""
    clock = Clock()
    g = _guard(clock)
    _feed(g, free=_FREE_OK)
    g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass")
    assert g.kind() == "disk"
    for _ in range(4):
        g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert g.engaged, "inside the hold an unreadable figure releases nothing"
    clock.advance(ERROR_HOLD_S + 1)
    g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert g.engaged, "one sample is not yet resume_after"
    g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert not g.engaged, "released as a retry"
    assert g.note_error(sqlite3.OperationalError("database or disk is full"), "collect pass") is True
    assert g.kind() == "disk", "the next failed write latches it again at once"


def test_a_latch_set_by_measurement_never_releases_on_an_unreadable_figure():
    clock = Clock()
    g = _guard(clock)
    _feed(g, free=MIB, n=2)
    assert g.kind() == "disk"
    clock.advance(ERROR_HOLD_S * 10)
    for _ in range(6):
        g.observe(wal_bytes=None, corpus_bytes=None, disk_free_bytes=None, disk_total_bytes=None)
    assert g.engaged, "no measurement said the drive recovered"


def test_wait_if_engaged_can_be_bounded():
    """P8: a caller that cannot wait for ever says how long it can."""
    g = _engaged("wal")
    g._clock = time.monotonic  # the helper's fake clock does not move; this wait is real, and short
    t0 = time.monotonic()
    assert g.wait_if_engaged(max_wait_s=0.3, poll_s=0.05) is True
    assert 0.25 <= time.monotonic() - t0 < 3.0
    stop = threading.Event()
    stop.set()
    assert g.wait_if_engaged(stop, poll_s=0.05) is False, "an interrupted wait returns at once"


def test_the_conftest_isolates_the_process_global_latch():
    assert "_storage_guard_not_leaked" in _src("tests/conftest.py")


def test_every_storage_string_is_in_the_twelve_locales():
    import json
    import re

    # The hover text is read from the page itself, so a reworded sentence that forgets its
    # locale keys fails here rather than showing English in eleven languages.
    hover = re.search(r't9?\("(Measured from the size of the database[^"]*)"\)', _src("src/static/app-core.js"))
    assert hover, "the hover text moved -- re-anchor this test"
    keys = [
        storage_guard.FRAME_WAL,
        storage_guard.FRAME_DISK,
        storage_guard.FRAME_DISK_ERROR,
        hover.group(1),
        "Paused: the database log has grown too large",
        "Paused: the data drive is nearly full",
        "Resume anyway",
        "Collection resumed although the limit is still exceeded. It stops again by itself if free space falls too low.",
        storage_guard.FRAME_OVERRIDE_WAL,
        storage_guard.FRAME_OVERRIDE_DISK,
        storage_guard.FRAME_OVERRIDE_STOPPED,
        storage_guard.FRAME_OVERRIDE_HELD,
        storage_guard.FRAME_OVERRIDE_UNREADABLE,
    ]
    for gone in ("Try again now", "Trying again. Collection pauses again by itself if the limit is still exceeded."):
        assert gone not in _src("src/static/app-core.js") and gone not in _src("src/static/taskmanager.js")
    for p in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in keys:
            assert k in d, f"{p.name} lacks {k[:50]!r}"
            if p.name != "en.json":
                assert d[k] != k, f"{p.name}: untranslated {k[:50]!r}"


def test_the_notice_runs_as_real_code_under_node_in_both_uis():
    """The vitals panel / Schedule tab and /tasks draw the engaged notice from the payload,
    and draw nothing over a stopped scheduler or airplane mode (tests/storage_guard_node_test.js)."""
    import subprocess

    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "storage_guard_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks ok" in proc.stdout


def test_the_ui_renders_the_notice_from_the_payload_and_the_button_is_dispatchable():
    core = _src("src/static/app-core.js")
    assert "function _storageGuardHtml" in core and "async function storageGuardResume" in core
    # the definition, then the vitals panel and the schedule tab
    assert core.count("_storageGuardHtml(a, ") - core.count("function _storageGuardHtml(a, ") == 2
    assert '"storageGuardResume"' in _src("src/static/oo-on.js")
    tm = _src("src/static/taskmanager.js")
    assert "storageGuardHtml(a)" in tm and 'data-tm="storage-resume"' in tm
    assert "paused-wal-pinned" in core and "paused-low-disk" in core
