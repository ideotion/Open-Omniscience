"""WHICH FILE the library's name pointed at when a connection was made, and the one window in which that changes (the swap, E3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The repair (``repair._swap``) and the restore (``backup.merge``) put a new file under the library's name and set the
old one aside. ``dispose_engine()`` closes the pool's IDLE connections; a connection a request has CHECKED OUT stays open on the OLD
inode, and in WAL mode SQLite does not notice that its file has moved (the check that does, "the database file has been moved", runs
only for rollback-journal databases). The deep read of E3 ran it: a form loads, waits on the write gate for the whole repair, then
saves, and the save commits into the damaged file (now ``<stem>.damaged-*``, which R129 removes thirty days later) with no error, while
the library reads as if the save never happened. Its delta read found the three ways the first guard still let one through.

WHAT IT DOES.

* A set of VALID generations (:data:`_VALID`) and a stamp on every connection of an engine (:func:`attach`): a statement, a COMMIT or a
  checkout on a connection whose stamp is not valid is refused BEFORE it runs, and the connection is invalidated so the pool never
  hands it out again. The COMMIT is guarded as well as the statement because the DBAPI commit is not a cursor statement: a transaction
  that began before the swap and commits after it must not land in the old file, and it does not, because the refusal rolls it back.
* The stamp is taken BEFORE the file is opened, under a shared lock the creator holds around the whole open (:func:`guarded_creator`),
  and :func:`swap_window` takes the same lock EXCLUSIVELY: a connection is either wholly before the swap (it opened the old file, its
  stamp is the old one, and the swap waited for it) or wholly after (it opens the new file). Without the lock a connection opened
  between the removal of the live ``-wal``/``-shm`` and the replace bound the NEW file's log names to the OLD file, and one stamped after
  the bump on the old file was never refused.
* The window BUMPS FIRST: the moment the swap holds it, every connection made before is refused. The repair's last check (whether any
  other connection committed to the file since the copy began) runs after that and before the replace, so a save that lands in the old
  file can only do so before the bump, where the check sees it, never between the check and the replace. If the swap then does NOT
  happen (a refusal, a replace that failed), the window gives the old connections their validity back: the file is the one they opened.

WHAT IT DOES NOT COVER. A raw DBAPI cursor on a pooled connection (``engine.raw_connection()``) runs no SQLAlchemy event; the app's
users of it (the log checkpoint, ``PRAGMA shrink_memory``, the data-version probe) run no DML. A statement already past its own check
and not yet at SQLite when the bump lands is the window's width (microseconds) and is what the repair's data-version check exists for.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_KEY = "oo_library_generation"

#: How long the swap waits for connections that are being opened (and for the lock's other holders) before it refuses. WHAT IT
#: PROTECTS: a swap that waits for an open that is stuck on a lock it will never get, against a swap refused for an open that is
#: only slow (an encrypted open derives its key in well under a second, and a plain one takes milliseconds).
WINDOW_WAIT_S = 60.0


class StaleLibraryError(RuntimeError):
    """A statement, a COMMIT or a checkout was about to run on a connection to a library file that has since been replaced (a repair
    or a restore switched to a new file). Nothing ran; the work is to be done again."""


class LibraryBusy(RuntimeError):
    """The swap could not get its window: a connection was still being opened after :data:`WINDOW_WAIT_S`."""


_STATE = threading.Lock()  # guards the names below
_GENERATION = 0
_VALID: frozenset[int] = frozenset({0})
_WINDOW_STAMP: int | None = None  # the stamp of a connection the swap itself opens inside its window, while there is one


def current() -> int:
    return _GENERATION


def valid(stamp: int | None) -> bool:
    """Whether a connection with this stamp may run (a connection nobody stamped, a bare engine of a test, may)."""
    if stamp is None:
        return True
    if stamp == _WINDOW_STAMP:  # opened by the swap itself, on the old file: only the swap's own thread may use it while the window runs
        return _LOCK.held_here()
    return stamp in _VALID


def bump() -> int:
    """The library's name now (or is about to) point at a different file: every connection made before this call is stale."""
    global _GENERATION, _VALID
    with _STATE:
        _GENERATION += 1
        _VALID = frozenset({_GENERATION})
        return _GENERATION


def _revive(earlier: frozenset[int]) -> None:
    """The swap did not happen: the connections that were valid before :func:`bump` open the file that is still the library."""
    global _VALID
    with _STATE:
        _VALID = frozenset(earlier | _VALID)


def _open_window() -> None:
    """The thread that holds the window opens connections of its own, on the OLD file (the data-version read, a fold of the log): they
    carry the window's own stamp, which only that thread may use while the window runs (:func:`valid`) and which is valid afterwards only
    if the swap did not happen (:func:`_close_window`)."""
    global _WINDOW_STAMP
    with _STATE:
        _WINDOW_STAMP = -_GENERATION  # never a generation: those count up from zero


def _close_window(*, swapped: bool) -> None:
    global _VALID, _WINDOW_STAMP
    with _STATE:
        if not swapped and _WINDOW_STAMP is not None:
            _VALID = frozenset(_VALID | {_WINDOW_STAMP})
        _WINDOW_STAMP = None


# --- the lock --------------------------------------------------------------------------------------------------------------


class _Lock:
    """Shared by every connect, exclusive for the swap; the holder's own thread passes through (the swap opens connections itself,
    to fold the log and to read the data version). No writer preference: a shared holder can never be made to wait on a swap that
    waits on it, and the swap's own wait is bounded."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._holder: int | None = None

    def shared(self) -> bool:
        me = threading.get_ident()
        with self._cond:
            if self._holder == me:
                return False
            while self._holder is not None:
                self._cond.wait()
            self._shared += 1
            return True

    def release_shared(self) -> None:
        with self._cond:
            self._shared -= 1
            if not self._shared:
                self._cond.notify_all()

    def exclusive(self, timeout: float) -> None:
        me = threading.get_ident()
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            if self._holder == me:
                raise RuntimeError("the library swap window is already held by this thread")
            while self._holder is not None or self._shared:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise LibraryBusy(
                        f"a connection to the library was still being opened after {timeout:.0f} s, so the file was not switched"
                    )
                self._cond.wait(left)
            self._holder = me

    def held_here(self) -> bool:
        return self._holder == threading.get_ident()

    def release_exclusive(self) -> None:
        with self._cond:
            self._holder = None
            self._cond.notify_all()


_LOCK = _Lock()
_local = threading.local()


@contextmanager
def connecting() -> Iterator[None]:
    """Around ONE open of a connection to the library file: the generation is read and the file opened under the shared lock, and the
    stamp is handed to the ``connect`` event of the same thread (the DBAPI connection cannot carry it, the pool's record can)."""
    took = _LOCK.shared()
    try:
        # The thread that holds the window opens its connections BEFORE the replace (the data-version read, a fold of the log): they are
        # on the OLD file, so they carry the window's own stamp, valid inside the window and after it only if the swap did not happen.
        _local.stamp = _GENERATION if took or _WINDOW_STAMP is None else _WINDOW_STAMP
        yield
    except BaseException:
        _local.stamp = None  # an open that failed hands nothing to the next ``connect`` event of this thread
        raise
    finally:
        if took:
            _LOCK.release_shared()


def guarded_creator(creator: Callable[[], Any]) -> Callable[[], Any]:
    """The engine's ``creator`` wrapped so every connection it makes is opened under :func:`connecting`."""

    def _guarded() -> Any:
        with connecting():
            return creator()

    return _guarded


@contextmanager
def swap_window(source: Path, *, timeout: float = WINDOW_WAIT_S) -> Iterator[None]:
    """The window in which the library's name is moved onto ``source``: no connection is being opened or can be, every connection made
    before it is refused from its first line (bump first), and when the window ends WITHOUT ``source`` having been moved (it still
    exists: a refusal, a replace that failed) the earlier connections are valid again. Raises :class:`LibraryBusy` if it cannot be had."""
    _LOCK.exclusive(timeout)
    earlier = _VALID
    swapped = True  # until the window ends with the source still there
    try:
        bump()
        _open_window()
        yield
    finally:
        try:
            swapped = not source.exists()
            if not swapped:
                _revive(earlier)
        except OSError:  # cannot tell whether the file moved: stale is the safe answer
            _LOG.debug("library generation: could not tell whether the swap happened; the old connections stay refused")
        finally:
            _close_window(swapped=swapped)
            _LOCK.release_exclusive()


# --- the guard -------------------------------------------------------------------------------------------------------------


def _refuse(conn: Any) -> None:
    """Refuse (and invalidate) a connection whose stamp is not valid."""
    if valid(conn.connection.info.get(_KEY)):
        return
    try:
        conn.invalidate()  # never returns to the pool: its file is not the library any more
    except Exception:  # noqa: BLE001 - the refusal below is what matters
        _LOG.debug("library generation: could not invalidate a stale connection (it is refused anyway)")
    raise StaleLibraryError(
        "the library file was replaced while this was open, so nothing was run or saved; do it again"
    )


def attach(engine: Any) -> None:
    """Stamp the connections of ``engine`` and refuse statements, commits and checkouts on stale ones. One call per engine."""
    from sqlalchemy import event, exc

    @event.listens_for(engine, "connect")
    def _stamp(_dbapi_connection, connection_record) -> None:  # noqa: ANN001 - SQLAlchemy's pool record
        taken = getattr(_local, "stamp", None)
        _local.stamp = None
        connection_record.info[_KEY] = _GENERATION if taken is None else taken

    @event.listens_for(engine, "checkout")
    def _refuse_stale_checkout(_dbapi_connection, connection_record, _proxy) -> None:  # noqa: ANN001
        if not valid(connection_record.info.get(_KEY)):
            raise exc.DisconnectionError("the library file was replaced; this connection belongs to the old one")

    @event.listens_for(engine, "before_cursor_execute")
    def _refuse_stale_statement(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:  # noqa: ANN001
        _refuse(conn)

    @event.listens_for(engine, "commit")
    def _refuse_stale_commit(conn) -> None:  # noqa: ANN001
        _refuse(conn)
