"""
Read-only WAL snapshot for heavy exports (field finding C).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the export path: a dedicated query_only connection that CANNOT write (so it
never takes the write gate or stalls a writer), reads ONE consistent WAL snapshot for
its whole duration (so a racing write can neither corrupt nor stall it), and does not
block a concurrent writer.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.database.read_snapshot import (
    dispose_read_engines,
    read_snapshot_session,
)


@pytest.fixture()
def wal_db(tmp_path):
    """A plaintext WAL SQLite file with a seeded table."""
    path = tmp_path / "c.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (id, v) VALUES (?, ?)", [(i, f"row{i}") for i in range(5)])
    con.commit()
    con.close()
    url = f"sqlite:///{path}"
    yield path, url
    dispose_read_engines()


def test_read_snapshot_is_query_only(wal_db):
    _, url = wal_db
    with read_snapshot_session(url) as rdb:
        assert rdb.execute(text("SELECT COUNT(*) FROM t")).scalar() == 5
        # A write on this connection is refused BY CONSTRUCTION (PRAGMA query_only=ON),
        # so the export can never take the write gate or block the collector.
        with pytest.raises(OperationalError):
            rdb.execute(text("INSERT INTO t (id, v) VALUES (99, 'x')"))
            rdb.commit()


def test_export_snapshot_is_consistent_under_a_concurrent_write(wal_db):
    """An export racing a write loses nothing + doesn't see a torn mid-scan state:
    the snapshot is pinned at the first read and stays consistent while a writer commits.
    """
    path, url = wal_db
    with read_snapshot_session(url) as rdb:
        first = rdb.execute(text("SELECT COUNT(*) FROM t")).scalar()  # pins the WAL snapshot
        assert first == 5

        # A concurrent writer commits new rows on its own connection — WAL lets it pass
        # the reader; no "database is locked".
        w = sqlite3.connect(path, timeout=30)
        try:
            w.execute("PRAGMA busy_timeout=30000")
            w.executemany("INSERT INTO t (id, v) VALUES (?, ?)", [(10, "a"), (11, "b")])
            w.commit()
        finally:
            w.close()

        # The export's ongoing scan still sees its ORIGINAL consistent snapshot (5),
        # never a half-written view — the whole point of one held snapshot.
        again = rdb.execute(text("SELECT COUNT(*) FROM t")).scalar()
        assert again == 5

    # After the snapshot is released, a fresh read sees the writer's rows: nothing lost.
    with read_snapshot_session(url) as rdb2:
        assert rdb2.execute(text("SELECT COUNT(*) FROM t")).scalar() == 7


def test_reader_does_not_block_a_writer(wal_db):
    """A long-lived export snapshot must not stall the collector's writes."""
    path, url = wal_db
    wrote = threading.Event()

    def _writer():
        w = sqlite3.connect(path, timeout=30)
        try:
            w.execute("PRAGMA busy_timeout=30000")
            w.execute("INSERT INTO t (id, v) VALUES (42, 'concurrent')")
            w.commit()
            wrote.set()
        finally:
            w.close()

    with read_snapshot_session(url) as rdb:
        rdb.execute(text("SELECT COUNT(*) FROM t")).scalar()  # hold a read snapshot open
        t = threading.Thread(target=_writer)
        t.start()
        t.join(timeout=15)
        # The writer completed while the export snapshot was held open (WAL, not blocked).
        assert wrote.is_set(), "the export snapshot blocked a concurrent writer"
