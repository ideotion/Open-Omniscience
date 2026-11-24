"""
R812 (coordinator ruling on #2333, decision 1): connections to stores on a data drive that is absent, cannot be identified, or
changed are NEVER closed in this process.

Why: when the LAST connection on a WAL store closes, SQLite writes the log back through the descriptor it holds (which still
reaches the old drive) and then deletes ``<db>-wal`` and ``<db>-shm`` BY PATH. With another drive at that path (mounted over it,
or swapped in during an erase), those are the OTHER drive's files (measured by the R812 security read on tmpfs drives with the
real panic). DuckDB does the same with its ``.wal`` on the close of a writable ATTACH.

So once the erase finds the drive not there, not identifiable or changed, :func:`pin_drive` takes every live connection on a
store under the data folder out of reach of every close: it holds a strong reference that no pool dispose or garbage collection
drops (an extra reference count through the C API, so not even the interpreter's own teardown frees it, and freeing is what would
close it), and the dialect's close skips it (pool dispose, checkin overflow, recycle, timeout, invalidation, ``atexit`` disposal:
src/database/after_shutdown.py:245 and every ``session.dispose_engine`` all reach ``Pool._close_connection`` ->
``dialect.do_close``). Only the end of the process releases it, where the operating system drops the descriptors without
SQLite's cleanup. The cost, said in the erase's result: the key for that drive's data stays in this app's memory until the app
is closed.

SQLITE_FCNTL_PERSIST_WAL (which would keep the log on close) is NOT reachable from our drivers: neither the stdlib ``sqlite3``
module nor ``sqlcipher3`` exposes ``sqlite3_file_control``. ``SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE`` is reachable from stdlib
``sqlite3`` (``Connection.setconfig``, plaintext stores only) and not from ``sqlcipher3`` (no ``setconfig``; checked on the
pinned version), so it cannot cover the encrypted store every real operator uses; pinning covers both.

STATED LIMITS: only connections opened through a SQLAlchemy pool are tracked (the corpus engine and the lane engines). A raw
``sqlite3``/``sqlcipher3`` connection a module opens and closes itself is short-lived and, after the erase latched the folder
(R802), refused. A connection closed before the drive was found changed was closed on the drive the erase last saw.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import default as _sa_default
from sqlalchemy.pool import Pool

_LOG = logging.getLogger("database.drive_pin")

_LOCK = threading.Lock()
#: id(dbapi connection) -> (connection, its main database file or None when it could not be read). Pool connections only.
_LIVE: dict[int, tuple[Any, str | None]] = {}
#: The connections pinned for the rest of the process (strong references, and an extra reference count each).
_PINNED: list[Any] = []
_PINNED_IDS: set[int] = set()
_ORIGINAL_DO_CLOSE = _sa_default.DefaultDialect.do_close


def _main_file(dbapi_connection) -> str | None:
    try:
        for row in dbapi_connection.execute("PRAGMA database_list").fetchall():
            if row[1] == "main":
                return str(row[2]) or None
    except Exception:  # noqa: BLE001 - a file that cannot be read is pinned when any drive is (see _under)
        return None
    return None


@event.listens_for(Pool, "connect")
def _track(dbapi_connection, _record) -> None:
    with _LOCK:
        _LIVE[id(dbapi_connection)] = (dbapi_connection, _main_file(dbapi_connection))


@event.listens_for(Pool, "close")
def _untrack(dbapi_connection, _record) -> None:
    with _LOCK:
        if id(dbapi_connection) not in _PINNED_IDS:
            _LIVE.pop(id(dbapi_connection), None)


@event.listens_for(Pool, "close_detached")
def _untrack_detached(dbapi_connection) -> None:
    _untrack(dbapi_connection, None)


def _do_close(self, dbapi_connection) -> None:
    """The dialect's close, except for a pinned connection, which is never closed in this process."""
    if id(dbapi_connection) in _PINNED_IDS:
        return
    _ORIGINAL_DO_CLOSE(self, dbapi_connection)


def _under(path: str | None, base: Path) -> bool:
    """On the drive: the file is in the data folder by its spelling or resolved path. A file that could not be read is ON it."""
    if path is None:
        return True
    for b in {os.path.abspath(base), os.path.realpath(base)}:
        for p in {os.path.abspath(path), os.path.realpath(path)}:
            if p == b or p.startswith(b.rstrip(os.sep) + os.sep):
                return True
    return False


def _immortal(obj: Any) -> None:
    _PINNED.append(obj)
    with contextlib.suppress(Exception):
        ctypes.pythonapi.Py_IncRef(ctypes.py_object(obj))  # never freed, so never closed by its own deallocation


def _pin_serves(base: Path) -> int:
    """DuckDB: a serve whose connection has a file under the data folder ATTACHed is taken out of its module's state (so the
    serve closes find nothing to close) and pinned. An in-memory serve has no log file and is left to its usual close."""
    n = 0
    for name in ("rollup_serve", "map_serve"):
        mod = sys.modules.get(f"src.analytics.{name}")
        state = getattr(mod, "_STATE", None) if mod is not None else None
        if not isinstance(state, dict) or state.get("con") is None:
            continue
        con = state["con"]
        try:
            files = [r[0] for r in con.execute("SELECT path FROM duckdb_databases() WHERE path IS NOT NULL").fetchall()]
        except Exception:  # noqa: BLE001 - not knowing is on the drive
            files = [None]
        if any(_under(f, base) for f in files):
            state["con"] = None
            _immortal(con)
            n += 1
    return n


def pin_drive(base: Path) -> int:
    """Pin every tracked connection on a store under ``base`` (and a DuckDB serve on one) for the rest of the process. Idempotent;
    returns how many connections are pinned in all (0: none was open on the drive). Never raises."""
    try:
        _sa_default.DefaultDialect.do_close = _do_close  # type: ignore[method-assign]  # every later close goes through the skip
        with _LOCK:
            for key, (conn, path) in list(_LIVE.items()):
                if key not in _PINNED_IDS and _under(path, base):
                    _PINNED_IDS.add(key)
                    _immortal(conn)
        _pin_serves(base)
    except Exception:  # noqa: BLE001 - never stops an erase; the result still says the key may be in memory
        _LOG.exception("could not pin the connections on the data drive")
    if _PINNED:
        _LOG.warning("CRYPTO-ERASE: %d connections on the data drive are kept open until the app closes (R812)", len(_PINNED))
    return len(_PINNED)


def pinned_count() -> int:
    return len(_PINNED)


def _reset_for_tests() -> None:
    """Tests only: forget the pins (the extra references stay: those objects are leaked, as in the app) and restore the close."""
    _sa_default.DefaultDialect.do_close = _ORIGINAL_DO_CLOSE  # type: ignore[method-assign]
    with _LOCK:
        _PINNED_IDS.clear()
        _PINNED.clear()
