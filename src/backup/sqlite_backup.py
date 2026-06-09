"""
Honest, consistent SQLite backup & restore for the unified store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A journalist's corpus is evidence; losing or corrupting it is unacceptable, so
both directions are done safely and verifiably rather than by naively copying a
file that may be mid-write:

  * **Backup** uses SQLite's online backup API (``Connection.backup``), which
    produces a single, internally-consistent snapshot file even while the WAL is
    active and the app is running. No app downtime, no half-written page.
  * **Restore** is destructive, so it is *defensive*: the uploaded file is first
    validated (real SQLite header, ``quick_check`` passes, core tables present);
    only then is the current database snapshotted to a timestamped
    ``pre-restore-*.db`` and atomically replaced. If validation fails, nothing is
    touched and an explicit error is raised -- we never overwrite a good corpus
    with an unverified blob.

This is SQLite-specific by design. For a PostgreSQL deployment the caller must
refuse rather than pretend (see :func:`is_sqlite`); ``pg_dump`` is the right tool
there and is out of scope for this local-first build.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Tables that any genuine Open Omniscience database must contain. Used to reject
# an unrelated SQLite file (e.g. someone's Firefox places.sqlite) before it can
# clobber the live corpus.
_REQUIRED_TABLES = ("articles", "sources")


class BackupError(RuntimeError):
    """Raised when a backup or restore cannot be performed safely."""


@dataclass
class RestoreReport:
    restored_from_bytes: int
    pre_restore_snapshot: str
    tables_seen: int


def is_sqlite() -> bool:
    """True when the live engine is backed by an on-disk SQLite file."""
    from src.database.session import engine

    return (
        engine.url.get_backend_name() == "sqlite"
        and bool(engine.url.database)
        and engine.url.database != ":memory:"
    )


def live_db_path() -> Path:
    """Absolute path of the live SQLite database file."""
    from src.database.session import engine

    if not is_sqlite():
        raise BackupError(
            "Backup/restore is only supported for the SQLite backend; this "
            f"deployment uses {engine.url.get_backend_name()!r}. Use the backend's "
            "native dump tool (e.g. pg_dump) instead."
        )
    return Path(engine.url.database).resolve()


def backup_to(dest: Path) -> Path:
    """Write a consistent snapshot of the live database to ``dest``.

    Uses the online backup API so the snapshot is valid even with concurrent
    readers/writers and an active WAL. Returns ``dest``.
    """
    src_path = live_db_path()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Connect to the real file (not through SQLAlchemy) for the backup API.
    src_conn = sqlite3.connect(str(src_path))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)  # atomic, page-consistent copy
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return dest


def validate_sqlite_file(path: Path) -> int:
    """Validate ``path`` is a healthy Open Omniscience SQLite DB.

    Returns the number of tables seen. Raises :class:`BackupError` if the file is
    not a valid SQLite database, fails an integrity quick-check, or is missing the
    required core tables (so we never restore from an unrelated file).
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise BackupError("uploaded file is empty or missing")
    try:
        # Read-only URI connection: never mutate the candidate file.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        raise BackupError(f"cannot open uploaded file as SQLite: {exc}") from exc
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError(f"integrity check failed: {check[0] if check else 'unknown'}")
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"not a valid SQLite database: {exc}") from exc
    finally:
        conn.close()

    missing = [t for t in _REQUIRED_TABLES if t not in names]
    if missing:
        raise BackupError(
            "this does not look like an Open Omniscience backup "
            f"(missing tables: {', '.join(missing)})"
        )
    return len(names)


def restore_from_bytes(data: bytes) -> RestoreReport:
    """Atomically replace the live database with ``data`` after validating it.

    Steps (fail-safe ordering): write to a temp file in the data dir, validate it,
    snapshot the current DB to ``pre-restore-<ts>.db``, dispose the engine pool,
    swap the file into place (removing stale -wal/-shm), then rebuild schema/FTS
    state. The pre-restore snapshot path is returned so the operator can roll back.
    """
    from src.database.session import dispose_engine, init_db

    target = live_db_path()
    data_dir = target.parent

    # 1. Stage the upload in the same directory (so os.replace is atomic).
    fd, tmp_name = tempfile.mkstemp(prefix=".restore-", suffix=".db", dir=str(data_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)

        # 2. Validate BEFORE touching the live file.
        tables_seen = validate_sqlite_file(tmp_path)

        # 3. Snapshot the current corpus so a bad restore is recoverable.
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        snapshot = data_dir / f"pre-restore-{ts}.db"
        backup_to(snapshot)

        # 4. Release pooled connections, then swap files atomically.
        dispose_engine()
        for suffix in ("-wal", "-shm"):
            stale = target.with_name(target.name + suffix)
            if stale.exists():
                stale.unlink()
        os.replace(tmp_path, target)  # atomic on the same filesystem
        tmp_path = None  # consumed

        # 5. Reconcile schema/FTS on the restored file (idempotent).
        init_db()
        return RestoreReport(
            restored_from_bytes=len(data),
            pre_restore_snapshot=str(snapshot),
            tables_seen=tables_seen,
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
