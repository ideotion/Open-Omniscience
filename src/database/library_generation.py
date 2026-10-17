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
  happen AND nothing on disk was changed (a refusal before :func:`disk_changing`), the window gives the old connections their validity back: the
  file is the one they opened. After the live log names were removed they stay refused, replace or not (:func:`disk_changing`).

WHAT IT DOES NOT COVER. A raw DBAPI cursor on a pooled connection (``engine.raw_connection()``) runs no SQLAlchemy event; the app's
users of it (the log checkpoint, ``PRAGMA shrink_memory``, the data-version probe) run no DML. A statement already past its own check
and not yet at SQLite when the bump lands is the window's width (microseconds), and the repair's data-version check sees a save that
landed before the bump. A statement that COMMITS ITSELF is wider: Core DDL and Core writes under pysqlite's legacy transaction mode, which
no gate holds (``analytics/spell_index.py``, ``database/fts.py``, ``database/maintenance.py``, ``database/migrate.py``), can wait out
``busy_timeout`` PAST the probe's rollback and land in the set-aside file. Those are boot and derived-store steps, never a user's save,
and ``write_lock()`` at those sites (the write-gate holds PR) is what closes them.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.utils.interrupts import wait as _wait

_LOG = logging.getLogger(__name__)

_KEY = "oo_library_generation"

#: How long the swap waits for connections that are being opened (and for the lock's other holders) before it refuses. WHAT IT
#: PROTECTS: a swap that waits for an open that is stuck on a lock it will never get, against a swap refused for an open that is
#: only slow (an encrypted open derives its key in well under a second, and a plain one takes milliseconds).
WINDOW_WAIT_S = 60.0

#: THE LONGEST A LOST WAKE-UP MAY COST, not a timeout. A connection open waits for the window in steps of this many seconds and looks again
#: after each, so it still waits as long as the window is held; what the step bounds is a wake-up that never came. The window is given back by
#: clearing the holder and THEN calling ``notify_all``; a MemoryError in that call (forced in ``tests/test_swap_window_allocation_failures.py``)
#: leaves the holder clear and every open that was already waiting asleep with nothing to wake it. The give-back of a shared level (the end of
#: ``connecting``) loses the swap's wake-up the same way, and the swap's own wait takes steps of this size too (never longer than the time it has
#: left). WHAT IT PROTECTS: a request that waits for a connection against one that waits for ever, and a swap that waits for an open that was
#: already over. One second because the wait it adds is paid only after that failure, and a stalled request is noticed in seconds; it is chosen,
#: not measured (the failure has been seen only when forced).
_RECHECK_S = 1.0


class StaleLibraryError(RuntimeError):
    """A statement, a COMMIT or a checkout was about to run on a connection to a library file that has since been replaced (a repair
    or a restore switched to a new file). Nothing ran; the work is to be done again."""


class LibraryBusy(RuntimeError):
    """The swap could not get its window: a connection was still being opened after :data:`WINDOW_WAIT_S`."""


# The four names below are WRITTEN only inside the exclusive window: by :func:`swap_window` and by the functions it and its body call on the
# swap's own thread (:func:`bump`, :func:`_open_window`, :func:`_close_window`, :func:`disk_changing`; the restore, the repair and the encrypt call
# the last one from the body of their window). The window is held by one thread at a time (:class:`_Lock`), so two writers never overlap, and the
# readers (:func:`current`, :func:`valid`, the stamp in :func:`attach`, :func:`connecting`) never took a lock for them. A lock of their own
# guarded nothing the window did not already guard, and its one effect was a hazard: a plain ``threading.Lock`` whose ``with`` exit fails (the
# exit builds a 3-tuple, which allocates on CPython 3.13) stays held for ever, and every later section waits behind it with the window held
# (tests/test_swap_window_allocation_failures.py). ``tests/test_library_generation_writers_run_in_the_window.py`` pins that every call of a
# writer, in ``src/``, is made inside the window, so a new writer outside it fails a test and does not race.
_GENERATION = 0
_VALID: frozenset[int] = frozenset({0})
_WINDOW_STAMP: int | None = None  # the stamp of a connection the swap itself opens inside its window, while there is one
_DISK_CHANGED = False  # set inside the window by :func:`disk_changing`: the live log names are being removed or the file replaced


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
    _GENERATION += 1
    _VALID = frozenset({_GENERATION})
    return _GENERATION


def _open_window() -> None:
    """The thread that holds the window opens connections of its own, on the OLD file (the data-version read, a fold of the log): they
    carry the window's own stamp, which only that thread may use while the window runs (:func:`valid`) and which is valid afterwards only
    if the swap did not happen (:func:`_close_window`)."""
    global _WINDOW_STAMP
    _WINDOW_STAMP = -_GENERATION  # never a generation: those count up from zero


def _close_window(*, swapped: bool, earlier: frozenset[int] | None = None) -> None:
    """The window ends. What is read here (``swapped``, :data:`_DISK_CHANGED`), what is decided and what is written are one step, so they cannot
    disagree: an allocation that fails before it leaves only the new generation valid (the safe side), never the window's own connections.

    ``swapped`` says the source is gone, or that nobody could tell (the safe answer); :func:`disk_changing` having been called says the file the
    earlier connections opened is not the library's either. When neither, the swap did not happen: the connections that were valid before
    :func:`bump` (``earlier``, none given means none to give back) and the window's own stamp open the file that is still the library."""
    global _VALID, _WINDOW_STAMP
    # the stamp is taken and cleared in ONE step (no call between), so an interrupt in what follows leaves no stamp set; the cost of that
    # interrupt is a window connection that stays refused, which is the safe side
    stamp, _WINDOW_STAMP = _WINDOW_STAMP, None
    if not swapped and not _DISK_CHANGED:
        _VALID = _VALID.union(earlier or (), () if stamp is None else (stamp,))


# --- the lock --------------------------------------------------------------------------------------------------------------


class _Levels(threading.local):
    """The shared levels THIS thread holds. ``n`` is set in ``__init__``, which runs at the thread's FIRST read of its record
    (:func:`connecting` reads :meth:`_Lock.shared_held_here` before it asks for a level, holding nothing): from then on every store to ``n``
    REPLACES a value, so the take (``self._mine.n += 1``) makes no dict entry. The first store into a thread's empty record allocates, and a
    failure there after the lock's count was raised left the count up and the record empty, which the give-back cannot see (a level raised
    until restart). A read is also an attribute load, not a ``getattr`` call, so the take and the give-back have no call between the
    lock's count and the thread's record of it."""

    n: int

    def __init__(self) -> None:
        self.n = 0


class _Lock:
    """Shared by every connect, exclusive for the swap; the holder's own thread passes through (the swap opens connections itself,
    to fold the log and to read the data version). No writer preference: a shared holder can never be made to wait on a swap that
    waits on it, and the swap's own wait is bounded."""

    def __init__(self) -> None:
        # a plain RLock under the Condition and `with self._lock:` everywhere: a Condition's own __enter__/__exit__ are Python frames, where a
        # KeyboardInterrupt can land between "taken" and "released" and leave the lock taken for ever (see src/config/kv_store.py::_hold_lock)
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._shared = 0
        self._holder: int | None = None
        self._mine = _Levels()  # shared levels THIS thread holds: what a caller reads to learn, after an exception, whether it took one

    def shared_held_here(self) -> int:
        return self._mine.n

    def shared(self) -> bool:
        me = threading.get_ident()
        with self._lock:
            if self._holder == me:
                return False
            # the loop is `while True: if not <wanted>: break` and not `while <wanted>:` -- CPython 3.13 leaves the back-edge of the second form outside the `with`'s exception table (src/utils/interrupts.py)
            while True:
                if self._holder is None:
                    break
                _wait(self._cond, self._lock, _RECHECK_S)  # a step, not a timeout: see _RECHECK_S
            # the count and this thread's record in one step, with no call between them: an exception after the count was raised and before
            # the caller saw the answer still leaves the record, which is what the caller releases by
            self._shared += 1
            self._mine.n += 1
            return True

    def release_shared(self) -> None:
        with self._lock:
            self._shared -= 1
            self._mine.n -= 1
            if not self._shared:
                self._cond.notify_all()

    def release_shared_since(self, before: int) -> None:
        """Give back the level this thread took since it held ``before`` (what :meth:`shared_held_here` said, read BEFORE it asked for one), if
        it took one: the comparison and the two decrements are plain loads, stores and small-integer arithmetic (a result below 257 is a cached
        object, so it makes none), with no call between "the record says it is ours" and "it is released". A caller whose ``shared`` may have
        been interrupted after the level was raised and before it saw the answer cannot tell from outside, and a check made by a call of its
        own (``shared_held_here()`` again) is an instruction that can fail before the release. The one call left after the level is back is
        ``notify_all``; a failure there loses a wake-up, which the swap's bounded wait (:data:`_RECHECK_S`) turns into a delay."""
        with self._lock:
            if self._mine.n > before:
                self._shared -= 1
                self._mine.n -= 1
                if not self._shared:
                    self._cond.notify_all()

    def exclusive(self, timeout: float) -> None:
        me = threading.get_ident()
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            if self._holder == me:
                raise RuntimeError("the library swap window is already held by this thread")
            # the loop is `while True: if not <wanted>: break` and not `while <wanted>:` -- CPython 3.13 leaves the back-edge of the second form outside the `with`'s exception table (src/utils/interrupts.py)
            while True:
                if self._holder is None and not self._shared:
                    break
                left = deadline - time.monotonic()
                if left <= 0:
                    raise LibraryBusy(
                        f"a connection to the library was still being opened after {timeout:.0f} s, so the file was not switched"
                    )
                _wait(self._cond, self._lock, min(left, _RECHECK_S))  # a step, not a shorter timeout: see _RECHECK_S
            self._holder = me

    def held_here(self) -> bool:
        return self._holder == threading.get_ident()

    def release_exclusive(self) -> None:
        with self._lock:
            self._holder = None
            self._cond.notify_all()

    def release_if_held_here(self, me: int) -> None:
        """Release the window only if the thread ``me`` holds it, checked and released under the lock in one call: a caller whose
        ``exclusive`` may have been interrupted after the holder was set and before it saw the answer cannot tell from outside, and two calls
        (``held_here`` then ``release_exclusive``) leave a gap between them.

        ``me`` is the caller's own identity, read BEFORE it asked for the window: the comparison and the clearing of the holder are then plain
        loads and a store with no call between them, so an allocation that fails here cannot leave the holder set (a ``threading.get_ident()``
        call made here was such a site). The one call left after the holder is clear is ``notify_all``; a failure there loses a wake-up, which
        :data:`_RECHECK_S` bounds."""
        with self._lock:
            if self._holder == me:
                self._holder = None
                self._cond.notify_all()


_LOCK = _Lock()
_local = threading.local()


@contextmanager
def connecting() -> Iterator[None]:
    """Around ONE open of a connection to the library file: the generation is read and the file opened under the shared lock, and the
    stamp is handed to the ``connect`` event of the same thread (the DBAPI connection cannot carry it, the pool's record can)."""
    before = _LOCK.shared_held_here()
    took = False
    try:
        took = _LOCK.shared()
        # The thread that holds the window opens its connections BEFORE the replace (the data-version read, a fold of the log): they are
        # on the OLD file, so they carry the window's own stamp, valid inside the window and after it only if the swap did not happen.
        _local.stamp = _GENERATION if took or _WINDOW_STAMP is None else _WINDOW_STAMP
        yield
    except BaseException:
        _local.stamp = None  # an open that failed hands nothing to the next ``connect`` event of this thread
        raise
    finally:
        # what THIS thread holds says whether a level was taken, even if the exception arrived between the take and the answer; ``before`` was
        # read ahead of the take, so the release compares with a value it already has. The one call here that cannot be made safe: if the
        # allocator refuses to start it, nothing after it can run (tests/test_connecting_allocation_failures.py names the site)
        _LOCK.release_shared_since(before)


def _first_read(conn: Any) -> None:
    """ONE read of the schema on a connection just opened, so the file's log names are bound while the lock is still held."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        cur.fetchall()
    finally:
        cur.close()


def guarded_creator(creator: Callable[[], Any]) -> Callable[[], Any]:
    """The engine's ``creator`` wrapped so every connection it makes is opened under :func:`connecting`, and READ once under it.

    A plaintext SQLite connection opens the main file at ``connect`` but opens the ``-wal`` and ``-shm`` BY NAME at its first read, and the
    first read is the engine's ``connect`` listener (the pragmas), which runs AFTER the creator returns and the lock is released. A swap that
    landed in between bound the NEW file's log names to the OLD file, and the schema read failed as malformed: the damage hook read that as damage
    in a healthy file. An encrypted connection reads page 1 to check its key, so the one read here is the plaintext one's; it costs a page already
    in the cache on the other. A connection whose read fails is closed and the error raised from the creator, as an open that failed is."""

    def _guarded() -> Any:
        with connecting():
            conn = creator()
            try:
                _first_read(conn)
            except BaseException:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - the read's error is what matters
                    _LOG.debug("library generation: could not close a connection whose first read failed")
                raise
            return conn

    return _guarded


@contextmanager
def swap_window(source: Path, *, timeout: float = WINDOW_WAIT_S) -> Iterator[None]:
    """The window in which the library's name is moved onto ``source``: no connection is being opened or can be, every connection made
    before it is refused from its first line (bump first), and when the window ends WITHOUT ``source`` having been moved (it still
    exists) and without :func:`disk_changing` having been called (a refusal before anything was touched) the earlier connections are valid
    again. Raises :class:`LibraryBusy` if it cannot be had.

    The lock is given back whatever the cleanup does, except at the one place no code can protect: the call that gives it back, if the
    allocator refuses to start it (natively the ``BEFORE_WITH`` inside it, which makes the bound ``__enter__`` and ``__exit__``). The exit of
    that call's own ``with self._lock:`` is the same kind of site (``__exit__(None, None, None)`` builds a 3-tuple on CPython 3.13 and so
    allocates when the tuple free list is empty); the ``with`` form is what the interrupt rules require (R144, R171) and nothing runs after an
    exit that did not run.

    The swap passes no lock for the module's state. The four names this module writes (:data:`_GENERATION`, :data:`_VALID`, :data:`_WINDOW_STAMP`,
    :data:`_DISK_CHANGED`) are written only here, inside the window, which one thread holds at a time, and they have no lock of their own: a
    plain lock's failed exit stays held, and every later section of the same swap or of the next one would wait behind it with the window held
    (a pool stopped until restart). ``tests/test_swap_window_allocation_failures.py`` forces a MemoryError at every instruction of the cleanup that
    can allocate and names the call, and pins that the module has no ``with`` section left in a writer; ``tests/test_library_generation_writers_run_in_the_window.py``
    pins that every call of a writer in ``src/`` is made inside a window."""
    global _DISK_CHANGED
    # Everything after the identity is inside the outer ``try``, and what the outer ``finally`` releases is read from the lock itself
    # (``held_here``), not from a flag set after ``exclusive`` returned: an interrupt between "the holder was set" and "the caller saw the
    # answer" still finds the lock held by this thread and releases it (src/utils/interrupts.py). The identity is read FIRST, before anything
    # is held, so the release at the end compares with a value it already has and calls nothing to learn it.
    me = threading.get_ident()
    before = _LOCK.held_here()  # already held: ``exclusive`` raises, and what this thread holds is not ours to release
    earlier = _VALID
    swapped = True  # until the window ends with the source still there
    try:
        _LOCK.exclusive(timeout)
        earlier = _VALID
        _DISK_CHANGED = False
        try:
            bump()
            _open_window()
            yield
        finally:
            try:
                swapped = not source.exists()
            except OSError:  # cannot tell whether the file moved: stale is the safe answer
                _LOG.debug("library generation: could not tell whether the swap happened; the old connections stay refused")
    finally:
        try:
            if not before and _LOCK.held_here():  # a window that was never had (LibraryBusy) has no stamp to clear
                _close_window(swapped=swapped, earlier=earlier)
        finally:
            if not before:
                _LOCK.release_if_held_here(me)  # the one call here that cannot be made safe: if it cannot start, nothing after it can run


def disk_changing() -> None:
    """Called by the swap, inside its window, just BEFORE it removes the live file's ``-wal``/``-shm`` (or replaces the file).

    From then on the connections made before the window are not the library's again, even if the replace fails. A pooled connection
    reads at connect (the pragmas), so it holds the log by an inode no name points at once the names are removed: a save through it
    commits into that log, which no later connection opens (a fresh ``-wal`` is made by name), and the file under it can answer
    ``disk I/O error``. Measured with the app's own connect listener on the engine. A refusal BEFORE this call (the repair's
    data-version check) changes nothing on disk, and the window still gives the earlier connections their validity back."""
    global _DISK_CHANGED
    _DISK_CHANGED = True


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
        "the library file was replaced, or was being replaced, while this was open, so nothing was run or saved; do it again"
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
            raise exc.DisconnectionError("the library file was replaced, or was being replaced; this connection belongs to the old one")

    @event.listens_for(engine, "before_cursor_execute")
    def _refuse_stale_statement(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:  # noqa: ANN001
        _refuse(conn)

    @event.listens_for(engine, "commit")
    def _refuse_stale_commit(conn) -> None:  # noqa: ANN001
        _refuse(conn)
