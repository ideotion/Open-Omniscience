"""The split corpus's writer core (R826 stage 3a, row 409).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS STAGE IS. The one place a segment file is written, and nothing in the app that calls it yet: every public entry
starts with :func:`segment_open.require_writes`, which refuses while the module's switch is off (it stays off until the
erase, backup/restore and passphrase stages are on main, R826). The app's write sites move onto it after stage 4, because
de-duplication has to see every segment first.

ONE WRITER, THE OPEN SEGMENT. :func:`open_writer` settles the registry (a ``reserved`` row a crash left is opened or
abandoned by stage 1's rule; more than one ``open`` row keeps only the newest), makes the first segment when there is
none, and opens the one ``open`` segment READ-WRITE through the app's factory, checked exactly as the reader is
(``segment_open._prechecked`` and ``_check_open``). A read-write open rolls back a hot journal a crash left, by SQLite's
own rule, before the first read. Temporary storage is memory only (R825: SQLCipher's FILE temp was measured plaintext).
One writer per process.

IDS. A write transaction takes ids with :meth:`SegmentTransaction.allocate`, from the segment's own ``next_id``, raised in
the SAME transaction as the rows that use them: a rollback gives the ids back, a commit keeps them, and an id is never given
out twice, even after the article holding it is deleted. A segment that cannot hold the ids asked for raises
:class:`SegmentFull`; :func:`rollover` then closes it and opens the next, whose size follows R826 Q4
(``segments.next_segment_size``).

THE GENERATION NUMBER. Every committed write transaction raises the file's ``segment_meta.generation`` inside that
transaction, and then the registry's ``corpus_segments.generation`` in a shared-file transaction of its own. The file is
always raised FIRST, so a crash between the two leaves the file NEWER than the registry: that is recovered (the next open
raises the registry to the file's number) and never refused. A file OLDER than the registry is an earlier copy put back in
the segment's place, and the reader and the writer both refuse it ("older_copy").
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Iterator
from typing import Any

from src.database import segment_open
from src.database.segment_open import (
    SegmentUnavailable,
    _absent_sidecars,
    _check_open,
    _checked_connect,
    _held_or_unreadable,
    _prechecked,
    _remove_sidecars_made,
    create_segment,
    require_writes,
)
from src.database.segments import (
    Segment,
    SegmentError,
    mark_closed,
    mark_open,
    next_segment_size,
    reconcile,
    record_generation,
    registry,
    reserve_segment,
    segment_counters,
    segment_identity,
)
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: Held by the one open :class:`SegmentWriter` of this process.
_WRITER_LOCK = threading.Lock()
#: Held across every registry step of :func:`open_writer`, :func:`rollover` and :meth:`SegmentWriter.open`, so two threads never
#: both find "no open segment" and each make one, and settling never closes the segment a live writer holds.
_REGISTRY_LOCK = threading.RLock()


class SegmentFull(SegmentError):
    """The open segment's id range cannot hold the ids asked for: :func:`rollover` to the next segment."""


class WriterBusy(SegmentError):
    """This process already has the open segment open for writing (or the caller is inside that writer's transaction)."""


class SegmentTransaction:
    """One write transaction on the open segment (see :meth:`SegmentWriter.transaction`)."""

    def __init__(self, con: Any, seg: Segment) -> None:
        self.con = con
        self.seg = seg

    def allocate(self, n: int) -> range:
        """``n`` new article ids from the segment's range, taken in this transaction. Raises :class:`SegmentFull` when the
        range cannot hold them (nothing is taken)."""
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise SegmentError("ids are taken a whole number at a time, at least 1")
        _still_in_transaction(self.con)
        counters = segment_counters(self.con)
        if counters is None:
            raise SegmentError("the segment records no id counter")
        lo = counters[1]
        hi = self.seg.id_hi
        if hi is None or lo < self.seg.id_lo or lo + n - 1 > hi:
            raise SegmentFull("the open segment cannot hold that many more articles")
        self.con.execute("UPDATE segment_meta SET next_id = ?", (lo + n,))
        return range(lo, lo + n)


def _still_in_transaction(con: Any) -> None:
    # SQLite rolls a transaction back by itself on SQLITE_FULL, an I/O error and the like; a caller that caught that error and
    # carried on would otherwise commit every later statement on its own, in autocommit.
    if not getattr(con, "in_transaction", False):
        raise SegmentError("the segment's transaction ended early (SQLite rolled it back); nothing more is written in it")


class SegmentWriter:
    """The read-write connection to the open segment. Use :func:`open_writer`; close it with :meth:`close`."""

    def __init__(self, seg: Segment, con: Any, shared_con: Any, owed: int | None) -> None:
        self.seg = seg
        self._con = con
        self._shared = shared_con
        self._lock = threading.Lock()
        self._owner: int | None = None  # the thread inside a transaction, so a nested call raises instead of hanging
        self._closed = False
        self._owed = owed  # a generation the file has and the registry does not yet

    @classmethod
    def open(cls, shared_con: Any, seg: Segment, *, key: str | None = None) -> SegmentWriter:
        """Open ``seg`` (an ``open`` registry row) for writing. The file is first opened READ-ONLY by the reader with every
        check (a hot journal rolled back, rollback-journal mode, schema, identity, generation), so a file a read-write open
        could harm is refused before one is made; then it is opened read-write and checked again. The registry's
        generation is raised to the file's when a crash left it behind. Raises :class:`SegmentUnavailable`,
        :class:`WriterBusy` or :class:`SegmentError`."""
        require_writes()
        if seg.state != "open":
            raise SegmentError("only the open segment is written")
        with _REGISTRY_LOCK:
            if not _WRITER_LOCK.acquire(blocking=False):
                raise WriterBusy("this process already has the open segment open for writing")
            try:
                con = _open_read_write(seg, key)
                counters = segment_counters(con)
                if counters is None:
                    con.close()
                    raise SegmentUnavailable(seg.seg_no, "identity")
                writer = cls(seg, con, shared_con, counters[0] if seg.generation is None or counters[0] > seg.generation else None)
            except BaseException:
                _WRITER_LOCK.release()
                raise
        writer._pay_generation()
        return writer

    def _pay_generation(self) -> None:
        """Raise the registry to the generation the file already has. A failure is kept owed and retried at the next commit
        and at close, never raised: the file's write is committed, and an error here would make a caller write it again."""
        owed = self._owed
        if owed is None:
            return
        try:
            record_generation(self._shared, self.seg.seg_no, owed)
        except Exception as exc:  # noqa: BLE001 - see the docstring; the text stays in the debug log
            log_failure(_LOG, "the segment registry's generation could not be raised yet", exc, level=logging.DEBUG)
            return
        if self._owed == owed:
            self._owed = None

    @contextlib.contextmanager
    def transaction(self) -> Iterator[SegmentTransaction]:
        """One write transaction on the segment (BEGIN IMMEDIATE): the caller writes its rows and takes their ids with
        ``allocate``; on success the file's generation is raised inside the transaction and it commits, and then the
        registry's generation follows in a shared-file transaction of its own (a failure there is retried later, never
        raised: the rows are committed). Any error before the commit rolls the segment back. A transaction (or
        :func:`rollover`, or :meth:`close`) started inside another one in the same thread raises :class:`WriterBusy`."""
        me = threading.get_ident()
        if self._owner == me:
            raise WriterBusy("a transaction is already open on this writer in this thread")
        with self._lock:
            try:
                self._owner = me
                require_writes()
                if self._closed:
                    raise SegmentError("this writer is closed")
                con = self._con
                con.execute("BEGIN IMMEDIATE")
                try:
                    yield SegmentTransaction(con, self.seg)
                    _still_in_transaction(con)
                    con.execute("UPDATE segment_meta SET generation = generation + 1")
                    counters = segment_counters(con)
                    if counters is None:
                        raise SegmentError("the segment records no generation")
                    con.execute("COMMIT")
                except BaseException:
                    if getattr(con, "in_transaction", False):
                        con.execute("ROLLBACK")
                    raise
                # The file is raised; a crash from here on leaves it newer than the registry, which is recovered.
                self._owed = counters[0]
                self._pay_generation()
            finally:
                self._owner = None

    def close(self) -> None:
        """Close the writer: the registry's generation is caught up first when it was owed, then the connection closes and
        the process's writer lock is released."""
        if self._owner == threading.get_ident():
            raise WriterBusy("the writer is closed outside its own transaction")
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._pay_generation()
                self._con.close()
            finally:
                _WRITER_LOCK.release()


def _open_read_write(seg: Segment, key: str | None) -> Any:
    """The checked read-write connection to ``seg`` (see :meth:`SegmentWriter.open`)."""
    segment_open.open_segment(seg, key=key).close()  # every check, read-only first
    path, before, shared_encrypted = _prechecked(seg)
    if not segment_open._no_log_beside(path):
        raise SegmentUnavailable(seg.seg_no, "not_a_segment_file")
    absent_before = _absent_sidecars(path)
    con = _checked_connect(seg, path, key, bool(shared_encrypted), read_only=False)
    try:
        _check_open(seg, con, path, before, bool(shared_encrypted))
        con.execute("PRAGMA temp_store = MEMORY")  # R825: never a plaintext temporary file
        con.isolation_level = None
    except SegmentUnavailable:
        con.close()
        _remove_sidecars_made(path, absent_before)
        raise
    except Exception as exc:  # noqa: BLE001 - one fixed reason, the text stays in the debug log
        con.close()
        _remove_sidecars_made(path, absent_before)
        log_failure(_LOG, "a corpus segment could not be opened for writing", exc, level=logging.DEBUG)
        raise SegmentUnavailable(seg.seg_no, _held_or_unreadable(exc)) from None
    return con


def _settle(shared_con: Any, key: str | None) -> list[Segment]:
    """Settle what a crash may have left: ``reserved`` rows (opened when the file proves its identity, else abandoned) and
    more than one ``open`` row (all but the newest close). Returns the registry afterwards."""
    by_name = {s.file_name: s for s in registry(shared_con) if s.file_name is not None}

    def identity_of(file_name: str | None) -> tuple[int, int, int] | None:
        seg = by_name.get(file_name) if file_name is not None else None
        if seg is None:
            return None
        try:
            con = segment_open.open_segment(seg, key=key)
        except (SegmentUnavailable, SegmentError):
            return None
        try:
            return segment_identity(con)
        finally:
            con.close()

    reconcile(shared_con, identity_of)
    segs = registry(shared_con)
    opens = sorted((s for s in segs if not s.implicit and s.seg_no >= 1 and s.state == "open"), key=lambda s: s.seg_no)
    for s in opens[:-1]:
        mark_closed(shared_con, s.seg_no)
    return registry(shared_con) if len(opens) > 1 else segs


def _start_segment(shared_con: Any, segs: list[Segment], key: str | None) -> None:
    """Reserve, make and open the next segment (stage 1's three durable steps)."""
    r = reserve_segment(shared_con, next_segment_size(segs))
    create_segment(r, key=key)
    mark_open(shared_con, r)


def open_writer(shared_con: Any, *, key: str | None = None) -> SegmentWriter:
    """The writer of the one open segment, making the first segment when there is none. ``shared_con`` is a DB-API
    connection to the SHARED file in autocommit mode (``isolation_level=None``). Raises :class:`WriterBusy` while this
    process already has a writer: settling then could close the segment it is writing."""
    require_writes()
    with _REGISTRY_LOCK:
        if _WRITER_LOCK.locked():
            raise WriterBusy("this process already has the open segment open for writing")
        segs = _settle(shared_con, key)
        opens = [s for s in segs if not s.implicit and s.seg_no >= 1 and s.state == "open"]
        if not opens:
            _start_segment(shared_con, segs, key)
            segs = registry(shared_con)
            opens = [s for s in segs if not s.implicit and s.seg_no >= 1 and s.state == "open"]
        if len(opens) != 1:
            raise SegmentError("the registry has no single open segment")
        return SegmentWriter.open(shared_con, opens[0], key=key)


def rollover(writer: SegmentWriter, *, key: str | None = None) -> SegmentWriter:
    """Close the full segment and open the next, all under the registry lock (no other thread can open a writer or settle
    the registry in between). The old writer is closed first (its owed generation caught up); the old segment's row moves
    to ``closed`` before the next is reserved, so a crash in between leaves no open segment, and the next
    :func:`open_writer` makes one."""
    require_writes()
    with _REGISTRY_LOCK:
        shared_con, seg_no = writer._shared, writer.seg.seg_no
        writer.close()
        mark_closed(shared_con, seg_no)
        return open_writer(shared_con, key=key)
