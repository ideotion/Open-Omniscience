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
    (:mod:`src.backup.merge` / the ``/api/backup/import-queue`` + ``legacy/restore``
    endpoints), which
    complements the live corpus duplicate-lessly and can refuse, but never
    overwrites. The old destructive "replace the live file" path has been
    REMOVED from this module so no flow can clobber a journalist's evidence.
    The validators below (``validate_sqlite_file``) are reused by the merge.

This is SQLite-specific by design. For a PostgreSQL deployment the caller must
refuse rather than pretend (see :func:`is_sqlite`); ``pg_dump`` is the right tool
there and is out of scope for this local-first build.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from src.monitoring.secret_scrub import record_text

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
    # `url.database` is None for a pure in-memory SQLite URL ("sqlite://"), which has
    # no file to snapshot. Named here rather than left to fail as `Path(None)` deep in
    # a backup run -- the same shape as the non-SQLite refusal above.
    if engine.url.database is None:
        raise BackupError(
            "This deployment uses an in-memory SQLite database, which has no file to "
            "back up. Point OO_DATA_DIR at a real database first."
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


#: The memory map the validation walk asks for. The stdlib driver caps it at 2 GiB whatever is asked; the cap is the
#: point of asking a fixed figure rather than the file size.
_VALIDATE_MMAP_BYTES = 2**31 - 2**16

#: One sequential read of the staged file is done in pieces of this size.
_WARM_CHUNK = 8 * 2**20


def _validate_warm_enabled() -> bool:
    return os.getenv("OO_VALIDATE_WARM", "1") != "0"


def _warm_sequentially(path: Path, should_stop: Callable[[], bool] | None = None) -> None:
    """Read ``path`` front to back once, so the page walk that follows finds it in the OS cache.

    ``PRAGMA quick_check`` visits a large file in b-tree order, which on disk is close to random: the field run
    (2026-11-15, a 10.7 GB staged file on a 7.9 GB machine) read 41 GB in 32 minutes for it. Measured in a
    sandbox at the same file-to-memory ratio (a 4.06 GB file, the process held to 3 GB of memory, reads held to
    150 MB/s and 1,500 operations a second): the plain walk took 660 s, a memory map alone 342 s, this read
    plus the memory map 63 s (27 s of it this read). It changes WHAT IS READ FIRST, never what is checked: the
    same ``quick_check`` runs on the same file, read-only. Best-effort: a failure here leaves the walk as it
    was. ``OO_VALIDATE_WARM=0`` turns both off. It does push other files out of the OS cache, which is why it
    runs only here, on the import's own staged copy. With the map, a READ ERROR on the staged file during the
    walk ends the process (a signal) where it used to refuse the import; the live store is untouched at this point
    either way, and ``OO_VALIDATE_WARM=0`` is the switch for a staging folder on an unreliable drive."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        return
    try:
        if hasattr(os, "posix_fadvise"):
            with suppress(OSError):
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
        while True:  # the guard-clause form keeps the back-edge inside the finally (src/utils/interrupts.py)
            if should_stop is not None and should_stop():
                break
            if not os.read(fd, _WARM_CHUNK):
                break
    except OSError:
        return
    finally:
        os.close(fd)


def validate_sqlite_file(
    path: Path,
    *,
    quick_check: bool = True,
    connection_cb: Callable[[sqlite3.Connection], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Validate ``path`` is a healthy Open Omniscience SQLite DB.

    Returns the number of tables seen. Raises :class:`BackupError` if the file is
    not a valid SQLite database, fails an integrity quick-check, or is missing the
    required core tables (so we never restore from an unrelated file).

    ``quick_check=False`` keeps the open and the required-tables look and leaves out the page walk: an
    import runs the walk itself, alongside its merge (R827 R3(a), ``merge._quick_check_alongside``), and
    refuses before the swap when it fails. ``connection_cb`` receives the open connection, so that caller
    can interrupt the walk from its own thread; ``should_stop`` is asked before the walk starts.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        raise BackupError("uploaded file is empty or missing")
    from src.backup.staged_key import db_errors, is_keyed, open_staged
    from src.database.connect import is_encrypted_file

    keyed = is_keyed(path)  # a staged copy the import keyed itself (R829 A): encrypted, and read with its key
    if not keyed and is_encrypted_file(path):
        raise BackupError(
            "this file is an ENCRYPTED database (raw SQLCipher bytes). Restore the "
            ".oobak.ooenc backup artifact instead -- raw encrypted files cannot be "
            "validated or merged without their original context"
        )
    errors = db_errors()
    try:
        # Read-only connection: never mutate the candidate file. Hardened for a foreign file (R829 A1).
        conn = open_staged(path)
    except errors as exc:  # pragma: no cover - defensive
        raise BackupError(f"cannot open uploaded file as SQLite: {record_text(exc)}") from None
    except Exception:  # noqa: BLE001 - StagedKeyError: fixed words of its own, never a key
        raise BackupError("the staged copy of the backup could not be opened with its key") from None
    try:
        if connection_cb is not None:
            connection_cb(conn)
        if quick_check:
            if _validate_warm_enabled():
                # Same check, read in a cheaper order (P1.3, measured 2026-11-15): see _warm_sequentially.
                _warm_sequentially(path, should_stop)
                if not keyed:  # SQLCipher reads through its own page cipher, never a map
                    with suppress(*errors):
                        conn.execute(f"PRAGMA mmap_size={_VALIDATE_MMAP_BYTES}")
            if should_stop is not None and should_stop():
                raise BackupError("integrity check stopped before it finished")
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise BackupError(f"integrity check failed: {check[0] if check else 'unknown'}")
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    except errors as exc:
        if isinstance(exc, sqlite3.Error) and not isinstance(exc, sqlite3.DatabaseError):
            raise
        raise BackupError(f"not a valid SQLite database: {record_text(exc)}") from None
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
