"""Small shared SQLAlchemy query helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Iterator
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
    read. That is the same read mark ``.all()`` held while it built its list; a GROUP
    BY cannot be split into keyset chunks without re-reading the window once per chunk.
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
