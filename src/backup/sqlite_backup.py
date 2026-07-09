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
  * **Restore is ADDITIVE-ONLY** (maintainer-ruled 2026-06-13): a restore must
    NEVER replace the corpus. The ONLY restore is the merge engine
    (:mod:`src.backup.merge` / the ``/api/database/v2/restore`` endpoints), which
    complements the live corpus duplicate-lessly and can refuse, but never
    overwrites. The old destructive "replace the live file" path has been
    REMOVED from this module so no flow can clobber a journalist's evidence.
    The validators below (``validate_sqlite_file``) are reused by the merge.

This is SQLite-specific by design. For a PostgreSQL deployment the caller must
refuse rather than pretend (see :func:`is_sqlite`); ``pg_dump`` is the right tool
there and is out of scope for this local-first build.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Tables that any genuine Open Omniscience database must contain. Used to reject
# an unrelated SQLite file (e.g. someone's Firefox places.sqlite) before it can
# clobber the live corpus.
_REQUIRED_TABLES = ("articles", "sources")


class BackupError(RuntimeError):
    """Raised when a backup or restore cannot be performed safely."""


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
    """Write a consistent snapshot of a PLAINTEXT live database to ``dest``
    (online backup API: WAL-safe, page-consistent).

    An ENCRYPTED live store REFUSES loudly (P0.1, 2026-07-09): exporting it here
    meant decrypting the WHOLE corpus into a plaintext temp file — an
    at-rest-encryption violation and, at field scale (11.7 GB on a 10 GB VM,
    /tmp = tmpfs on the reference Qubes machine), an OOM/disk-death on a
    single click. The supported encrypted-corpus backup is the streaming
    volumes+parity export (Settings -> Export / write_volume_backup), which
    never decrypts the corpus at all. Callers that need a snapshot KEEPING the
    live encryption state use ``connect.snapshot_preserving``.
    """
    from src.database.connect import is_encrypted_file, snapshot_to_plaintext

    src = live_db_path()
    if is_encrypted_file(src):
        raise BackupError(
            "the corpus is encrypted: this legacy download would decrypt the whole "
            "database into a plaintext file (an at-rest-encryption violation, and an "
            "out-of-memory/disk crash at field scale). Use the streaming encrypted "
            "backup instead (Settings -> Export / the volumes+parity backup) — it "
            "never decrypts the corpus."
        )
    return snapshot_to_plaintext(src, Path(dest))


def validate_sqlite_file(path: Path) -> int:
    """Validate ``path`` is a healthy Open Omniscience SQLite DB.

    Returns the number of tables seen. Raises :class:`BackupError` if the file is
    not a valid SQLite database, fails an integrity quick-check, or is missing the
    required core tables (so we never restore from an unrelated file).
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise BackupError("uploaded file is empty or missing")
    from src.database.connect import is_encrypted_file

    if is_encrypted_file(path):
        raise BackupError(
            "this file is an ENCRYPTED database (raw SQLCipher bytes). Restore the "
            ".oobak.ooenc backup artifact instead -- raw encrypted files cannot be "
            "validated or merged without their original context"
        )
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


# NOTE: ``restore_from_bytes`` (the destructive "atomically replace the live
# database" path) was REMOVED on 2026-06-13 (maintainer ruling: restore is
# additive-only). Restoring now goes exclusively through the merge engine
# (:mod:`src.backup.merge`), which complements the corpus and never overwrites it.
# Do not reintroduce a replace-restore here — the guard test
# tests/test_additive_restore_only.py fails the build if one reappears.
