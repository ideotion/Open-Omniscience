"""
The ``app_state`` key→value store — the durable home for small config/UI state (D1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (DB-reliability D1, docs/design/DB_RELIABILITY_02_DESIGN.md §D1):
  Settings and small UI state used to live in loose JSON files under ``data_dir()``.
  A JSON file is **not transactional** (a crash mid-rewrite can truncate it), it is
  **not in the encrypted store** (settings sit in cleartext beside a SQLCipher corpus),
  and it is **absent from every backup** (the backup snapshots the DB, not the side
  files). Moving this state into a row of the encrypted corpus DB fixes all three.

What it is, stated honestly:
  A tiny ``key TEXT PRIMARY KEY → value TEXT`` table (``app_state``) holding one JSON
  blob per namespace. This module is the *generic* read/write primitive; each caller
  (the settings modules, the agenda-prefs endpoint) owns its own key + parse/validate.

Why a lazy raw connection instead of the shared ORM engine:
  ``src.database.session.engine`` is a module singleton bound to ``data_dir()`` at
  IMPORT time. The settings modules, by contrast, resolve ``data_dir()`` LAZILY on every
  call — which is exactly what lets the test-suite point each test at its own throwaway
  ``OO_DATA_DIR`` (per-test isolation). To keep that isolation intact — and to keep the
  callers' read/write API unchanged — this store resolves the live SQLite file the same
  lazy way and opens it through the ONE :func:`src.database.connect.connect` factory
  (so encryption is handled identically to the corpus). Writes take the process-wide
  single-writer gate (:func:`src.database.writer.write_lock`), so a settings write can
  never collide with the collector on the SQLite write lock (the same guarantee the ORM
  path gets). Reads never gate (WAL lets a reader pass a writer).

  A small in-process cache (keyed by db-path + key) means a hot read — e.g. the custody
  auto-log check per ingested article — does NOT re-open the encrypted file every call;
  a write refreshes its own cache entry. Single process (API + scheduler threads), so a
  lock-guarded dict is coherent; the cache is keyed by db-path so two test data dirs
  never see each other's rows.

Non-SQLite backends (a future PostgreSQL ``DATABASE_URL``) are not served here — the
readers return ``None`` so the caller falls back to its legacy file/defaults; the whole
SQLCipher/write-gate machinery is SQLite-only anyway.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

TABLE = "app_state"

# Cache: {(db_path, key): value_str_or_None}. Keyed by db_path so per-test
# ``OO_DATA_DIR`` isolation holds and two data dirs never share a row.
_lock = threading.Lock()
_cache: dict[tuple[str, str], str | None] = {}


def _db_path() -> str | None:
    """Resolve the live SQLite file path the *lazy* (current-``data_dir()``) way.

    Returns ``None`` for a non-SQLite ``DATABASE_URL`` (kv-in-DB unsupported there →
    the caller falls back to its legacy file / defaults).
    """
    url = os.getenv("DATABASE_URL", "")
    if url:
        if not url.startswith("sqlite"):
            return None
        return url.removeprefix("sqlite:///")
    from src.paths import data_dir

    return str(data_dir() / "open_omniscience.db")


def _open(path: str, *, read_only: bool = False):
    """Open the live DB through the ONE connect() factory (handles SQLCipher). ``read_only`` opens an existing file ``mode=ro``: the
    connection that closes last on a file checkpoints a leftover ``-wal`` into it and deletes it, and a settings read is made before
    the boot reading of that ``-wal`` can be taken whenever something reads a setting early; a read-only open also never creates a
    file (a missing one raises, and :func:`kv_get_json` reads that as no value)."""
    from src.database.connect import connect

    conn = connect(path, check_same_thread=False, timeout=30, read_only=read_only)
    # A short busy-timeout so a transient checkpoint waits rather than erroring;
    # the write gate already prevents a *contended* writer, this is belt-and-braces.
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:  # noqa: BLE001 - pragma failure must never break a settings read
        pass
    return conn


def _ensure_table(conn) -> None:
    """Create ``app_state`` if the file predates it / a fresh test DB never ran init_db.

    Matches the alembic migration + the ``AppState`` model; a self-heal belt in the
    same spirit as ``src.database.maintenance.ensure_*`` (create_all/migration make it
    on real installs; this covers the lazy-opened, never-init_db'd test file).
    """
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)"
    )


def _read_value(path: str, key: str, *, read_only: bool) -> str | None:
    """The raw value stored under ``key`` (``None`` when the row is absent), through one connection opened and closed here."""
    conn = _open(path, read_only=read_only)
    try:
        row = conn.execute(
            f"SELECT value FROM {TABLE} WHERE key = ?",  # noqa: S608  # nosec B608 - {TABLE} is a fixed constant ("app_state"), never input; the key is a bound param
            (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class KvReadError(Exception):
    """A stored value that EXISTS (or may) could not be read: the store is locked, keyed to another passphrase, damaged or
    unreachable. Carries the class of the failure and none of the engine's words. Absent (no file, no table, no row) is not this."""


#: How long a failed read is remembered, so that a caller asking again and again (a stream's every event) does not open a
#: failing store each time. It protects the store from a retry storm and nothing else: a write or an invalidation clears it.
_FAIL_HOLD_S = 2.0
_failed: dict[tuple[str, str], tuple[float, str]] = {}

#: The failures of a READ-ONLY open that a read-write open can get past (a hot rollback journal to recover, a directory the
#: process cannot write the ``-shm`` into). Anything else (a wrong key, a lock, a busy timeout, a damaged file) is not retried:
#: a read-write open of a keyed store with a wrong key folds and deletes a leftover ``-wal``, and a lock would stall twice.
_RO_ONLY_FAILURES = ("unable to open database file", "readonly database")


def _ro_only_failure(exc: BaseException) -> bool:
    # By name: the keyed driver (sqlcipher3) raises its own ``OperationalError``, not sqlite3's.
    return type(exc).__name__ == "OperationalError" and any(w in str(exc).lower() for w in _RO_ONLY_FAILURES)


def kv_get_json_checked(key: str) -> dict | None:
    """:func:`kv_get_json`, except that a read which FAILED raises :class:`KvReadError` instead of reading as absent.

    ``None`` is a fact (no file, no table or no row, or a value that is not an object); an error is not, and a caller whose
    default is the permissive answer (the transport setting) must not take one for the other. The failure is recorded by class
    only: the driver's text can quote a statement, and the error behind a keyed open chains the driver's own."""
    import time

    path = _db_path()
    if path is None:
        return None
    ck = (path, key)
    with _lock:
        if ck in _cache:
            return _loads(_cache[ck])
        held = _failed.get(ck)
        if held is not None and held[0] > time.monotonic():
            raise KvReadError(held[1])
    try:
        try:
            raw = _read_value(path, key, read_only=True)
        except Exception as ro_exc:  # noqa: BLE001 - classified below
            if not _ro_only_failure(ro_exc):
                raise
            _LOG.debug("kv_get_json(%r): read-only open failed (%s); retrying read-write", key, type(ro_exc).__name__)
            raw = _read_value(path, key, read_only=False)
    except Exception as exc:  # noqa: BLE001 - absent is a value; the rest is a failure
        if isinstance(exc, FileNotFoundError) or "no such table" in str(exc).lower():
            return None
        what = type(exc).__name__
        _LOG.debug("kv_get_json(%r) unreadable (%s)", key, what)
        with _lock:
            _failed[ck] = (time.monotonic() + _FAIL_HOLD_S, what)
        raise KvReadError(what) from None
    with _lock:
        _cache[ck] = raw
        _failed.pop(ck, None)
    return _loads(raw)


def kv_get_json(key: str) -> dict | None:
    """Return the JSON object stored under ``key`` (parsed), or ``None`` if absent.

    Read-only: never creates the table or writes. Any error (locked/missing DB, no
    table yet, unreadable value) degrades to ``None`` so the caller can fall back.
    A caller for which the fallback is the permissive answer uses :func:`kv_get_json_checked`.
    """
    try:
        return kv_get_json_checked(key)
    except KvReadError:
        return None


def kv_get_json_strict(key: str) -> dict | None:
    """Like :func:`kv_get_json`, but an UNREADABLE store raises instead of reading as absent.

    ``None`` here means the key is genuinely not there (or the table does not exist yet, which is
    the same fact on a fresh file); a value that IS there but cannot be parsed as a JSON object
    raises too, since reading corruption as "no record" is the same silent replacement. Use it
    where a caller will REWRITE what it read: treating a
    locked or failing database as "no record" and then writing would silently replace a record the
    caller was meant to extend. Bypasses the cache on a miss only, like :func:`kv_get_json`.
    """
    path = _db_path()
    if path is None:
        return None
    ck = (path, key)
    with _lock:
        if ck in _cache:
            return _loads_strict(_cache[ck])
    conn = _open(path)
    try:
        try:
            row = conn.execute(
                f"SELECT value FROM {TABLE} WHERE key = ?",  # noqa: S608  # nosec B608 - {TABLE} is a fixed constant ("app_state"), never input; the key is a bound param
                (key,),
            ).fetchone()
        except Exception as exc:  # noqa: BLE001 - only "no such table" means absent
            if "no such table" in str(exc).lower():
                return None
            raise
        raw = row[0] if row else None
    finally:
        conn.close()
    with _lock:
        _cache[ck] = raw
    return _loads_strict(raw)


def kv_set_json(key: str, obj: dict) -> None:
    """Upsert ``obj`` (as JSON) under ``key`` transactionally, under the write gate.

    Raises on a genuine write failure (a locked encrypted store, a disk error) so a
    save the operator initiated is never silently lost.

    CALLER CONSTRAINT: do not call this (nor ``save_settings``) from inside an OPEN ORM
    write transaction on the SAME thread. The write gate is reentrant per-thread, so it
    would let this open a SECOND raw connection whose INSERT then contends with the still-
    open ORM writer on the one SQLite file (busy_timeout stall → OperationalError). Every
    current caller loads/saves settings OUTSIDE a write txn (after commit, or on the
    network/fetcher path); keep it that way.
    """
    path = _db_path()
    if path is None:
        raise RuntimeError("app_state kv is only available on a SQLite backend")
    value = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    now = datetime.now(UTC).isoformat()
    from src.database.writer import write_lock

    with write_lock():
        conn = _open(path)
        try:
            _ensure_table(conn)
            conn.execute(
                f"INSERT INTO {TABLE} (key, value, updated_at) VALUES (?, ?, ?) "  # noqa: S608  # nosec B608 - {TABLE} is a fixed constant ("app_state"), never input; values are bound params
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, now),
            )
            conn.commit()
        finally:
            conn.close()
    with _lock:
        _cache[(path, key)] = value
        _failed.pop((path, key), None)


def kv_delete(key: str) -> None:
    """Remove ``key`` (best-effort; a missing table is a no-op)."""
    path = _db_path()
    if path is None:
        return
    from src.database.writer import write_lock

    with write_lock():
        try:
            conn = _open(path)
            try:
                _ensure_table(conn)
                conn.execute(
                    f"DELETE FROM {TABLE} WHERE key = ?",  # noqa: S608  # nosec B608 - {TABLE} is a fixed constant ("app_state"), never input; the key is a bound param
                    (key,),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - delete is best-effort; the class only (a keyed open chains the driver's error)
            _LOG.debug("kv_delete(%r) failed (%s)", key, type(exc).__name__)
    with _lock:
        _cache.pop((path, key), None)
        _failed.pop((path, key), None)


def kv_invalidate(key: str | None = None) -> None:
    """Clear the in-process cache (test hook / after an external DB swap).

    ``None`` clears everything; a key clears just that key's entries across data dirs.
    """
    with _lock:
        if key is None:
            _cache.clear()
            _failed.clear()
        else:
            for ck in [ck for ck in _failed if ck[1] == key]:
                _failed.pop(ck, None)
            for ck in [ck for ck in _cache if ck[1] == key]:
                _cache.pop(ck, None)


def _loads_strict(raw: str | None) -> dict | None:
    """``None`` only for an absent value; a value that is there but is not a JSON object raises."""
    if raw is None:
        return None
    val = json.loads(raw)  # ValueError on a truncated or corrupt value
    if not isinstance(val, dict):
        raise ValueError("stored value is not a JSON object")
    return val


def _loads(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return val if isinstance(val, dict) else None
