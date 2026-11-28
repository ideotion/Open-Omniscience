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
import functools
import json
import logging
import threading
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
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
from src.database.segment_schema import SEGMENT_TABLES, SHARED_REFERENCES
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

    def __init__(self, con: Any, seg: Segment, shared_con: Any = None) -> None:
        self.con = con
        self.seg = seg
        self._shared = shared_con

    def add_articles(self, rows: Sequence[Mapping[str, Any]]) -> list[int]:
        """Insert ``rows`` into the segment's ``articles`` with new ids from its range (an ``id`` in a row is refused), and
        return the ids in row order. Model defaults fill the columns a row leaves out. Every reference to the shared file is
        checked first (:func:`check_shared_references`). Raises :class:`SegmentFull` when the range cannot hold them."""
        if not rows:
            return []
        if any("id" in r for r in rows):
            raise SegmentError("an article's id is given by the segment, never by the caller")
        ids = self.allocate(len(rows))
        self._insert("articles", [{**r, "id": i} for r, i in zip(rows, ids, strict=True)])
        return list(ids)

    def add_rows(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        """Insert ``rows`` into one of the segment's per-article tables other than ``articles``. Each row's ``article_id``
        must be an article of THIS segment (a foreign key inside the file, enforced by SQLite) and every reference to the
        shared file must exist there (:func:`check_shared_references`)."""
        if table == "articles" or table not in SEGMENT_TABLES:
            raise SegmentError("not a per-article table of a segment (articles go through add_articles)")
        if rows:
            self._insert(table, rows)

    def _insert(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        _still_in_transaction(self.con)
        columns = _columns(table)
        filled = [_with_defaults(table, r) for r in rows]
        names = sorted({k for r in filled for k in r})
        unknown = [n for n in names if n not in columns]
        if unknown:
            raise SegmentError("a row names a column the segment's table does not have")
        check_shared_references(self._shared, table, filled)
        sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"  # noqa: S608  # nosec B608 # table from SEGMENT_TABLES, names checked against its columns above; values bound
        self.con.executemany(sql, [tuple(r.get(n) for n in names) for r in filled])

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


@functools.cache
def _columns(table: str) -> frozenset[str]:
    from src.database.models import Base

    return frozenset(c.name for c in Base.metadata.tables[table].columns)


@functools.cache
def _defaults(table: str) -> tuple[tuple[str, Any], ...]:
    """(column, model default) for every column whose default the MODEL supplies (Python side): a raw INSERT would leave it
    NULL where the ORM would have filled it."""
    from src.database.models import Base

    out = []
    for col in Base.metadata.tables[table].columns:
        d = col.default
        if d is not None and (getattr(d, "is_scalar", False) or getattr(d, "is_callable", False)):
            out.append((col.name, d))
    return tuple(out)


def _with_defaults(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for name, d in _defaults(table):
        if name not in out:
            out[name] = d.arg(None) if d.is_callable else d.arg
    return {k: _stored(v) for k, v in out.items()}


def _stored(value: Any) -> Any:
    """A value as SQLAlchemy stores it on SQLite, so a segment row reads like a shared-file row: a datetime as naive UTC
    text ``YYYY-MM-DD HH:MM:SS.ffffff``, a date as ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


#: For each shared table a segment row may name: the ids of a JSON list that the shared file does NOT have. One literal
#: statement per table (no SQL is built from data).
_MISSING_IN_SHARED: dict[str, str] = {
    "sources": "SELECT DISTINCT value FROM json_each(?) WHERE value NOT IN (SELECT id FROM sources)",
    "keywords": "SELECT DISTINCT value FROM json_each(?) WHERE value NOT IN (SELECT id FROM keywords)",
}


def check_shared_references(shared_con: Any, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """THE CHECK THAT STANDS IN FOR THE CROSS-FILE FOREIGN KEYS (R826 §2; ``segment_schema.SHARED_REFERENCES``): every
    non-NULL id a segment row gives in a column that names a shared-file row must exist in the shared file, which commits
    those rows BEFORE the segment rows that use them. Refused with :class:`SegmentError` otherwise, before anything is
    written. A non-integer id is refused too."""
    for (ref_table, column), shared_table in SHARED_REFERENCES.items():
        if ref_table != table:
            continue
        values = {r[column] for r in rows if r.get(column) is not None}
        if not values:
            continue
        if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
            raise SegmentError("a row names a shared-file row by something that is not an id")
        if shared_con is None:
            raise SegmentError("the shared file is needed to check this row's references")
        if getattr(shared_con, "in_transaction", False):
            # A shared row inside an open transaction could still roll back after the segment commits; it must be committed.
            raise SegmentError("the shared rows a segment names must be committed first; nothing was written")
        missing = shared_con.execute(_MISSING_IN_SHARED[shared_table], (json.dumps(sorted(values)),)).fetchall()
        if missing:
            raise SegmentError("a row names a shared-file row that does not exist; nothing was written")


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
        # The schema version the exact-schema check saw. Each transaction re-reads it, so a schema changed under the open
        # writer (a trigger added by another writer of the folder) never runs with trusted_schema on.
        self._schema_version = con.execute("PRAGMA schema_version").fetchone()[0]

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
                    if con.execute("PRAGMA schema_version").fetchone()[0] != self._schema_version:
                        raise SegmentError("the segment's schema changed after it was checked; it is not written")
                    yield SegmentTransaction(con, self.seg, self._shared)
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
        con.execute("PRAGMA foreign_keys = ON")  # article_id -> articles, inside the file
        # The search indexes' sync triggers call the app's own functions (registered on every connection the factory makes),
        # which SQLite refuses inside a trigger while trusted_schema is off. The schema was just checked to be EXACTLY what
        # this build makes (no trigger or view of anyone else's), so the triggers that run are the app's own.
        con.execute("PRAGMA trusted_schema = ON")
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


def _open_segments(segs: list[Segment]) -> list[Segment]:
    """The registered segment files in the ``open`` state. A function of its own so the filter's loop never runs inside the
    registry lock's ``with`` (tests/test_database_loop_heads_are_classified.py)."""
    return [s for s in segs if not s.implicit and s.seg_no >= 1 and s.state == "open"]


def open_writer(shared_con: Any, *, key: str | None = None) -> SegmentWriter:
    """The writer of the one open segment, making the first segment when there is none. ``shared_con`` is a DB-API
    connection to the SHARED file in autocommit mode (``isolation_level=None``). Raises :class:`WriterBusy` while this
    process already has a writer: settling then could close the segment it is writing."""
    require_writes()
    with _REGISTRY_LOCK:
        if _WRITER_LOCK.locked():
            raise WriterBusy("this process already has the open segment open for writing")
        segs = _settle(shared_con, key)
        opens = _open_segments(segs)
        if not opens:
            _start_segment(shared_con, segs, key)
            opens = _open_segments(registry(shared_con))
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
