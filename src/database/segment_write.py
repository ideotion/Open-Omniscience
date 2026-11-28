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
import os
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
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
    create_bulk_segment,
    create_segment,
    require_writes,
)
from src.database.segment_schema import SEGMENT_TABLES, SHARED_REFERENCES
from src.database.segments import (
    Reservation,
    Segment,
    SegmentError,
    commit_segment,
    mark_abandoned,
    mark_closed,
    mark_open,
    mark_sealed,
    next_segment_size,
    reconcile_one,
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
#: The reservations a live :class:`BulkLoad` of this process holds (changed only under :data:`_REGISTRY_LOCK`): settling the
#: registry leaves them alone, since a file with no identity yet is a load in progress, not a crash's leftover.
_BULK_LOADING: set[int] = set()
#: Held across every statement this module runs on the SHARED connection. The writer, a bulk load and the registry steps can
#: run on different threads over ONE ``shared_con``; without it one thread's BEGIN could meet another's open transaction on
#: the same connection (refused, or worse, a statement committed inside someone else's transaction), and the reference
#: check could read another thread's uncommitted rows. No lock of THIS module is taken while it is held, and nothing called
#: under it calls back into this module, so it adds no lock order to :data:`_REGISTRY_LOCK`, the writer's or a load's. (It
#: is held only around registry statements: a segment file is never opened under it, see :func:`_settle`.)
_SHARED_LOCK = threading.RLock()


def _on_shared(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """``fn(*args, **kwargs)``, a registry step or a read on the shared connection, under :data:`_SHARED_LOCK`."""
    with _SHARED_LOCK:
        return fn(*args, **kwargs)


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
        if _on_shared(_missing_in_shared, shared_con, shared_table, values):
            raise SegmentError("a row names a shared-file row that does not exist; nothing was written")


def _missing_in_shared(shared_con: Any, shared_table: str, values: set[int]) -> list[Any]:
    if getattr(shared_con, "in_transaction", False):
        # A shared row inside an open transaction could still roll back after the segment commits; it must be committed.
        raise SegmentError("the shared rows a segment names must be committed first; nothing was written")
    return list(shared_con.execute(_MISSING_IN_SHARED[shared_table], (json.dumps(sorted(values)),)).fetchall())


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
            _on_shared(record_generation, self._shared, self.seg.seg_no, owed)
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
    # The read-only open above confirmed this file and rolled back any journal it had. A journal there NOW was not
    # confirmed: a read-write open would roll it into whatever file holds the name, so it is refused and left alone.
    if segment_open._journal_left(path):
        raise SegmentUnavailable(seg.seg_no, "unreadable")
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
    more than one ``open`` row (all but the newest close). Returns the registry afterwards.

    A reservation a LIVE bulk load holds is not a crash's leftover and is left alone: this process's own
    (:data:`_BULK_LOADING`) and any other process's on the same data folder (its claim file, :func:`_claimed_elsewhere`).
    The claims are read AFTER the registry: a load writes its claim before its reservation commits, so a reservation this
    settle sees is always one whose claim it sees too. Each file is opened outside :data:`_SHARED_LOCK`, which is held only
    around the registry's own statements."""
    segs = _on_shared(registry, shared_con)
    by_name = {s.file_name: s for s in segs if s.file_name is not None}
    own = frozenset(_BULK_LOADING)
    claimed: _Claims | None = None
    for s in segs:
        if s.implicit or s.state != "reserved" or s.seg_no in own:
            continue
        if claimed is None:
            claimed = _claimed_elsewhere()
        if claimed.reserving or s.seg_no in claimed.seg_nos:
            continue
        _on_shared(reconcile_one, shared_con, s, _identity_on_disk(by_name.get(s.file_name), key))
    segs = _on_shared(registry, shared_con)
    opens = sorted((s for s in segs if not s.implicit and s.seg_no >= 1 and s.state == "open"), key=lambda s: s.seg_no)
    for s in opens[:-1]:
        _on_shared(mark_closed, shared_con, s.seg_no)
    return _on_shared(registry, shared_con) if len(opens) > 1 else segs


def _identity_on_disk(seg: Segment | None, key: str | None) -> tuple[int, int, int] | None:
    """The identity ``seg``'s file records, read by the checked opener, or None when it proves nothing."""
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


# --- a live bulk load's claim, seen by every process on the data folder (R826 stage 4a) -------------------------------

#: This process's claim file name part (as a corpus lease names its process).
_CLAIM_PROCESS = uuid.uuid4().hex
_CLAIM_SUFFIX = ".claim"
#: How long a claim file that cannot be read still holds every reservation: ``corpus_lease``'s figure for a lease (10 s).
_UNREADABLE_CLAIM_S = 10.0
#: True between a load's claim and its reservation's commit (changed only under :data:`_REGISTRY_LOCK`).
_RESERVING: list[bool] = [False]


@dataclass(frozen=True)
class _Claims:
    seg_nos: frozenset[int]
    reserving: bool  # another process is between its claim and its reservation: no reserved row is settled now


def _claims_folder() -> Any:
    from src.paths import data_dir

    return data_dir() / "leases"


def _write_claim() -> None:
    """Write (or remove, when it holds nothing) this process's claim: the reservations its live bulk loads hold, and
    whether one is being reserved now. The caller holds :data:`_REGISTRY_LOCK`. Raises when it cannot be written: a load
    that other processes cannot see could be abandoned under it, so it is refused before anything is reserved."""
    from src.safety import process_owner
    from src.safety.file_lock import atomic_replace

    path = _claims_folder() / f"segment-load.{_CLAIM_PROCESS}{_CLAIM_SUFFIX}"
    if not _BULK_LOADING and not _RESERVING[0]:
        path.unlink(missing_ok=True)
        return
    owner = process_owner.owner_record()
    if not owner:  # psutil failed: a claim nobody can ever judge dead would hold every settle until it is deleted by hand
        raise SegmentError("this process could not be recorded, so no bulk load is started")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    record = {**owner, "process": _CLAIM_PROCESS, "seg_nos": sorted(_BULK_LOADING),
              "reserving": _RESERVING[0]}
    atomic_replace(path, json.dumps(record), fsync=True)


def _rewrite_claim() -> None:
    """:func:`_write_claim` after a load ended, its registry row already moved on. Best effort: a claim left naming a row
    that is no longer reserved holds nothing, and one left "reserving" only makes other processes wait to settle until
    this process ends (its owner is then dead and the file is removed)."""
    try:
        _write_claim()
    except Exception as exc:  # noqa: BLE001 - see the docstring; the text stays in the debug log
        log_failure(_LOG, "a bulk load's claim could not be updated", exc, level=logging.DEBUG)


def _claimed_elsewhere() -> _Claims:
    """Every OTHER process's live claim on this data folder. A claim whose owner is alive, or cannot be judged (another
    host on a shared drive, an unreadable record), holds its reservations; a dead owner's claim is a leftover and is
    removed. A claim file that cannot be read at all holds every reservation (fail closed: the next settle tries again)."""
    from src.safety import process_owner

    seg_nos: set[int] = set()
    reserving = False
    try:
        files = sorted(_claims_folder().glob(f"segment-load.*{_CLAIM_SUFFIX}"))
    except OSError:
        return _Claims(frozenset(), True)
    for f in files:
        rec = _read_claim(f)
        if rec is None:
            # Unreadable: held while it is new (a shared drive's rename that is not atomic can show a live writer's file
            # half written), then a leftover, as ``corpus_lease`` treats an unreadable lease (10 s).
            if _older_than(f, _UNREADABLE_CLAIM_S):
                f.unlink(missing_ok=True)
            else:
                reserving = True
            continue
        if rec.get("process") == _CLAIM_PROCESS:
            continue
        if process_owner.record_state(rec, machine=process_owner.machine_tag()) == "dead":
            f.unlink(missing_ok=True)
            continue
        seg_nos.update(int(n) for n in rec.get("seg_nos", ()) if isinstance(n, int) and not isinstance(n, bool))
        reserving = reserving or bool(rec.get("reserving"))
    return _Claims(frozenset(seg_nos), reserving)


def _older_than(f: Any, seconds: float) -> bool:
    try:
        return time.time() - os.lstat(f).st_mtime > seconds
    except OSError:
        return False


def _read_claim(f: Any) -> dict | None:
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _start_segment(shared_con: Any, segs: list[Segment], key: str | None) -> None:
    """Reserve, make and open the next segment (stage 1's three durable steps)."""
    r = _on_shared(reserve_segment, shared_con, next_segment_size(segs))
    create_segment(r, key=key)
    _on_shared(mark_open, shared_con, r)


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
            opens = _open_segments(_on_shared(registry, shared_con))
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
        _on_shared(mark_closed, shared_con, seg_no)
        return open_writer(shared_con, key=key)


class _BulkTransaction(SegmentTransaction):
    """One transaction of a :class:`BulkLoad`: ids come from the load's own counter (the file records no identity, and so
    no ``next_id``, until the seal), taken for good only when the transaction commits."""

    def __init__(self, con: Any, seg: Segment, shared_con: Any, next_id: int) -> None:
        super().__init__(con, seg, shared_con)
        self.next_id = next_id

    def allocate(self, n: int) -> range:
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise SegmentError("ids are taken a whole number at a time, at least 1")
        _still_in_transaction(self.con)
        lo, hi = self.next_id, self.seg.id_hi
        if hi is None or lo < self.seg.id_lo or lo + n - 1 > hi:
            raise SegmentFull("the segment being loaded cannot hold that many more articles")
        self.next_id = lo + n
        return range(lo, lo + n)


class BulkLoad:
    """AN IMPORT'S ROWS LOADED INTO A FRESH SEGMENT (R826 stage 3c, row 409; the index window's segment form, row 407).

    :func:`open_bulk_load` reserves a new segment and makes its file with the per-article tables, their UNIQUE indexes and
    the title index, but none of the non-unique indexes and none of the article search index's sync triggers, and no
    identity. Each :meth:`transaction` then writes rows exactly as the open segment's writer does (ids from the segment's
    range, every shared-file reference checked first), without paying per row for an index nobody reads yet. :meth:`seal`
    adds the deferred indexes and triggers and indexes every article for search once (``fts.rebuild_index``), all in one
    transaction; writes the identity; reads the file back with every reader check (the exact schema among them); names it
    in the at-rest record; and moves the registry row from ``reserved`` to ``closed``. The segment the app writes to stays
    the one already open.

    A CRASH LEAVES NOTHING READABLE. Until the identity is written the file proves nothing, so the reservation of a process
    that died mid-load is abandoned by ``segments.reconcile`` and the file is never read; its ids are never given out again.
    A crash after the identity and before the registry step leaves a complete segment that ``reconcile`` opens, and
    settling then keeps it as the open segment (the newest); nothing is lost. A load that fails in this process (an error,
    :meth:`abandon`) abandons its reservation and removes its own file, as a failed create does.

    EVERY PROCESS (stage 4a). This process's settles leave the reservation alone through ``_BULK_LOADING``; every other
    process's through the load's claim file in the leases folder (``segment-load.<uuid hex>.claim``), written before the
    reservation commits and read by a settle after its registry read. A claim whose owner is dead is a leftover and is
    removed. NOT covered: the writer's own reservation (``_start_segment``) holds no claim; stage 4's write-site wiring
    claims it, or runs every settle in the writer's process, before any write path is turned on.

    Temporary storage is memory only (R825), and nothing is read from the file before the seal checks it, so no sync
    trigger of anyone else's can run: the schema the load writes under is the one this call made, on a file name this call
    took empty."""

    def __init__(self, shared_con: Any, r: Reservation, path: Any, ident: tuple[int, int], con: Any, encrypted: bool,
                 key: str | None) -> None:
        self._shared = shared_con
        self._r = r
        self.seg = Segment(r.seg_no, r.file_name, "reserved", r.id_lo, r.id_hi)
        self._path = path
        self._ident = ident
        self._con = con
        self._encrypted = encrypted
        self._key = key
        self._next = r.id_lo
        self._done = False
        self._lock = threading.Lock()
        # The schema this call made: a change by anyone else is refused before any trigger can run (as the writer does).
        self._schema_version = con.execute("PRAGMA schema_version").fetchone()[0]

    def __enter__(self) -> BulkLoad:
        return self

    def __exit__(self, *exc: object) -> None:
        """A load left unsealed when its ``with`` block ends is abandoned, so it never holds its reservation."""
        if not self._done:
            self.abandon()

    def _check_schema(self, con: Any) -> None:
        if con.execute("PRAGMA schema_version").fetchone()[0] != self._schema_version:
            raise SegmentError("the segment's schema changed while it was loaded; it is not written")

    @property
    def next_id(self) -> int:
        """The first id the load has not used."""
        return self._next

    @contextlib.contextmanager
    def transaction(self) -> Iterator[SegmentTransaction]:
        """One write transaction on the segment being loaded (BEGIN IMMEDIATE): ``add_articles`` takes ids from the
        segment's range and raises :class:`SegmentFull` when it cannot hold them; ``add_rows`` writes the other per-article
        tables. An error before the commit rolls this transaction back and keeps the load usable."""
        require_writes()
        if not self._lock.acquire(blocking=False):
            raise WriterBusy("a transaction is already open on this bulk load")
        try:
            if self._done:
                raise SegmentError("this bulk load is sealed or abandoned")
            con = self._con
            con.execute("BEGIN IMMEDIATE")
            try:
                self._check_schema(con)
                tx = _BulkTransaction(con, self.seg, self._shared, self._next)
                yield tx
                _still_in_transaction(con)
                con.execute("COMMIT")
            except BaseException:
                if getattr(con, "in_transaction", False):
                    con.execute("ROLLBACK")
                raise
            self._next = tx.next_id
        finally:
            self._lock.release()

    def seal(self) -> Segment:
        """Finish the load (see the class note) and return the segment as the registry now has it, ``closed``. On any
        failure the load is abandoned and its file removed, and the error is raised."""
        from src.database import fts
        from src.database.segment_open import _identity_of_name, record_keyed, segment_ddl
        from src.database.segment_schema import bulk_split

        require_writes()
        if not self._lock.acquire(blocking=False):
            raise WriterBusy("the bulk load is sealed outside its own transaction")
        try:
            if self._done:
                raise SegmentError("this bulk load is sealed or abandoned")
            con = self._con
            try:
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._check_schema(con)
                    for ddl in bulk_split(segment_ddl())[1]:
                        con.execute(ddl)
                    fts.rebuild_index(con)  # after the triggers: the index is written the way their delete side reads it
                    _still_in_transaction(con)
                    con.execute("COMMIT")
                except BaseException:
                    if getattr(con, "in_transaction", False):
                        con.execute("ROLLBACK")
                    raise
                if _identity_of_name(self._path) != self._ident:
                    raise SegmentError("the segment's name led to another file while it was loaded; it is not sealed")
                commit_segment(con, self._r, next_id=self._next)
                con.close()
                if self._encrypted:
                    record_keyed(self.seg, self._path, self._key)
                else:
                    segment_open.open_segment(self.seg, key=self._key).close()  # every reader check, the schema among them
                if _identity_of_name(self._path) != self._ident:
                    raise SegmentError("the segment's name led to another file while it was checked; it is not sealed")
                _on_shared(record_generation, self._shared, self._r.seg_no, 1)
                _on_shared(mark_sealed, self._shared, self._r)
            except BaseException:
                self._give_up()
                raise
            self._finish()
        finally:
            self._lock.release()
        return next(s for s in _on_shared(registry, self._shared) if s.seg_no == self._r.seg_no)

    def abandon(self) -> None:
        """Give the load up: its reservation is abandoned and its file removed. Nothing of it was ever readable."""
        if not self._lock.acquire(blocking=False):
            raise WriterBusy("the bulk load is abandoned outside its own transaction")
        try:
            if not self._done:
                self._give_up()
        finally:
            self._lock.release()

    def _give_up(self) -> None:
        from src.database.segment_open import _free_failed, corpus_folder

        # The file goes first and the registry step runs whatever that did: a reserved row whose file is gone is always
        # abandoned safely, where a kept file with an identity would be opened by the next settle. A row the registry
        # already has ``closed`` (a seal whose last commit raised yet landed) keeps its file; a registry that cannot be
        # read keeps it too, since removing a closed segment's file would lose it.
        try:
            with contextlib.suppress(Exception):
                self._con.close()
            try:
                closed = any(s.seg_no == self._r.seg_no and s.state == "closed" for s in _on_shared(registry, self._shared))
            except Exception:
                closed = True
            try:
                if not closed:
                    _free_failed(corpus_folder(), self._path, self._ident)
            finally:
                _on_shared(mark_abandoned, self._shared, self._r.seg_no)
        finally:
            self._finish()

    def _finish(self) -> None:
        self._done = True
        with _REGISTRY_LOCK:
            _BULK_LOADING.discard(self._r.seg_no)
            _rewrite_claim()


def open_bulk_load(shared_con: Any, *, key: str | None = None, size: int | None = None) -> BulkLoad:
    """A :class:`BulkLoad` into a new segment of ``size`` articles (by default the size R826 Q4 gives the next segment).
    ``shared_con`` is a DB-API connection to the SHARED file in autocommit mode. The registry is settled first, as
    :func:`open_writer` settles it, unless this process has a writer open: settling then could close the segment it is
    writing, and that writer's own open already settled what a crash left."""
    require_writes()
    with _REGISTRY_LOCK:
        segs = _on_shared(registry, shared_con) if _WRITER_LOCK.locked() else _settle(shared_con, key)
        # The claim is on disk BEFORE the reservation commits (another process's settle that sees the reservation then
        # sees the claim too), and names the reservation before this call returns.
        _RESERVING[0] = True
        try:
            _write_claim()
            r = _on_shared(reserve_segment, shared_con, size if size is not None else next_segment_size(segs))
            _BULK_LOADING.add(r.seg_no)
        except BaseException:
            _RESERVING[0] = False
            _rewrite_claim()
            raise
        _RESERVING[0] = False
        try:
            _write_claim()
            path, ident, con, encrypted = create_bulk_segment(r, key=key)
        except BaseException:
            _BULK_LOADING.discard(r.seg_no)
            try:
                _on_shared(mark_abandoned, shared_con, r.seg_no)
            finally:
                _rewrite_claim()  # even when the registry step fails: the claim never names a load that ended
            raise
    try:
        con.execute("PRAGMA temp_store = MEMORY")  # R825: never a plaintext temporary file
        con.execute("PRAGMA foreign_keys = ON")  # article_id -> articles, inside the file
        # The title index's sync triggers call the app's own functions, which SQLite refuses inside a trigger while
        # trusted_schema is off. The schema is the one this call just made, on a name it took empty.
        con.execute("PRAGMA trusted_schema = ON")
        return BulkLoad(shared_con, r, path, ident, con, encrypted, key)
    except BaseException:
        from src.database.segment_open import _free_failed, corpus_folder

        with contextlib.suppress(Exception):
            con.close()
        try:
            _free_failed(corpus_folder(), path, ident)
        finally:
            with _REGISTRY_LOCK:
                _BULK_LOADING.discard(r.seg_no)
            try:
                _on_shared(mark_abandoned, shared_con, r.seg_no)
            finally:
                with _REGISTRY_LOCK:
                    _rewrite_claim()
        raise
