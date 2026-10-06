"""What one indexed article costs the keyword tables to write, measured without dbstat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The segmented derived index (D47, R96) has one open choice that a number
decides: whether writing an article's keyword rows is slow because the ten indexes on the
mentions table are bigger than memory (every row lands at a random place in each). The
per-table split that would answer it (``dbstat``, :func:`src.monitoring.storage.
storage_composition`) is not compiled into the SQLCipher build the operator runs, so the
question could not be asked. :func:`storage_composition` already sampled the ARTICLE text
share for such builds and left "everything else" as one undivided remainder; this module
divides that remainder as far as it honestly can, and adds the one rate the redesign is
judged against.

WHAT IT REPORTS, every number carrying the method that produced it:

* ``file`` -- the measured file size (page size x page count) and its free pages;
* ``row_size`` -- the mean bytes of a mention row, sampled at evenly spaced ids through
  the read seam (the ``keyword_mentions_all`` view), per column;
* ``estimated_split`` -- the mentions table and each of its indexes ESTIMATED as
  ``rows x (sampled entry bytes + a cell pointer) / page fill``, as a LOW and a HIGH
  figure (a packed page and the textbook steady-state fill of a B-tree fed random keys),
  set against the file size. It is an estimate and is named one; the rest of the file
  stays undivided, exactly as it did;
* ``write_rate`` -- mentions and distinct articles written in the last hour and the last
  six, read off the ``created_at`` index, so a drain is measured whether or not a job
  happens to be running. A row counts when it was WRITTEN: a re-index leaves an unchanged row
  with its old ``created_at``, so the figure is the work that reached the file, not the
  articles walked (the drain's own ``mentions_kept`` says how many were left alone). A window
  that cannot be measured says why; it is never ``0``;
* ``reindex_job`` -- the live re-index job's own articles/hour, when one is running.

Read-only, no network, bounded by the statement deadline (an abort is reported, never a
hang), counts and bytes only -- no score, no recommendation. ``PRAGMA index_list`` needs
the physical table's name, which the read seam's view does not have (a view owns no
index), so that one raw reference is recorded in ``tests/test_derived_read_seam.py``.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.database.derived_views import KeywordMentionRead
from src.database.maintenance import (
    MemoryShort,
    StatementTimeout,
    deadline_expired,
    statement_deadline,
)
from src.monitoring.engine_text import engine_text

_LOG = logging.getLogger(__name__)

#: The physical table, for PRAGMA index_list / sqlite_stat1 only (a view has neither).
_TABLE = "keyword_mentions"

#: Rows sampled for the row size: evenly spaced ids, one index seek each.
_SAMPLE = 1000
#: SQLite's own steady-state page fill for a B-tree built by random inserts is ln 2.
_RANDOM_FILL = math.log(2)
#: Bytes a cell costs on its page beyond its content: the two-byte cell pointer.
_CELL_POINTER = 2
#: Windows the write rate is read over, in hours.
_WINDOWS_H = (1, 6)

_METHOD = (
    f"Sampled and estimated, never dbstat. Row size: up to {_SAMPLE} rows at evenly spaced ids "
    "between the smallest and largest id (one seek each), each column measured as SQLite "
    "stores it (integers by magnitude, text in UTF-8 bytes, dates as text, the rowid alias "
    "not at all) plus a record header. Index size: rows x (the indexed columns' sampled "
    f"bytes + the row id + an entry header + a {_CELL_POINTER}-byte cell pointer), divided by "
    f"the page fill -- LOW is a packed page (1.0), HIGH the {_RANDOM_FILL:.2f} that random "
    "inserts settle at. Rows: a RANGE -- the id span is the upper bound (deleted rows leave "
    "gaps) and sqlite_stat1, when ANALYZE has run, the lower (the app runs it with a capped "
    "sample and refreshes it only after a large change, so it can be stale and is never "
    "trusted alone). Write rate: rows whose created_at falls in the window, "
    "read off the created_at index. Counts and bytes only, no score."
)

_CAVEAT = (
    "An estimate: SQLite's page reserve, overflow pages, interior pages, free space inside a "
    "page and the sample's spread by id (which follows insertion order) are not modelled, so read each "
    "figure as a range and the split as an order of magnitude, not an audit. What it cannot "
    "divide -- the articles, the full-text index, the other derived tables -- stays in "
    "'rest_of_file_bytes'. A re-index writes only the rows that CHANGED (changed ones are "
    "stamped now, new ones are added, unchanged ones keep their time), so the write rate counts "
    "rows WRITTEN, not articles indexed and not new articles: a re-index of rows that all stayed "
    "the same writes none, and its articles per hour here is a lower bound, not comparable "
    "with a figure measured before that change."
)


def _varint_len(n: int) -> int:
    """Bytes of SQLite's varint for a non-negative integer (1..9)."""
    n = max(0, int(n))
    for size in range(1, 9):
        if n < (1 << (7 * size)):
            return size
    return 9


def _int_bytes(v: int) -> int:
    """Payload bytes SQLite's record format spends on an integer (0 and 1 cost none)."""
    a = abs(int(v))
    if v in (0, 1):
        return 0
    for limit, size in ((1 << 7, 1), (1 << 15, 2), (1 << 23, 3), (1 << 31, 4), (1 << 47, 6)):
        if a < limit:
            return size
    return 8


def _value_bytes(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return _int_bytes(v)
    if isinstance(v, float):
        return 8
    if isinstance(v, datetime):  # before date: a datetime IS a date
        return 26  # 'YYYY-MM-DD HH:MM:SS.ffffff'
    if isinstance(v, date):
        return 10  # 'YYYY-MM-DD'
    if isinstance(v, bytes):
        return len(v)
    return len(str(v).encode("utf-8"))


def _pragma(session: Session, sql: str, **params: Any) -> list:
    try:
        return list(session.execute(text(sql), params))
    except StatementTimeout:
        raise  # a deadline or memory stop is an abort to report, never a quiet fallback
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return []


def _sample_rows(session: Session) -> tuple[list[str], list[tuple], int | None, int | None]:
    """Up to ``_SAMPLE`` rows at evenly spaced ids, through the read seam."""
    t = KeywordMentionRead.__table__
    cols = list(t.columns)
    lo = session.execute(select(func.min(t.c.id))).scalar()
    hi = session.execute(select(func.max(t.c.id))).scalar()
    if lo is None or hi is None:
        return [c.name for c in cols], [], None, None
    lo, hi = int(lo), int(hi)
    k = min(_SAMPLE, hi - lo + 1)
    step = (hi - lo) / (k - 1) if k > 1 else 0
    seen: set[int] = set()
    rows: list[tuple] = []
    for i in range(k):
        # One seek is far below the progress handler's tick, so the deadline can never
        # interrupt this loop from inside a statement; it asks instead.
        if deadline_expired(session):
            raise StatementTimeout(f"the sample was cut short after {len(rows)} rows")
        r = session.execute(
            select(*cols).where(t.c.id >= lo + round(i * step)).order_by(t.c.id).limit(1)
        ).fetchone()
        if r is None or int(r[0]) in seen:
            continue
        seen.add(int(r[0]))
        rows.append(tuple(r))
    return [c.name for c in cols], rows, lo, hi


def _row_count(session: Session, lo: int | None, hi: int | None) -> dict[str, Any]:
    """The row count as a RANGE, and how each end was got.

    The id span is always current but counts the gaps deletions leave (an upper bound).
    ``sqlite_stat1`` is exact only right after a full ANALYZE: the app's own
    ``PRAGMA optimize`` runs with a capped sample and refreshes only after a large change,
    and each index carries its own figure, so alone it can read several times too low.
    Both are reported; the lower end is the largest stat1 figure, never above the span.
    """
    out: dict[str, Any] = {}
    stats = _pragma(session, "SELECT stat FROM sqlite_stat1 WHERE tbl = :t", t=_TABLE)
    counts: list[int] = []
    for r in stats:
        try:
            counts.append(int(str(r[0]).split()[0]))
        except (ValueError, IndexError):
            continue
    span = (hi - lo + 1) if lo is not None and hi is not None else None
    if span is not None:
        out["rows"] = span
        out["rows_kind"] = "id span, an upper bound (deleted rows leave gaps)"
        out["rows_high"] = span
    if counts:
        low = max(counts) if span is None else min(max(counts), span)
        out["rows_low"] = low
        out["rows_stat1"] = {
            "min": min(counts),
            "max": max(counts),
            "note": (
                "approximate: ANALYZE runs with a capped sample and each index carries its "
                "own figure; it is stale after a large change until the next optimize"
            ),
        }
        if span is None:
            out["rows"] = low
            out["rows_kind"] = "sqlite_stat1, approximate (no id span could be read)"
            out["rows_high"] = max(counts)
    if "rows_low" not in out and "rows" in out:
        out["rows_low"] = out["rows"]
    return out


def _mean_by_column(names: list[str], rows: list[tuple]) -> dict[str, float]:
    n = len(rows)
    return {
        name: (sum(_value_bytes(r[i]) for r in rows) / n) if n else 0.0
        for i, name in enumerate(names)
    }


def _entry_bytes(col_bytes: list[float], row_id_bytes: int) -> float:
    """One index entry: a header byte per column plus one for the row id, the columns'
    bytes, the row id, and the payload-length varint."""
    header = 1 + len(col_bytes) + 1
    payload = header + sum(col_bytes) + row_id_bytes
    return payload + 1


def _index_split(
    session: Session, means: dict[str, float], rows_low: int, rows_high: int, row_id_bytes: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in _pragma(session, "SELECT * FROM pragma_index_list(:t)", t=_TABLE):
        name = str(r[1])
        entry: dict[str, Any] = {"name": name}
        if len(r) > 4 and r[4]:
            entry["columns"] = []
            entry["estimated"] = False
            entry["reason"] = "a partial index: only some rows are in it, so it is not sized"
            out.append(entry)
            continue
        cols = _pragma(session, "SELECT * FROM pragma_index_info(:n)", n=name)
        names = [c[2] for c in cols]
        entry["columns"] = [str(n) for n in names if n]
        if not names:
            entry["estimated"] = False
            entry["reason"] = "its columns could not be read, so it is not sized"
            out.append(entry)
            continue
        if any(n is None for n in names):
            entry["estimated"] = False
            entry["reason"] = "an expression index: its key is not a column, so it is not sized"
            out.append(entry)
            continue
        if any(str(n) not in means for n in names):
            entry["estimated"] = False
            entry["reason"] = "a column the read model does not carry, so it is not sized"
            out.append(entry)
            continue
        per = _entry_bytes([means[str(n)] for n in names], row_id_bytes) + _CELL_POINTER
        entry["estimated"] = True
        entry["entry_bytes"] = round(per, 1)
        entry["bytes_low"] = int(rows_low * per)
        entry["bytes_high"] = int(rows_high * per / _RANDOM_FILL)
        out.append(entry)
    out.sort(key=lambda e: -(e.get("bytes_high") or 0))
    return out


def _write_rate(session: Session, now: datetime) -> dict[str, Any]:
    t = KeywordMentionRead.__table__
    out: dict[str, Any] = {}
    for hours in _WINDOWS_H:
        key = f"last_{hours}h"
        since = now - timedelta(hours=hours)
        try:
            with statement_deadline(session):
                mentions, articles = session.execute(
                    select(func.count(), func.count(func.distinct(t.c.article_id))).where(
                        t.c.created_at >= since
                    )
                ).one()
        except StatementTimeout as exc:
            why = "memory guard" if isinstance(exc, MemoryShort) else "statement deadline"
            out[key] = {"available": False, "reason": f"stopped by the {why} ({engine_text(exc)})"}
            continue
        except Exception as exc:  # noqa: BLE001
            out[key] = {"available": False, "reason": f"unreadable: {engine_text(exc, 160)}"}
            continue
        if not mentions:
            out[key] = {
                "available": False,
                "reason": (
                    "no mention row was written in this window, so there is no rate to state "
                    "(a re-index that found every row unchanged writes none)"
                ),
            }
            continue
        out[key] = {
            "mentions": int(mentions),
            "articles": int(articles),
            "articles_per_hour": round(articles / hours, 1),
            "mentions_per_hour": round(mentions / hours, 1),
            "mentions_per_article": round(mentions / articles, 1) if articles else None,
        }
    return out


def _reindex_job() -> dict[str, Any] | None:
    try:
        from src.analytics.reindex_job import get_reindex_manager

        st = get_reindex_manager().status()
    except Exception:  # noqa: BLE001 - optional context, never an error in the member
        return None
    if not st.get("running"):
        return {"running": False}
    return {
        "running": True,
        "state": st.get("state"),
        # The JOB's own run rate; write_rate's figure is the window average, idle time included.
        "articles_per_hour": st.get("articles_per_hour"),
        "keywords_per_hour": st.get("keywords_per_hour"),
        "percent": st.get("percent"),
    }


def _cut_reason(exc: StatementTimeout) -> str:
    why = "memory guard" if isinstance(exc, MemoryShort) else "statement deadline"
    return f"stopped before the sample finished, by the {why} ({engine_text(exc)})"


def keyword_write_cost(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """The report; see the module docstring. Never raises."""
    out: dict[str, Any] = {"method": _METHOD, "caveat": _CAVEAT}
    if session.get_bind().dialect.name != "sqlite":
        out["available"] = False
        out["reason"] = "not a SQLite store"
        return out
    stamp = now or datetime.now(UTC).replace(tzinfo=None)
    names: list[str] = []
    rows: list[tuple] = []
    lo = hi = None
    counted: dict[str, Any] = {}
    cut: str | None = None
    try:
        page_size = _first_int(_pragma(session, "PRAGMA page_size"))
        page_count = _first_int(_pragma(session, "PRAGMA page_count"))
        freelist = _first_int(_pragma(session, "PRAGMA freelist_count"))
        file_bytes = page_size * page_count if page_size and page_count is not None else None
        out["file"] = {
            "page_size": page_size,
            "bytes": file_bytes,
            "free_bytes": page_size * freelist if page_size and freelist is not None else None,
        }
        with statement_deadline(session):
            names, rows, lo, hi = _sample_rows(session)
            counted = _row_count(session, lo, hi)
    except StatementTimeout as exc:
        # The write rate does not depend on the sample, and it is the rate the redesign is
        # judged against: a cut-short sample never takes it down with it.
        cut = _cut_reason(exc)
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, never raises
        _LOG.debug("keyword write cost unavailable: %s", engine_text(exc))
        out["available"] = False
        out["reason"] = f"unreadable: {engine_text(exc, 200)}"
        return out

    out["write_rate"] = _write_rate(session, stamp)
    job = _reindex_job()
    if job is not None:
        out["reindex_job"] = job
    if cut is not None:
        out["available"] = False
        out["reason"] = cut
        return out

    out["available"] = True
    out["rows"] = counted
    if not rows:
        out["row_size"] = {"sampled": 0}
        return out

    means = _mean_by_column(names, rows)
    # The rowid alias is the key, not part of the record.
    record = 1 + len(names) + sum(v for k, v in means.items() if k != "id")
    id_bytes = _varint_len(int(hi or 0))  # a table cell stores the rowid as a varint
    out["row_size"] = {
        "sampled": len(rows),
        "mean_record_bytes": round(record, 1),
        "mean_cell_bytes": round(record + id_bytes + 1 + _CELL_POINTER, 1),
        "columns": {k: round(v, 1) for k, v in means.items() if k != "id"},
    }
    rows_high = int(counted.get("rows_high") or counted.get("rows") or 0)
    rows_low = int(counted.get("rows_low") or rows_high)
    if not rows_high:
        return out
    table_cell = record + id_bytes + 1 + _CELL_POINTER
    table = {
        "name": _TABLE,
        # LOW is a packed page. HIGH allows the holes a partial re-index leaves (it deletes
        # and rewrites an article's rows) and the page header and reserve, by the same fill.
        "bytes_low": int(rows_low * table_cell),
        "bytes_high": int(rows_high * table_cell / _RANDOM_FILL),
    }
    # An index entry stores the rowid as a record integer, not a varint.
    indexes = _index_split(session, means, rows_low, rows_high, _int_bytes(int(hi or 0)))
    low = table["bytes_low"] + sum(i.get("bytes_low", 0) for i in indexes)
    high = table["bytes_high"] + sum(i.get("bytes_high", 0) for i in indexes)
    split: dict[str, Any] = {
        "table": table,
        "indexes": indexes,
        "index_count": len(indexes),
        "mentions_total_bytes_low": low,
        "mentions_total_bytes_high": high,
    }
    if file_bytes:
        split["share_of_file_low"] = round(low / file_bytes, 3)
        split["share_of_file_high"] = round(high / file_bytes, 3)
        split["rest_of_file_bytes_low"] = max(0, file_bytes - high)
        split["rest_of_file_bytes_high"] = max(0, file_bytes - low)
        if high > file_bytes:
            split["exceeds_file"] = (
                "the high estimate is larger than the file: the sample over-represents wide "
                "rows or the row count is an upper bound. Read the split as an upper bound."
            )
    out["estimated_split"] = split
    return out


def _first_int(rows: list) -> int | None:
    try:
        return int(rows[0][0])
    except (IndexError, TypeError, ValueError):
        return None
