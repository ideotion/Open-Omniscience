"""A salvage copy of a damaged SQLite file (damaged-database plan, slice E3, R121).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS MODULE IS. A file in, a file out: it reads every row the damaged file can still give and writes them
into a NEW file of the same kind (same page size, same encryption, same key), and it never writes to the damaged
one. It knows nothing about the app's own tables, except that a table called ``article_fts`` is the search
index and is rebuilt from the copied articles instead of copied. What happens around it (when it runs, the
space it asks for, the swap of the new file for the old one, what the person is told) is ``database/repair.py``.

HOW IT READS. The damaged file is opened through the app's one factory (``verify.open_read_only``: ``mode=ro``,
``query_only``, so nothing on it can write and a leftover write-ahead log is read, not folded). The rows of a
table with a row id are read in id order on ONE cursor, a step at a time, so every row before the first unreadable
page is in hand when the failure comes. A failure is then classified by the DRIVER's code and nothing else:
``SQLITE_CORRUPT`` means the pages from there on are unreadable; ANY other failure (an out-of-memory, a disk
I/O error, a file that does not open) ABORTS the copy, because treating one of those as an unreadable row would
drop good data without saying so.

THE DRIVER READS ONE ROW AHEAD. CPython's ``sqlite3`` (and ``sqlcipher3``, the same code) fetches the current row and then
steps the statement to the next one before it hands the current row over, so when that step lands on an unreadable page
the exception replaces a row that was read fine (measured: the last good row before a damaged leaf, every time, on both
drivers). The row right after the last row that arrived is therefore ALWAYS read again by itself (``_copy_one``, a
point read that touches only that row) before the unreadable span is searched for, so that row is copied when it is
good and counted lost only when its own pages (an overflow chain) are not.

AFTER A FAILED READ THE CONNECTION IS CLOSED AND OPENED AGAIN, always. Measured on SQLCipher: after the first
page that fails its check, every later page read on that connection raises ``MemoryError`` (empty message,
the text of a real out-of-memory), including reads of tables that are fine; only a new connection reads again,
at the price of one key derivation (0.2 to 0.4 s). A plaintext connection is not affected, and gets the same
treatment because there is one code path.

WHERE THE UNREADABLE PART ENDS. After a failure the next readable row is found without reading every id in
between: a probe asks for the first row at or above an id (``SELECT rowid ... WHERE rowid >= ? LIMIT 1``, which
descends the table's b-tree and fails exactly when the page the id belongs to cannot be read), the id is
doubled from the failure until a probe answers, and the boundary is bisected: a damaged leaf costs about
``1.5 * log2(its id span)`` reconnects whatever its width, where reading every id of a leaf of tiny rows would
cost one reconnect per id (a leaf of 500 rows, an hour for a thousand leaves). The range between the failure
and the boundary is recorded as UNREADABLE IDS: an upper bound on the rows lost, because ids in a span that
nothing ever used (deleted rows, gaps) are counted too. HONEST LIMIT: a readable island narrower than the search
step lying between two unreadable spans can be counted lost with them; the count only ever errs upward.

WHAT IS NOT COPIED, and why that costs nothing. ``sqlite_stat*`` (the planner's statistics: the app's start-up
refreshes them), the search index and its shadow tables (rebuilt through the app's own ``fts.rebuild_index`` from
the copied articles, so the index carries the normalisation record the triggers write), and every b-tree of an
INDEX (indexes are CREATEd from the schema after the rows, so a damaged index tree is never read and never
copied). A table ``WITHOUT ROWID`` has no id to probe, so it is copied by its primary-key order up to its first
unreadable page and the report says the rest of it could not be read (the corpus has one, ``spell_deletes``, a
derived table its own job rebuilds).

MEMORY. Every connection of the app sets ``temp_store=MEMORY`` and so does this copy: under SQLCipher a
file-backed sorter would write the index keys to a temporary file in the clear (measured: the titles). So the sort
of ``CREATE INDEX`` holds every key in RAM. A table whose sort would not fit the memory that is free (the memory
guard's reader, ``SORT_RAM_BYTES_PER_ROW`` bytes a row: the article list's own figure, measured on titles and stated, not a promise) gets
its indexes created BEFORE its rows, so the pages are built as the rows arrive and the footprint is the page cache,
at the price of a slower copy. A memory figure that cannot be read is not a reason to take the slow road.

THE PASSPHRASE. Nothing here writes a value, a path or an engine message into a record: the report holds table
names, counts and id ranges, and the one place an engine's text could enter it (a failure's reason) goes through
``secret_scrub.scrub_text``, the same helper every other record uses.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.database import damage
from src.database.article_indexes import RAM_BYTES_PER_ARTICLE

_LOG = logging.getLogger(__name__)

#: Rows travel in batches of at most this many rows or this many bytes, whichever comes first, committed per batch.
#: WHAT IT PROTECTS: one statement's write held in memory (``temp_store=MEMORY``, and a row of an article is kilobytes).
BATCH_ROWS = 2000
BATCH_BYTES = 16 * 1024 * 1024

#: The target's page cache in KiB while it is scratch: enough for the index-first road to be tolerable, small enough
#: to fit the machines whose memory is the problem. A scratch file's journal is in memory and its sync is off.
TARGET_CACHE_KIB = 65536

#: RAM the sort of ONE index holds per row of its table, in bytes: the article list's own figure (``article_indexes.
#: RAM_BYTES_PER_ARTICLE``, measured on the title index: 128 bytes for Latin titles, 272 for Devanagari ones, 300 stated), so the
#: two builds of the same index never disagree about what it costs. A narrow key sorts in less, so this only ever asks for more
#: memory than was needed. WHAT IT DOES: it picks, per table, whether the indexes are built before or after the rows; it never
#: refuses a repair.
SORT_RAM_BYTES_PER_ROW = RAM_BYTES_PER_ARTICLE

#: The id the search runs to when a table's last row id cannot be read: the end of the 64-bit space.
_ID_CEILING = 2**62

#: Report caps, so a file with a thousand damaged pages is a record, not a log: this many unreadable id ranges are listed
#: per table (the count of all of them is kept).
RANGES_LISTED = 50

SEARCH_INDEX_TABLE = "article_fts"


class SalvageRefused(Exception):  # noqa: N818 - a stated decision, not an error
    """Nothing was copied, for a reason that is the file's, said in words. ``code`` is a stable key the caller maps to
    its keyed sentence (``schema-unreadable``, ``cannot-open``)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class SalvageStopped(Exception):  # noqa: N818 - a signal, not an error
    """The caller asked the copy to stop (the app is shutting down). The partial file is the caller's to remove."""


class SalvageFailed(RuntimeError):
    """A failure that is not an unreadable page: nothing may be concluded from it, so the copy ends and no file is
    swapped in. ``where`` names the step (a table, an index, the search index); ``reason`` is scrubbed text."""

    def __init__(self, where: str, reason: str) -> None:
        super().__init__(f"{where}: {reason}")
        self.where = where
        self.reason = reason


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _scrub(text: str) -> str:
    """``text`` with the passphrase the process holds taken out of it in every form this code could write it: as typed, SQL-quoted
    (a quote doubled), as ``repr`` and as JSON writes it, the longest form first. The one place an engine's text enters a record
    of this module. A scrub that cannot run withholds the text: it never lets the raw text through."""
    try:
        from src.database.connect import get_passphrase
        from src.monitoring.secret_scrub import scrub_text

        needle = get_passphrase()
        if not needle:
            return text
        forms = {needle, needle.replace("'", "''"), repr(needle)[1:-1], json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1]}
        for form in sorted((f for f in forms if f), key=len, reverse=True):
            text = scrub_text(text, form)
        return text
    except Exception:  # noqa: BLE001 - a scrub that cannot run must not put the raw text in a record
        return "(text withheld: the passphrase scrub could not run)"


def _failure_text(exc: BaseException) -> str:
    """The reason for a failure, from the DRIVER's exception when there is one (its first line), scrubbed. Never the
    wrapper's text, which can carry a statement and its values."""
    driver = damage.driver_error(exc) or exc
    first = (str(driver).splitlines() or [""])[0].strip() or type(driver).__name__
    return _scrub(f"{type(driver).__name__}: {first}")[:240]


def _row_bytes(row: tuple) -> int:
    n = 16
    for v in row:
        if isinstance(v, (str, bytes, bytearray)):
            n += len(v)
        else:
            n += 8
    return n


def sort_budget_bytes() -> int | None:
    """The memory a table's index sort may take now: what is free minus the memory guard's floor, or ``None`` when
    nothing could be read (an unreadable figure is not a refusal)."""
    from src.database import article_indexes

    available = article_indexes._available_ram_bytes()
    if available is None:
        return None
    return max(0, int(available) - int(article_indexes._floor_bytes()))


class _Reader:
    """The damaged file, read-only, reopened after every failed read (see the module docstring)."""

    def __init__(self, path: Path, on_replaced_text: Callable[[], None]) -> None:
        self.path = path
        self.con: Any = None
        self.reopens = 0
        self._on_replaced_text = on_replaced_text

    def _text(self, raw: bytes) -> str:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            self._on_replaced_text()
            return raw.decode("utf-8", "replace")

    def open(self) -> None:
        from src.database import verify

        self.con = verify.open_read_only(self.path)
        self.con.text_factory = self._text

    def reopen(self) -> None:
        self.close()
        self.open()
        self.reopens += 1

    def close(self) -> None:
        if self.con is not None:
            with contextlib.suppress(Exception):
                self.con.close()
            self.con = None


class _Table:
    """What the schema says about one table: how its rows are reached and which columns are copied."""

    def __init__(self, name: str, sql: str) -> None:
        self.name = name
        self.sql = sql
        self.virtual = sql.lstrip().upper().startswith("CREATE VIRTUAL")
        self.autoincrement = "AUTOINCREMENT" in sql.upper()
        self.without_rowid = False
        self.columns: list[str] = []
        self.alias: str | None = None  # the INTEGER PRIMARY KEY column that IS the row id
        self.rid: str | None = None  # the name the row id is selected by
        self.indexes: list[tuple[str, str]] = []  # (name, sql) of the indexes created from the schema


class Salvage:
    """One salvage copy of ``source`` into ``target``. ``run()`` returns the report; it raises ``SalvageRefused`` (nothing
    could be copied), ``SalvageStopped`` or ``SalvageFailed``. ``cancel`` is checked at every batch and every probe;
    ``progress(event)`` is called with plain dicts (``phase``, ``table``, ``table_index``, ``tables_total``, ``kept``,
    ``unreadable_ids``) and must be cheap and never raise."""

    def __init__(
        self,
        source: Path,
        target: Path,
        *,
        cancel: threading.Event | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
        sort_budget: Callable[[], int | None] = sort_budget_bytes,
    ) -> None:
        self.source = Path(source)
        self.target = Path(target)
        self.cancel = cancel or threading.Event()
        self._progress = progress
        self._sort_budget = sort_budget
        self.replaced_text = 0
        self.src = _Reader(self.source, self._count_replaced)
        self.dst: Any = None
        self.encrypted = False
        self.page_size = 0
        self.auto_vacuum = 0
        self._shadow: set[str] = set()
        self._without_rowid: set[str] = set()
        self._autoincrement: set[str] = set()
        self._started = time.monotonic()
        self.report: dict[str, Any] = {"tables": [], "reconnects": 0}

    # -- plumbing --------------------------------------------------------------------------------
    def _count_replaced(self) -> None:
        self.replaced_text += 1

    def _emit(self, **event: Any) -> None:
        if self._progress is not None:
            with contextlib.suppress(Exception):
                self._progress(event)

    def _check_stop(self) -> None:
        if self.cancel.is_set():
            raise SalvageStopped

    def _is_corrupt(self, exc: BaseException) -> bool:
        return damage.corruption_of(exc) is not None

    def _classify(self, where: str, exc: BaseException) -> SalvageFailed:
        return SalvageFailed(where, _failure_text(exc))

    # -- run -------------------------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        try:
            self._open_source()
            tables, others = self._read_schema()
            self._open_target()
            self._create_tables(tables)
            self._copy_all(tables)
            self._create_rest(tables, others)
            self._finish(tables)
        except (SalvageRefused, SalvageStopped, SalvageFailed):
            raise
        except Exception as exc:  # noqa: BLE001 - nothing past this point may be read as "an unreadable page"
            raise self._classify("the copy", exc) from exc
        finally:
            self.src.close()
            if self.dst is not None:
                with contextlib.suppress(Exception):
                    self.dst.close()
                self.dst = None
        self.report["reconnects"] = self.src.reopens
        self.report["replaced_text_values"] = self.replaced_text
        self.report["seconds"] = round(time.monotonic() - self._started, 1)
        return self.report

    # -- the source ------------------------------------------------------------------------------
    def _open_source(self) -> None:
        from src.database import connect as conn_mod

        try:
            self.src.open()
            con = self.src.con
            self.page_size = int(con.execute("PRAGMA page_size").fetchone()[0])  # SQLCipher answers a string
            self.auto_vacuum = int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, SalvageStopped):
                raise
            if self._is_corrupt(exc):
                # The first statement that reads the schema (a PRAGMA does) failed on a damaged schema page.
                raise SalvageRefused(
                    "schema-unreadable", "the list of tables in the damaged file cannot be read, so nothing can be copied"
                ) from exc
            raise SalvageRefused("cannot-open", f"the damaged file could not be opened for reading ({_failure_text(exc)})") from exc
        self.encrypted = bool(conn_mod.is_encrypted_file(self.source))

    def _read_schema(self) -> tuple[list[_Table], list[tuple[str, str, str, str]]]:
        """``(tables, others)``: the tables to create and copy in creation order, and the indexes, triggers and views
        (``(type, name, tbl_name, sql)``) to create after the rows. A schema that cannot be read refuses the copy:
        without the list of tables nothing can be copied."""
        con = self.src.con
        try:
            master = con.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY rowid"
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            if self._is_corrupt(exc):
                raise SalvageRefused(
                    "schema-unreadable", "the list of tables in the damaged file cannot be read, so nothing can be copied"
                ) from exc
            raise self._classify("the schema", exc) from exc
        self._read_table_kinds(master)
        tables: list[_Table] = []
        others: list[tuple[str, str, str, str]] = []
        for kind, name, tbl, sql in master:
            if kind == "table":
                if name.startswith("sqlite_") or name in self._shadow:
                    continue
                tables.append(_Table(name, sql))
            elif kind in ("index", "trigger", "view"):
                others.append((kind, name, tbl, sql))
        try:
            for t in tables:
                self._describe(t)
        except Exception as exc:  # noqa: BLE001
            if self._is_corrupt(exc):
                raise SalvageRefused(
                    "schema-unreadable", "the list of columns of a table in the damaged file cannot be read, so nothing can be copied"
                ) from exc
            raise self._classify("the schema", exc) from exc
        by_name = {t.name: t for t in tables}
        self._autoincrement = {t.name for t in tables if t.autoincrement}
        for kind, name, tbl, sql in others:
            if kind == "index" and tbl in by_name:
                by_name[tbl].indexes.append((name, sql))
        return tables, others

    def _read_table_kinds(self, master: list[tuple]) -> None:
        """The shadow tables of every virtual table (never copied) and the tables WITHOUT ROWID. SQLite's own
        ``PRAGMA table_list`` says both; where it is not available (older than 3.37) or cannot answer, the five shadow
        names an FTS5 table has are used and ``WITHOUT ROWID`` is read from the table's SQL."""
        con = self.src.con
        virtual = {n for k, n, _t, sql in master if k == "table" and str(sql).lstrip().upper().startswith("CREATE VIRTUAL")}
        try:
            for row in con.execute("PRAGMA table_list").fetchall():
                # (schema, name, type, ncol, wr, strict)
                if row[2] == "shadow":
                    self._shadow.add(row[1])
                if row[4]:
                    self._without_rowid.add(row[1])
            return
        except Exception as exc:  # noqa: BLE001
            if self._is_corrupt(exc):
                with contextlib.suppress(Exception):
                    self.src.reopen()  # a poisoned connection must not be read from again
        for v in virtual:
            for suffix in ("_data", "_idx", "_content", "_docsize", "_config"):
                self._shadow.add(v + suffix)
        for k, n, _t, sql in master:
            if k == "table" and re.search(r"\bWITHOUT\s+ROWID\b", str(sql), re.IGNORECASE):
                self._without_rowid.add(n)

    def _describe(self, t: _Table) -> None:
        """The columns to copy (generated columns are computed, not copied) and how the row id is reached."""
        if t.virtual:
            return
        con = self.src.con
        t.without_rowid = t.name in self._without_rowid
        info = con.execute(f"PRAGMA table_xinfo({_ident(t.name)})").fetchall()
        # (cid, name, type, notnull, dflt_value, pk, hidden): hidden 0 is an ordinary column
        t.columns = [r[1] for r in info if r[6] == 0]
        if t.without_rowid:
            return
        pks = [r for r in info if r[5] > 0]
        if len(pks) == 1 and str(pks[0][2]).upper() == "INTEGER":
            t.alias = pks[0][1]
            t.rid = t.alias
            return
        taken = {c.lower() for c in t.columns}
        t.rid = next((n for n in ("rowid", "_rowid_", "oid") if n not in taken), None)

    # -- the target ------------------------------------------------------------------------------
    def _open_target(self) -> None:
        from src.database.connect import connect

        if not self.encrypted:
            self._create_plain_header()
        con = connect(
            str(self.target),
            check_same_thread=False,
            timeout=30,
            create_encrypted=self.encrypted,
            cipher_page_size=self.page_size if self.encrypted else None,
        )
        try:
            con.execute(f"PRAGMA auto_vacuum = {int(self.auto_vacuum)}")
            con.execute("PRAGMA synchronous = OFF")
            con.execute("PRAGMA journal_mode = MEMORY")
            con.execute("PRAGMA temp_store = MEMORY")
            con.execute("PRAGMA foreign_keys = OFF")
            con.execute(f"PRAGMA cache_size = -{int(TARGET_CACHE_KIB)}")
            con.set_progress_handler(lambda: 1 if self.cancel.is_set() else 0, 100_000)
        except Exception:
            con.close()
            raise
        self.dst = con
        self.report["page_size"] = self.page_size
        self.report["encrypted"] = self.encrypted

    def _create_plain_header(self) -> None:
        """A plaintext target with the damaged file's page size and auto-vacuum mode. The factory's fresh-file branch runs
        its own ``PRAGMA auto_vacuum`` first, which fixes the page size at 4096 before anything here could set it (measured),
        so the header is written by a plain connection and the factory then opens an existing plaintext file."""
        import sqlite3

        raw = sqlite3.connect(str(self.target))
        try:
            raw.execute(f"PRAGMA page_size = {int(self.page_size)}")
            raw.execute(f"PRAGMA auto_vacuum = {int(self.auto_vacuum)}")
            raw.execute("CREATE TABLE _salvage_header (x)")
            raw.execute("DROP TABLE _salvage_header")
            raw.commit()
        except sqlite3.Error as exc:
            raise self._classify("the new file", exc) from exc
        finally:
            raw.close()

    def _create_tables(self, tables: list[_Table]) -> None:
        for t in tables:
            self._exec(f"table {t.name}", t.sql)
        self.dst.commit()

    def _exec(self, where: str, sql: str, params: tuple = ()) -> None:
        try:
            self.dst.execute(sql, params)
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target(where, exc)

    def _raise_for_target(self, where: str, exc: BaseException) -> None:
        self._check_stop()
        if str(exc).lower().startswith("interrupted"):
            raise SalvageStopped from exc
        raise self._classify(where, exc) from exc

    # -- the rows --------------------------------------------------------------------------------
    def _copy_all(self, tables: list[_Table]) -> None:
        budget = self._sort_budget()
        copied = [t for t in tables if not t.virtual]
        for i, t in enumerate(copied):
            self._check_stop()
            entry: dict[str, Any] = {"table": t.name, "kept": 0, "unreadable_ids": 0, "unreadable_ranges": 0}
            self.report["tables"].append(entry)
            self._emit(phase="tables", table=t.name, table_index=i + 1, tables_total=len(copied), kept=0, unreadable_ids=0)
            self._copy_table(t, entry, i, len(copied), budget)
        self.dst.commit()

    def _copy_table(self, t: _Table, entry: dict[str, Any], index: int, total: int, budget: int | None) -> None:
        if t.without_rowid or t.rid is None:
            self._copy_scan(t, entry, index, total)
            return
        lo, hi, bounds_note = self._bounds(t)
        if bounds_note:
            entry["note"] = bounds_note
        if lo is None or hi is None:
            return  # an empty table
        if budget is not None and t.indexes and (hi - lo + 1) * SORT_RAM_BYTES_PER_ROW > budget and hi - lo < _ID_CEILING:
            # The sort would not fit the memory that is free: the pages are built as the rows arrive instead.
            entry["indexes_before_rows"] = True
            self._create_indexes(t)
            self.dst.commit()
        ranges: list[list[int]] = []
        pos = lo
        while True:
            self._check_stop()
            last, failed = self._stream(t, pos, entry, index, total)
            if last is not None:
                pos = last + 1
            if not failed:
                break
            nxt = self._skip_unreadable(t, pos, hi, ranges, entry, index, total)
            if nxt is None:
                break
            pos = nxt
        self._note_ranges(entry, ranges)

    def _bounds(self, t: _Table) -> tuple[int | None, int | None, str | None]:
        """``(lowest id, highest id, note)``. An end that cannot be read is replaced, and the note says so: the lowest by 1
        (the app's ids start there), the highest by ``None`` (the search then runs to the end of the id space)."""
        q = _ident(t.name)
        lo: int | None
        hi: int | None
        note = None
        try:
            lo = self.src.con.execute(f"SELECT min({t.rid}) FROM {q}").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            self.src.reopen()
            lo, note = 1, "its first row id could not be read; ids from 1 were looked for"
        try:
            hi = self.src.con.execute(f"SELECT max({t.rid}) FROM {q}").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            self.src.reopen()
            hi = None
            note = (note + "; " if note else "") + "its last row id could not be read; the search ran to the end of the id space"
        if lo is None and hi is None:
            return None, None, note
        return int(lo if lo is not None else 1), int(hi) if hi is not None else _ID_CEILING, note

    def _select_list(self, t: _Table) -> tuple[str, int]:
        """The SELECT list and the position of the row id in a row. A table with an INTEGER PRIMARY KEY has the id in that
        column; any other table is copied with its row id explicit (``rowid`` first)."""
        cols = ", ".join(_ident(c) for c in t.columns)
        if t.alias is not None:
            return cols, t.columns.index(t.alias)
        return f"{t.rid}, {cols}", 0

    def _insert_sql(self, t: _Table) -> str:
        names = [_ident(c) for c in t.columns]
        if t.alias is None:
            names.insert(0, t.rid or "rowid")  # the row id is not a column here: named bare, as SQLite spells it
        marks = ", ".join("?" for _ in names)
        return f"INSERT INTO {_ident(t.name)}({', '.join(names)}) VALUES ({marks})"

    def _stream(self, t: _Table, pos: int, entry: dict[str, Any], index: int, total: int) -> tuple[int | None, bool]:
        """Copy the rows at or above ``pos``, in id order, one cursor step at a time. Returns ``(the last id copied,
        whether the read failed on an unreadable page)``; any other failure raises."""
        select, key_at = self._select_list(t)
        sql = f"SELECT {select} FROM {_ident(t.name)} WHERE {t.rid} >= ? ORDER BY {t.rid}"
        insert = self._insert_sql(t)
        buf: list[tuple] = []
        size = 0
        last: int | None = None
        failed = False
        try:
            cur = self.src.con.execute(sql, (pos,))
            for row in cur:
                buf.append(row)
                size += _row_bytes(row)
                if len(buf) >= BATCH_ROWS or size >= BATCH_BYTES:
                    last = int(buf[-1][key_at])
                    self._flush(t, insert, buf, entry, index, total)
                    buf, size = [], 0
                    self._check_stop()
        except (SalvageFailed, SalvageStopped):
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            failed = True
            self.src.reopen()
        if buf:
            # Rows read before the failure (or the end) are good rows whichever it was.
            last = int(buf[-1][key_at])
            self._flush(t, insert, buf, entry, index, total)
        return last, failed

    def _flush(self, t: _Table, insert: str, rows: list[tuple], entry: dict[str, Any], index: int, total: int) -> None:
        try:
            self.dst.executemany(insert, rows)
            self.dst.commit()
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target(f"table {t.name}", exc)
        entry["kept"] += len(rows)
        self._emit(
            phase="tables", table=t.name, table_index=index + 1, tables_total=total,
            kept=entry["kept"], unreadable_ids=entry["unreadable_ids"],
        )

    def _probe(self, t: _Table, x: int) -> tuple[bool, int | None]:
        """``(readable, the first id at or above x or None)``: whether the page ``x`` belongs to can be read."""
        self._check_stop()
        sql = f"SELECT {t.rid} FROM {_ident(t.name)} WHERE {t.rid} >= ? ORDER BY {t.rid} LIMIT 1"
        try:
            row = self.src.con.execute(sql, (x,)).fetchone()
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            self.src.reopen()
            return False, None
        return True, (int(row[0]) if row is not None else None)

    def _copy_one(self, t: _Table, rid: int, entry: dict[str, Any], index: int, total: int) -> bool:
        """Copy the one row ``rid`` by a point read. ``False`` when its own pages do not read."""
        select, _key_at = self._select_list(t)
        sql = f"SELECT {select} FROM {_ident(t.name)} WHERE {t.rid} = ?"
        try:
            row = self.src.con.execute(sql, (rid,)).fetchone()
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            self.src.reopen()
            return False
        if row is None:
            return False
        self._flush(t, self._insert_sql(t), [row], entry, index, total)
        return True

    def _skip_unreadable(
        self, t: _Table, pos: int, hi: int, ranges: list[list[int]], entry: dict[str, Any], index: int, total: int
    ) -> int | None:
        """The read failed at ``pos``. Record what cannot be read and return where reading resumes, or ``None`` when
        nothing readable is left."""
        ok, first = self._probe(t, pos)
        if ok:
            if first is None:
                return None  # nothing at or above pos: the failure was the end of the table
            # The page of the next row reads. Either the driver dropped it (it reads one row ahead, so the step onto the next
            # unreadable page replaced a good row: see the module docstring) and the point read below gets it, or its content
            # does not read (an overflow page) and that one row is lost.
            if not self._copy_one(t, first, entry, index, total):
                self._add_range(ranges, pos, first)
            return first + 1
        low, step = pos, 1  # low is an id whose page cannot be read
        while True:
            x = low + step
            if x > hi:
                x = hi + 1
            readable, _first = self._probe(t, x)
            if readable:
                break
            if x > hi or x >= _ID_CEILING:
                self._add_range(ranges, pos, min(hi, _ID_CEILING))
                return None
            low, step = x, step * 2
        high = x
        while high - low > 1:
            mid = (low + high) // 2
            if self._probe(t, mid)[0]:
                high = mid
            else:
                low = mid
        self._add_range(ranges, pos, high - 1)
        return high

    @staticmethod
    def _add_range(ranges: list[list[int]], a: int, b: int) -> None:
        if ranges and ranges[-1][1] + 1 >= a:
            ranges[-1][1] = max(ranges[-1][1], b)
        else:
            ranges.append([a, b])

    @staticmethod
    def _note_ranges(entry: dict[str, Any], ranges: list[list[int]]) -> None:
        if not ranges:
            return
        # A range that runs to the end of the id space is the table's tail, whose last id could not be read (``max(id)``
        # failed): how many ids it holds is NOT known, so it is not counted, and the entry says so instead of reporting
        # the width of the id space as a number of rows.
        bounded = [r for r in ranges if r[1] < _ID_CEILING]
        entry["unreadable_ranges"] = len(ranges)
        entry["unreadable_ids"] = sum(b - a + 1 for a, b in bounded)
        entry["unreadable_listed"] = [list(r) for r in bounded[:RANGES_LISTED]]
        if bounded:
            entry["highest_unreadable_id"] = max(b for _a, b in bounded)
        open_from = [a for a, b in ranges if b >= _ID_CEILING]
        if open_from:
            entry["open_ended"] = True
            entry["unreadable_from"] = open_from[0]
            entry["note"] = (
                (entry["note"] + "; " if entry.get("note") else "")
                + f"every id from {open_from[0]} up could not be read, and how many rows that is is not known"
            )

    def _copy_scan(self, t: _Table, entry: dict[str, Any], index: int, total: int) -> None:
        """A table with no id to probe: copied in its own order up to the first unreadable page."""
        cols = ", ".join(_ident(c) for c in t.columns)
        insert = f"INSERT INTO {_ident(t.name)}({cols}) VALUES ({', '.join('?' for _ in t.columns)})"
        buf: list[tuple] = []
        size = 0
        try:
            cur = self.src.con.execute(f"SELECT {cols} FROM {_ident(t.name)}")
            for row in cur:
                buf.append(row)
                size += _row_bytes(row)
                if len(buf) >= BATCH_ROWS or size >= BATCH_BYTES:
                    self._flush(t, insert, buf, entry, index, total)
                    buf, size = [], 0
                    self._check_stop()
        except (SalvageFailed, SalvageStopped):
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._is_corrupt(exc):
                raise self._classify(f"table {t.name}", exc) from exc
            entry["note"] = (
                f"kept {entry['kept'] + len(buf)} rows; the rest of this table could not be read "
                + ("(a table without row ids is read in order and cannot step past an unreadable page)")
            )
            entry["truncated"] = True
            self.src.reopen()
        if buf:
            self._flush(t, insert, buf, entry, index, total)

    # -- indexes, triggers, views, the search index -----------------------------------------------
    def _create_indexes(self, t: _Table) -> None:
        for name, sql in t.indexes:
            self._check_stop()
            try:
                self.dst.execute(sql)
            except Exception as exc:  # noqa: BLE001
                self._check_stop()
                raise SalvageFailed(f"index {name}", _failure_text(exc)) from exc
        t.indexes = []  # created: the later pass skips them

    def _create_rest(self, tables: list[_Table], others: list[tuple[str, str, str, str]]) -> None:
        t0 = time.monotonic()
        total = sum(len(t.indexes) for t in tables)
        done = 0
        for t in tables:
            for name, sql in list(t.indexes):
                self._check_stop()
                self._emit(phase="indexes", table=t.name, index=done + 1, total=total)
                try:
                    self.dst.execute(sql)
                except Exception as exc:  # noqa: BLE001
                    self._check_stop()
                    raise SalvageFailed(f"index {name}", _failure_text(exc)) from exc
                done += 1
        self.report["indexes_seconds"] = round(time.monotonic() - t0, 1)
        for kind, name, _tbl, sql in others:
            if kind in ("trigger", "view"):
                self._exec(f"{kind} {name}", sql)
        self.dst.commit()

    def _rebuild_search_index(self, tables: list[_Table]) -> None:
        if not any(t.virtual and t.name == SEARCH_INDEX_TABLE for t in tables):
            return
        if not any(t.name == "articles" for t in tables):
            return
        from src.database import fts

        self._emit(phase="search-index")
        t0 = time.monotonic()
        try:
            documents = fts.rebuild_index(self.dst)
            self.dst.commit()
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the search index", exc)
        self.report["search_index"] = {"documents": int(documents), "seconds": round(time.monotonic() - t0, 1)}

    def _finish(self, tables: list[_Table]) -> None:
        self._rebuild_search_index(tables)
        self._restore_counters()
        self._orphans()
        with contextlib.suppress(Exception):
            version = int(self.src.con.execute("PRAGMA user_version").fetchone()[0])
            self.dst.execute(f"PRAGMA user_version = {version}")
            self.report["user_version"] = version
        try:
            self.dst.commit()
            self.dst.execute("PRAGMA journal_mode = WAL")
            self.dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the finished copy", exc)

    def _restore_counters(self) -> None:
        """An AUTOINCREMENT table must never hand out an id that belonged to a row that was lost: the counter is the
        highest of what the damaged file said, the highest id copied and the highest id that could not be read."""
        floors: dict[str, int] = {}
        try:
            for name, seq in self.src.con.execute("SELECT name, seq FROM sqlite_sequence").fetchall():
                floors[str(name)] = int(seq)
        except Exception as exc:  # noqa: BLE001
            if self._is_corrupt(exc):
                self.src.reopen()
        for entry in self.report["tables"]:
            high = entry.get("highest_unreadable_id")
            if high is not None and high < _ID_CEILING and entry["table"] in self._autoincrement:
                floors[entry["table"]] = max(floors.get(entry["table"], 0), int(high))
        for name, floor in floors.items():
            try:
                cur = self.dst.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (floor, name))
                if cur.rowcount == 0 and self.dst.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone():
                    self.dst.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (name, floor))
            except Exception:  # noqa: BLE001 - a table that has no counter has nothing to restore
                _LOG.debug("salvage: could not restore a counter", exc_info=True)

    def _orphans(self) -> None:
        """Children whose parent row was unreadable are KEPT and counted per table: deleting them would turn one lost page
        of a parent into the loss of every row that refers to it."""
        counts: dict[str, int] = {}
        try:
            for row in self.dst.execute("PRAGMA foreign_key_check"):
                counts[str(row[0])] = counts.get(str(row[0]), 0) + 1
                if self.cancel.is_set():
                    raise SalvageStopped
        except SalvageStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the foreign key check", exc)
        if counts:
            self.report["orphans"] = counts


def check_copy(path: Path, *, cancel: threading.Event | None = None) -> tuple[bool, list[dict[str, Any]]]:
    """Read every table of the finished copy through the SAME per-table check the start-up uses (``verify.check_table``), so
    "reads clean" is judged by one piece of code. ``(True, [])`` when every table answers ``ok``; else
    ``(False, the tables that did not)``."""
    from src.database import verify

    info = verify.inspect_file(path)
    if "error" in info:
        verdict, reason = info["error"]
        return False, [{"table": verify.SCHEMA_ENTRY, "verdict": verdict, "detail": [reason]}]
    bad: list[dict[str, Any]] = []
    for name in info["names"]:
        if cancel is not None and cancel.is_set():
            raise SalvageStopped
        result = verify.check_table(path, name, cancel=cancel)
        if result["verdict"] != damage.VERDICT_OK:
            bad.append(result)
    return not bad, bad
