"""
Tests for SQLite backup & restore.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The destructive path is exercised against a TEMP engine (monkeypatched in), so a
test run never touches the developer's real corpus. Proves: a backup round-trips
its rows; an unrelated/corrupt file is rejected before any overwrite; and a real
restore swaps the file while leaving a recoverable pre-restore snapshot.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine

import src.database.session as session_mod
from src.backup import sqlite_backup
from src.database.models import Base


@pytest.fixture()
def temp_engine(tmp_path, monkeypatch):
    """Point the live engine at a fresh on-disk SQLite DB with core tables + a row."""
    db_file = tmp_path / "live.db"
    eng = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO sources (name, domain, enabled, priority) VALUES ('T','t.test',1,2)"
        )
        conn.commit()
    monkeypatch.setattr(session_mod, "engine", eng)
    yield eng, tmp_path
    eng.dispose()


def test_backup_roundtrips_rows(temp_engine, tmp_path):
    _eng, _ = temp_engine
    dest = tmp_path / "snap.db"
    sqlite_backup.backup_to(dest)
    assert dest.exists() and dest.stat().st_size > 0
    # The snapshot is itself a valid OO database carrying the row we inserted.
    assert sqlite_backup.validate_sqlite_file(dest) >= 2
    conn = sqlite3.connect(str(dest))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
    finally:
        conn.close()
    assert n == 1


def test_validate_rejects_non_sqlite(tmp_path):
    bogus = tmp_path / "notdb.db"
    bogus.write_bytes(b"this is definitely not a sqlite file" * 10)
    with pytest.raises(sqlite_backup.BackupError):
        sqlite_backup.validate_sqlite_file(bogus)


def test_validate_rejects_unrelated_sqlite(tmp_path):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(str(other))
    conn.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite_backup.BackupError, match="missing tables"):
        sqlite_backup.validate_sqlite_file(other)


def test_restore_swaps_file_and_keeps_snapshot(temp_engine, tmp_path):
    eng, data_dir = temp_engine

    # Build a DIFFERENT valid OO database (two sources) to restore from.
    incoming = tmp_path / "incoming.db"
    ieng = create_engine(f"sqlite:///{incoming}", future=True)
    Base.metadata.create_all(ieng)
    with ieng.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO sources (name, domain, enabled, priority) "
            "VALUES ('A','a.test',1,2), ('B','b.test',1,2)"
        )
        conn.commit()
    ieng.dispose()
    payload = incoming.read_bytes()

    report = sqlite_backup.restore_from_bytes(payload)

    # Live DB now has the restored two rows.
    live = sqlite_backup.live_db_path()
    conn = sqlite3.connect(str(live))
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
    finally:
        conn.close()
    assert n == 2

    # A recoverable pre-restore snapshot (the original single row) exists.
    from pathlib import Path

    snap = Path(report.pre_restore_snapshot)
    assert snap.exists()
    conn = sqlite3.connect(str(snap))
    try:
        (orig,) = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
    finally:
        conn.close()
    assert orig == 1


def test_bad_restore_leaves_live_untouched(temp_engine, tmp_path):
    eng, _ = temp_engine
    live = sqlite_backup.live_db_path()
    before = live.read_bytes()
    with pytest.raises(sqlite_backup.BackupError):
        sqlite_backup.restore_from_bytes(b"corrupt blob, not a database")
    # Nothing was overwritten.
    assert live.read_bytes() == before
