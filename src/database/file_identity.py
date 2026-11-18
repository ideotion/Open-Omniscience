"""
Which file a store connection opened, so one that outlives a swap of that file is refused (row 148, the R742 follow-up).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Encrypting a store replaces its file (``encrypt_tool``: an encrypted copy is moved over the plaintext one). A connection opened on
the plaintext file before the swap and still open after it keeps its handle on the REPLACED file: a save through it lands in a
file nobody opens again, which is then overwritten and removed. The library has its own guard (``library_generation``: a lock and
an order). The custody log and the versioned-source lanes were kept out only by the exclusive window and the wait for work in
flight that both encryption paths take. This module is the second line for those two: each connection carries the identity of the
file it opened (device and inode, the file index on Windows), and a save through a connection whose path now names another file
is refused with fixed words, before anything is written.

* :func:`open_pinned` opens through ``opener`` and takes the identity before and after: a file that changed under the open is
  opened again once, then refused.
* The custody log checks its identity under its append lock before it reads the tail and before it writes (``custody/log.py``);
  the encryption swaps the custody file holding that same lock, so the check and the swap cannot interleave.
* :func:`attach` guards a SQLAlchemy engine (the lanes): a pooled connection on a replaced file is dropped at checkout (the pool
  opens a new one, with the key), a commit on one is refused (the transaction rolls back), and a statement on one is refused
  once any swap has been noted (:func:`note_replaced`), which costs an integer comparison per statement and a ``stat`` only after
  a swap.

What it does not cover, stated (the exclusive window and the wait for work in flight remain the guard there, as before):

* a statement that autocommits on its own (DDL outside a transaction) in the instant between a swap and its :func:`note_replaced`;
* a raw DBAPI connection taken from a lane engine (``engine.raw_connection()``; no lane code does), and the backup merge's own raw
  connections to a lane or to the custody log (``backup/lane_merge.py``, ``backup/merge.py``'s ``merge_custody``);
* a file system that reports no inode (``st_ino == 0``, some network and FUSE mounts): the identity cannot tell two files apart
  there, so :func:`same` answers True and the guard does nothing, rather than refuse every healthy save.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: (device, inode). On Windows ``os.stat`` fills both from the volume serial number and the file index.
Identity = tuple[int, int]

#: Fixed words (keyed in every locale): what happened, that nothing was saved, and what to do.
REPLACED_WORDS = (
    "this store's file was replaced (for example, encrypted) or removed while this connection was open, so nothing was saved "
    "through it; do it again"
)

#: The key the identity is kept under in a pooled connection's ``info``.
_KEY = "oo_file_identity"


class StoreReplacedError(RuntimeError):
    """A connection's file is no longer the one its path names: nothing was run or saved through it."""

    def __init__(self, detail: str = REPLACED_WORDS) -> None:
        super().__init__(detail)


_swaps = 0
_swaps_lock = threading.Lock()
_local = threading.local()


def identity(path: Path | str) -> Identity | None:
    """The identity of the file ``path`` names now, or None when it names none (or cannot be read)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def same(path: Path | str, ident: Identity | None) -> bool:
    """True when ``path`` still names the file ``ident`` was taken from. An identity never taken (None) is never the same, and a
    path that names no file now (removed, or a stat that failed) is not the same either. On a file system with no inode numbers
    (``st_ino == 0``) the answer is True: the guard cannot tell, and says so in the module's limits."""
    if ident is None:
        return False
    if ident[1] == 0:
        return True
    return identity(path) == ident


def note_replaced() -> None:
    """Called by every swap of a store file, right after the replace: statements on guarded engines check their file again."""
    global _swaps
    with _swaps_lock:
        _swaps += 1


def swaps() -> int:
    return _swaps


def _attempt[T](path: Path | str, opener: Callable[[], T]) -> tuple[T | None, Identity | None]:
    before = identity(path)
    conn = opener()
    after = identity(path)
    if after is not None and (before is None or before == after):
        # ``before`` is None only when the open created the file: the file it made is the one the path names after it.
        return conn, after
    _close(conn)
    return None, None


def _close(conn: Any) -> None:
    close = getattr(conn, "close", None)
    if close is None:
        return
    with contextlib.suppress(Exception):  # a connection being refused is closed best-effort
        close()


def open_pinned[T](path: Path | str, opener: Callable[[], T]) -> tuple[T, Identity]:
    """Open with ``opener`` and return the connection with the identity of the file it opened. A file that changed under the
    open (a swap ran during it) is opened once more; a second change is refused (:class:`StoreReplacedError`)."""
    conn, ident = _attempt(path, opener)
    if conn is None:
        conn, ident = _attempt(path, opener)
    if conn is None or ident is None:
        raise StoreReplacedError()
    return conn, ident


def pinned_creator[T](path: Path | str, opener: Callable[[], T]) -> Callable[[], T]:
    """A pool ``creator`` that opens through :func:`open_pinned` and hands the identity to :func:`attach`'s ``connect``
    listener (same thread, the next connection made)."""

    def _create() -> T:
        conn, ident = open_pinned(path, opener)
        # SQLAlchemy's pool runs the ``connect`` event right after the creator returns, on the same thread, so the thread-local
        # carries exactly this connection's identity to ``_stamp``.
        _local.ident = ident
        return conn

    return _create


def _refuse(_conn: Any) -> None:
    # Not invalidated here: closing a connection from inside its own statement hook makes SQLAlchemy log a failed cursor close at
    # ERROR. The transaction rolls back, and the connection, once back in the pool, is dropped at its next checkout.
    raise StoreReplacedError()


def attach(engine: Any, path: Path | str) -> None:
    """Guard the connections of ``engine`` (one file, ``path``): stamped when made, dropped at checkout, refused at commit, and
    refused per statement after any noted swap, when their file is no longer the one ``path`` names. One call per engine."""
    from sqlalchemy import event, exc

    @event.listens_for(engine, "connect")
    def _stamp(_dbapi_connection, connection_record) -> None:  # noqa: ANN001 - SQLAlchemy's pool record
        taken = getattr(_local, "ident", None)
        _local.ident = None
        connection_record.info[_KEY] = [taken if taken is not None else identity(path), swaps()]

    @event.listens_for(engine, "checkout")
    def _drop_replaced(_dbapi_connection, connection_record, _proxy) -> None:  # noqa: ANN001
        stamp = connection_record.info.get(_KEY)
        if stamp is None:
            return
        seen = swaps()
        if not same(path, stamp[0]):
            raise exc.DisconnectionError("this store's file was replaced; this connection belongs to the old one")
        stamp[1] = seen

    @event.listens_for(engine, "before_cursor_execute")
    def _refuse_replaced_statement(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:  # noqa: ANN001
        stamp = conn.connection.info.get(_KEY)
        if stamp is None:
            return
        seen = swaps()
        if stamp[1] == seen:
            return
        if not same(path, stamp[0]):
            _refuse(conn)
        stamp[1] = seen

    @event.listens_for(engine, "commit")
    def _refuse_replaced_commit(conn) -> None:  # noqa: ANN001
        stamp = conn.connection.info.get(_KEY)
        if stamp is not None and not same(path, stamp[0]):
            _refuse(conn)
