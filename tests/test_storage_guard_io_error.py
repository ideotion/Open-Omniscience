"""SQLite's plain "disk I/O error" and the storage guard.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The guard latches DISK at once when a write fails with "database or disk is full". A full
drive also reaches SQLite as a plain "disk I/O error" when its filesystem reports ENOSPC late
(at fsync, on a copy-on-write or delayed-allocation filesystem), and so does a dying or
unplugged drive. The message alone cannot tell them apart, so it never latches: the drive's own
free space, read at that moment, does (``StorageGuard.note_io_error``). The hook sits on the
corpus engine and on every lane engine, because a lane is written to the same drive.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from src.scheduler import storage_guard as sg
from src.scheduler.storage_guard import (
    GIB,
    MIB,
    StorageGuard,
    disk_reserve_bytes,
    is_disk_full,
    is_io_error,
)

_TOTAL = 500 * GIB
_RESERVE = disk_reserve_bytes(_TOTAL)  # max(1 GiB, 2% of 500 GiB) = 10 GiB


@pytest.fixture(autouse=True)
def _guard_enabled(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")


def _guard(free):
    fake = {"wal_bytes": 10 * MIB, "corpus_bytes": 10 * GIB, "disk_free_bytes": free, "disk_total_bytes": _TOTAL}
    g = StorageGuard(readings_fn=lambda: {"lane_wal_bytes": {}, **fake}, trip_after=2, resume_after=2)
    g.fake = fake
    return g


class _CodedError(Exception):
    """What a Python 3.11+ ``sqlite3.Error`` carries, without depending on the driver."""

    def __init__(self, message, code):
        super().__init__(message)
        self.sqlite_errorcode = code


def test_the_plain_io_error_is_recognised_by_code_message_and_chain_and_nothing_else_is():
    assert is_io_error(sqlite3.OperationalError("disk I/O error"))
    assert is_io_error(_CodedError("anything at all", 778))  # SQLITE_IOERR_WRITE = 10 | 3 << 8
    assert is_io_error(_CodedError("anything at all", 10))
    wrapped = OperationalError("INSERT", {}, sqlite3.OperationalError("disk I/O error"))
    assert is_io_error(wrapped), "SQLAlchemy's wrapper carries it in .orig"
    try:
        try:
            raise sqlite3.OperationalError("disk I/O error")
        except sqlite3.OperationalError as inner:
            raise RuntimeError("the pass failed") from inner
    except RuntimeError as outer:
        assert is_io_error(outer), "a pass that died of it names it in the chain"
    assert not is_io_error(None)
    assert not is_io_error(sqlite3.OperationalError("database is locked"))
    assert not is_io_error(_CodedError("busy", 5))  # SQLITE_BUSY
    assert not is_io_error(_CodedError("full", 13))  # SQLITE_FULL is its own, strict, classification


def test_the_strict_full_drive_classification_did_not_widen_to_the_io_error():
    assert not is_disk_full(sqlite3.OperationalError("disk I/O error"))
    assert is_disk_full(sqlite3.OperationalError("database or disk is full"))


def test_an_io_error_with_the_drive_below_the_reserve_latches_disk_and_says_why():
    g = _guard(free=2 * GIB)
    assert g.note_io_error(sqlite3.OperationalError("disk I/O error"), "collect pass") is True
    assert g.engaged and g.kind() == "disk"
    st = g.state()
    assert st["io_errors"] == 1
    last = st["last_io_error"]
    assert last["latched"] is True and last["disk_free_bytes"] == 2 * GIB
    assert last["disk_reserve_bytes"] == _RESERVE and last["where"] == "collect pass"
    assert st["disk_full_events"] == 1, "it went through the one latch path, hold and all"
    assert "I/O error" in st["last_disk_full"]["detail"] and "below the" in st["last_disk_full"]["detail"]


def test_an_io_error_on_a_drive_with_room_is_recorded_and_never_latches():
    g = _guard(free=300 * GIB)
    assert g.note_io_error(sqlite3.OperationalError("disk I/O error")) is False
    assert not g.engaged, "a drive that reports room and fails with an I/O error is not 'full'"
    st = g.state()
    assert st["io_errors"] == 1 and st["last_io_error"]["latched"] is False
    assert st["disk_full_events"] == 0 and st["last_disk_full"] is None


def test_an_io_error_when_free_space_cannot_be_read_is_not_classified_as_full():
    g = _guard(free=None)
    assert g.note_io_error(sqlite3.OperationalError("disk I/O error")) is False
    assert not g.engaged
    assert g.state()["last_io_error"]["disk_free_bytes"] is None

    def broken():
        raise OSError("the drive does not answer")

    g2 = StorageGuard(readings_fn=broken, trip_after=2, resume_after=2)
    assert g2.note_io_error(sqlite3.OperationalError("disk I/O error")) is False, "never raises"
    assert not g2.engaged and g2.state()["io_errors"] == 1


def test_the_boundary_is_the_guards_own_free_below_the_reserve_comparison():
    below = _guard(free=_RESERVE - 1)
    at = _guard(free=_RESERVE)
    assert below.note_io_error(sqlite3.OperationalError("disk I/O error")) is True
    assert at.note_io_error(sqlite3.OperationalError("disk I/O error")) is False


def test_an_error_that_is_not_an_io_error_changes_nothing():
    g = _guard(free=1 * GIB)
    assert g.note_io_error(sqlite3.OperationalError("database is locked")) is False
    assert g.note_io_error(None) is False
    assert g.state()["io_errors"] == 0 and not g.engaged


def test_the_pass_failure_path_covers_the_io_error_too():
    g = _guard(free=2 * GIB)
    assert g.note_error(RuntimeError("the pass failed"), "collect pass") is False
    try:
        try:
            raise sqlite3.OperationalError("disk I/O error")
        except sqlite3.OperationalError as inner:
            raise RuntimeError("scrape run failed") from inner
    except RuntimeError as outer:
        assert g.note_error(outer, "collect pass") is True
    assert g.engaged and g.kind() == "disk"


def test_a_guard_that_is_switched_off_records_and_latches_nothing(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    g = _guard(free=1 * GIB)
    assert g.note_io_error(sqlite3.OperationalError("disk I/O error")) is False
    assert not g.engaged and g.state()["io_errors"] == 0


def _fail_every_statement(eng, exc_factory):
    def boom(cursor, statement, parameters, context):
        raise exc_factory()

    event.listen(eng, "do_execute", boom)
    return boom


def _swap_in(monkeypatch, g):
    monkeypatch.setattr(sg, "storage_guard", g)


def test_the_corpus_engines_hook_latches_on_a_real_failed_statement_and_lets_the_error_through(monkeypatch):
    from src.database import session as dbsession

    g = _guard(free=2 * GIB)
    _swap_in(monkeypatch, g)
    eng = dbsession.engine
    boom = _fail_every_statement(eng, lambda: sqlite3.OperationalError("disk I/O error"))
    try:
        with pytest.raises(OperationalError, match="disk I/O error"), eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        event.remove(eng, "do_execute", boom)
    assert g.engaged and g.kind() == "disk"
    assert g.state()["last_io_error"]["latched"] is True


def test_the_corpus_engines_hook_leaves_an_io_error_on_a_drive_with_room_alone(monkeypatch):
    from src.database import session as dbsession

    g = _guard(free=300 * GIB)
    _swap_in(monkeypatch, g)
    eng = dbsession.engine
    boom = _fail_every_statement(eng, lambda: sqlite3.OperationalError("disk I/O error"))
    try:
        with pytest.raises(OperationalError), eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        event.remove(eng, "do_execute", boom)
    assert not g.engaged and g.state()["io_errors"] == 1


def test_the_corpus_engines_hook_still_latches_on_the_full_message(monkeypatch):
    from src.database import session as dbsession

    g = _guard(free=300 * GIB)  # room reported: the message is what latches
    _swap_in(monkeypatch, g)
    eng = dbsession.engine
    boom = _fail_every_statement(eng, lambda: sqlite3.OperationalError("database or disk is full"))
    try:
        with pytest.raises(OperationalError), eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        event.remove(eng, "do_execute", boom)
    assert g.engaged and g.kind() == "disk"
    assert g.state()["io_errors"] == 0


def test_a_lane_engine_carries_the_same_hook(monkeypatch, tmp_path):
    """A lane is written to the same drive as the corpus (one reached 100 GB), so a full drive
    found by a lane's write stops collection too."""
    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = _guard(free=2 * GIB)
    _swap_in(monkeypatch, g)
    try:
        eng = store.lane_engine("wiki", create=True)
        boom = _fail_every_statement(eng, lambda: sqlite3.OperationalError("database or disk is full"))
        try:
            with pytest.raises(OperationalError), eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            event.remove(eng, "do_execute", boom)
        assert g.engaged and g.kind() == "disk"
        g2 = _guard(free=2 * GIB)
        _swap_in(monkeypatch, g2)
        boom = _fail_every_statement(eng, lambda: sqlite3.OperationalError("disk I/O error"))
        try:
            with pytest.raises(OperationalError), eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            event.remove(eng, "do_execute", boom)
        assert g2.engaged and g2.state()["last_io_error"]["latched"] is True
    finally:
        store.dispose_all()
