"""The late-entries count is a plain read: no signer, no append lock, no file made, its failures named, its moment stated.

THE FIELD RECORD: GET /api/custody/settings took 25.3 s once (2026-10-16). The first-call cause is pinned in
test_first_custody_read_builds_no_config.py; this file pins the second contributor measured in a synthetic repro (150,000
custody rows, encrypted, 2 cores, 50 threads recording): the count built a CustodyLog, which opens the file (a key derivation
under CPU contention) and takes the process-wide append lock every ingest holds. Of 9-12 s, 2.6-14 s was the open and 3.5-6 s the
lock; the scan itself was 0.2 s.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.custody import log as clog
from src.custody import pending
from src.custody.log import CustodyAction, CustodyLog
from tests.js_source_helper import read_static


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    return tmp_path


def _record(n: int, late: bool = False) -> None:
    with CustodyLog() as log:
        for i in range(n):
            log.record(f"article:{i}", "h" * 64, CustodyAction.INGEST, metadata={"late": True} if late else {})


#: How long a read that a writer holds is waited for before the test calls it hung. It is a hang guard, never the verdict: the verdict
#: is whether the read came back while the writer STILL held the file, which no pause of this process can change (a bound on how long
#: the read took could: the encrypted read measured 2.73 s healthy against the 3.0 s it was held to, because each page-size
#: candidate under the open pays a key derivation).
_HELD_READ_HANG_GUARD_S = 20.0


def _read_while_writer_holds() -> tuple[dict, bool, list]:
    """``late_reading()`` on a thread; the caller's writer keeps the file until this returns. ``(the reading, whether it came back while
    the writer still held, the timeout each open of the log was given)``: a read that waits for the writer cannot come back until the
    guard ends it, and a read whose open is given more than the bound would wait that long on a writer, which the guard alone would let
    pass when it is shorter than the guard (the encrypted open pays it once per page-size candidate)."""
    import src.database.connect as dbc

    real, timeouts = dbc.connect, []

    def recording(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return real(*args, **kwargs)

    dbc.connect = recording
    box: dict = {}
    try:
        reader = threading.Thread(target=lambda: box.update(got=pending.late_reading()), daemon=True)
        reader.start()
        reader.join(_HELD_READ_HANG_GUARD_S)
    finally:
        dbc.connect = real
    return box.get("got", {}), not reader.is_alive(), timeouts


def test_the_count_counts_what_the_log_holds(data):
    _record(3)
    _record(2, late=True)
    assert pending.late_reading()["count"] == 2
    assert pending.late_count() == 2


def test_the_count_never_waits_for_the_append_lock(data):
    _record(1, late=True)
    held, release, got = threading.Event(), threading.Event(), []

    def holder():
        with clog._APPEND_LOCK:
            held.set()
            release.wait(20)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    try:
        asker = threading.Thread(target=lambda: got.append(pending.late_reading()["count"]))
        asker.start()
        asker.join(10)
        assert not asker.is_alive(), "the late count queued behind the append lock every ingest holds"
        assert got == [1]
    finally:
        release.set()
        t.join(5)


def test_the_count_builds_no_custody_log_and_no_signer(data, monkeypatch):
    _record(1, late=True)

    def boom(*a, **k):
        raise AssertionError("the late count built a CustodyLog or a signer")

    monkeypatch.setattr(CustodyLog, "__init__", boom)
    monkeypatch.setattr("src.custody.signing.HybridSigner.__init__", boom)
    assert pending.late_reading()["count"] == 1


def test_asking_about_a_log_that_does_not_exist_does_not_make_it(data):
    got = pending.late_reading()
    assert got["count"] == 0 and got["reason"] is None
    assert not (data / "custody_log.db").exists()


def test_a_log_without_its_table_has_no_late_entries(data):
    sqlite3.connect(data / "custody_log.db").execute("CREATE TABLE other (x)").connection.commit()
    assert pending.late_reading()["count"] == 0


def test_an_unreadable_log_is_none_with_the_class_and_none_of_the_drivers_words(data):
    (data / "custody_log.db").write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    got = pending.late_reading()
    assert got["count"] is None
    assert re.fullmatch(r"[A-Za-z_]+", got["reason"] or ""), got
    assert pending.late_count() is None


def test_a_writer_holding_the_file_makes_the_count_unread_not_a_wait(data, monkeypatch):
    _record(1, late=True)
    monkeypatch.setattr(pending, "_LATE_READ_BUSY_MS", 100)
    writer = sqlite3.connect(data / "custody_log.db", isolation_level=None)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        got, came_back_while_held, timeouts = _read_while_writer_holds()
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert came_back_while_held, "the count waited for the writer that holds the file"
    assert timeouts == [0.1], f"the open of the log was given {timeouts}, not the 0.1 s bound"
    assert got["count"] is None and got["reason"] == "OperationalError"


def test_a_count_states_the_moment_it_was_taken(data):
    got = pending.late_reading()
    taken = datetime.fromisoformat(got["computed_at"])
    assert abs((datetime.now(taken.tzinfo) - taken).total_seconds()) < 30


def test_the_route_carries_the_moment_and_can_leave_the_count_out(data, monkeypatch):
    _record(1, late=True)
    with TestClient(app) as c:
        full = c.get("/api/custody/settings").json()["late"]
        assert full["recorded_late"] == 1 and full["recorded_late_reason"] is None
        assert datetime.fromisoformat(full["recorded_late_computed_at"])

        def boom():
            raise AssertionError("late=false still scanned the log")

        monkeypatch.setattr(pending, "late_reading", boom)
        light = c.get("/api/custody/settings?late=false").json()
        assert c.get("/api/custody/settings?late=0").json()["late"]["recorded_late_reason"] == "not requested"
    assert light["late"]["recorded_late"] is None
    assert light["late"]["recorded_late_reason"] == "not requested"
    assert light["late"]["recorded_late_computed_at"] is None
    assert light["anchoring_mode"] == "local", "the rest of the answer is unchanged"


def test_the_network_consent_popup_reads_the_route_without_the_count():
    src = read_static("app-core.js")
    assert '["custody", "/api/custody/settings?late=0"]' in src


def test_an_encrypted_log_held_by_a_writer_is_also_unread_within_the_bound_not_waited_out(tmp_path, monkeypatch):
    """The open of an encrypted file reads it once per page-size candidate under the connection's own timeout: a bound set after the
    open did not hold (an exclusive writer held for 10 s made the encrypted read wait 10.2 s, where the plaintext one waited 3)."""
    import src.database.connect as dbc
    from src.database.connect import connect

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    previous = dbc.get_passphrase()
    dbc.set_passphrase("late-count-test-passphrase")
    monkeypatch.setattr(pending, "_LATE_READ_BUSY_MS", 300)
    _record(1, late=True)
    from src.database.connect import is_encrypted_file

    assert is_encrypted_file(tmp_path / "custody_log.db") is True, "the fixture must be an encrypted log"
    writer = connect(tmp_path / "custody_log.db", check_same_thread=False)
    writer.isolation_level = None
    writer.execute("BEGIN EXCLUSIVE")
    try:
        got, came_back_while_held, timeouts = _read_while_writer_holds()
    finally:
        writer.execute("ROLLBACK")
        writer.close()
        dbc.set_passphrase(previous)
    assert came_back_while_held, "the encrypted read waited for a writer with a 0.3 s bound"
    assert timeouts == [0.3], f"the open of the log was given {timeouts}, not the 0.3 s bound (it pays it once per page-size candidate)"
    assert got["count"] is None and got["reason"], got


def test_a_failed_open_beside_a_rollback_journal_says_so_and_does_not_blame_the_passphrase(data, monkeypatch):
    import src.database.connect as dbc

    _record(1, late=True)
    (data / "custody_log.db-journal").write_bytes(b"\x00" * 64)

    class WrongPassphraseError(Exception):
        pass

    def refuse(*a, **k):
        raise WrongPassphraseError("driver words that must not be copied")

    monkeypatch.setattr(dbc, "connect", refuse)
    got = pending.late_reading()
    assert got["count"] is None
    assert got["reason"].startswith("WrongPassphraseError; a rollback journal is present"), got
    assert "driver words" not in got["reason"]


def test_the_moment_is_taken_when_the_read_ends_not_before_the_open_and_the_wait(data, monkeypatch):
    import src.database.connect as dbc

    _record(1, late=True)
    real = dbc.connect

    def slow(*a, **k):
        time.sleep(2.2)
        return real(*a, **k)

    monkeypatch.setattr(dbc, "connect", slow)
    started = datetime.now().astimezone()
    got = pending.late_reading()
    taken = datetime.fromisoformat(got["computed_at"])
    assert (taken - started).total_seconds() >= 1.0, "computed_at was stamped before the read it describes"
