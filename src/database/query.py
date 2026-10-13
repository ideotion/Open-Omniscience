"""Small shared SQLAlchemy query helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

#: Rows one chunk of :func:`keyset_scan` reads before its statement completes. A chunk
#: of two small columns is a few MB of Python objects; the whole table is not.
KEYSET_CHUNK = 20_000


def keyset_scan(query, id_col, *, chunk: int | None = None) -> Iterator[Any]:
    """Yield every row of ``query`` in ``id_col`` order, one bounded chunk at a time.

    ``query`` must select ``id_col`` as its FIRST column and carry no ``order_by`` or
    ``limit`` of its own. Each chunk is its own ``WHERE id > last ORDER BY id LIMIT n``
    query drained by ``.all()``, so:

    * at most one chunk of rows is held in Python at once. A whole-table ``.all()``
      holds every row, about four Python objects each, so a table of a few million
      rows comes to the 13.5 million objects a 3.9 GB machine gained in the 25 seconds
      before it died (crash bundle, 2026-09-26, which does not record which read that
      was);
    * the statement COMPLETES between chunks, so SQLite releases its read mark and a
      checkpoint can pass. A single streamed ``yield_per`` cursor would hold that mark
      for the whole scan, which is how a long read grows the WAL (the S4.2 note in
      ``reconcile_keyword_language``).

    THE TRADE, as ``reconcile_keyword_language`` states it for its own loop: chunks are
    separate reads, so a row written during the scan may be seen or missed. A caller
    that needs one consistent snapshot must not use this.
    """
    size = chunk if chunk and chunk > 0 else KEYSET_CHUNK
    last = None
    while True:
        q = query if last is None else query.filter(id_col > last)
        rows = q.order_by(id_col).limit(size).all()
        if not rows:
            return
        last = rows[-1][0]
        yield from rows
        if len(rows) < size:
            return


#: Rows :func:`grouped_counts` fetches per round trip.
GROUPED_CHUNK = 10_000


def grouped_counts(session, stmt, keep) -> tuple[dict[Any, Any], int]:
    """Run a ``(key, value)`` GROUP BY and keep only the groups ``keep`` accepts.

    Returns ``(kept, groups)``: ``{key: value}`` for the accepted groups, in the order
    the statement returns them, and how many groups it returned in all.

    For a caller that reads a few groups of a big window. ``dict(query.all())`` held a
    row object for every group (about four Python objects each) and then a dict of all
    of them; on a window of a few million keywords that is a burst the size of the one
    a 3.9 GB machine died of (crash bundle, 2026-09-26, which does not record which read
    that was). Here the rows arrive ``GROUPED_CHUNK`` at a time and a rejected group is
    dropped as it passes.

    Unlike :func:`keyset_scan`, this is ONE statement, open until the last group is
    read. That is the same read mark ``.all()`` held while it built its list. A GROUP BY
    over a date window that can be walked by days is read in short statements by
    :func:`windowed_group_counts` instead; this stays for the groups that cannot (and for
    ``emergence.py``, which was left as it was).
    """
    kept: dict[Any, Any] = {}
    groups = 0
    result = session.execute(stmt.execution_options(yield_per=GROUPED_CHUNK))
    try:
        for key, value in result:
            groups += 1
            if keep(key, value):
                kept[key] = value
    finally:
        result.close()
    return kept, groups


def capped(query, n: int | None):
    """Apply an OPTIONAL row cap.

    ``n <= 0`` (or ``None``/falsy) means **UNBOUNDED** -- return the query
    unchanged so every matching row is covered. A guard is required because
    SQLite ``LIMIT 0`` returns NO rows, the exact opposite of "no limit".

    Rationale (maintainer 2026-06-13): a per-run source cap silently *selects*
    which sources to skip, and that selection cannot be justified -- collection
    must reach every source. Ordering still decides what runs first; this only
    removes the exclusion.
    """
    return query.limit(n) if n and n > 0 else query


#: Keyword ids one range of :func:`windowed_group_counts` covers (the width of the dict a range
#: builds before ``keep`` sees it: this many keywords, or more only when :data:`MAX_RANGE_STATEMENTS`
#: widens the range on a very wide key span). What it protects is the flat peak the readers were built
#: for (``tests/test_concentration_bounded_reads.py`` measures it: at 50,000 the range dict was 12 MB
#: against 4 MB for the single statement, at 10,000 the peaks are equal); what it costs is statements,
#: about 110 us each on a 1.3 M-mention table (70 us of it SQLite), so a wide key span is not free:
#: ``trending_windows`` over a 3 M-id span took 7.3 s in 42,618 statements against 2.6 s for the single
#: statements (8.2 to 9.0 s once the pool slot goes back after each range: 1,723 check-outs; the ledger entry "A LONG GROUP BY IS READ AS MANY SHORT STATEMENTS" has the numbers).
KEY_RANGE_IDS = 10_000
#: The most statements one :func:`windowed_group_counts` call may issue; a wider key range is used
#: before more are (so on a very wide key span with a long baseline the range dict can hold more than
#: ``KEY_RANGE_IDS`` keys: the statement count is capped first). Each statement is one day of one key
#: range, so this is the number of short index seeks, not a size of anything held.
MAX_RANGE_STATEMENTS = 20_000
#: A window of more days than this is not read by days at all (it is read as one statement, as
#: before): the day axis exists to make each statement one index seek, and a window this long is not
#: the trending question.
MAX_WINDOW_DAYS = 3_660


def _as_date(value: Any) -> date | None:
    """A ``date`` bound as itself; anything else (a ``datetime``, a string) is not walkable by days.

    A ``datetime`` is refused on purpose, not truncated: SQLAlchemy binds a ``datetime`` compared to a ``Date``
    column as ``YYYY-MM-DD HH:MM:SS.ffffff`` text, so the single statement EXCLUDES the day of a ``datetime``
    lower bound and INCLUDES the day of a ``datetime`` upper bound, and walking whole days from its date reads
    other rows (measured on the real schema: 179 groups against 155). Such a window is read as the single
    statement, which is the answer to match. ``day = d`` matches the date-only text the writers store,
    ``YYYY-MM-DD`` (the old range predicate would also have matched a ``YYYY-MM-DDTHH...`` string; no writer
    stores one)."""
    if isinstance(value, datetime):
        return None
    return value if isinstance(value, date) else None


def release_between_pieces(session) -> bool:
    """Hand ``session``'s pooled connection back between two pieces of one read; ``True`` if it went back.

    An ORM ``Session`` autobegins on its first statement and keeps its connection checked out until the
    caller commits, rolls back or closes. A read made of many short statements therefore still HOLDS a
    pool slot for the whole call (the pool watch's holder age, which the storage guard's pin report lists
    oldest first as the candidate that pinned the log) unless something ends the transaction between pieces.
    MEASURED on a 1.3 M-mention table: ``trending_windows`` held its slot for 52.6 s of 52.6 s before this.

    ``release_idle_connection`` does it for a session that has read and not written, and declines otherwise
    (slower, never wrong). It is NOT done on a ``read_snapshot_session`` / ``read_only_db`` session: that
    engine holds one explicit BEGIN across every statement ON PURPOSE (one consistent snapshot for the
    diagnostics bundle), and ending it would hand the NEXT piece, and every later read of the caller, a newer
    one. Releasing expires the ORM objects the session had loaded (they reload on next use, one SELECT each, and
    a row deleted meanwhile raises on the next read of its entity), so a caller that holds entities across these
    reads sees them expired: it loads them AFTER the pieces, as ``trending`` and the corpus keyword rows do, or
    loads them again (``source_quality`` does).

    THE SESSION'S OWN FLAGS CANNOT SEE EVERY WRITE: DML run through ``session.execute(text(...))`` or on
    ``session.connection()`` sets none of them (``release_idle_connection`` reads ``new/dirty/deleted``, the
    write flags and a savepoint), and rolling back there discards the write without a sound (MEASURED by the
    deep read of this PR: both writes were lost, a Core ``update()`` through ``session.execute`` was not). The
    DRIVER knows: its connection reports ``in_transaction`` after any write and not after a SELECT (pysqlite's
    legacy mode begins none), so a session with a transaction open on the driver is declined as well, which
    also declines a snapshot session whatever the registry says (it holds an explicit BEGIN)."""
    try:
        from src.database.read_snapshot import holds_snapshot
        from src.database.session import release_idle_connection

        if holds_snapshot(session.get_bind()):
            return False
        if session.in_transaction() and session.connection().connection.dbapi_connection.in_transaction:
            return False
        return release_idle_connection(session)
    except Exception:  # noqa: BLE001 - releasing early is never worth an error
        return False


def windowed_group_counts(
    session,
    *,
    key,
    day,
    rowid,
    value,
    lo,
    hi,
    keep: Callable[[Any, Any], bool],
    where: tuple = (),
    range_ids: int | None = None,
) -> tuple[dict[Any, Any], int]:
    """``grouped_counts`` for ``SELECT key, value WHERE day IN [lo, hi) GROUP BY key``, read as many SHORT
    statements instead of one that stays open for the whole window.

    Same answer as :func:`grouped_counts`: ``(kept, groups)``, ``kept`` in ascending ``key`` order (the
    order the single GROUP BY returned them in) and ``groups`` the number of keys with any row in the
    window. WHY IT EXISTS: ``grouped_counts`` is ONE statement, open until the last group is read; on
    a corpus of millions of mentions under SQLCipher that is minutes, and a statement that is running
    is a reader a WAL checkpoint cannot pass (the 10-06 bundles' pin reports name this very call, in
    ``fetchmany``, for 1,496 s). A pin report proves the thread was inside the statement when it was
    taken, not that one statement lasted that long; either way, on an ordinary session the longest a reader
    holds the log is one statement over one day of one key range. NOT on a ``read_only_db`` /
    ``read_snapshot_session`` session: that engine emits one explicit BEGIN and holds it across every statement
    ON PURPOSE (the diagnostics bundle reads one consistent snapshot), and the bundle's own trending probes run
    on it, so there the chunks return the same numbers and pin the log as before.

    HOW. The window is walked day by day and the key space range by range (``range_ids`` keys each).
    Each statement is ``day = d AND key >= a AND key < b`` over the covering index that leads with the
    day and then the key (``ix_mention_date_keyword``), so it is a seek and an index-ordered group, and
    the total work equals the one window scan: each index entry is read once. A range's days are
    summed into one dict (``range_ids`` keys wide, or wider when :data:`MAX_RANGE_STATEMENTS` needs it on a
    very wide key span: 65,991 keys for a 90-day window at 14.65 M ids), ``keep`` is asked about each key of the range
    only AFTER every statement of the range has finished, and the dict is dropped, so ``keep`` never
    runs with a statement open and memory is bounded by the range, not the window. The session's pooled
    connection goes back to the pool after each range (:func:`release_between_pieces`), so no pool slot
    is held for the whole call either.

    CONSISTENCY, stated, and it is NOT one snapshot. ``rowid <= max(rowid) read at the start`` is part of
    every statement, so a row INSERTED above that id while the read runs is not counted
    (``tests/test_windowed_group_counts.py`` writes between statements and compares). What it does NOT
    promise ((a) and (b) are pinned by tests): (a) SQLite re-uses the highest rowids after a delete (no AUTOINCREMENT),
    so an insert made after such a delete can land at or below the bound and CAN be counted (when its key's range
    has not been read yet and its key lies inside the probes' [min, max]); (b) an article
    RE-INDEXED while the read runs (a delete, then inserts that get ids above the bound) can be missing
    from the read altogether: a statement after that commit finds neither its old rows (deleted) nor its
    new ones (above the bound), where one snapshot would have counted the old and two reads a moment apart
    the new; and an article that holds the table's TOP ids gets them back (that is (a)), so its re-inserted
    rows land under the bound and a keyword that moved from a range already read to one not yet read is counted
    under both its old and its new keys; (c) a row deleted is seen or missed according to which statement reached it, and a row MOVED to another
    key (a keyword folded into another rewrites ``keyword_id`` in place, ``keyword_fold.py``) is counted TWICE when
    it moves from a range already read to one not yet read (under both keys: a state that never existed) and is
    missed when it moves the other way (pinned by a test). Each statement is atomic, so no article's rows are
    half old and half new within one key range. The reads this serves (trending's
    thresholded ratios) read their two windows in two statements before this change too, and nothing relies
    on one snapshot. ``rowid`` is assumed to be ONE id space: when the derived view becomes a head plus
    sealed segments (R96) the bound has to be taken per segment, or the ids guaranteed disjoint.

    ``value`` must ADD across days (``SUM(count)`` does; an average does not). ``where`` is any further
    filter (the country). A window it cannot walk by days (not ``date`` bounds, a ``datetime`` included, or
    longer than ``MAX_WINDOW_DAYS``) is read by :func:`grouped_counts` instead, as before. THE HELPER IS
    SHARED, so its contract is stated: ``key`` and ``value`` must be NOT NULL columns (a NULL key is never
    selected by ``key >= start``, where the single GROUP BY returns a NULL group, and a day whose SUM is NULL
    cannot be added); the mentions' ``keyword_id`` and ``count`` are both NOT NULL.
    """
    from sqlalchemy import bindparam, func, select

    first, stop = _as_date(lo), _as_date(hi)
    if first is None or stop is None or (stop - first).days > MAX_WINDOW_DAYS:
        stmt = select(key, value).where(day >= lo, day < hi, *where).group_by(key)
        return grouped_counts(session, stmt, keep)
    days = (stop - first).days
    kept: dict[Any, Any] = {}
    if days <= 0:
        return kept, 0
    top_row = session.execute(select(func.max(rowid))).scalar()
    key_lo = session.execute(select(func.min(key))).scalar()
    key_hi = session.execute(select(func.max(key))).scalar()
    if top_row is None or key_lo is None or key_hi is None:
        return kept, 0
    span = int(key_hi) - int(key_lo) + 1
    width = int(range_ids) if range_ids and range_ids > 0 else KEY_RANGE_IDS
    if -(-span // width) * days > MAX_RANGE_STATEMENTS:
        allowed = max(1, MAX_RANGE_STATEMENTS // days)  # ranges, so that ranges x days stays within the cap
        width = -(-span // allowed)
    window_days = [first + timedelta(days=i) for i in range(days)]
    # ONE statement object for every seek, with the day, the key range and the bound as parameters, and the
    # seeks go through the session's CONNECTION, not ``session.execute``: the briefing's WAL guard wraps every
    # result ``session.execute`` returns and keeps each wrapper (its statement, its parameters and its
    # exhausted cursor result) until the next producer starts. MEASURED with ``tracemalloc`` on the test's
    # fixture (``tests/test_windowed_group_counts.py`` pins only that at most three wrappers are retained): 15 KB
    # per seek with a statement built each time, 7.4 KB with one, which is 41 MB for the 5,550
    # seeks of a 1.5M-id span and 180 MB for the Home poll's three presets. These seeks are read whole by
    # ``.all()``, which the guard passes through untouched, so it had nothing to protect here.
    seek = (
        select(key, value)
        .where(
            day == bindparam("oo_day"),
            key >= bindparam("oo_start"),
            key < bindparam("oo_stop"),
            rowid <= bindparam("oo_top"),
            *where,
        )
        .group_by(key)
    )
    groups = 0
    for start in range(int(key_lo), int(key_hi) + 1, width):
        acc: dict[Any, Any] = {}
        conn = session.connection()  # the same one within a range; a new one after the release below
        for d in window_days:
            rows = conn.execute(
                seek, {"oo_day": d, "oo_start": start, "oo_stop": start + width, "oo_top": top_row}
            ).all()
            for k, v in rows:
                acc[k] = v if k not in acc else acc[k] + v
        release_between_pieces(session)  # after the range's last statement, before ``keep`` or the next range
        for k in sorted(acc):
            groups += 1
            if keep(k, acc[k]):
                kept[k] = acc[k]
    return kept, groups

