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
names, counts and id ranges, and a failure's reason is the driver's CLASS and a fixed label (:func:`damage.failure_text`), never
a part of the driver's own text.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.database import damage, stand_in
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

#: What :meth:`Salvage._stand_in_value` answers when the key's parent could not be made (no value of the column's own is ever this object).
_REFUSED = object()

#: What the report says about the stand-in rows (``stand_ins``): what they are and why they exist.
STAND_IN_NOTE = (
    "A row whose parent row could not be read was kept, and a stand-in row, marked as lost, holds the place of the lost parents "
    "in each parent table, so that a row saved later is not handed the number of a lost one and does not seem to own the rows that "
    "belong to it. A stand-in that has a parent of its own (a stand-in article has a source) belongs to a stand-in parent that is "
    "marked as lost too, never to a real row. A stand-in article is quarantined, with the reason \"stand-in for a lost row\": it is not in "
    "the search, the article list, the export, the analyses, the reader, the AI routes that take an article's number, the date tags or a signed "
    "evidence bundle, and not in the advanced search that includes quarantined articles; a stand-in source is not enabled and is not in the source lists, the groups, the qualification passes "
    "or the exports, and no source route finds it by its number, so it is never collected or qualified. The rows that were kept for a lost "
    "parent stay in the library, are counted in this report, and show the lost parent's name. A stand-in is a row like any other: if it is "
    "deleted with a database tool, its number may be handed out again. The plain counts of the articles and sources tables (the totals in the summaries, the "
    "disabled-source count, the snapshots) still include it, and so does a raw export of either table."
)

#: The columns of a table the search index reads (``fts.rebuild_index``: ``SELECT id, title, content FROM articles``). A stand-in row of such a
#: table is given NOTHING to index in them (an empty text, no title), so the search finds no stand-in: the index is rebuilt from the table, and
#: the other way to keep a row out of it (an FTS5 'delete' of a document that was never indexed, or indexed under other text) corrupts the index.
_SEARCH_INDEXED: dict[str, tuple[str, ...]] = {"articles": ("title", "content")}

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
    swapped in. ``where`` names the step (a table, an index, the search index); ``reason`` is a class and a fixed label, never a driver's text."""

    def __init__(self, where: str, reason: str) -> None:
        super().__init__(f"{where}: {reason}")
        self.where = where
        self.reason = reason


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


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
        self._row_id_alias: dict[str, str] = {}  # table -> the INTEGER PRIMARY KEY column that IS its row id (the next id is the highest + 1)
        self._stand_in_ids: dict[str, int] = {}  # table -> the id of the stand-in row this copy wrote into it (a parent's own parent is one)
        self._made: list[tuple[str, int]] = []  # every stand-in row written, in order, so a refused one takes the parents it made with it
        self._orphan_needs: dict[str, int] = {}  # parent table -> the highest id an orphan refers to above the table's own highest id
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
        return SalvageFailed(where, damage.failure_text(exc))

    # -- run -------------------------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        try:
            self._open_source()
            tables, others = self._read_schema()
            self._open_target()
            self._create_tables(tables)
            self._copy_all(tables)
            self._orphans()  # before the triggers and the search index exist: a stand-in row is a row, written plainly
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
            raise SalvageRefused("cannot-open", f"the damaged file could not be opened for reading ({damage.failure_text(exc)})") from exc
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
        self._row_id_alias = {t.name: t.alias for t in tables if t.alias and not t.without_rowid}
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
                raise SalvageFailed(f"index {name}", damage.failure_text(exc)) from exc
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
                    raise SalvageFailed(f"index {name}", damage.failure_text(exc)) from exc
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
            except Exception as exc:  # noqa: BLE001 - a table that has no counter has nothing to restore
                _LOG.debug("salvage: could not restore a counter (%s)", type(exc).__name__)

    def _orphan_groups(self) -> dict[tuple[str, str, int], int]:
        """The rows whose parent is not there, counted per ``(child table, parent table, foreign key number)``."""
        groups: dict[tuple[str, str, int], int] = {}
        try:
            for row in self.dst.execute("PRAGMA foreign_key_check"):
                key = (str(row[0]), str(row[2]), int(row[3]))
                groups[key] = groups.get(key, 0) + 1
                if self.cancel.is_set():
                    raise SalvageStopped
        except SalvageStopped:
            raise
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the foreign key check", exc)
        return groups

    def _single_key(self, child: str, number: int) -> tuple | None:
        """The one-column foreign key ``number`` of ``child`` as ``PRAGMA foreign_key_list`` gives it
        (``id, seq, table, from, to, on_update, on_delete, match``), or ``None`` for a key over several columns."""
        try:
            keys = [r for r in self.dst.execute(f"PRAGMA foreign_key_list({_ident(child)})") if int(r[0]) == number]
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the foreign keys of a table", exc)
        return keys[0] if len(keys) == 1 else None

    def _null_the_set_null_keys(self, groups: dict[tuple[str, str, int], int]) -> dict[str, int]:
        """A key declared ``ON DELETE SET NULL`` (``places.article_id``) is what the app would have written had the parent been
        deleted: NULL. The copy writes that instead of keeping a value that points at nothing (and instead of removing the row, which
        the app never does for such a key). A column that does not take NULL, or a key that is not one column, is left as it was: the
        row is kept and counted."""
        nulled: dict[str, int] = {}
        for (child, parent, number), _n in groups.items():
            key = self._single_key(child, number)
            if key is None or str(key[6]).upper() != "SET NULL":
                continue
            target_column = key[4] or self._row_id_alias.get(parent)
            if not target_column:
                continue
            try:
                cur = self.dst.execute(
                    f"UPDATE {_ident(child)} SET {_ident(str(key[3]))} = NULL WHERE {_ident(str(key[3]))} IS NOT NULL AND "
                    f"{_ident(str(key[3]))} NOT IN (SELECT {_ident(str(target_column))} FROM {_ident(parent)})"
                )
            except Exception as exc:  # noqa: BLE001
                self._check_stop()
                if "constraint" in str(exc).lower() or type(exc).__name__ == "IntegrityError":
                    continue  # the column does not take NULL: kept, counted
                self._raise_for_target("the keys that set NULL", exc)
            if cur.rowcount and cur.rowcount > 0:
                nulled[child] = nulled.get(child, 0) + int(cur.rowcount)
            self._check_stop()
        return nulled

    def _highest_referenced(self, groups: dict[tuple[str, str, int], int]) -> dict[str, int]:
        """For each parent table whose row id is the key of the orphans: the highest id an orphan refers to ABOVE the parent's own
        highest id. Ids below it are gaps, which a table that hands out ``max(id) + 1`` never gives again; ids above are the ones a
        new row would be given (the deep read of E3, S6), and are the only ones that need protecting."""
        needs: dict[str, int] = {}
        for (child, parent, number), _n in groups.items():
            alias = self._row_id_alias.get(parent)
            key = self._single_key(child, number)
            if alias is None or key is None or key[4] not in (None, alias):
                continue  # a key over several columns, or over a column that is not the parent's row id: kept and counted only
            try:
                top = self.dst.execute(f"SELECT max({_ident(alias)}) FROM {_ident(parent)}").fetchone()[0] or 0
                high = self.dst.execute(
                    f"SELECT max({_ident(str(key[3]))}) FROM {_ident(child)} WHERE {_ident(str(key[3]))} > ?", (int(top),)
                ).fetchone()[0]
            except Exception as exc:  # noqa: BLE001
                self._raise_for_target("the highest id the orphans refer to", exc)
            if high is not None:
                needs[parent] = max(needs.get(parent, 0), int(high))
            self._check_stop()
        return needs

    def _raise_sequence(self, table: str, floor: int) -> None:
        """An AUTOINCREMENT table never hands out an id up to ``floor`` again: its counter is raised to it."""
        try:
            cur = self.dst.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (int(floor), table))
            if cur.rowcount == 0:
                self.dst.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, int(floor)))
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the counter of a table", exc)

    def _id_above(self, table: str) -> int | None:
        """The first id of ``table`` no row has, no orphan refers to and (for an AUTOINCREMENT table) the counter has not passed: the id of a
        stand-in that is NOT a place a lost row held. ``None`` when the table's highest id cannot be read as a number."""
        alias = self._row_id_alias[table]
        try:
            top = self.dst.execute(f"SELECT max({_ident(alias)}) FROM {_ident(table)}").fetchone()[0] or 0
            seq = 0
            if table in self._autoincrement:
                row = self.dst.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
                seq = int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the highest id of a table that needs a stand-in row", exc)
        try:
            return max(int(top), seq, self._orphan_needs.get(table, 0)) + 1
        except (TypeError, ValueError):
            return None

    def _lost_parent(self, ref: str, chain: tuple[str, ...]) -> int | None:
        """The id of a stand-in row of ``ref`` for a key of another stand-in row: the one this copy already wrote, else a new one at the first
        id above everything (:meth:`_id_above`), itself marked as lost. ``None`` when ``ref`` has no row id to put one at, the keys lead back
        to a table already being made, or the table's own constraints refuse the row: the stand-in that needed it is refused too, because a
        stand-in under a REAL parent would be a lost row that seems to belong to somebody."""
        if ref in self._stand_in_ids:
            return self._stand_in_ids[ref]
        if ref in chain or ref not in self._row_id_alias:
            return None
        new_id = self._id_above(ref)
        if new_id is None or not self._stand_in(ref, new_id, chain):
            return None
        return new_id

    def _stand_in_value(self, table: str, row_id: int, name: str, declared: str, key: tuple | None, chain: tuple[str, ...]) -> Any:
        """A value for a NOT NULL column of a stand-in row: a text column says the row is lost, a column that is a key to another table
        points at a stand-in row of THAT table, marked as lost too (:meth:`_lost_parent`), a column the search index reads is empty, and the
        rest take the neutral value of their type. ``_REFUSED`` when a key's parent could not be made."""
        if key is not None:
            ref = str(key[2])
            if (key[4] or self._row_id_alias.get(ref)) != self._row_id_alias.get(ref):
                return _REFUSED  # a key to a column that is not the parent's row id: no stand-in id can be put there
            found = self._lost_parent(ref, (*chain, table))
            return _REFUSED if found is None else found
        if name in _SEARCH_INDEXED.get(table, ()):
            return ""
        kind = declared.upper()
        if "BLOB" in kind:
            return b""
        if "INT" in kind or "BOOL" in kind or any(x in kind for x in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
            return 0
        if "DATE" in kind or "TIME" in kind:
            return "1970-01-01 00:00:00.000000"
        if "JSON" in kind:
            return "{}"
        return stand_in.lost_text(table, row_id)

    def _stand_in(self, table: str, row_id: int, chain: tuple[str, ...] = ()) -> bool:
        """Write ONE row at ``row_id`` into ``table``, marked as lost: every NOT NULL column without a default is given a value
        (:meth:`_stand_in_value`; a key's parent is a stand-in row too), every other column stays NULL. ``False`` when the table's own
        constraints refused it, or a parent it needs could not be made."""
        alias = self._row_id_alias[table]
        try:
            info = self.dst.execute(f"PRAGMA table_xinfo({_ident(table)})").fetchall()
            keys = {str(r[3]): r for r in self.dst.execute(f"PRAGMA foreign_key_list({_ident(table)})").fetchall()}
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the columns of a table that needs a stand-in row", exc)
        columns, values = [alias], [int(row_id)]
        for _cid, name, declared, notnull, default, _pk, hidden in info:
            if hidden != 0 or name == alias or not notnull or default is not None:
                continue
            value = self._stand_in_value(table, row_id, str(name), str(declared or ""), keys.get(str(name)), chain)
            if value is _REFUSED:
                return False
            columns.append(str(name))
            values.append(value)
        present = {str(r[1]) for r in info if r[6] == 0}
        for name, value in stand_in.MARKS.get(table, {}).items():  # the marks every reader leaves a stand-in out by (stand_in.py)
            if name in present and name not in columns:
                columns.append(name)
                values.append(value)
        try:
            self.dst.execute(
                f"INSERT INTO {_ident(table)} ({', '.join(_ident(c) for c in columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(values),
            )
        except Exception as exc:  # noqa: BLE001
            self._check_stop()
            if "constraint" in str(exc).lower() or type(exc).__name__ == "IntegrityError":
                return False
            self._raise_for_target("a stand-in row", exc)
        self._made.append((table, int(row_id)))
        self._stand_in_ids[table] = max(self._stand_in_ids.get(table, row_id), row_id)
        return True

    def _undo_stand_ins(self, mark: int) -> None:
        """Remove the stand-in rows made since ``mark`` (a stand-in that was refused, and the parents it had already made for its keys): a
        stand-in nobody needs is a row that does not exist in the user's data."""
        for table, row_id in reversed(self._made[mark:]):
            try:
                self.dst.execute(f"DELETE FROM {_ident(table)} WHERE {_ident(self._row_id_alias[table])} = ?", (row_id,))
            except Exception as exc:  # noqa: BLE001
                self._raise_for_target("a stand-in row that was not needed", exc)
        del self._made[mark:]
        self._stand_in_ids = {}
        for table, row_id in self._made:
            self._stand_in_ids[table] = max(self._stand_in_ids.get(table, row_id), row_id)

    def _orphans(self) -> None:
        """NOTHING READABLE IS REMOVED (the deep read of E3, NEW-4: the user's R100, local data never gives way). A row whose parent
        row could not be read is kept and counted per table (``orphans``), and the tables among them that hold a verdict this install
        MEASURED (a column named ``verdict``) are named (``orphans_verdict_tables``). What the earlier fold removed them for was real:
        a table without AUTOINCREMENT hands out ``max(id) + 1``, so when the newest pages of a parent table are lost the next row saved
        takes a lost id and seems to own the rows kept for it (S6). That is stopped without removing anything: a key declared ``ON
        DELETE SET NULL`` is set to NULL, as the app would have written it; where the parent table is AUTOINCREMENT its counter is
        raised to the highest id any row refers to; otherwise ONE stand-in row marked as lost is written into the parent table at that
        id (``stand_ins``), so the highest id is taken and every lost id below it is a gap, which is never handed out again. A stand-in
        the table's own constraints refuse is named (``id_reuse_possible``) and nothing is removed for it either."""
        groups = self._orphan_groups()
        if not groups:
            return
        nulled = self._null_the_set_null_keys(groups)
        if nulled:
            self.report["set_null"] = nulled
            groups = self._orphan_groups()
        counts: dict[str, int] = {}
        for (child, _parent, _number), n in groups.items():
            counts[child] = counts.get(child, 0) + n
        if counts:
            self.report["orphans"] = counts
            verdict_tables = []
            for table in sorted(counts):
                try:
                    columns = {str(r[1]) for r in self.dst.execute(f"PRAGMA table_info({_ident(table)})")}
                except Exception as exc:  # noqa: BLE001
                    self._raise_for_target("the list of columns of a table with orphans", exc)
                if "verdict" in columns:
                    verdict_tables.append(table)
            if verdict_tables:
                self.report["orphans_verdict_tables"] = verdict_tables
        reuse: list[str] = []
        self._orphan_needs = self._highest_referenced(groups)
        for parent, high in sorted(self._orphan_needs.items()):
            if parent in self._autoincrement:
                self._raise_sequence(parent, high)
            elif self._stand_in_ids.get(parent, 0) >= high:
                continue  # a stand-in made for another table's key is above every id an orphan refers to: that id is taken
            else:
                mark = len(self._made)
                if not self._stand_in(parent, high):
                    self._undo_stand_ins(mark)
                    reuse.append(parent)
        if self._stand_in_ids:
            self.report["stand_ins"] = dict(sorted(self._stand_in_ids.items()))
            self.report["stand_ins_note"] = STAND_IN_NOTE
        if reuse:
            self.report["id_reuse_possible"] = reuse
        try:
            self.dst.commit()
        except Exception as exc:  # noqa: BLE001
            self._raise_for_target("the orphans", exc)


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
