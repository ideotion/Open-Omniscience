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


# --------------------------------------------------------------------------- #
# The manifest's "excluded" block (D3: an omission is listed, never silent)
# --------------------------------------------------------------------------- #
def test_the_two_big_directories_inside_data_dir_are_named_as_excluded(
    tmp_path, monkeypatch
):
    """``models/`` (AI weights) and ``cache/`` (the vLLM server's Triton/Inductor/CUDA
    caches) both moved INSIDE ``data_dir()`` in 2026-08. Neither is collected as a
    member -- ``_collect_members`` is an explicit allowlist -- so both were being left
    out correctly and not SAID, which is the silence this block exists to prevent.

    They are the two largest things an operator finds in that folder, so a backup that
    quietly omits them owes the reason and the way back."""
    from src.backup import artifact

    monkeypatch.setattr(artifact, "data_dir", lambda: tmp_path)
    for sub in ("models/ollama", "cache/triton"):
        d = tmp_path / sub
        d.mkdir(parents=True)
        (d / "blob").write_bytes(b"x" * 16)

    named = {e["name"]: e for e in artifact._excluded_inventory()}
    assert "models" in named and "cache" in named
    assert named["models"]["bytes"] == 16 and named["models"]["files"] == 1
    # Each states WHY and what to do about it -- weights come back, caches rebuild.
    assert "re-download" in named["models"]["reason"]
    assert "rebuilt" in named["cache"]["reason"]


def test_an_empty_or_absent_directory_is_not_listed_as_an_omission(tmp_path, monkeypatch):
    """The twin. Reporting an omission that never happened is a fabricated gap, and it
    reads as badly as a hidden one.

    BOTH cases, because they are guarded separately and only the second is interesting:
    an ABSENT folder never reaches the size walk, while an EMPTY one does -- and the app
    creates ``models/`` at launch whether or not anything was ever downloaded, so
    "exists, holds nothing" is the normal state on a machine with no local AI. A first
    draft of this test used the absent case alone and could not fail: removing the
    ``if files`` guard left it green, because ``is_dir()`` had already short-circuited."""
    from src.backup import artifact

    monkeypatch.setattr(artifact, "data_dir", lambda: tmp_path)
    assert artifact._excluded_inventory() == [], "absent"

    (tmp_path / "models" / "huggingface" / "hub").mkdir(parents=True)
    (tmp_path / "cache").mkdir()
    assert artifact._excluded_inventory() == [], "present but empty"
