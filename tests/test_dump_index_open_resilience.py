"""The dump-index _open must survive concurrent openers (macOS lane, 2026-07-09).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

`PRAGMA journal_mode=WAL` needs a moment with no other active connection; the
endpoint round-trip races build_index (worker thread) against a reader and the
observation lane hit `database is locked` on exactly that line. WAL is a
persistent file property, so _open now reads the mode lock-free, switches only
when needed, and never fails an index build over the optimization.
"""

from __future__ import annotations

import sqlite3

from src.wiki import dump_index


def test_open_succeeds_beside_an_active_reader_on_a_wal_file(tmp_path):
    path = tmp_path / "ix.db"
    first = dump_index._open(path)  # first open sets WAL once
    assert str(first.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    reader = sqlite3.connect(str(path))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM dump_index_meta").fetchone()
    try:
        again = dump_index._open(path)  # steady state: mode check only, no switch
        again.execute("SELECT count(*) FROM dump_index_meta").fetchone()
        again.close()
    finally:
        reader.rollback(); reader.close(); first.close()


def test_open_never_raises_when_the_mode_switch_is_locked_out(tmp_path, monkeypatch):
    # The CI-observed race: the index file exists (schema built) but sits in
    # rollback mode, and a concurrent READER holds a shared lock — the WAL switch
    # cannot get its exclusive moment. _open must degrade to rollback mode and
    # serve the index, never raise (the pragma is an optimization).
    monkeypatch.setattr(dump_index, "_BUSY_TIMEOUT_MS", 100)
    path = tmp_path / "ix.db"
    dump_index._open(path).close()  # build the schema (file becomes WAL)
    raw = sqlite3.connect(str(path))
    raw.execute("PRAGMA journal_mode=DELETE")  # force back to rollback mode
    raw.close()
    reader = sqlite3.connect(str(path))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM dump_index_meta").fetchone()  # holds SHARED
    try:
        conn = dump_index._open(path)  # WAL switch is locked out -> except path
        mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        assert mode != "wal"  # honestly still rollback mode - and fully usable:
        conn.execute("SELECT count(*) FROM dump_index_meta").fetchone()
        conn.close()
    finally:
        reader.rollback(); reader.close()
