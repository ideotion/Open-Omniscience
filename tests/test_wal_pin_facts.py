"""The measured facts the storage guard is built on, pinned against real SQLite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics of 16 instances (2026-09-30) found the corpus ``-wal`` at 18.7 to 42.9 GB on six
machines. The design that followed (``src/scheduler/storage_guard.py``) rests on four facts about
SQLite that were MEASURED, not assumed, and that a future SQLite (or a future reading of the
documentation) could quietly change. They are pinned here against the real library, with no
mocks, so a change in the premise fails a test instead of shipping a guard for a problem that
has moved:

1. A reader holding a snapshot makes the WAL unresettable: ``PRAGMA wal_checkpoint(TRUNCATE)``
   comes back busy and the file keeps its size, while writers keep appending to it.
2. ``PASSIVE`` backfills only up to that reader's mark, so it cannot bound the file either.
3. The pin is invisible to ``sqlite3.Connection.in_transaction`` when it is an open SELECT
   cursor -- so no pool-level "is this checkout in a transaction" flag can find it, and the
   pin report has to NAME the holder instead (thread, age, stack).
4. Once the reader ends, one TRUNCATE takes the file to zero and the next write does not regrow
   it. So a bounded pause (stop the writers, wait for the reader) is self-healing.

Autocheckpoint is switched OFF on every connection so that only the explicit checkpoints under
test move the file (the facts are about explicit checkpoints; ``wal_autocheckpoint`` is left
alone in production).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_ROW = b"x" * 3000  # one row ~ one 4 KiB page


def _open(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    # Zero, as the pass boundary's own checkpoint runs it (hygiene._ckpt_busy_timeout_ms): the
    # default busy handler would make every busy TRUNCATE below wait its full 5 s for nothing.
    c.execute("PRAGMA busy_timeout=0")
    return c


def _burst(w: sqlite3.Connection, n: int = 256) -> None:
    """About 1 MiB of WAL: n rows of ~one page each, in one transaction."""
    w.execute("BEGIN")
    w.executemany("INSERT INTO t(b) VALUES (?)", [(_ROW,)] * n)
    w.execute("COMMIT")


def _wal(path: Path) -> int:
    p = Path(str(path) + "-wal")
    return p.stat().st_size if p.exists() else 0


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "pin.db"
    w = _open(path)
    w.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    _burst(w)
    yield path, w
    w.close()


def _truncate(w: sqlite3.Connection) -> tuple[int, int, int]:
    return w.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()


def test_an_unpinned_wal_resets_to_zero(store):
    path, w = store
    assert _wal(path) > 0
    busy, _log, _ck = _truncate(w)
    assert busy == 0
    assert _wal(path) == 0


def test_a_finished_select_does_not_pin(store):
    """A read that ran to completion (fetchall) leaves nothing behind: pysqlite's autocommit
    read ends its snapshot with the statement. This is the ordinary API request."""
    path, w = store
    r = _open(path)
    try:
        r.execute("SELECT id FROM t").fetchall()
        _burst(w)
        busy, _log, _ck = _truncate(w)
        assert busy == 0
        assert _wal(path) == 0
    finally:
        r.close()


def test_an_open_select_cursor_pins_the_wal_and_truncate_is_busy(store):
    path, w = store
    r = _open(path)
    cur = r.execute("SELECT id FROM t")
    cur.fetchone()  # the statement is now mid-flight: a snapshot is held
    try:
        _burst(w)
        before = _wal(path)
        assert before > 0
        busy, _log, _ck = _truncate(w)
        assert busy == 1, "TRUNCATE must report busy while a reader holds a snapshot"
        assert _wal(path) == before, "a busy TRUNCATE must not have reset the file"
    finally:
        cur.close()
        r.close()


def test_a_pinned_wal_keeps_growing_under_writers_and_passive_cannot_bound_it(store):
    path, w = store
    r = _open(path)
    cur = r.execute("SELECT id FROM t")
    cur.fetchone()
    try:
        sizes = []
        for _ in range(4):
            _burst(w)
            # PASSIVE never waits and never blocks, and is the most the checkpointer can do.
            w.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            sizes.append(_wal(path))
        assert sizes == sorted(sizes) and sizes[-1] > sizes[0], (
            f"the file must grow by appending while pinned, got {sizes}"
        )
        busy, log, ck = w.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        assert ck < log, "PASSIVE backfills only up to the reader's mark, never the whole log"
    finally:
        cur.close()
        r.close()


def test_a_begin_transaction_pins_the_same_way(store):
    path, w = store
    r = _open(path)
    r.execute("BEGIN")
    r.execute("SELECT count(*) FROM t").fetchall()
    try:
        _burst(w)
        busy, _log, _ck = _truncate(w)
        assert busy == 1
    finally:
        r.execute("ROLLBACK")
        r.close()


def test_in_transaction_cannot_see_a_cursor_pin():
    """pysqlite's ``in_transaction`` is False for an open SELECT cursor and True only after a
    BEGIN -- which is why the pin report names threads and stacks rather than testing a flag."""
    c = sqlite3.connect(":memory:")  # default isolation_level: the legacy implicit-BEGIN mode
    try:
        c.execute("CREATE TABLE t(x)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(10)])
        c.commit()
        cur = c.execute("SELECT x FROM t")
        cur.fetchone()
        assert c.in_transaction is False, "an open SELECT cursor is invisible to in_transaction"
        cur.close()
        c.execute("BEGIN")
        assert c.in_transaction is True
        c.execute("ROLLBACK")
    finally:
        c.close()


def test_once_the_reader_ends_one_truncate_resets_and_the_next_write_does_not_regrow(store):
    path, w = store
    r = _open(path)
    cur = r.execute("SELECT id FROM t")
    cur.fetchone()
    for _ in range(3):
        _burst(w)
    pinned = _wal(path)
    assert _truncate(w)[0] == 1
    cur.close()
    r.close()

    busy, _log, _ck = _truncate(w)
    assert busy == 0
    assert _wal(path) == 0, "the reset is complete, not partial"
    _burst(w)
    assert _wal(path) < pinned, "a write after the reset restarts the log instead of regrowing it"


# --------------------------------------------------------------------------- #
#  5. The status probe's pinned connection (insights._data_version) is idle, not a pin
# --------------------------------------------------------------------------- #
def test_an_idle_data_version_probe_connection_does_not_pin_the_wal(store):
    """The standing "one API-thread checkout held for the whole process life" on all 16
    field instances is ``insights._data_version``'s deliberately pinned probe connection
    (``PRAGMA data_version`` only reports other connections' commits on a LONG-LIVED
    connection). The suspicion was that it pins the WAL. It does not: after the pragma's one
    row is read and its cursor closed, the connection holds no read snapshot, so writers
    keep committing, the probe still sees them, and TRUNCATE is not busy. Real SQLite, the
    probe's own calls, default pysqlite isolation (the probe never sets one)."""
    path, w = store
    probe = sqlite3.connect(path, check_same_thread=False)  # default isolation, like the probe
    probe.execute("PRAGMA busy_timeout=0")

    def read_version() -> int:
        cur = probe.cursor()
        try:
            cur.execute("PRAGMA data_version")
            return cur.fetchone()[0]
        finally:
            cur.close()

    v0 = read_version()
    for _ in range(3):
        _burst(w)
    assert _wal(path) > 1 * 1024 * 1024
    assert read_version() != v0, "the probe must still observe another connection's commits"
    busy, _log, _ck = _truncate(w)
    assert busy == 0, "an idle probe connection must not make TRUNCATE busy"
    assert _wal(path) == 0
    probe.close()


# --- what a pooled CHECKOUT pins, by what the checkout did (the Opus read of the findings PR, S2) ---------
#
# The pin report lists checked-out connections; it can only call them CANDIDATES. These are the measured
# facts that say which checkouts ARE holders, on the driver's own default (legacy) transaction mode, which is
# what the corpus pool runs, and on an engine that issues an explicit BEGIN, which is what the export's
# read-only snapshot engine (``pool: read_snapshot``) does.

_DRIVERS = ["sqlite3", "sqlcipher3"]


def _legacy_pair(tmp_path, driver: str):
    mod = pytest.importorskip(driver + ("" if driver == "sqlite3" else ".dbapi2"))
    path = tmp_path / f"legacy-{driver}.db"

    def conn(**kw):
        c = mod.connect(str(path), check_same_thread=False, **kw)  # default isolation_level: legacy mode
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute("PRAGMA busy_timeout=0")
        return c

    w = conn(isolation_level=None)
    w.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, b BLOB)")
    _burst(w)
    return path, w, conn


@pytest.mark.parametrize("driver", _DRIVERS)
def test_a_legacy_mode_checkout_that_only_read_and_fetched_pins_nothing(tmp_path, driver):
    path, w, conn = _legacy_pair(tmp_path, driver)
    r = conn()  # a pooled checkout: held, not returned
    try:
        r.execute("SELECT id FROM t").fetchall()
        _burst(w)
        assert _truncate(w)[0] == 0, "a checkout that only read, and fetched, held the log"
    finally:
        r.close()
        w.close()


@pytest.mark.parametrize("driver", _DRIVERS)
def test_a_checkout_with_an_uncommitted_write_pins_until_it_commits(tmp_path, driver):
    """Legacy mode starts a transaction on the first INSERT/UPDATE/DELETE: the checkout then holds the write
    lock, and the log cannot be reset, for as long as it has not committed."""
    path, w, conn = _legacy_pair(tmp_path, driver)
    r = conn()
    try:
        r.execute("INSERT INTO t(b) VALUES (?)", (_ROW,))  # implicit BEGIN, never committed
        assert r.in_transaction is True
        assert _truncate(w)[0] == 1, "an uncommitted write did not stop the checkpoint"
        r.commit()
        assert _truncate(w)[0] == 0
    finally:
        r.close()
        w.close()


@pytest.mark.parametrize("driver", _DRIVERS)
def test_an_engine_that_issues_begin_holds_its_snapshot_from_the_first_read_to_the_end(tmp_path, driver):
    """``read_snapshot``'s engine emits BEGIN itself, so ITS checkout is the holder even when every statement
    has been fetched: the legacy-mode sentence in the pin report does not apply to that row."""
    path, w, conn = _legacy_pair(tmp_path, driver)
    r = conn(isolation_level=None)
    try:
        r.execute("BEGIN")
        r.execute("SELECT id FROM t").fetchall()
        _burst(w)
        assert _truncate(w)[0] == 1, "a BEGIN-ed snapshot reader did not hold the log"
        r.execute("COMMIT")
        assert _truncate(w)[0] == 0
    finally:
        r.close()
        w.close()
