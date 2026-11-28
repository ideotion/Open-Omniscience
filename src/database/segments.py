"""The split corpus's registry and article-id ranges (R826, row 409, stage 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS STAGE IS. The bookkeeping the split corpus stands on, and nothing that uses it yet: the registry of segment
files (``corpus_segments``) and the counter their article-id ranges come from (``corpus_id_counter``), both in the
SHARED file (today's ``open_omniscience.db``). Nothing in the app calls :func:`reserve_segment` or
:func:`commit_segment` in this stage, and :func:`registry` answers an empty table without writing anything, so an
existing corpus keeps working untouched as legacy segment 0 (R826 g).

THE CRASH RULE (R826 Q3, condition f). No transaction spans two files. A segment comes to exist in three steps, each
durable on its own:

1. :func:`reserve_segment` -- ONE shared-file transaction: the range is taken from the counter, the counter moves past
   it, and the registry row is written as ``reserved``. Committed BEFORE anything touches a segment file.
2. :func:`commit_segment` -- the segment file's OWN transaction writes its self-identity (``segment_meta``: number and
   range), so the file can be told apart from any other file with that name.
3. :func:`mark_open` -- one shared-file transaction moves the row from ``reserved`` to ``open``.

A crash after (1) leaves a ``reserved`` row: :func:`reconcile` marks it ``abandoned`` unless its file proves step 2
with the exact number and range, in which case the work is durable and the row is opened. Either way the counter is
already past the range, so an id is never given out twice: **a crash may waste ids, never reuse them.** A file is never
deleted here: what happens to a file left by an abandoned reservation is the erase and folder rules' business (R823,
R806), a later stage with its own security reads.

The registry is never erase evidence by itself (R826 e): it says which files the app MEANT to have, never what a file
on disk is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

#: The exact name a segment file has, and the only name the corpus folder may hold (R826 e; R806 for anything else).
SEGMENT_NAME_RE = re.compile(r"\Aseg-([1-9][0-9]{0,3})\.db\Z")

#: R826 Q2: a segment closes at about this many articles (a starting value; Q4's measurement may change it).
DEFAULT_SEGMENT_SIZE = 500_000

#: R826 Q4: at most this many segment files; the size of a new segment doubles every :data:`SEGMENTS_PER_DOUBLING` files,
#: so 64 files hold 16 x 500k x (1 + 2 + 4 + 8) = 120M articles before the cap refuses another (starting values).
MAX_SEGMENT_FILES = 64
SEGMENTS_PER_DOUBLING = 16

STATES = frozenset({"reserved", "open", "closed", "abandoned"})


class SegmentError(RuntimeError):
    """A registry or segment operation refused, with a fixed sentence (never driver text, never a path's contents)."""


@dataclass(frozen=True)
class Segment:
    seg_no: int
    file_name: str | None  # None: the shared file itself (legacy segment 0)
    state: str
    id_lo: int
    id_hi: int | None  # None: open-ended, which only segment 0 may be
    implicit: bool = False  # True: answered for an empty registry, not read from a row
    generation: int | None = None  # the registry's generation (stage 3a); None: none recorded, never compared


#: What an empty registry means: the whole corpus is the shared file, open-ended (R826 g).
LEGACY_SEGMENT_0 = Segment(
    seg_no=0, file_name=None, state="open", id_lo=1, id_hi=None, implicit=True
)


def segment_file_name(seg_no: int) -> str:
    if not isinstance(seg_no, int) or isinstance(seg_no, bool) or not 1 <= seg_no <= 9999:
        raise SegmentError("a segment number is a whole number from 1 to 9999")
    return f"seg-{seg_no}.db"


def _has_tables(con: Any) -> bool:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('corpus_segments', 'corpus_id_counter')"
    ).fetchall()
    return len(rows) == 2


def _has_generation(con: Any) -> bool:
    return any(r[1] == "generation" for r in con.execute("PRAGMA table_info(corpus_segments)").fetchall())


def registry(con: Any) -> list[Segment]:
    """Every segment, in number order. Writes nothing: an absent or empty registry is legacy segment 0 alone."""
    if not _has_tables(con):
        return [LEGACY_SEGMENT_0]
    sql = (
        "SELECT seg_no, file_name, state, id_lo, id_hi, generation FROM corpus_segments ORDER BY seg_no"
        if _has_generation(con)
        else "SELECT seg_no, file_name, state, id_lo, id_hi, NULL FROM corpus_segments ORDER BY seg_no"
    )
    rows = con.execute(sql).fetchall()
    if not rows:
        return [LEGACY_SEGMENT_0]
    return [
        Segment(
            int(r[0]), r[1], str(r[2]), int(r[3]), None if r[4] is None else int(r[4]),
            generation=None if r[5] is None else int(r[5]),
        )
        for r in rows
    ]


def next_segment_size(segments: list[Segment]) -> int:
    """The size of the next segment file (R826 Q4): it doubles every :data:`SEGMENTS_PER_DOUBLING` files. Refused at
    :data:`MAX_SEGMENT_FILES` files (abandoned reservations made no file and are not counted)."""
    files = sum(1 for s in segments if not s.implicit and s.seg_no >= 1 and s.state != "abandoned")
    if files >= MAX_SEGMENT_FILES:
        raise SegmentError("the corpus has reached its limit of segment files")
    return DEFAULT_SEGMENT_SIZE * 2 ** (files // SEGMENTS_PER_DOUBLING)


def _now() -> str:
    # Naive UTC text, the form SQLAlchemy writes a DateTime in on SQLite (the model default is aware UTC).
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")


def _begin(con: Any) -> None:
    if getattr(con, "in_transaction", False):
        raise SegmentError(
            "the registry is changed in a transaction of its own, never inside another one"
        )
    con.execute("BEGIN IMMEDIATE")


def _rollback(con: Any) -> None:
    # SQLite may already have rolled back by itself (SQLITE_FULL, an I/O error): a second ROLLBACK would raise
    # "no transaction is active" and hide the error that matters.
    if getattr(con, "in_transaction", False):
        con.execute("ROLLBACK")


def _commit(con: Any) -> None:
    # A COMMIT that fails (busy, I/O) must not leave the connection inside the transaction: every later step on it
    # would then be refused as "inside another one".
    try:
        con.execute("COMMIT")
    except BaseException:
        _rollback(con)
        raise


@dataclass(frozen=True)
class Reservation:
    seg_no: int
    file_name: str
    id_lo: int
    id_hi: int


def reserve_segment(con: Any, size: int = DEFAULT_SEGMENT_SIZE) -> Reservation:
    """Step 1: reserve the next segment's number and id range in ONE committed shared-file transaction.

    The range starts above everything ever given out: the counter, every registry row's range, and the shared file's
    own highest article id (legacy segment 0 hands out ids by itself until it closes). Segment 0 is written as a row
    the first time, closed at the highest id it holds, because from then on new articles belong to the new segment.
    ``con`` is a DB-API connection to the SHARED file in autocommit mode (``isolation_level=None``)."""
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise SegmentError("a segment's size is a whole number of articles, at least 1")
    if not _has_tables(con):
        raise SegmentError("this corpus has no segment registry yet; the schema upgrade adds it")
    _begin(con)
    try:
        max_article = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM articles").fetchone()[0])
        counter = con.execute("SELECT next_id FROM corpus_id_counter WHERE id = 1").fetchone()
        top_range = con.execute(
            "SELECT MAX(COALESCE(id_hi, id_lo)) FROM corpus_segments"
        ).fetchone()[0]
        seg_max = con.execute("SELECT COALESCE(MAX(seg_no), 0) FROM corpus_segments").fetchone()[0]
        lo = max(max_article + 1, int(counter[0]) if counter else 1, int(top_range or 0) + 1)
        hi = lo + size - 1
        if not con.execute("SELECT 1 FROM corpus_segments WHERE seg_no = 0").fetchone():
            # Legacy segment 0 closes at what it holds; it never gets a new id again. An empty corpus closes it as the
            # EMPTY range [1, 0] (id_hi < id_lo), which overlaps nothing.
            con.execute(
                "INSERT INTO corpus_segments (seg_no, file_name, state, id_lo, id_hi, created_at, state_at)"
                " VALUES (0, NULL, 'closed', 1, ?, ?, ?)",
                (max(max_article, 0), _now(), _now()),
            )
        seg_no = int(seg_max) + 1
        name = segment_file_name(seg_no)
        con.execute(
            "INSERT INTO corpus_segments (seg_no, file_name, state, id_lo, id_hi, created_at, state_at)"
            " VALUES (?, ?, 'reserved', ?, ?, ?, ?)",
            (seg_no, name, lo, hi, _now(), _now()),
        )
        con.execute(
            "INSERT INTO corpus_id_counter (id, next_id) VALUES (1, ?)"
            " ON CONFLICT(id) DO UPDATE SET next_id = MAX(next_id, excluded.next_id)",
            (hi + 1,),
        )
    except BaseException:
        _rollback(con)
        raise
    _commit(con)
    return Reservation(seg_no, name, lo, hi)


_SEGMENT_META_DDL = (
    "CREATE TABLE IF NOT EXISTS segment_meta ("
    " seg_no INTEGER NOT NULL, id_lo INTEGER NOT NULL, id_hi INTEGER NOT NULL, created_at TEXT NOT NULL,"
    " generation INTEGER NOT NULL, next_id INTEGER NOT NULL)"
)


def commit_segment(seg_con: Any, r: Reservation, *, next_id: int | None = None) -> None:
    """Step 2: the segment file's own transaction records its number and range. ``seg_con`` is a DB-API connection to
    the (new, empty) segment file in autocommit mode, opened by the caller with the app's factory and the corpus key.
    ``next_id`` is for a bulk-loaded segment (``segment_write.BulkLoad``), whose rows are in the file before its identity
    is: the first id not yet used, inside ``[id_lo, id_hi + 1]``. Left out, it is ``id_lo`` (an empty segment)."""
    if next_id is None:
        next_id = r.id_lo
    if not isinstance(next_id, int) or isinstance(next_id, bool) or not r.id_lo <= next_id <= r.id_hi + 1:
        raise SegmentError("a segment's next id lies inside its own range")
    if getattr(seg_con, "in_transaction", False):
        raise SegmentError("the segment's identity is written in a transaction of its own")
    seg_con.execute("BEGIN IMMEDIATE")
    try:
        seg_con.execute(_SEGMENT_META_DDL)
        if seg_con.execute("SELECT COUNT(*) FROM segment_meta").fetchone()[0]:
            raise SegmentError(
                "this file already records a segment identity; it is not a new segment"
            )
        seg_con.execute(
            "INSERT INTO segment_meta (seg_no, id_lo, id_hi, created_at, generation, next_id) VALUES (?, ?, ?, ?, 1, ?)",
            (r.seg_no, r.id_lo, r.id_hi, _now(), next_id),
        )
    except BaseException:
        _rollback(seg_con)
        raise
    _commit(seg_con)


def segment_identity(seg_con: Any) -> tuple[int, int, int] | None:
    """The (number, id_lo, id_hi) a segment file records, or None when it records none (or not exactly one)."""
    try:
        rows = seg_con.execute("SELECT seg_no, id_lo, id_hi FROM segment_meta").fetchall()
    except Exception:  # noqa: BLE001 - no table, not a database, unreadable: no identity, which is the safe answer
        return None
    if len(rows) != 1:
        return None
    return (int(rows[0][0]), int(rows[0][1]), int(rows[0][2]))


def _set_state(con: Any, seg_no: int, frm: str, to: str) -> bool:
    if to not in STATES:
        raise SegmentError("not a segment state")
    _begin(con)
    try:
        cur = con.execute(
            "UPDATE corpus_segments SET state = ?, state_at = ? WHERE seg_no = ? AND state = ?",
            (to, _now(), seg_no, frm),
        )
        changed = cur.rowcount == 1
    except BaseException:
        _rollback(con)
        raise
    _commit(con)
    return changed


def segment_counters(seg_con: Any) -> tuple[int, int] | None:
    """(generation, next_id) the segment file records, or None when it records none (or not exactly one row)."""
    try:
        rows = seg_con.execute("SELECT generation, next_id FROM segment_meta").fetchall()
    except Exception:  # noqa: BLE001 - no table or no column: nothing recorded, which is the safe answer
        return None
    if len(rows) != 1 or rows[0][0] is None or rows[0][1] is None:
        return None
    return (int(rows[0][0]), int(rows[0][1]))


def mark_closed(con: Any, seg_no: int) -> bool:
    """An open segment closes (it is full, or another took its place): one shared-file transaction. False: it was not open."""
    return _set_state(con, seg_no, "open", "closed")


def record_generation(con: Any, seg_no: int, generation: int) -> None:
    """The registry's half of a generation raise, written AFTER the file's. Only ever raises the number (a crash between
    the two writes left the file newer; this catches the registry up), in one shared-file transaction."""
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise SegmentError("a generation is a whole number, at least 1")
    _begin(con)
    try:
        con.execute(
            "UPDATE corpus_segments SET generation = ? WHERE seg_no = ? AND (generation IS NULL OR generation < ?)",
            (generation, seg_no, generation),
        )
    except BaseException:
        _rollback(con)
        raise
    _commit(con)


def mark_sealed(con: Any, r: Reservation) -> None:
    """A bulk-loaded segment's last step (``segment_write.BulkLoad.seal``): its row moves from ``reserved`` straight to
    ``closed``, in one shared-file transaction, so the segment the app writes to stays the one already open."""
    if not _set_state(con, r.seg_no, "reserved", "closed"):
        raise SegmentError("that segment is not reserved; it was opened or abandoned already")


def mark_abandoned(con: Any, seg_no: int) -> bool:
    """A reservation given up by its own process (a bulk load that failed). False: it was not reserved."""
    return _set_state(con, seg_no, "reserved", "abandoned")


def mark_open(con: Any, r: Reservation) -> None:
    """Step 3: the reservation's row moves from ``reserved`` to ``open`` in the shared file."""
    if not _set_state(con, r.seg_no, "reserved", "open"):
        raise SegmentError("that segment is not reserved; it was opened or abandoned already")


def reconcile(con: Any, identity_of: Any, *, skip: frozenset[int] = frozenset()) -> dict[str, list[int]]:
    """Settle every ``reserved`` row a crash left: ``identity_of(file_name)`` returns the identity the file records
    (see :func:`segment_identity`) or None when the file is absent or proves nothing. An exact match means step 2
    committed, so the row opens; anything else abandons it. Its range stays used either way. Returns what it did.
    ``skip`` names reservations a live bulk load of this process still holds: they are not a crash's leftovers."""
    done: dict[str, list[int]] = {"opened": [], "abandoned": []}
    for s in registry(con):
        if s.implicit or s.state != "reserved" or s.seg_no in skip:
            continue
        seen = identity_of(s.file_name)
        if seen is not None and seen == (s.seg_no, s.id_lo, s.id_hi):
            if _set_state(con, s.seg_no, "reserved", "open"):
                done["opened"].append(s.seg_no)
        elif _set_state(con, s.seg_no, "reserved", "abandoned"):
            done["abandoned"].append(s.seg_no)
    return done


def ranges_overlap(segments: list[Segment]) -> list[tuple[int, int]]:
    """Every pair of segments whose id ranges overlap (an open-ended range runs to infinity). Empty is the invariant."""
    out = []
    for i, a in enumerate(segments):
        for b in segments[i + 1 :]:
            a_hi = a.id_hi if a.id_hi is not None else float("inf")
            b_hi = b.id_hi if b.id_hi is not None else float("inf")
            if a.id_lo <= b_hi and b.id_lo <= a_hi:
                out.append((a.seg_no, b.seg_no))
    return out
