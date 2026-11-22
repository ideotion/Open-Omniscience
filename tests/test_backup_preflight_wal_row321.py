"""Row 321: the backup's free-space preflight counts each store's write-ahead log.

The app runs its store in WAL mode, so recent commits sit in ``<store>-wal`` until a checkpoint and the
snapshot copies them. A preflight that measured the main file alone could pass with a large log pending and the
backup then fail on a full disk part-way through. These tests build REAL WAL stores (plaintext and SQLCipher) with
a large log held open by a live connection, and check that the preflight refuses where the main file alone would
have let it through, for the corpus and for the custody log. The log is read by stat only (R789): an audit hook
records any open of the store's files while the preflight runs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.backup import artifact as art
from src.backup.artifact import BackupSpaceError

KEY = "a passphrase that is long enough"

# Paths whose open() is recorded while ``_WATCH`` is non-empty (an audit hook cannot be removed, so it stays
# inert outside these tests).
_WATCH: list[str] = []
_OPENED: list[str] = []


def _audit(event: str, args: tuple) -> None:
    if _WATCH and event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0])
        if any(name.startswith(w) for w in _WATCH):
            _OPENED.append(name)


sys.addaudithook(_audit)


def _wal_store(path: Path, *, encrypted: bool, log_bytes: int = 2_000_000):
    """A WAL store at ``path`` whose commits stay in ``-wal``: the returned connection holds it open with the
    automatic checkpoint off, so the log is still there while the test runs. The caller closes it."""
    if encrypted:
        pytest.importorskip("sqlcipher3")
    from src.database.connect import connect

    conn = connect(
        str(path),
        key=KEY if encrypted else None,
        check_same_thread=False,
        timeout=30,
        create_encrypted=encrypted,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t (b BLOB)")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    chunk = os.urandom(50_000)
    for _ in range(max(1, log_bytes // len(chunk))):
        conn.execute("INSERT INTO t VALUES (?)", (chunk,))
        conn.commit()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    return conn


def _sizes(path: Path) -> tuple[int, int]:
    return path.stat().st_size, Path(str(path) + "-wal").stat().st_size


def _patch_paths(monkeypatch, tmp_path: Path, live: Path) -> Path:
    import src.backup.sqlite_backup as sb

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(sb, "live_db_path", lambda: live)
    monkeypatch.setattr(art, "data_dir", lambda: data)
    return data


def _refuses(monkeypatch, tmp_path: Path, free: int, watch: Path) -> None:
    import src.backup.folder_backup as fb

    monkeypatch.setattr(fb, "free_bytes", lambda p: free)
    out = tmp_path / "out"
    out.mkdir()
    _WATCH.append(str(watch))
    try:
        with pytest.raises(BackupSpaceError):
            art.write_backup_v2(out / "b.oo-backup-2", passphrase=KEY)
    finally:
        _WATCH.clear()
    assert _OPENED == [], f"the preflight opened a live store file: {_OPENED}"
    # It refused before staging anything.
    assert not any(p.name.startswith(".bak-build-") for p in out.iterdir())


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_corpus_log_counts_toward_the_room_needed(tmp_path, monkeypatch, encrypted):
    live = tmp_path / "open_omniscience.db"
    conn = _wal_store(live, encrypted=encrypted)
    try:
        main, wal = _sizes(live)
        assert wal > 10 * main, (main, wal)  # the log really is the bulk of the store
        assert art._store_bytes(live) == main + wal
        _patch_paths(monkeypatch, tmp_path, live)
        # Room for the main file alone (the old measure), not for main + log.
        free = (main + wal) * art._BUILD_SPACE_FACTOR - 1
        assert free > main * art._BUILD_SPACE_FACTOR
        _OPENED.clear()
        _refuses(monkeypatch, tmp_path, free, live)
    finally:
        conn.close()


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_custody_log_counts_toward_the_room_needed(tmp_path, monkeypatch, encrypted):
    live = tmp_path / "open_omniscience.db"
    live.write_bytes(b"Z" * 4096)  # a small corpus; the custody log is what tips it
    data = _patch_paths(monkeypatch, tmp_path, live)
    custody = data / art._CUSTODY_DB
    conn = _wal_store(custody, encrypted=encrypted)
    try:
        main, wal = _sizes(custody)
        assert wal > 10 * main, (main, wal)
        free = (4096 + main + wal) * art._BUILD_SPACE_FACTOR - 1
        assert free > (4096 + main) * art._BUILD_SPACE_FACTOR
        _OPENED.clear()
        _refuses(monkeypatch, tmp_path, free, custody)
    finally:
        conn.close()


def test_store_bytes_is_stat_only_and_ignores_shm_and_missing_files(tmp_path):
    store = tmp_path / "s.db"
    assert art._store_bytes(store) == 0  # nothing there
    store.write_bytes(b"a" * 100)
    Path(str(store) + "-shm").write_bytes(b"s" * 32768)  # the shared-memory index is not data
    assert art._store_bytes(store) == 100
    Path(str(store) + "-wal").write_bytes(b"w" * 700)
    _OPENED.clear()
    _WATCH.append(str(store))
    try:
        assert art._store_bytes(store) == 800
    finally:
        _WATCH.clear()
    assert _OPENED == []
    store.unlink()
    assert art._store_bytes(store) == 700  # a log without its main file still occupies the disk


# --------------------------------------------------------------------------- #
# Part 2: the diagnostics report the log as its own figure, and db_bytes keeps meaning the main file alone.


def test_wal_file_bytes_reads_the_log_by_stat_only(tmp_path):
    from src.paths import wal_file_bytes

    store = tmp_path / "open_omniscience.db"
    assert wal_file_bytes(store) is None  # no store: no figure, as db_bytes
    store.write_bytes(b"a" * 100)
    assert wal_file_bytes(store) == 0  # no log (rollback journal, or a checkpoint removed it)
    Path(str(store) + "-wal").write_bytes(b"w" * 700)
    _OPENED.clear()
    _WATCH.append(str(store))
    try:
        assert wal_file_bytes(store) == 700
    finally:
        _WATCH.clear()
    assert _OPENED == []


def _live_figures(live: Path) -> tuple[int, int]:
    return live.stat().st_size, Path(str(live) + "-wal").stat().st_size


def test_benchmark_store_reports_wal_bytes_apart_from_db_bytes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import src.paths as paths
    from src.api.main import app
    from src.database.session import SessionLocal
    from src.monitoring import benchmark

    with TestClient(app):  # the app's own start-up builds the schema the corpus figures read
        pass

    live = tmp_path / "open_omniscience.db"
    conn = _wal_store(live, encrypted=False, log_bytes=300_000)
    try:
        monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
        main, wal = _live_figures(live)
        with SessionLocal() as s:
            store, _corpus = benchmark._store_and_corpus(s)
        assert store["db_bytes"] == main
        assert store["wal_bytes"] == wal > 0
    finally:
        conn.close()


def test_performance_report_carries_wal_bytes_beside_db_bytes():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/diagnostics/performance", params={"selftest": "false"})
    assert r.status_code == 200
    store = r.json()["data"]["store"]
    assert "db_bytes" in store and "wal_bytes" in store
    if store["db_bytes"] is None:
        assert store["wal_bytes"] is None
    else:
        assert isinstance(store["wal_bytes"], int) and store["wal_bytes"] >= 0


def test_debug_bundle_environment_carries_wal_bytes():
    import inspect

    from src.api.diagnostics import bundle

    src = inspect.getsource(bundle)
    assert '"db_bytes": db_file.stat().st_size if db_file.exists() else None,' in src
    assert '"wal_bytes": wal_file_bytes(db_file),' in src
