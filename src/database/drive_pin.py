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

ROW 390 (R813, outside any erase): the same close deletes the other drive's files when the drive is swapped while the app runs and
the app then closes a connection on it in the ordinary way (a pool recycle or overflow, the lifespan's shutdown disposal at
src/api/main.py ``dispose_engine``, the ``atexit`` disposal at src/database/after_shutdown.py ``_dispose_at_exit``, a serve's
close). So the dialect's close is patched from import on, and before it closes a connection it asks whether the marked drive is
still the one at the data folder (src/safety/data_volume.py ``probe``): when it is absent, unidentified or another drive, a
connection with a file in the data folder (its main file or one it ATTACHed, read on the connection being closed) is pinned
instead, the same way. A DuckDB serve's close and its offload folder's removal ask the same question (:func:`close_or_keep`,
:func:`on_frozen_drive`), and so does the write-back before the shutdown disposal (src/database/shutdown_checkpoint.py), which
would otherwise open the other drive's file. Unlike an erase's finding, this one is not kept: each close asks again, so a
marker read that fails for a moment pins only the connections closed in that moment. A folder an erase latched (R802) is the
erase's to decide. Only a watched data folder (one marked on a drive at first launch, R86) is asked about; a data folder on the
internal disk has no drive to be swapped.

A connection the disposal does not close (one checked out at that moment, which goes back to the replaced pool and is freed with it;
or one opened after the shutdown disposal) is closed by its deallocation, which no patched close sees. So every tracked connection
on a drive that is not the marked one is pinned at the three moments that can leave one to that: when the watchdog finds the drive
gone (src/safety/data_volume.py ``VolumeMonitor._trigger``), at every :func:`~src.database.session.dispose_engine`, and at exit
(an ``atexit`` hook registered at import, so it runs after every hook the app registers later, before the interpreter frees
anything) (:func:`pin_if_gone`).

STATED LIMITS: only connections opened through a SQLAlchemy pool are tracked (the corpus engine and the lane engines). A raw
``sqlite3``/``sqlcipher3`` connection a module opens and closes itself is short-lived and, after the erase latched the folder
(R802), refused. A connection closed before the drive was found changed was closed on the drive the erase last saw. A pool
connection DETACHED from its pool (``Connection.detach()``; nothing in the app detaches one) is not followed once detached.
A connection freed between the drive changing and the next of those three moments (seconds: the watchdog polls) is closed on the
drive there by its deallocation. Raw ``sqlite3`` connections a module opens and closes itself (the wiki dump index, the OSM reader,
the keyword log scan) are not pooled and not covered: they open the file at the path, so they read or write the other drive's file
(as every write in the data folder would) and close it whole, without removing another store's log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import logging
import os
import sys
import threading
import weakref
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import default as _sa_default
from sqlalchemy.pool import Pool

_LOG = logging.getLogger("database.drive_pin")

_LOCK = threading.Lock()
#: id(dbapi connection) -> (a WEAK reference to its pool record, its database files at connect: the main one and any ATTACHed, "" in
#: memory, None when they could not be read). Pool connections only. Weak, so tracking never keeps alive a connection its engine let go of: a pool's record is
#: freed with the engine, and its connection closed by its own deallocation as before (a sqlite3 connection takes no weak reference).
_LIVE: dict[int, tuple[Any, list[str | None]]] = {}
#: The connections pinned for the rest of the process (strong references, and an extra reference count each).
_PINNED: list[Any] = []
_PINNED_IDS: set[int] = set()
#: The data folders found absent, unidentified or changed: nothing on them is closed or removed for the rest of the process.
_FROZEN: list[Path] = []
_ORIGINAL_DO_CLOSE = _sa_default.DefaultDialect.do_close


def _live_connection(key: int, ref: Any) -> Any:
    """The connection a tracked record still holds under ``key``, or None (the record is gone, closed, or holds another one)."""
    record = ref() if ref is not None else None
    conn = getattr(record, "dbapi_connection", None) if record is not None else None
    return conn if conn is not None and id(conn) == key else None


@event.listens_for(Pool, "connect")
def _track(dbapi_connection, record) -> None:
    try:
        ref = weakref.ref(record)
    except TypeError:  # not a pool record: nothing to follow it by, so it is not tracked
        return
    files = _files(dbapi_connection)
    with _LOCK:
        for key, (old_ref, _p) in list(_LIVE.items()):  # forget the records already freed (their engines were let go of)
            if key in _PINNED_IDS or old_ref() is not None:
                continue
            del _LIVE[key]
        _LIVE[id(dbapi_connection)] = (ref, files)


@event.listens_for(Pool, "close")
def _untrack(dbapi_connection, _record) -> None:
    with _LOCK:
        if id(dbapi_connection) not in _PINNED_IDS:
            _LIVE.pop(id(dbapi_connection), None)


@event.listens_for(Pool, "close_detached")
def _untrack_detached(dbapi_connection) -> None:
    _untrack(dbapi_connection, None)


def _changed_drive() -> Path | None:
    """Row 390: the watched data folder when the marked drive is not the one there right now (``probe``: missing, or another drive's
    marker; a question that could not be answered counts as changed). None: no folder is watched, the drive is there, or an erase
    latched the folder (R802: the erase decides, and pins through :func:`pin_drive`). Never raises."""
    try:
        from src.safety import data_volume

        if not data_volume.watched():
            return None
        folder = data_volume.configured_folder()
    except Exception:  # noqa: BLE001 - no folder known: nothing to ask about
        return None
    if folder is None:
        return None
    try:
        from src.paths import erased_folder_of

        if erased_folder_of(folder):
            return None
    except Exception:  # noqa: BLE001 - not knowing whether an erase latched it: the drive is asked about  # nosec B110
        pass
    try:
        if data_volume.probe().get("state") == "ok":
            return None
    except Exception:  # noqa: BLE001 - not knowing whether the drive is there is changed  # nosec B110
        pass
    return Path(folder)


def _gone_bases() -> list[Path]:
    """The data folders whose drive is not the marked one: those an erase found so (kept for the process) and, asked now, the
    watched folder (row 390, not kept)."""
    bases = list(_FROZEN)
    now = _changed_drive()
    if now is not None and not any(os.path.abspath(b) == os.path.abspath(now) for b in bases):
        bases.append(now)
    return bases


def _files(dbapi_connection) -> list[str | None]:
    """Every database file a connection holds (its main file and every ATTACHed one; "" in memory). ``[None]`` (on the drive) when
    they cannot be read; ``[]`` when the connection is already closed (nothing left to close or delete)."""
    try:
        return [str(row[2]) for row in dbapi_connection.execute("PRAGMA database_list").fetchall()]
    except Exception as exc:  # noqa: BLE001 - not knowing is on the drive
        if type(exc).__name__ == "ProgrammingError" and "closed" in str(exc).lower():  # "Cannot operate on a closed database."
            return []
        return [None]


def _pin_one(conn: Any) -> None:
    with _LOCK:
        if id(conn) in _PINNED_IDS:
            return
        _PINNED_IDS.add(id(conn))
        _immortal(conn)
    _LOG.warning("data drive: a connection on it is kept open until the app closes, since the drive there is not the marked one (row 390)")


def _pin_tracked(base: Path) -> None:
    """Pin every tracked pool connection with a file on ``base`` (checked out or not): never closed, never freed."""
    with _LOCK:
        for key, (ref, files) in list(_LIVE.items()):
            if key in _PINNED_IDS or not any(_under(f, base) for f in files):
                continue
            conn = _live_connection(key, ref)
            if conn is None:
                _LIVE.pop(key, None)
                continue
            _PINNED_IDS.add(key)
            _immortal(conn)


def pin_if_gone() -> int:
    """Row 390: when a data drive is not the marked one (found by an erase, or asked now), pin every tracked connection on it, before
    a disposal leaves one to its deallocation or the exit frees it. Returns how many are pinned in all. Never raises."""
    try:
        for base in _gone_bases():
            _pin_tracked(base)
    except Exception as exc:  # noqa: BLE001 - never stops a disposal or the exit
        _LOG.error("could not pin the connections on the data drive (%s)", type(exc).__name__)  # the type only: no path
    return len(_PINNED)


def _do_close(self, dbapi_connection) -> None:
    """The dialect's close, except for a pinned connection, which is never closed in this process, and (row 390) a connection with a
    file on a data drive that is not the marked one right now, which is pinned instead. The connection is the one being closed, so
    reading its files here races no other user of it."""
    if id(dbapi_connection) in _PINNED_IDS:
        return
    if getattr(self, "name", "sqlite") != "sqlite":  # another backend (DATABASE_URL elsewhere) has no file in the data folder
        _ORIGINAL_DO_CLOSE(self, dbapi_connection)
        return
    try:
        bases = _gone_bases()
        gone = bool(bases) and any(_under(f, b) for b in bases for f in _files(dbapi_connection))
    except Exception:  # noqa: BLE001 - not knowing, with a drive gone, is on the drive
        gone = bool(_FROZEN) or _changed_drive() is not None
    if gone:
        _pin_one(dbapi_connection)
        pin_if_gone()  # the rest on that drive too: one checked out now is otherwise freed later with its pool, unseen
        return
    _ORIGINAL_DO_CLOSE(self, dbapi_connection)


_sa_default.DefaultDialect.do_close = _do_close  # type: ignore[method-assign]  # row 390: from import on, every close asks
atexit.register(pin_if_gone)  # registered first, so it runs last: after the app's own exit disposal, before anything is freed


def _under(path: str | None, base: Path) -> bool:
    """On the drive: the file is in the data folder by its spelling or resolved path. A file that could not be read is ON it."""
    if path is None:
        return True
    if path == "":
        return False  # an in-memory database is on no drive
    for b in {os.path.abspath(base), os.path.realpath(base)}:
        for p in {os.path.abspath(path), os.path.realpath(path)}:
            if p == b or p.startswith(b.rstrip(os.sep) + os.sep):
                return True
    return False


def _immortal(obj: Any) -> None:
    _PINNED.append(obj)
    with contextlib.suppress(Exception):
        ctypes.pythonapi.Py_IncRef(ctypes.py_object(obj))  # never freed, so never closed by its own deallocation


def _serve_files(con: Any) -> list[str | None]:
    """The files a DuckDB connection has ATTACHed; ``[None]`` (on the drive) when they cannot be read. The caller holds the serve's
    lock, or owns the connection alone (a build's own connection), so this never runs on a connection another thread is using."""
    try:
        return [r[0] for r in con.execute("SELECT path FROM duckdb_databases() WHERE path IS NOT NULL").fetchall()]
    except Exception as exc:  # noqa: BLE001 - not knowing is on the drive
        # DuckDB's "Connection already closed!": nothing left to close or delete. Any other connection error is not knowing.
        if type(exc).__name__ == "ConnectionException" and "already closed" in str(exc).lower():
            return []
        return [None]


def on_frozen_drive(path: Any) -> bool:
    """True when ``path`` is on a drive found absent, unidentified or changed (by an erase, for the process; or asked now, row 390):
    it is not removed (an offload folder at that path is the other drive's now)."""
    return bool(path) and any(_under(str(path), b) for b in _gone_bases())


def serve_on_gone_drive(con: Any, spill: Any = None) -> bool:
    """True when a DuckDB serve connection has a file, or its offload folder, on a drive that is not the marked one (its files
    unreadable count as on it). The caller holds the serve's lock or owns the connection alone. Never raises."""
    try:
        bases = _gone_bases()
        if not bases:
            return False
        if spill and any(_under(str(spill), b) for b in bases):
            return True
        return any(_under(f, b) for b in bases for f in _serve_files(con))
    except Exception:  # noqa: BLE001 - not knowing, with a drive gone, is on it
        return bool(_FROZEN)


def close_or_keep(con: Any, spill: Any = None) -> bool:
    """Close a DuckDB serve connection, unless a drive is frozen and the connection has a file on it, its offload folder is there, or
    its files cannot be read: then it is pinned, never closed (closing deletes its ``.wal`` and its offload files BY PATH, on the
    drive there now). Returns True when it was kept. Call it where the connection is not in use by another thread: under the
    serve's lock, or on a connection the caller alone holds. Never raises."""
    if con is None:
        return False
    if serve_on_gone_drive(con, spill):
        _immortal(con)
        return True
    with contextlib.suppress(Exception):
        con.close()
    return False


def _pin_serves(base: Path) -> int:
    """DuckDB: a serve whose connection has a file under the data folder ATTACHed, or its offload folder there, is taken out of its
    module's state, under that module's own lock, and pinned. A serve whose lock is held right now is left where it is: every later
    close of it (the cleared-key close, the close once free, a build's retiring swap, the shutdown close) goes through
    :func:`close_or_keep`, which keeps it, since the drive is already frozen."""
    n = 0
    for name in ("rollup_serve", "map_serve"):
        mod = sys.modules.get(f"src.analytics.{name}")
        state = getattr(mod, "_STATE", None) if mod is not None else None
        lock = getattr(mod, "_LOCK", None) if mod is not None else None
        if not isinstance(state, dict) or lock is None or not lock.acquire(blocking=False):
            continue
        try:
            con = state.get("con")
            if con is None:
                continue
            if _FROZEN and (on_frozen_drive(state.get("spill")) or any(_under(f, base) for f in _serve_files(con))):
                _immortal(con)
                state.update(con=None, built_at=0.0, spill=None, persisted=False)
                n += 1
        finally:
            lock.release()
    return n


def pin_drive(base: Path) -> int:
    """Pin every tracked connection on a store under ``base`` (and a DuckDB serve on one) for the rest of the process. Idempotent;
    returns how many connections are pinned in all (0: none was open on the drive). Never raises."""
    try:
        with _LOCK:
            if not any(os.path.abspath(b) == os.path.abspath(base) for b in _FROZEN):
                _FROZEN.append(Path(base))  # first: a serve closed from here on, by any thread, is kept (close_or_keep)
        _sa_default.DefaultDialect.do_close = _do_close  # type: ignore[method-assign]  # installed at import; again, should anything have reset it
        _pin_tracked(base)
        _pin_serves(base)
    except Exception as exc:  # noqa: BLE001 - never stops an erase; the result still says the key may be in memory
        _LOG.error("could not pin every connection on the data drive (%s)", type(exc).__name__)  # the type only: no path
    if _PINNED:
        _LOG.warning("CRYPTO-ERASE: %d connections on the data drive are kept open until the app closes (R812)", len(_PINNED))
    return len(_PINNED)


def pinned_count() -> int:
    return len(_PINNED)


def _reset_for_tests() -> None:
    """Tests only: forget the pins (the extra references stay: those objects are leaked, as in the app). The patched close stays."""
    _sa_default.DefaultDialect.do_close = _do_close  # type: ignore[method-assign]
    with _LOCK:
        _PINNED_IDS.clear()
        _PINNED.clear()
        _FROZEN.clear()
