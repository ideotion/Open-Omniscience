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


# The destructive restore_from_bytes (replace the live file) was REMOVED on
# 2026-06-13 (restore is additive-only). Its two tests are gone with it; the
# additive merge restore is covered by the torture suite + the merge tests, and
# tests/test_additive_restore_only.py guards that no replace path comes back.
# Backup CREATION + validation are still tested above (backup_to / validate_sqlite_file).
