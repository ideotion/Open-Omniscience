"""A damaged database file is NOTICED, NAMED and CONTAINED (damaged-database plan, slice E1).

WHY THIS EXISTS. The Asus bundle of 2026-10-06 held a corpus SQLite itself called malformed from
2026-10-02, and collection went on for a day and a half: about 300 "batched collect commit failed;
redoing N article(s) one at a time" lines, each a pass that wrote into a file the database could not
fully read. Nothing in the app named the word: ``grep malformed src`` found one reader, the FTS health
probe. This module is the missing sentence.

WHAT IT DOES.

* **Notices.** A ``handle_error`` observer on the corpus engine and on every lane engine
  (:func:`attach`) asks one question of each failed statement: is the DRIVER's own exception
  ``SQLITE_CORRUPT`` (primary code 11, any extended code)? It reads the code off the driver's exception,
  never the SQLAlchemy wrapper's text, which carries the statement and its bound values (the lesson of
  #1306's ``is_disk_full``). ``SQLITE_NOTADB`` (26, "file is not a database") NEVER counts: it is what a
  wrong passphrase produces under SQLCipher, measured on the real driver (``tests/test_database_damage.py``).
* **Names.** One incident record per distinct (file, scope, statement shape) per process, in
  ``data/database-damage.json`` (atomic, the newest 20 kept, survives restarts): when, which FILE, the
  driver's code and a FIXED LABEL for what it said (never the driver's own text: see :func:`corruption_of`) with the
  driver's class, the statement's SHAPE with every value stripped, the thread and the route,
  how the previous session ended, and the sizes of the file, its log and the drive. A repeat of a known
  incident is counted, not re-recorded. NO value from any row, no passphrase and no URL reaches the record.
* **Contains, per file.** The latch names the file: the CORPUS latch stops collection's writes to the
  corpus (passes, the housekeeping lanes, maintenance: :meth:`StorageGuard.admit`), the LAW latch stops the
  law step of the housekeeping lane, a WIKI latch stops the Wikipedia lane's writing (``wiki/runner.py``),
  and none stops another; any other file is recorded and NAMED, with nothing to pause. The latch is memory
  only: a restart is the operator trying again, and the first failed read puts it back.

* **Discards a poisoned connection.** On an ENCRYPTED file a read of a page that fails its check leaves that
  connection answering an empty ``MemoryError`` to every later read, healthy tables included, until it is closed
  (measured on SQLCipher 4.12, sqlcipher3 0.6.2 and 0.6.3; SQLCipher 4.19, sqlcipher3 0.6.4, answers the same code-11
  ``SQLITE_CORRUPT`` instead, on every statement, until it is closed: the branch below that reads an empty ``MemoryError`` is not
  reached there and stays for the floor). The observer therefore marks a SQLCipher ``SQLITE_CORRUPT`` as a disconnect for that ONE connection
  (:func:`discard_poisoned_connection`), so the pool opens a fresh one instead of handing the poisoned one to the
  next request. It does the same for an empty ``MemoryError`` raised on a SQLCipher connection, because the LAST
  overflow page of a long value fails silently (the read returns the right length with wrong tail bytes and the
  poison arrives on the NEXT statement, measured), and it NEVER latches or records on that: an empty
  ``MemoryError`` is also what a real allocation failure raises, so by itself it names no file (on 4.19 the next
  statement raises a real corruption error instead, which latches; with the automatic re-read on, the re-read of the tables
  that statement named is clean and releases the latch again). A wrong key and a
  plain SQLite file's corruption are never reclassified. A statement the driver runs for the app on a pooled
  connection WITHOUT going through SQLAlchemy raises past this observer, so those sites go through
  :func:`guard_raw_driver`, which does the same for them.

* **Verifies (E2, ``database/verify.py``).** After an unexpected stop the app reads each table of the corpus,
  Wikipedia and law files once with ``PRAGMA quick_check(table)`` on its own read-only connection before
  collection writes to them again, and this registry keeps the progress (collection waits while it runs:
  :meth:`verifying`), each table's verdict (the record's ``verification`` block) and the latch a damaged table
  sets, by the same door a corruption error uses (:meth:`_apply_incident`).

WHAT IT DOES NOT DO (and the PR says so). It does not repair or salvage: that is E3 (a salvage copy). The
latch releases only when the operator starts collection again (:func:`retry_for_collection_start`: the
corpus's and the law file's; going online and the unattended start are the operator starting it), or starts
the Wikipedia lane (its own start releases its own file), never by itself and never by a courtesy resume
after a backup. A latch the per-table check set is not released by that start on its say-so: the start
RE-READS the tables the check reported (:func:`database.verify.recheck`, on its own thread, the latch held
meanwhile) and releases only when every one of them reads clean, which is what a restart already does (the
boot check reads the file again and the latch, in memory, is gone when it reads clean); a table that still
reads damaged, or cannot be read, keeps the latch. Going online is the routine click (R117), so a start that
released a check-found latch unread would let collection write into a file the check had just found damaged.
A latch a failed read set (E1) is released by the start directly, and the first failed read puts it back. A
RESTORE that replaced the file releases its latch outright (:meth:`retry`, ``file_replaced``): the verdict was
about a file that no longer is.

THE SCOPE FIELD. ``search-index`` is claimed when the full-text index is what the failing statement reads:
the virtual-table corruption code (extended 267, which FTS5 raises for its own structure) or a statement
over ``article_fts`` or one of its shadow tables that does NOT also name ``articles`` (the app's own Search
gates each hit on the articles table inside the same statement, and damaged ARTICLE pages raise the same
code from it: measured, so that statement is ``data``, and the scope is decided on the WHOLE statement, not
the cut the record keeps). MEASURED: damaged index pages read through ``MATCH`` raise
plain code 11, never 267, so the statement is the only evidence there is, and it is a SUSPICION: an
external-content FTS5 table reads the ``articles`` table through the index (the gotcha
``fts._decide_fts_rebuild`` documents), and a trigger that writes the index fails inside a statement that
names only ``articles``. So the record says which basis it used, the sentence never says the articles are
intact (E1 has not looked), and ``data`` is sticky while a file is latched (the worst scope wins: a later
index-only incident must not soften a data one). Everything else is ``data``. The scope picks the route the
record names (``search-index-rebuild`` or ``verify-then-salvage``); E1 only RECORDS the route, and E2's
per-table check is what decides.

The observer touches no database (an observer on a damaged file must not read it) and never raises; the
reading of tables is ``database/verify.py``'s, on its own connections.
"""
from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import re
import threading
import time
import uuid
import weakref
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import scrubbed_name

_LOG = logging.getLogger(__name__)

SCHEMA = 1
RECORD_FILE = "database-damage.json"

SQLITE_CORRUPT = 11  # primary code; every extended code shares its low byte
SQLITE_CORRUPT_VTAB = 267  # extended: what FTS5 raises for its own structure

FILE_CORPUS = "corpus"
FILE_WIKI = "wiki"
FILE_LAW = "law"
#: The file starting collection again does NOT release: the Wikipedia lane has its own start. The corpus and the
#: law file are released by it (a file that is only recorded has no writer to pause, so a start never names it).
NOT_RELEASED_BY_COLLECTION = (FILE_WIKI,)
#: The files that have a writer this module pauses (the corpus's passes, the Wikipedia lane's loop, the law
#: step). Any other file's incident is recorded and named, and nothing waits on it.
PAUSED_FILES = (FILE_CORPUS, FILE_WIKI, FILE_LAW)

SCOPE_DATA = "data"
SCOPE_SEARCH_INDEX = "search-index"
ROUTE_VERIFY_THEN_SALVAGE = "verify-then-salvage"
ROUTE_REBUILD_INDEX = "search-index-rebuild"

#: Incidents kept in the record. Twenty is a day's worth of distinct problems on the worst machine
#: measured, and a file that grows without bound in a failing data directory is its own incident.
INCIDENTS_KEEP = 20
#: How many repair attempts the record keeps (the newest). One attempt is a few hundred bytes plus its per-table lines.
REPAIRS_KEEP = 10

#: How many days the damaged file a repair set aside is kept, counted from the moment the repaired file first read clean (R129, the
#: user's answer 35 = b); ``repair.KEPT_COPY_DAYS`` is this number, which lives here because the notice needs it and ``repair`` imports
#: this module. The notice that the app removed the file is shown for as many days again, so a banner does not outlive its use.
KEPT_COPY_DAYS = 30

#: Repeats of a known incident are written back at most this often. The latch stops the writers within a
#: statement or two, so a repeat is rare; the bound is for the case where something else keeps reading.
FLUSH_EVERY_S = 60.0

#: How long the failing statement's thread waits for the record to be gathered and written (see
#: :meth:`DamageRegistry.note`). What it protects: a thread that may hold the write gate, on a drive that
#: may be the failing one. The record still lands when the drive answers; this is how long a hung one can
#: delay a statement that has already failed.
RECORD_WAIT_S = 2.0

#: The one job that writes the record back after a repeat or a retry (a record job is keyed by its incident).
_FLUSH_JOB: tuple = ("flush",)

#: The check that follows an unexpected stop (``database/verify.py``) is attempted at most this many starts in a
#: row when it does not finish (a start that began it and ended before it did: the process was killed or the
#: machine went down mid-check). What it protects: a check that itself brings the process down must not become
#: a boot loop that never reaches collection. A check that finishes resets the count. THE CAP STOPS RE-RUNNING
#: THE CHECK; IT NEVER CLEARS A FINDING: a file an earlier check reported as damaged is latched from that record
#: (``FRAME_CHECK_STOPPED`` says why) and stays paused until the tables reported read clean or the file is replaced.
#: THE HOLD LASTS: it is not one start's, a file held at the cap stays held at every clean start until a new unexpected
#: stop (a new reason to check) starts the count again at 0; without that a check that keeps dying would run three more times
#: after every hold, which is the loop this cap exists to stop.
MAX_VERIFY_ATTEMPTS = 3

#: The ways a per-table check ends (``database/verify.py``).
VERDICT_OK = "ok"
VERDICT_DAMAGED = "damaged"
VERDICT_UNCHECKED = "unchecked"

#: How much of a statement's shape a record keeps.
_SHAPE_KEEP = 240

#: The words a record keeps of what the driver said when it said ``SQLITE_CORRUPT``: one of these three FIXED labels, chosen
#: by the CLASS of the driver's first line and never a part of it. What this protects: SQLite words some corruption errors with
#: the name of the schema object or a fragment of its definition ("malformed database schema (name) - ...") and a driver's text
#: is the one thing in the record that no code of ours wrote; the record rides the diagnostics bundle, so engine text into a
#: record is class-only. The first label is the text SQLite gives for a damaged page; the second is the head of its schema one.
CORRUPT_IMAGE = "database disk image is malformed"
CORRUPT_SCHEMA = "malformed database schema"
CORRUPT_OTHER = "the driver reported SQLITE_CORRUPT"

_DBAPI_MODULES = ("sqlite3", "sqlcipher3")

#: The keys of a file's state that live in memory only and never reach the record: the latch (a restart is the
#: operator trying again), the tables the per-table check reported (the incident names them), and the progress of a
#: re-read.
_MEMORY_ONLY = ("latched", "check_tables", "rechecking", "check_stopped_after", "auto_released", "auto_stayed")

#: What the automatic re-read of a first failed read ended with, as the file's record says it (``reread.result``). Fixed words,
#: never an engine's: the record rides the diagnostics bundle.
REREAD_CLEAN = "clean"  # every table the statement named read clean again: the pause ended by itself
REREAD_CLEAN_HELD = "clean-held"  # read clean, but another read failed while it ran: the pause stays (see ``recheck_finished``)
REREAD_DAMAGED = "damaged"  # a table read damaged twice, on two connections
REREAD_UNREAD = "unread"  # a table could not be read (a busy file, no memory, an I/O error): no answer, the pause stays
REREAD_NOT_MADE = "not-made"  # no re-read could be made (``reread.why`` says which of the fixed reasons)
REREAD_STAYED = "stayed"  # the same table failed again after one clean re-read: it latches and stays, with no second re-read

#: The full-text index (``article_fts``) and its shadow tables. A statement over these is the evidence that
#: the index is what could not be read (a suspicion, not proof: see the module docstring).
_SHADOW_TABLE = re.compile(r"\barticle_fts(?:_(?:data|idx|docsize|config|content))?\b", re.IGNORECASE)

#: The articles table. A statement that reads the index AND this table cannot say which of the two raised.
_CONTENT_TABLE = re.compile(r"\barticles\b", re.IGNORECASE)

_MISSING_CAPABILITY = re.compile(r" - no such (?:function|module|collation)\b")

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_NUMBER = re.compile(r"(?<![\w\"])-?\d+(?:\.\d+)?(?![\w\"])")
_PLACEHOLDER_RUN = re.compile(r"\?(?:\s*,\s*\?)+")


def switch_on() -> bool:
    """``OO_DAMAGE_GUARD=0`` turns the PAUSE off (the record is still written). Its own switch, never the
    storage guard's: a machine that disabled the resource guard has not said it wants to keep writing into
    a file the database reports as damaged."""
    return os.getenv("OO_DAMAGE_GUARD", "1") != "0"


# --- classification -----------------------------------------------------------------------


def driver_error(exc: BaseException | None) -> BaseException | None:
    """The DRIVER's own exception (sqlite3 or sqlcipher3) behind ``exc``: SQLAlchemy's ``.orig``, then
    ``__cause__`` (``raise ... from``). Not ``__context__``: that is merely the exception being handled
    when another was raised, and a ``TypeError`` raised inside the ``except`` of an earlier corrupt error
    is not corruption. SQLAlchemy's wrapper is never read, for its text carries the statement and every
    value bound to it."""
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__module__.split(".")[0] in _DBAPI_MODULES:
            return cur
        cur = getattr(cur, "orig", None) or cur.__cause__
    return None


def _corrupt_label(low_first_line: str) -> str:
    """The fixed label for the class of a driver's (lower-cased) first line: the only thing of the line that is recorded."""
    if low_first_line.startswith(CORRUPT_IMAGE):
        return CORRUPT_IMAGE
    if low_first_line.startswith(CORRUPT_SCHEMA):
        return CORRUPT_SCHEMA
    return CORRUPT_OTHER


def failure_label(exc: BaseException) -> str:
    """What a record keeps of a failure that is NOT a driver's ``SQLITE_CORRUPT``: the exception's class and, for an ``OSError``, the NAME of
    its errno (``OSError ENOSPC``). Never the message and never the path: an ``OSError`` carries the file it failed on (a home folder with a
    person's name in it), and any other exception can carry an engine's own words, a statement or a bound value. What this protects: the
    record rides the diagnostics bundle, and engine text into a record is class-only."""
    name = type(exc).__name__
    code = exc.errno if isinstance(exc, OSError) else None
    named = errno.errorcode.get(code) if isinstance(code, int) else None
    return f"{name} {named}" if named else name


def corruption_of(exc: BaseException | None) -> dict[str, Any] | None:
    """What the driver said, when it said ``SQLITE_CORRUPT`` (primary code 11, any extended code); else
    ``None``. ``{"code", "name", "message", "driver_class"}``. The message is a FIXED LABEL
    (:data:`CORRUPT_IMAGE`, :data:`CORRUPT_SCHEMA` or :data:`CORRUPT_OTHER`) and never the driver's text: the
    classification reads the driver's own first line, and nothing of that line goes further, so the record
    (and the verdict's reason, which is the same label) carries the class of the line and the class of the
    exception (``driver_class``, its type name) and no schema name, no fragment of a definition and no value.

    A driver that carries ``sqlite_errorcode`` (CPython's ``sqlite3`` from 3.11, and ``sqlcipher3``, both
    measured) is matched on the code alone: ``SQLITE_NOTADB`` (26) is not corruption whatever its text
    says, and a message that merely contains the words does not make a code-26 error one. The message is
    the fallback for a driver without the attribute, and then only the two messages SQLite gives for
    ``SQLITE_CORRUPT``, matched at the START of the driver's own first line."""
    driver = driver_error(exc)
    if driver is None:
        return None
    first = (str(driver).splitlines() or [""])[0].strip()
    low = first.lower()
    if low.startswith("malformed database schema") and _MISSING_CAPABILITY.search(low):
        # SQLite can give this SQLITE_CORRUPT text when a connection lacks a function, module or collation
        # the schema needs: a missing capability of the connection, not a damaged file. ONLY those three:
        # "no such table" or "no such column" in a schema row is real damage (measured on both drivers with a
        # schema row edited out), and on the drivers the app ships a missing capability gives a different
        # error (a function: code 1; a collation: 257; a module: code 1), so this is a guard for an older
        # SQLite and never a reason to ignore a damaged schema.
        return None
    code = getattr(driver, "sqlite_errorcode", None)
    if isinstance(code, int):
        if (code & 0xFF) != SQLITE_CORRUPT:
            return None
        name = getattr(driver, "sqlite_errorname", None)
        return {
            "code": code,
            "name": name if isinstance(name, str) else "SQLITE_CORRUPT",
            "message": _corrupt_label(low),
            "driver_class": type(driver).__name__,
        }
    if low.startswith(CORRUPT_IMAGE) or low.startswith(CORRUPT_SCHEMA):
        return {"code": None, "name": None, "message": _corrupt_label(low), "driver_class": type(driver).__name__}
    return None


# SQLite's own constants ("SQLITE_IOERR_READ"): a name from a fixed set, never a message. Anything that does not look like one is dropped, so
# a driver that put text in the attribute adds none.
_SQLITE_NAME = re.compile(r"SQLITE_[A-Z0-9_]{1,40}")


def failure_text(exc: BaseException) -> str:
    """The reason for a failure, as a record keeps it: the DRIVER's class (never the wrapper's) and, when the driver gave one, a FIXED
    label: the label of the damage class for ``SQLITE_CORRUPT`` (:func:`corruption_of`), else SQLite's own constant name for the
    error (``SQLITE_IOERR_READ``, a vocabulary of the library and not text of any statement). NEVER a part of the driver's message, scrubbed or
    not: it can carry a schema name, a statement or a bound value, the copy runs on keyed connections, and this line is written to records
    that ride the diagnostics bundle (the repair record, the full-text probe of the integrity report; engine text into a record is
    class-only). The classification reads the raw error; nothing of its text goes further."""
    driver = driver_error(exc) or exc
    found = corruption_of(exc)
    if found is not None:
        return f"{type(driver).__name__}: {found['message']}"
    name = getattr(driver, "sqlite_errorname", None)
    if isinstance(name, str) and _SQLITE_NAME.fullmatch(name):
        return f"{type(driver).__name__}: {name}"
    return failure_label(driver)


def is_corruption(exc: BaseException | None) -> bool:
    return corruption_of(exc) is not None


def statement_shape(statement: str | None, *, keep: int | None = _SHAPE_KEEP) -> str | None:
    """A statement with every VALUE taken out: whitespace collapsed, string literals ``?``, numbers
    ``N``, a run of placeholders one. Bound parameters are never given to this at all (only the SQL
    text is), so the shape is what is left of a statement that already carried none; the stripping is for
    the SQL that has a literal written into it. ``keep`` is how much of it is kept (``None``: all of it,
    which is what the SCOPE is decided on: a long statement can name a second table past the cut)."""
    if not statement:
        return None
    text = " ".join(str(statement).split())
    text = _STRING_LITERAL.sub("?", text)
    text = _NUMBER.sub("N", text)
    text = _PLACEHOLDER_RUN.sub("?, ?", text)
    return text if keep is None else text[:keep]


_IDENTIFIER = re.compile(r'"((?:[^"]|"")+)"|`([^`]+)`|\[([^\]]+)\]|([A-Za-z_][A-Za-z0-9_$]*)')


def statement_names(statement: str | None) -> frozenset[str]:
    """Every identifier a statement writes, lower-cased (SQLite's names are case-blind): bare, ``"double-quoted"``, ``backticked`` or
    ``[bracketed]``, with the values already taken out of it (:func:`statement_shape`, so a string literal names nothing).

    What it is FOR: the re-read of a failed read intersects these with the tables the file really has, so it reads every table the
    statement can have touched. WORDS, not a parse of FROM / JOIN / INTO: a table reached through a comma join, an alias list or a
    subquery is a word too, and a reading that missed one would release a pause on a table it never read. It over-includes (a column
    named like a table is read as well), which costs a read, never a missed table. What it cannot see is a table reached WITHOUT being
    written: through a view or a trigger, or one written in a form of SQLite's grammar this app's schema never uses (a non-ASCII bare
    name, a table name in single quotes, a bracketed all-digit name). The second failure of the statement latches and stays
    (:data:`REREAD_STAYED`)."""
    shape = statement_shape(statement, keep=None)
    if not shape:
        return frozenset()
    out: set[str] = set()
    for m in _IDENTIFIER.finditer(shape):
        quoted = m.group(1)
        word = quoted.replace('""', '"') if quoted is not None else (m.group(2) or m.group(3) or m.group(4))
        out.add(word.lower())
    return frozenset(out)


def scope_of(code: int | None, shape: str | None) -> tuple[str, str]:
    """``(scope, basis)``: ``search-index`` only on evidence (see the module docstring), else ``data``."""
    if code == SQLITE_CORRUPT_VTAB:
        return SCOPE_SEARCH_INDEX, "the driver reported corruption in a virtual table (extended code 267)"
    if shape and _SHADOW_TABLE.search(shape):
        if _CONTENT_TABLE.search(shape):
            # The app's own Search statement matches the index and gates each hit on the articles table, so
            # damaged ARTICLE pages raise the same code from it (measured): it cannot say which one failed.
            return SCOPE_DATA, (
                "the failing statement reads the search index and the articles table, so the damage may "
                "be in either"
            )
        return SCOPE_SEARCH_INDEX, (
            "the failing statement reads the search index (a damaged index reports plain code 11 through "
            "MATCH, so this is a suspicion: the per-table check of E2 decides)"
        )
    return SCOPE_DATA, "nothing shows the damage is limited to the search index"


def route_for(scope: str) -> str:
    return ROUTE_REBUILD_INDEX if scope == SCOPE_SEARCH_INDEX else ROUTE_VERIFY_THEN_SALVAGE


# --- the facts an incident carries (stats only; never a read of the damaged file) --------------


def _file_paths(file_key: str) -> tuple[Path | None, str | None]:
    """The file a key names, as a path and the file's own name. Stats only, never an open."""
    try:
        if file_key == FILE_CORPUS:
            from src.database.session import engine

            if engine.url.get_backend_name() != "sqlite":
                return None, None
            db_file = engine.url.database
            if not db_file or db_file == ":memory:":
                return None, None
            path = Path(db_file)
            return path, path.name
        from src.versioned.store import lane_path

        path = lane_path(file_key)
        return path, path.name
    except Exception:  # noqa: BLE001 - a record without a path is still a record
        return None, None


def _engine_path(context: Any) -> Path | None:
    """The file the failing engine is over, from the engine itself (a SQLite URL's database), so a
    record names the file that raised and not the one its key usually stands for."""
    try:
        database = context.engine.url.database
        if database and database != ":memory:":
            return Path(database)
    except Exception:  # noqa: BLE001
        pass
    return None


def _sizes(path: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {"file_bytes": None, "wal_bytes": None, "disk_free_bytes": None}
    if path is None:
        return out
    with contextlib.suppress(OSError):
        out["file_bytes"] = path.stat().st_size
    try:
        out["wal_bytes"] = Path(str(path) + "-wal").stat().st_size
    except FileNotFoundError:
        out["wal_bytes"] = 0
    except OSError:
        pass
    try:
        from src.config.hardware_reading import disk_bytes

        out["disk_free_bytes"] = disk_bytes(path.parent)[0]
    except Exception:  # noqa: BLE001
        pass
    return out


def _previous_end() -> dict[str, Any] | None:
    """How the session before this one ended, from the session ledger (a small file read)."""
    try:
        from src.monitoring import session_history

        current = session_history.current_session().get("session_id")
        for rec in reversed(session_history.read_records()):
            if rec.get("kind") == "end" and rec.get("session_id") != current:
                return {"clean": rec.get("clean"), "at": rec.get("at"), "basis": rec.get("basis")}
    except Exception:  # noqa: BLE001
        pass
    return None


def _current_session_id() -> str | None:
    try:
        from src.monitoring import session_history

        return session_history.current_session().get("session_id")
    except Exception:  # noqa: BLE001
        return None


def _endpoint() -> str | None:
    """The route TEMPLATE the failing request is serving, when it is one (the pool watcher's own label)."""
    try:
        from src.database import pool_watch

        return pool_watch.endpoint_template()  # the template only: a raw path may carry an id or a file name
    except Exception:  # noqa: BLE001
        return None


def record_path() -> Path:
    from src.paths import data_dir

    return data_dir() / RECORD_FILE


# --- the registry ------------------------------------------------------------------------------


def _table_records(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-table records of a verification entry that are records. A function of its own because a comprehension is inlined into its
    caller on CPython 3.13 and the back-edge of its filter-skip then sits outside the exception table of the ``with self._lock`` in
    ``DamageRegistry.confirmed_damage`` (R205): an interrupt there would skip the lock's release."""
    return [t for t in entry.get("tables") or [] if isinstance(t, dict)]


def _damaged_table_names(tables: list[dict[str, Any]]) -> list[str]:
    """The names of the tables read as damaged, for the same reason as :func:`_table_records`."""
    return [str(t.get("table")) for t in tables if t.get("verdict") == VERDICT_DAMAGED]


class DamageRegistry:
    """The per-file latch and the incident record. Thread-safe; every method that an observer reaches
    never raises."""

    def __init__(self, *, path_fn=None, clock=time.time, mono=time.monotonic, rereads: bool = False) -> None:
        self._path_fn = path_fn or record_path
        self._clock = clock
        self._mono = mono
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()  # one writer of the record at a time; never held with _lock
        self._load_lock = threading.Lock()  # one reader of the record file; never held with _lock
        #: Tells this process's incidents from an earlier process's in the record (the session id can be
        #: unknown, and two unknowns must not read as the same incident).
        self._process = uuid.uuid4().hex[:12]
        self._claims = 0  # the next re-read claim's token
        #: Whether a first failed read starts the automatic re-read of the tables its statement names (``verify.reread``). The
        #: process's own registry (``registry``, below) is built with it ON, always; a registry a caller builds for itself is not
        #: re-reading unless asked, because a re-read is a thread that reads a file and a test that injects an error into a healthy file
        #: asked for the latch it injected. The suite's isolation fixture switches the global one off for the same reason, and the tests
        #: of the re-read build theirs with it on. ``_reset_for_tests`` leaves it as it is.
        self.rereads = rereads
        self._loaded = False
        self._prior_unreadable = False
        self._incidents: deque[dict[str, Any]] = deque(maxlen=INCIDENTS_KEEP)
        self._files: dict[str, dict[str, Any]] = {}
        self._last_flush_mono: float | None = None
        self._write_error: str | None = None
        self._seq = 0  # numbers the documents handed to ``_flush`` so an older one never overwrites a newer
        self._flushed_seq = 0
        #: The record threads alive, one per key (a record's incident, or the write-back): a drive that hangs
        #: holds ONE thread, never one per failing statement. ``_pending`` counts what arrived meanwhile.
        self._jobs: dict[tuple, threading.Thread] = {}
        self._pending: dict[tuple, int] = {}
        #: The per-table check in progress (``None`` when none): ``{"state": "pending" | "running", ...}``.
        self._verifying: dict[str, Any] | None = None
        #: The newest check of each file (this process's, or an earlier one's read from the record).
        self._verification: dict[str, dict[str, Any]] = {}
        #: The attempts of the repair of a damaged file (``database/repair.py``), newest last, this process's and earlier ones'.
        self._repairs: deque[dict[str, Any]] = deque(maxlen=REPAIRS_KEEP)

    def _reset_for_tests(self, *, path_fn=None) -> None:
        with self._lock:
            self._loaded = True  # a test starts from nothing, never from a file a neighbour wrote
            self._prior_unreadable = False
            self._incidents.clear()
            self._files.clear()
            self._last_flush_mono = None
            self._write_error = None
            self._seq = self._flushed_seq = 0
            self._jobs.clear()
            self._pending.clear()
            self._verifying = None
            self._verification.clear()
            self._repairs.clear()
            self._path_fn = path_fn or record_path

    # -- persistence ------------------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        """Pick up the record an earlier session wrote, once per process. The FILE is read outside the
        registry's lock (``latched`` is read on every unit of collection work and must never queue behind
        a slow drive); only the merge of what was read happens under it. A record that cannot be read is
        said so (``prior_record_unreadable``) and replaced by the next incident, never a reason to fail."""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            raw: Any = None
            unreadable = False
            try:
                raw = json.loads(Path(self._path_fn()).read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                unreadable = True
            with self._lock:
                self._merge_loaded_locked(raw, unreadable)
                self._loaded = True

    def _merge_loaded_locked(self, raw: Any, unreadable: bool) -> None:
        if unreadable:
            self._prior_unreadable = True
            return
        if raw is None:
            return
        try:
            earlier = list(self._incidents)  # an incident noted while the file was being read stays newest
            self._incidents.clear()
            for inc in raw.get("incidents", [])[-INCIDENTS_KEEP:]:
                if isinstance(inc, dict):
                    self._incidents.append(inc)
            self._incidents.extend(earlier)
            for key, st in (raw.get("files") or {}).items():
                if not isinstance(st, dict):
                    continue
                cur = self._files.get(str(key))
                if cur is None:
                    # The history carries over; the LATCH does not (a new session is a retry).
                    self._files[str(key)] = {
                        "latched": False,
                        "incidents": int(st.get("incidents") or 0),
                        "first_at": st.get("first_at"),
                        "last_at": st.get("last_at"),
                        "scope": st.get("scope"),
                        "retries": int(st.get("retries") or 0),
                    }
                else:
                    # The file was latched in this process before its record was read (the latch is set
                    # first): the earlier counts join this process's, and the first time stays the first.
                    cur["incidents"] = int(cur.get("incidents") or 0) + int(st.get("incidents") or 0)
                    rc = cur.get("rechecking")
                    if rc is not None:
                        # A re-read claimed before the earlier record was read counted this process's incidents only: an EARLIER
                        # session's are not reads that failed while it ran (a clean answer would read as "held" for ever).
                        rc["incidents"] = int(rc.get("incidents") or 0) + int(st.get("incidents") or 0)
                    cur["retries"] = int(cur.get("retries") or 0) + int(st.get("retries") or 0)
                    first = st.get("first_at")
                    if isinstance(first, str) and first and (not cur.get("first_at") or first < cur["first_at"]):
                        cur["first_at"] = first
            for key, ver in (raw.get("verification") or {}).items():
                # What an EARLIER process recorded stays readable (the boot decision asks whether a check was
                # left unfinished); a result this process already produced is newer and wins.
                if isinstance(ver, dict) and str(key) not in self._verification:
                    self._verification[str(key)] = dict(ver)
            mine = list(self._repairs)  # an attempt noted while the file was being read stays newest
            self._repairs.clear()
            self._repairs.extend(r for r in (raw.get("repairs") or [])[-REPAIRS_KEEP:] if isinstance(r, dict))
            self._repairs.extend(mine)
        except (AttributeError, TypeError, ValueError):
            self._prior_unreadable = True

    def _doc_locked(self) -> dict[str, Any]:
        """The record as it stands. Caller holds the lock; the WRITE happens outside it (:meth:`_flush`),
        because ``corpus_latched`` is read on every unit of collection work and must never queue behind
        a slow drive."""
        self._seq += 1
        return {
            "schema": SCHEMA,
            "write_seq": self._seq,
            "written_at": datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds"),
            "files": {k: {kk: vv for kk, vv in v.items() if kk not in _MEMORY_ONLY} for k, v in self._files.items()},
            "incidents": [dict(i) for i in self._incidents],
            "verification": {k: dict(v) for k, v in self._verification.items()},
            "repairs": [dict(r) for r in self._repairs],
        }

    def _flush(self, doc: dict[str, Any], *, durable: bool = False) -> bool:
        """Atomic: write a sibling and rename. A drive that cannot take it is said in ``write_error``;
        the in-memory latch holds regardless. Never called with the registry lock held. ``durable`` makes the
        file's data and then the folder's entry ``fsync``ed before it returns (:meth:`flush_durable`); the
        daemon thread's write is not, because a latch is re-read from the file system's own state at the next
        start. Returns whether this snapshot is now the file."""
        landed = False
        with self._io_lock:
            if doc.get("write_seq", 0) <= self._flushed_seq:
                return False  # a newer snapshot already landed (two threads raced): never write an older one over it
            path = Path(self._path_fn())
            tmp = path.with_name(path.name + ".tmp")
            error: str | None = None
            try:
                text = json.dumps(doc, indent=1, sort_keys=True)
                if durable:
                    with open(tmp, "w", encoding="utf-8") as handle:
                        handle.write(text)
                        handle.flush()
                        os.fsync(handle.fileno())
                else:
                    tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, path)
                if durable:
                    fsync_folder(path.parent)
                self._flushed_seq = doc.get("write_seq", 0)
                landed = True
            except OSError as exc:
                error = failure_label(exc)  # the class and the errno name: a drive's message names the path, and the record rides the bundle
                with contextlib.suppress(OSError):
                    tmp.unlink()
        with self._lock:
            self._write_error = error
            self._last_flush_mono = self._mono()  # every attempt: a failing drive is tried once per window
        return landed

    def flush_durable(self) -> bool:
        """Write the record as it stands NOW, on the calling thread, ``fsync``ed (file and folder): ``True`` only when it is on the
        drive. The repair spends the sidecar that names its kept file (the size of the whole library) only after this: the record is
        what names that file and removes it, and the daemon thread that ordinarily writes it never ``fsync``s and swallows its errors
        (the deep read of E3, NEW-6). Tried twice: a newer snapshot of the daemon thread that lands between the two is not durable and
        must be written over. Never raises."""
        try:
            self._ensure_loaded()
            for _attempt in range(2):
                with self._lock:
                    doc = self._doc_locked()
                if self._flush(doc, durable=True):
                    return True
        except Exception as exc:  # noqa: BLE001 - a record that cannot be written is said by the caller
            _LOG.debug("database damage: the record could not be made durable (%s)", type(exc).__name__)
        return False

    # -- noticing ----------------------------------------------------------------------------------
    def on_engine_error(self, context: Any, file_key: str) -> None:
        """The ``handle_error`` listener body for an engine over ``file_key``. Observes only: the error
        still propagates unchanged and nothing here raises."""
        try:
            exc = getattr(context, "original_exception", None)
            if not is_corruption(exc):
                return
            statement = getattr(context, "statement", None)
            if statement and re.match(r"\s*attach\b", str(statement), re.IGNORECASE):
                # An ATTACHed file is not this engine's file (the DATABASE keyword is optional in SQLite,
                # so the statement is matched on its first word); the error cannot say which of the two it
                # came from, and a latch on the wrong one would pause the right file for nothing. What
                # this does NOT cover: a later statement over an attached schema (``INSERT INTO main.x
                # SELECT * FROM other.y``) reads like the engine's own. No engine-level ATTACH exists
                # today (every ATTACH in the app is on a raw driver connection, which has no such
                # listener); whoever adds one must attach through this seam's knowledge.
                return
            self.note(file_key, exc, statement=statement, path=_engine_path(context))
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            pass

    def _known_locked(self, file_key: str, scope: str, shape: str | None) -> dict[str, Any] | None:
        """The record of this very incident in this PROCESS, if one exists. Caller holds the lock. (The
        process token, not the session id: an unknown id would make an earlier process's incident read as
        this one's repeat.)"""
        for inc in reversed(self._incidents):
            if (
                inc.get("file") == file_key
                and inc.get("scope") == scope
                and inc.get("statement_shape") == shape
                and inc.get("process") == self._process
            ):
                return inc
        return None

    def _count_repeat_locked(self, known: dict[str, Any], at: str) -> bool:
        """Count a repeat; whether the record is due to be written back (at most once per
        ``FLUSH_EVERY_S``: the window is CLAIMED here, so a write that hangs or fails is not asked for again
        by every repeat that follows)."""
        known["repeats"] = int(known.get("repeats") or 0) + 1
        known["last_at"] = at
        known.pop("superseded", None)  # a failed read after the answer is a new reason to check at the next start
        known.pop("answered_by", None)  # and nothing answered it any more
        now = self._mono()
        if self._last_flush_mono is None or (now - self._last_flush_mono) >= FLUSH_EVERY_S:
            self._last_flush_mono = now
            return True
        return False

    def note(
        self,
        file_key: str,
        exc: BaseException | None,
        *,
        statement: str | None = None,
        path: Path | None = None,
    ) -> bool:
        """Record one corruption error against ``file_key`` and latch it. ``path`` is the file the
        failing engine is over (the key's usual file when it is not given). Returns whether the error
        was corruption. Never raises.

        The LATCH is set first, in memory, under the lock and nothing else: it is what stops the writers.
        The record (stats, the session ledger, the write of the JSON) is gathered and written on a short-
        lived thread this call waits for at most :data:`RECORD_WAIT_S`, because the failing statement's own
        thread may hold the write gate and the drive may be the failing one."""
        try:
            found = corruption_of(exc)
            if found is None:
                return False
            # The record's shape is cut for size; the SCOPE is decided on the whole statement, because a
            # long one can name a second table after the cut.
            shape_full = statement_shape(statement, keep=None)
            shape = shape_full[:_SHAPE_KEEP] if shape_full else None
            scope, basis = scope_of(found["code"], shape_full)
            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            names = statement_names(shape_full)  # the whole statement: a long one can name a second table after the cut
            newly, known, due, claim = self._apply_incident(
                file_key, scope, shape, at, reread=names if self._rereads_file(file_key) else None
            )
            if newly:
                _log_latched(file_key, found["name"], scope, shape)
            if known is not None:
                if due:
                    self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
            else:
                # The first of its kind in this process. What belongs to the CALLING thread is taken here (a
                # context variable does not follow into another thread); the rest, including the one read of
                # an earlier session's record, is gathered and written off it.
                thread_name = scrubbed_name(threading.current_thread().name) or ""
                endpoint = _endpoint()
                self._single_flight(
                    ("record", file_key, scope, shape),
                    lambda: self._record_new(
                        file_key, found, shape, scope, basis, at, path, thread_name=thread_name, endpoint=endpoint
                    ),
                )
            if claim is not None:
                # After the record, so the incident exists when a clean answer supersedes the file's incidents (see
                # :meth:`_record_new` for the slow drive that makes this wait time out).
                self._start_reread(file_key, names, claim, path, at)
            return True
        except Exception as exc:  # noqa: BLE001 - never raises
            _LOG.debug("database damage: could not record an incident (%s)", type(exc).__name__)
            return False

    def _apply_incident(
        self,
        file_key: str,
        scope: str,
        shape: str | None,
        at: str,
        *,
        check_tables: tuple[str, ...] = (),
        stopped_after: int | None = None,
        reread: frozenset[str] | None = None,
    ) -> tuple[bool, dict[str, Any] | None, bool, int | None]:
        """Count one incident against ``file_key`` and latch it, under the lock: ``(newly latched, the record
        of this very incident when this process already has one, whether its repeat is due to be written
        back, the token of the automatic re-read this latch claimed)``. The ONE place the latch is set, so a
        corruption error and a per-table verdict cannot latch differently. ``check_tables`` (the tables a per-table
        check read as damaged) is stored in the SAME lock block as the latch: a start that landed between the two used
        to read a latched file with no set as an E1 latch and release it unread (the deep delta read's S2).

        ``reread`` (the names a failed read's statement writes; ``None`` for a latch that is not a first failed read) asks for
        the automatic re-read of what that statement touched, and the claim on it is made HERE, in the latch's own lock block,
        for the same reason: a start that landed between the latch and the claim would release the latch unread. A table that an
        earlier re-read of this process released and that fails again is not read a second time: the latch stays
        (``auto_stayed``, :data:`REREAD_STAYED`) so a machine that nobody watches cannot pause, clear and pause for ever."""
        claim: int | None = None
        with self._lock:
            st = self._files.setdefault(
                file_key,
                {"latched": False, "incidents": 0, "first_at": at, "last_at": at, "scope": scope, "retries": 0},
            )
            st["incidents"] += 1
            st["last_at"] = at
            newly = not st["latched"]
            # ``data`` is sticky while latched: a later incident that reads only the search index must
            # not turn "part of your data could not be read" into "your articles were not changed".
            if newly or st.get("scope") != SCOPE_DATA:
                st["scope"] = scope
            st["latched"] = True
            if newly:
                st.pop("auto_stayed", None)
                st.pop("reread", None)  # a record of an earlier latch's re-read is not this latch's
                if reread is not None:
                    claim = self._claim_reread_locked(st, at, reread)
            if check_tables:
                rc = st.get("rechecking")
                if rc and rc.get("auto"):
                    # A per-table check's finding landed on a latch whose first failed read is still being re-read: the check's
                    # measurement decides, and the re-read of one statement's tables must not overwrite or pop its table set. The
                    # re-read's later answers find no claim and are dropped; a start then reads the check's tables.
                    st.pop("rechecking", None)
                    st["reread"] = {"tables": [], "result": REREAD_NOT_MADE, "why": "check-found", "at": at}
                st.pop("auto_stayed", None)  # a start now reads the check's tables, which "stayed" does not say
                # What a start of collection re-reads before it releases this latch (see :meth:`retry`).
                st["check_tables"] = sorted(set(st.get("check_tables") or ()) | set(check_tables))
            if stopped_after:
                # The check was not run again (the cap), said beside the latch it belongs to: set in THIS block, because a
                # retry that landed between the latch and a second block would leave it on an unlatched file, and the
                # next latch of that file would inherit a sentence about a check it never saw.
                st["check_stopped_after"] = int(stopped_after)
            known = self._known_locked(file_key, scope, shape)
            due = self._count_repeat_locked(known, at) if known is not None else False
        return newly, known, due, claim

    def _rereads_file(self, file_key: str) -> bool:
        """Whether a first failed read against ``file_key`` is re-read by itself: the pause is on, the re-read is on, and the file is one
        whose writers the latch pauses (a file with no writer to pause has nothing to release)."""
        return self.rereads and file_key in PAUSED_FILES and switch_on()

    def _claim_reread_locked(self, st: dict[str, Any], at: str, names: frozenset[str]) -> int | None:
        """Make the claim for the automatic re-read of a NEW latch, or settle in the file's record why none is made. Caller holds the
        lock and has just latched ``st``. Returns the claim's token, or ``None`` (the latch is then exactly what it was before the
        re-read existed: the operator's start releases it)."""
        stayed = sorted(set(st.get("auto_released") or ()) & names)
        if stayed:
            st["auto_stayed"] = stayed
            st["reread"] = {"tables": stayed, "result": REREAD_STAYED, "at": at}
            return None
        why = None
        if not names:
            why = "no-statement"
        elif self._verifying is not None:
            why = "check-running"  # the start-up check is reading the files and decides this latch
        elif st.get("rechecking"):
            why = "re-read-running"
        if why is not None:
            st["reread"] = {"tables": [], "result": REREAD_NOT_MADE, "why": why, "at": at}
            return None
        self._claims += 1
        st["rechecking"] = {
            "index": 0, "total": 0, "token": self._claims, "incidents": st["incidents"], "auto": True, "since": at,
        }
        return self._claims

    def _start_reread(self, file_key: str, names: frozenset[str], token: int, path: Path | None, at: str) -> None:
        """Hand the claimed re-read to ``verify.reread``. A re-read that cannot be started ends its claim here, with the reason in the
        file's record, and the latch stays as it was. Never raises."""
        why = "failed"
        try:
            from src.database import verify

            outcome = verify.reread(file_key, names, token=token, path=path)
            if outcome == "started":
                return
            why = outcome
        except Exception as exc:  # noqa: BLE001 - a latch that cannot be re-read stays
            _LOG.warning("database damage: could not start the re-read of a failed read (%s)", type(exc).__name__)
        self.reread_ended(file_key, token, why, at=at)

    def _single_flight(self, key: tuple, fn, *, rerun: bool = False) -> None:
        """Run ``fn`` on a daemon thread, ONE per ``key``: a call that finds its key's thread alive returns at
        once (counting itself in ``_pending``), and a call that starts one waits for it at most
        :data:`RECORD_WAIT_S`. A drive that hangs therefore costs the first failing statement that long and
        holds one thread, not a thread and a wait per statement; the record lands when the drive answers.
        What arrived while the thread ran is settled when it ends: with ``rerun`` the work is done once more
        (a write-back's snapshot is taken when it runs); otherwise it is added to the incident's repeats."""
        with self._lock:
            if key in self._jobs:
                self._pending[key] = self._pending.get(key, 0) + 1
                return
            t = threading.Thread(target=self._job_main, args=(key, fn, rerun), name="oo-damage-record", daemon=True)
            self._jobs[key] = t
            try:
                t.start()
            except BaseException:
                self._jobs.pop(key, None)
                raise
        t.join(RECORD_WAIT_S)

    def _job_main(self, key: tuple, fn, rerun: bool) -> None:
        while True:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("database damage: the record could not be written (%s)", failure_label(exc))
                with self._lock:
                    self._write_error = failure_label(exc)
            with self._lock:
                extra = self._pending.pop(key, 0)
                if extra and rerun:
                    continue  # a repeat or a retry arrived while this one wrote: write the newer record too
                if self._jobs.get(key) is threading.current_thread():  # a test's reset may have replaced it
                    del self._jobs[key]
                if extra and key[0] == "record":
                    known = self._known_locked(key[1], key[2], key[3])
                    if known is not None:
                        known["repeats"] = int(known.get("repeats") or 0) + extra
                return

    def _flush_latest(self) -> None:
        """Write the record as it stands NOW (the snapshot is taken when this runs, not when it was asked
        for)."""
        with self._lock:
            doc = self._doc_locked()
        self._flush(doc)

    def _record_new(
        self,
        file_key: str,
        found: dict[str, Any],
        shape: str | None,
        scope: str,
        basis: str,
        at: str,
        path: Path | None,
        *,
        thread_name: str,
        endpoint: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Gather the facts of a first-of-its-kind incident (stats, the session ledger: nothing reads the
        damaged file) and write the record. Not under the registry's lock until the append. The earlier
        session's record is read here (once per process), after the latch is already set."""
        self._ensure_loaded()
        if path is None:
            path, name = _file_paths(file_key)
        else:
            name = path.name
        record: dict[str, Any] = {
            "at": at,
            "last_at": at,
            "file": file_key,
            "file_name": name,
            "scope": scope,
            "scope_basis": basis,
            "route": route_for(scope),
            "code": found["code"],
            "code_name": found["name"],
            "message": found["message"],
            "driver_class": found.get("driver_class"),
            "statement_shape": shape,
            "thread": thread_name,
            "endpoint": endpoint,
            "session_id": _current_session_id(),
            "process": self._process,
            "previous_end": _previous_end(),
            "repeats": 0,
            **_sizes(path),
            **(extra or {}),
        }
        with self._lock:
            known = self._known_locked(file_key, scope, shape)  # a record thread that ended just before may have won
            if known is not None:
                due = self._count_repeat_locked(known, at)
                doc = self._doc_locked() if due else None
            else:
                st = self._files.get(file_key)
                if st is not None and not st["latched"] and (st.get("reread") or {}).get("result") == REREAD_CLEAN:
                    # The re-read of this very failed read came back clean and released the pause before a slow drive let the
                    # record be written: the incident is born answered, as the ones that existed then were.
                    record["superseded"] = True
                    record["answered_by"] = REREAD_CLEAN
                self._incidents.append(record)
                self._last_flush_mono = self._mono()  # this write IS the window's write: repeats wait for the next
                doc = self._doc_locked()
        if doc is not None:
            self._flush(doc)

    # -- the latch --------------------------------------------------------------------------------
    def latched(self, file_key: str) -> bool:
        """Whether ``file_key``'s writers are stopped. Cheap: a dict read under a lock nothing holds long."""
        if not switch_on():
            return False
        with self._lock:
            st = self._files.get(file_key)
            return bool(st and st["latched"])

    def corpus_latched(self) -> bool:
        return self.latched(FILE_CORPUS)

    def retry(
        self,
        *,
        reason: str,
        files: tuple[str, ...] | None = None,
        except_files: tuple[str, ...] = (),
        file_replaced: bool = False,
    ) -> list[str]:
        """The operator tries again: release the latch of ``files`` (every file's when ``None``) except
        ``except_files``. The record stays. Returns the files released. Never raises.

        A latch the per-table check set (``check_tables``: the tables it read as damaged) is NOT released here:
        the start RE-READS those tables (:func:`database.verify.recheck`, on its own thread) and the latch holds
        until every one reads clean (:meth:`recheck_finished`). It is released outright only when the file was
        REPLACED (``file_replaced``: a restore or a salvage swapped it, so the verdict is about a file that no
        longer is), when the check is switched off, or when the file is not there to be read. A re-check already
        running, or the start-up check still reading, keeps the latch and starts nothing."""
        released: list[str] = []
        recheck: dict[str, list[str]] = {}
        claims: dict[str, int] = {}
        try:
            self._ensure_loaded()
            with self._lock:
                for key, st in self._files.items():
                    if file_replaced and (files is None or key in files) and key not in except_files:
                        # What an automatic re-read learned was about the file that no longer is, latched now or not.
                        st.pop("auto_released", None)
                        st.pop("auto_stayed", None)
                        st.pop("reread", None)
                    if not (st["latched"] and (files is None or key in files) and key not in except_files):
                        continue
                    tables = st.get("check_tables")
                    if st.get("rechecking") and not tables and not file_replaced:
                        # The automatic re-read of a first failed read is running (it has not named its tables yet): its claim IS the
                        # pause, and it decides. A start does not release a latch whose answer is being read.
                        continue
                    if tables and not file_replaced:
                        if not st.get("rechecking"):
                            # Claimed here, under the lock: one re-read at a time. The claim carries a TOKEN (every
                            # method that settles it must present its own, so a second claim's state is never popped by
                            # the first read's ending) and the incident count it was made at (a failed read that
                            # lands while the re-read runs is not answered by the re-read's clean result).
                            self._claims += 1
                            st["rechecking"] = {"index": 0, "total": 0, "token": self._claims, "incidents": st["incidents"]}
                            claims[key] = self._claims
                            st["retries"] += 1
                            recheck[key] = list(tables)
                        continue
                    st["latched"] = False
                    st["retries"] += 1
                    st.pop("check_tables", None)
                    st.pop("rechecking", None)
                    st.pop("check_stopped_after", None)
                    st.pop("auto_stayed", None)
                    released.append(key)
            if recheck:
                released.extend(self._start_recheck(recheck, reason, claims))
            if released:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
                _LOG.warning(
                    "database damage: the %s file's writers are released (%s); the first failed read "
                    "pauses them again",
                    ", ".join(released),
                    reason,
                )
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("database damage: retry failed (%s)", type(exc).__name__)
        return released

    def _start_recheck(self, recheck: dict[str, list[str]], reason: str, claims: dict[str, int]) -> list[str]:
        """Hand the claimed re-reads to ``verify.recheck`` and settle the ones it did not take: a file with nothing to
        read (the check is switched off, the file is gone) is released as a plain retry would; any other refusal keeps
        the latch. Returns the files released."""
        try:
            from src.database import verify

            outcome = verify.recheck(recheck, reason=reason, claims=claims)
        except Exception as exc:  # noqa: BLE001 - a latch that cannot be re-read stays
            _LOG.warning("database damage: could not start the re-read of the reported tables (%s)", type(exc).__name__)
            outcome = {}
        with self._lock:
            return self._settle_unstarted(recheck, outcome, claims)

    def _settle_unstarted(self, recheck: dict[str, list[str]], outcome: dict[str, str], claims: dict[str, int]) -> list[str]:
        """The loop of :meth:`_start_recheck`, called with ``self._lock`` held. A function of its own because CPython 3.13 leaves a loop's back-edge
        outside the exception table of the ``with`` around it, so an interrupt delivered there would leave the lock owned (R163: the restore CLI
        reaches this through ``DamageRegistry.retry``). A function with no handler has nothing to skip."""
        released: list[str] = []
        for key in recheck:
            if outcome.get(key) == "started":
                continue
            st = self._files.get(key)
            if st is None:
                continue
            if self._claim_is(st, claims.get(key)):
                st.pop("rechecking", None)
            if outcome.get(key) == "nothing-to-read" and st["latched"]:
                st["latched"] = False
                st.pop("check_tables", None)
                st.pop("check_stopped_after", None)
                released.append(key)
        return released

    @staticmethod
    def _claim_is(st: dict[str, Any], token: int | None) -> bool:
        """Whether ``st`` carries a re-read claim and it is the one ``token`` names. A call with no token names no
        claim: one that matched whatever claim was there could settle a read it did not start."""
        rc = st.get("rechecking")
        return rc is not None and token is not None and rc.get("token") == token

    def recheck_total(self, file_key: str, total: int, token: int | None = None) -> None:
        """How many tables the re-read of ``file_key`` will read (the progress line's denominator)."""
        with self._lock:
            st = self._files.get(file_key)
            if st is not None and self._claim_is(st, token):
                st["rechecking"] = {**st["rechecking"], "index": 0, "total": int(total)}

    def recheck_progress(self, file_key: str, index: int, token: int | None = None) -> None:
        with self._lock:
            st = self._files.get(file_key)
            if st is not None and self._claim_is(st, token):
                st["rechecking"] = {**st["rechecking"], "index": int(index)}

    def recheck_abandoned(self, file_key: str, token: int | None = None) -> None:
        """The re-read of ``file_key`` ended without an answer (stopped, or it raised): the latch stays as it was.
        Idempotent, and always called when a re-read ends; it settles ONLY the claim it was started under."""
        with self._lock:
            st = self._files.get(file_key)
            if st is not None and self._claim_is(st, token):
                st.pop("rechecking", None)

    def reread_tables(self, file_key: str, tables: list[str], token: int | None = None) -> bool:
        """The automatic re-read of ``file_key`` has listed the file and found ``tables`` (the ones its statement names): store them as the
        latch's ``check_tables``, so the machinery of a per-table check (:meth:`recheck_finished`, the start's re-read) settles the latch,
        and set the progress line's denominator. ``False`` when the claim is no longer this read's (the latch was released or the file
        replaced meanwhile): the caller reads nothing. Under the lock, in one block."""
        with self._lock:
            st = self._files.get(file_key)
            if st is None or not st["latched"] or not self._claim_is(st, token) or not tables:
                return False
            st["check_tables"] = sorted(set(tables))
            st["rechecking"] = {**st["rechecking"], "index": 0, "total": len(tables)}
            return True

    def reread_ended(self, file_key: str, token: int | None, why: str, *, at: str | None = None) -> None:
        """The automatic re-read of ``file_key`` ended WITHOUT an answer (:func:`verify.reread` could not be made, the file could not be
        listed, no table of the file is named, a stop, a failure): the latch stays exactly as a first failed read left it, so the
        operator's start releases it, and the file's record says that no re-read was made and which of the fixed reasons ``why`` is.
        Settles only the claim it was made under. Never raises."""
        try:
            now = at or datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            with self._lock:
                st = self._files.get(file_key)
                if st is None or not self._claim_is(st, token):
                    return
                st.pop("rechecking", None)
                st.pop("check_tables", None)  # the table set was only the re-read's own; E1's latch has none
                st["reread"] = {"tables": [], "result": REREAD_NOT_MADE, "why": why, "at": now}
            self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("database damage: could not settle a re-read that ended (%s)", type(exc).__name__)

    def recheck_finished(
        self, file_key: str, tables: list[dict[str, Any]], *, path: Path | None, token: int | None = None
    ) -> bool:
        """The re-read of the tables the check reported ended with ``tables`` (one answer each). Merges the answers
        into the file's check record and decides the latch: it is released when no table is left that was reported
        damaged and has not since read clean (``ok``); a table that reads damaged again, or could not be read,
        keeps it, and a damaged one is recorded as an incident like the check's own finding. Returns whether the
        latch was released. Never raises."""
        try:
            from src.database.verify import SCHEMA_ENTRY, file_verdict

            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            ok_names = {t["table"] for t in tables if t.get("verdict") == VERDICT_OK}
            damaged = [t["table"] for t in tables if t.get("verdict") == VERDICT_DAMAGED]
            not_ok = {t["table"] for t in tables if t.get("verdict") != VERDICT_OK}
            released = False
            with self._lock:
                st = self._files.get(file_key)
                if st is None or not st["latched"] or not st.get("check_tables") or not self._claim_is(st, token):
                    # Released or replaced while it was read (a release ends the claim), or settled under another
                    # claim: the answer is about a file that no longer is, or is not this read's to give.
                    _LOG.info("database damage: a re-read's result for the %s file is stale and was dropped", file_key)
                    return False
                grew = int(st["incidents"]) > int(st["rechecking"].get("incidents") or 0)
                auto = bool(st["rechecking"].get("auto"))  # the re-read of a first failed read, not of a check's finding
                since = str(st["rechecking"].get("since") or "") or None
                st.pop("rechecking", None)
                reported = set(st["check_tables"])
                left_set = (reported - ok_names) | set(damaged)
                if SCHEMA_ENTRY in reported:
                    # The check could not list the tables, so it read none of them: this read read ALL of them, and a
                    # table that did not answer clean is left, damaged or not. Counting only the reported names (there
                    # is only the schema) let a table that answered "unchecked" (a busy file, no memory, an I/O error)
                    # release the latch, and nothing planned it again.
                    left_set |= not_ok
                left = sorted(left_set)
                held = self._verification.get(file_key)
                mine = held if held is not None and held.get("process") == self._process else None  # this process's own entry
                if mine is not None and isinstance(mine.get("tables"), list):
                    answered = {t["table"]: t for t in tables}
                    merged = []
                    for old_t in mine["tables"]:
                        new_t = answered.pop(old_t.get("table"), None)
                        # A read that could not happen is no answer: it never replaces a verdict of damage (the record is
                        # what the next start decides on, and a busy file or a stop must not make it forget the finding).
                        keep_old = new_t is None or (
                            new_t.get("verdict") == VERDICT_UNCHECKED and old_t.get("verdict") == VERDICT_DAMAGED
                        )
                        merged.append(old_t if keep_old else new_t)
                    mine["tables"] = merged + list(answered.values())
                    mine["verdict"] = file_verdict(mine["tables"])
                    mine["rechecked_at"] = at
                if left:
                    if auto and not damaged:
                        # No table read DAMAGED; one could not be read at all (a busy file, no memory, an I/O error). That is no
                        # finding about the file, so the latch is what a first failed read leaves, and the operator's start
                        # releases it the E1 way; a table set would make the start read it again and hold for ever on a read
                        # that never comes back.
                        st.pop("check_tables", None)
                    else:
                        st["check_tables"] = left
                        if mine is not None:
                            mine["earlier_damaged"] = list(left)  # what the next start reads again until it reads clean
                    if auto:
                        st["reread"] = {
                            "tables": sorted(reported),
                            "result": REREAD_DAMAGED if damaged else REREAD_UNREAD,
                            "at": at,
                        }
                else:
                    if mine is not None:
                        carried = sorted(set(mine.get("earlier_damaged") or ()) - ok_names)
                        if carried:
                            mine["earlier_damaged"] = carried  # an automatic re-read of one table forgets no other finding
                        else:
                            mine.pop("earlier_damaged", None)
                    st.pop("check_stopped_after", None)
                    if grew:
                        # A read FAILED while this re-read ran (E1's observer counted it). A clean answer about the
                        # reported tables says nothing about that one, so the latch holds and stops being a check's:
                        # the next start releases it the E1 way, and the first failed read after that pauses it again.
                        st.pop("check_tables", None)
                        if auto:
                            st["reread"] = {"tables": sorted(reported), "result": REREAD_CLEAN_HELD, "at": at}
                    else:
                        st["latched"] = False
                        st.pop("check_tables", None)
                        # The reported tables read clean: the earlier errors are answered (an automatic re-read answers only the failed
                        # read it was made for, and the ones after it).
                        self._supersede_incidents_locked(file_key, since=since if auto else None, by=REREAD_CLEAN if auto else None)
                        released = True
                        if auto:
                            # A table that reads clean and then fails again is not read a second time (:meth:`_claim_reread_locked`).
                            st["auto_released"] = sorted({n.lower() for n in reported} | set(st.get("auto_released") or ()))
                            st["reread"] = {"tables": sorted(reported), "result": REREAD_CLEAN, "at": at}
            if damaged:
                self._note_verified_damage(file_key, damaged, path=path, at=at)
            self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)  # the merged answers are part of the record
            if released:
                _LOG.warning(
                    "database damage: the %s file's reported tables read clean again; its writers are released "
                    "(the first failed read pauses them again)",
                    file_key,
                )
            return released
        except Exception as exc:  # noqa: BLE001 - a re-read's bookkeeping must never raise; the latch stays
            _LOG.debug("database damage: could not store a re-read's result (%s)", type(exc).__name__)
            return False

    # -- the per-table check (database/verify.py) --------------------------------------------------
    def verifying(self) -> bool:
        """Whether a check of the data files is armed or running: collection waits for it (the storage guard's
        ``"verifying"`` kind). It follows the pause's switch, so ``OO_DAMAGE_GUARD=0`` means writing carries on."""
        if not switch_on():
            return False
        with self._lock:
            return self._verifying is not None

    def writes_paused(self, file_key: str) -> bool:
        """The writers of ``file_key`` wait: its latch is set, or a check of the data files is armed or running."""
        return self.latched(file_key) or self.verifying()

    def verification_arm(self, trigger: str) -> None:
        """A check is going to run: from this call until :meth:`verification_end` collection waits, so an
        operator who goes online in the seconds before the check starts does not slip a pass in first."""
        with self._lock:
            self._verifying = {
                "state": "pending", "trigger": trigger, "since": self._clock(),
                "index": 0, "total": 0, "file": None, "table": None,
            }

    def verification_begin(self, total_tables: int) -> None:
        with self._lock:
            if self._verifying is not None:
                self._verifying.update(state="running", total=int(total_tables))

    def verification_progress(self, file_key: str, table: str | None, index: int) -> None:
        with self._lock:
            if self._verifying is not None:
                self._verifying.update(file=file_key, table=table, index=int(index))

    def verification_end(self) -> None:
        with self._lock:
            self._verifying = None

    def previous_verification(self, file_key: str) -> dict[str, Any] | None:
        """What an EARLIER process recorded about its check of ``file_key`` (``None`` when there is none, or
        when the newest entry is this process's own): the boot decision asks whether a check was left
        unfinished. ONE exception: this process's own ``owed`` entry. A boot that starts LOCKED writes it over
        the earlier process's entry (``verification_file_owed`` carries that entry's attempts and trigger), and the
        unlock, in the same process, plans from it: reading it as "nothing recorded" erased an earlier damaged
        verdict and an unfinished check, and the attempt cap never tripped (the deep delta read's B1)."""
        self._ensure_loaded()
        with self._lock:
            entry = self._verification.get(file_key)
            if entry is None or (entry.get("process") == self._process and entry.get("state") != "owed"):
                return None
            out = dict(entry)
            out["own"] = entry.get("process") == self._process  # this process's own ``owed`` entry (a locked boot)
            return out

    def checked_by_this_process(self, file_key: str) -> bool:
        """Whether THIS process already ran (or deliberately skipped) the check of ``file_key``: the start-up upkeep
        can run more than once in a process (an unlock after a locked boot), and a file is read once."""
        with self._lock:
            entry = self._verification.get(file_key)
            return entry is not None and entry.get("process") == self._process and entry.get("state") in ("done", "skipped")

    def verification_file_started(self, file_key: str, *, path: Path | None, trigger: str, tables_total: int, attempts: int) -> None:
        """Record that the check of ``file_key`` has begun, BEFORE its first table is read: a process that is
        killed mid-check leaves ``state: running`` behind, which is how the next start knows."""
        self._ensure_loaded()
        at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
        with self._lock:
            entry: dict[str, Any] = {
                "file": file_key,
                "file_name": path.name if path is not None else None,
                "process": self._process,
                "session_id": _current_session_id(),
                "trigger": trigger,
                "state": "running",
                "attempts": int(attempts),
                "started_at": at,
                "tables_total": int(tables_total),
            }
            carried = carried_damage(self._verification.get(file_key))
            if carried:
                entry["earlier_damaged"] = carried  # a record that replaces an earlier finding keeps it until a read clears it
            self._verification[file_key] = entry
        self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)

    def verification_file_owed(self, file_key: str, *, path: Path | None, trigger: str, attempts: int) -> None:
        """Record that the check of ``file_key`` is DUE and has not begun (``state: owed``). The next start reads it as an
        unfinished check, so a session that ended before it began does not cancel it. ``attempts`` is carried over,
        not counted: only a check that begins counts toward :data:`MAX_VERIFY_ATTEMPTS`. A file this process has
        already begun, finished or skipped is left as it is."""
        self._ensure_loaded()
        at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
        with self._lock:
            cur = self._verification.get(file_key)
            if cur is not None and cur.get("process") == self._process and cur.get("state") in ("running", "done", "skipped"):
                return
            entry: dict[str, Any] = {
                "file": file_key,
                "file_name": path.name if path is not None else None,
                "process": self._process,
                "session_id": _current_session_id(),
                "trigger": trigger,
                "state": "owed",
                "attempts": int(attempts),
                "owed_at": at,
            }
            carried = carried_damage(cur)
            if carried:
                entry["earlier_damaged"] = carried
            self._verification[file_key] = entry
        self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)

    def verification_forget(self, file_key: str) -> None:
        """Drop what was recorded about the check of ``file_key``: the file was REPLACED (a restore), so an earlier
        verdict is about a file that no longer is, and must not make the next start read the new one for it. Never
        raises."""
        try:
            self._ensure_loaded()
            with self._lock:
                gone = self._verification.pop(file_key, None)
                superseded = self._supersede_incidents_locked(file_key)  # they were about a file that no longer is
            if gone is not None or superseded:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("database damage: could not forget a check's record (%s)", type(exc).__name__)

    def verification_file_stopped(self, file_key: str) -> None:
        """The check of ``file_key`` was interrupted by a stop (the app is shutting down). The entry stays ``running`` so
        the next start reads the file again, but the attempt is given back: a quit is not a failure of the check, and
        quitting three times during it must not skip it. Never raises."""
        try:
            with self._lock:
                entry = self._verification.get(file_key)
                if entry is None or entry.get("process") != self._process or entry.get("state") != "running":
                    return
                entry["attempts"] = max(0, int(entry.get("attempts") or 1) - 1)
            self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("database damage: could not give an attempt back (%s)", type(exc).__name__)

    def verification_file_skipped(
        self, file_key: str, *, path: Path | None, attempts: int, reason: str, earlier_damaged: list[str] | None = None
    ) -> None:
        """Say that the check of ``file_key`` was NOT run (an earlier check was left unfinished on every one of
        the last ``MAX_VERIFY_ATTEMPTS`` starts): the next unexpected stop starts the count again. An earlier
        finding is carried (``earlier_damaged`` when the caller names it, else the entry this replaces): skipping
        a check never forgets what an earlier one found."""
        self._ensure_loaded()
        at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
        with self._lock:
            entry: dict[str, Any] = {
                "file": file_key,
                "file_name": path.name if path is not None else None,
                "process": self._process,
                "session_id": _current_session_id(),
                "state": "skipped",
                "verdict": VERDICT_UNCHECKED,
                "reason": reason,
                "attempts": int(attempts),
                "finished_at": at,
            }
            carried = list(earlier_damaged) if earlier_damaged is not None else carried_damage(self._verification.get(file_key))
            if carried:
                entry["earlier_damaged"] = carried
            self._verification[file_key] = entry
        self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)

    def verification_file_held(
        self, file_key: str, *, path: Path | None, attempts: int, reason: str, tables: list[str]
    ) -> None:
        """The check of ``file_key`` is NOT run (it was left unfinished on every one of the last
        ``MAX_VERIFY_ATTEMPTS`` starts, or the file could not be examined) while an earlier check's finding stands for
        it: the skip is recorded WITH the finding, and the file is LATCHED from it (``tables`` are the tables that
        check reported and no read has cleared). The cap stops the check from being re-run; it must never be what
        lets collection write into a file known to be damaged. The latch is released the way a check's latch is: when
        a re-read of those tables comes back clean (a start of collection asks for it), or the file is replaced.
        Never raises."""
        try:
            self.verification_file_skipped(file_key, path=path, attempts=attempts, reason=reason, earlier_damaged=list(tables))
            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            self._note_verified_damage(
                file_key, [], path=path, at=at, carried=list(tables),
                stopped_after=int(attempts) if attempts >= MAX_VERIFY_ATTEMPTS else None,
            )
        except Exception as exc:  # noqa: BLE001 - a check's bookkeeping must never take the boot down
            _LOG.debug("database damage: could not hold a file on an earlier finding (%s)", type(exc).__name__)

    def verification_file_done(self, file_key: str, result: dict[str, Any], *, path: Path | None = None) -> None:
        """Store the finished check of ``file_key`` and, when a table was read as damaged, latch the file the same
        way a corruption error does (:meth:`_apply_incident`). Never raises."""
        try:
            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            tables = list(result.get("tables", []))
            damaged = [t["table"] for t in tables if t.get("verdict") == VERDICT_DAMAGED]
            with self._lock:
                held = self._verification.get(file_key)
                if held is None or held.get("process") != self._process or held.get("state") != "running":
                    # Not a check this process began and still holds: the file was REPLACED while it was read
                    # (``verification_forget``), so this verdict is about a file that no longer is.
                    _LOG.info("database damage: a check's result for the %s file is stale and was dropped", file_key)
                    return
                # What an earlier check reported and THIS answer does not clear (a read that could not happen is no
                # clean read): it is carried, and it latches the file below, so an answer of "unchecked" never
                # releases a finding an earlier process measured.
                carry = self._carry_after(
                    set(held.get("earlier_damaged") or ()), tables, listed=bool(result.get("listed", True)), damaged=set(damaged)
                )
                entry = dict(held)
                entry.pop("earlier_damaged", None)
                entry.update(result)
                entry.update(file=file_key, process=self._process, state="done", finished_at=at, attempts=0)
                if carry:
                    entry["earlier_damaged"] = carry
                self._verification[file_key] = entry
            if damaged or carry:
                self._note_verified_damage(file_key, damaged, path=path, at=at, carried=carry)
            else:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
        except Exception as exc:  # noqa: BLE001 - a check's bookkeeping must never take the boot down
            _LOG.debug("database damage: could not store a check's result (%s)", type(exc).__name__)

    @staticmethod
    def _carry_after(earlier: set[str], tables: list[dict[str, Any]], *, listed: bool, damaged: set[str]) -> list[str]:
        """The tables an EARLIER check reported as damaged that this answer neither clears nor reports itself. A table
        clears only by reading ``ok``; a table that is no longer in the file has nothing in it to be damaged; a
        ``(schema)`` in the set means no table was read, so when the list reads now every table that does not answer
        ``ok`` is left; and when the list itself could not be read nothing is cleared."""
        if not earlier:
            return []
        from src.database.verify import PAGES_ENTRY, SCHEMA_ENTRY

        if not listed:
            left = set(earlier)
        else:
            everything = SCHEMA_ENTRY in earlier
            left = {t["table"] for t in tables if t.get("verdict") != VERDICT_OK and (everything or t["table"] in earlier)}
            if PAGES_ENTRY in earlier and not any(t.get("table") == PAGES_ENTRY and t.get("verdict") == VERDICT_OK for t in tables):
                # ``(pages)`` is no table of the list, so "no longer in the file" cannot clear it: only the page pass
                # reading ``ok`` does, and an answer that did not include the pass leaves the finding where it was.
                left.add(PAGES_ENTRY)
        return sorted(left - damaged)

    def _note_verified_damage(
        self,
        file_key: str,
        tables: list[str],
        *,
        path: Path | None,
        at: str,
        carried: list[str] | tuple[str, ...] = (),
        stopped_after: int | None = None,
    ) -> None:
        """A table the per-table check read as damaged: latch the file and record one incident. The scope is
        ``search-index`` only when EVERY damaged table is the full-text index's (its shadow tables), else
        ``data``; the names are schema names, never row values. ``carried`` are tables an EARLIER check reported
        that this check could not read again: they latch the file too (and are what a re-read must clear), whether
        or not this check found damage of its own."""
        names = sorted(set(tables))
        all_names = sorted(set(tables) | set(carried))
        index_only = all(_SHADOW_TABLE.fullmatch(t) for t in all_names)
        scope = SCOPE_SEARCH_INDEX if index_only else SCOPE_DATA
        shown = ", ".join(all_names[:6]) + (" and more" if len(all_names) > 6 else "")
        if names:
            basis = (
                "the per-table check found damage only in the tables of the search index: " + shown
                if index_only
                else "the per-table check found damage in: " + shown
            )
            if carried:
                basis += " (part of it reported by an earlier check and not read clean since)"
        else:
            basis = (
                "an earlier per-table check found damage only in the tables of the search index: " + shown
                if index_only
                else "an earlier per-table check found damage in: " + shown
            ) + "; it has not read clean since"
        from src.database.verify import PAGES_ENTRY

        named = [n for n in all_names if n != PAGES_ENTRY]
        shape = "; ".join(
            ([f"PRAGMA quick_check({', '.join(named[:6])})"] if named else [])
            + (["PRAGMA cipher_integrity_check"] if PAGES_ENTRY in all_names else [])
        )
        newly, known, due, _claim = self._apply_incident(
            file_key, scope, shape, at, check_tables=tuple(all_names), stopped_after=stopped_after
        )
        if newly:
            _log_latched(file_key, "SQLITE_CORRUPT", scope, shape)
        if known is not None:
            if due:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
            return
        found = {"code": SQLITE_CORRUPT, "name": "SQLITE_CORRUPT", "message": "the per-table check reported damage"}
        thread_name = scrubbed_name(threading.current_thread().name) or ""
        self._single_flight(
            ("record", file_key, scope, shape),
            lambda: self._record_new(
                file_key, found, shape, scope, basis, at, path,
                thread_name=thread_name, endpoint=None,
                extra={
                    "found_by": "per-table check" if names else "an earlier per-table check (carried over)",
                    "tables": all_names[:20],
                },
            ),
        )

    # -- the repair of a damaged file (database/repair.py) ----------------------------------------
    def confirmed_damage(self, file_key: str) -> dict[str, Any] | None:
        """What THIS process's start-up check confirmed about ``file_key``: ``{"tables": [the names read as damaged],
        "file_name", "pages_unread"}``, or ``None`` when it did not (no check ran, it read clean, it was left unfinished, or the finding
        is an earlier process's, carried over: a repair acts only on a verdict this process measured)."""
        self._ensure_loaded()
        with self._lock:
            entry = self._verification.get(file_key)
            if (
                entry is None
                or entry.get("process") != self._process
                or entry.get("state") != "done"
                or entry.get("verdict") != VERDICT_DAMAGED
            ):
                return None
            tables = _table_records(entry)
            return {
                "tables": _damaged_table_names(tables),
                "file_name": entry.get("file_name"),
                # Pages the DRIVE could not read during the check (the page pass counts them apart from damage): a drive that failed to
                # read the file once is a drive to look at, and a copy the repair keeps is never removed on the strength of a file
                # the disk itself could not give (``repair.sweep_kept_copies``).
                "pages_unread": sum(int(t.get("pages_unread") or 0) for t in tables),
            }

    def repair_upsert(self, rec_id: str, **fields: Any) -> None:
        """Create or update one repair attempt of the record (``fields`` are counts, names, times and a reason code:
        never a value, a path or an engine message). Never raises."""
        try:
            self._ensure_loaded()
            with self._lock:
                for rec in self._repairs:
                    if rec.get("id") == rec_id:
                        rec.update(fields)
                        break
                else:
                    self._repairs.append({"id": rec_id, "process": self._process, **fields})
            self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
        except Exception as exc:  # noqa: BLE001 - a record that cannot be kept must never stop a repair
            _LOG.debug("database damage: could not record a repair attempt (%s)", type(exc).__name__)

    def repairs(self) -> list[dict[str, Any]]:
        """The attempts, oldest first (copies)."""
        self._ensure_loaded()
        with self._lock:
            return [dict(r) for r in self._repairs]

    def repairing_now(self) -> bool:
        """Whether a repair of THIS process is running. An earlier process's ``running`` record is not: a repair that a crash, a
        power cut or a stop ended leaves its record ``running`` for good, and counting it would hold every later removal for ever
        (:meth:`settle_interrupted_repairs` marks those)."""
        with self._lock:
            return any(r.get("process") == self._process and r.get("state") == "running" for r in self._repairs)

    def settle_interrupted_repairs(self) -> int:
        """Mark the repair records an EARLIER process left ``running`` as ``interrupted``: that process is not running them. Returns
        how many. Never raises."""
        try:
            self._ensure_loaded()
            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            changed = 0
            with self._lock:
                for rec in self._repairs:
                    if rec.get("state") == "running" and rec.get("process") != self._process:
                        rec.update(state="interrupted", finished_at=at)
                        changed += 1
            if changed:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
            return changed
        except Exception as exc:  # noqa: BLE001 - bookkeeping must never stop a start
            _LOG.debug("database damage: could not settle an interrupted repair (%s)", type(exc).__name__)
            return 0

    def latch_is_set(self, file_key: str) -> bool:
        """Whether ``file_key`` is latched damaged, WHATEVER the pause's switch says. ``latched`` answers ``False`` under
        ``OO_DAMAGE_GUARD=0`` because that switch turns the PAUSE off; a removal of a kept file that waits for "the library is
        damaged again" must not stop waiting because someone switched the pause off."""
        with self._lock:
            st = self._files.get(file_key)
            return bool(st and st["latched"])

    def check_is_running(self) -> bool:
        """Whether a check of the data files is armed or running, whatever the pause's switch says (see :meth:`latch_is_set`)."""
        with self._lock:
            return self._verifying is not None

    def _supersede_incidents_locked(self, file_key: str, *, since: str | None = None, by: str | None = None) -> bool:
        """Mark the recorded corruption errors of ``file_key`` as answered (the file was replaced, or the tables a check reported read
        clean again): they stop being a reason to check at the next start. Caller holds the lock; whether any changed. ``since`` (the
        time of the failed read an automatic re-read answered) answers only the incidents that began then or later: a clean read of
        ONE table says nothing about an earlier error an operator's start released unread. ``by`` says what answered them (the
        record of the re-read lives with the file's state, which the next process's first write does not carry; the incident does)."""
        changed = False
        for inc in self._incidents:
            if inc.get("file") != file_key or inc.get("superseded"):
                continue
            if since is not None and str(inc.get("at") or "") < since:
                continue
            inc["superseded"] = True
            if by:
                inc["answered_by"] = by
            changed = True
        return changed

    def incident_after_last_check(self, file_key: str) -> bool:
        """Whether an EARLIER process recorded a corruption error against ``file_key`` that no check finished since: damage found
        while the app ran is a reason to read the file at the next start, which an ordinary quit would otherwise forget (the latch
        lives in memory and the ledger reads a clean end). ``False`` once a later check has finished; a check that read the file
        damaged is carried by :func:`carried_damage`, not here."""
        self._ensure_loaded()
        with self._lock:
            entry = self._verification.get(file_key)
            done_at = str(entry.get("finished_at") or "") if entry is not None and entry.get("state") == "done" else ""
            for inc in self._incidents:
                if inc.get("file") != file_key or inc.get("process") == self._process or inc.get("superseded"):
                    continue
                if str(inc.get("last_at") or inc.get("at") or "") <= done_at:
                    continue  # a loop ends in a guard clause, not a bare ``if``: that shape leaves its back-edge outside the ``with`` on CPython 3.13 (R163)
                return True
        return False

    def _repair_notes_locked(self, corpus_latched: bool) -> list[dict[str, Any]]:
        """The sentences about the repair. Caller holds the lock. This process's newest attempt says what it did; a
        repaired file says where the damaged one is kept for as long as it is there; a latched corpus with no attempt of
        this process says the repair happens at the next start."""
        out: list[dict[str, Any]] = []
        mine = [r for r in self._repairs if r.get("process") == self._process]
        newest = mine[-1] if mine else None
        if newest is not None:
            state, reason = newest.get("state"), newest.get("reason")
            if state == "running":
                out.append({"kind": "repair", "file": FILE_CORPUS, "frame": FRAME_REPAIRING, "vars": {}})
            elif state == "refused" or state == "failed":
                frame = {
                    "no-room": FRAME_REPAIR_NO_ROOM,
                    "schema-unreadable": FRAME_REPAIR_NO_SCHEMA,
                    "no-hard-links": FRAME_REPAIR_NO_LINKS,
                    "writer-busy": FRAME_REPAIR_BUSY,
                    "unfinished-starts": FRAME_REPAIR_UNFINISHED,
                    "write-gate-off": FRAME_REPAIR_NO_GATE,
                    "copy-stale": FRAME_REPAIR_WRITTEN,
                    "saved-during-the-copy": FRAME_REPAIR_WRITTEN,
                }.get(str(reason), FRAME_REPAIR_FAILED)
                values: dict[str, Any] = {}
                if frame == FRAME_REPAIR_NO_ROOM:
                    values = {"free": int(newest.get("free_mb") or 0), "needed": int(newest.get("needed_mb") or 0)}
                if corpus_latched:
                    out.append({"kind": "repair", "file": FILE_CORPUS, "frame": frame, "vars": values})
        elif corpus_latched and repair_switch_on() and _check_switch_on():
            # Said only while the start-up check can run: with ``OO_BOOT_VERIFY=0`` no check confirms anything at the next start and
            # nothing is repaired, so a promise of a repair there would be one the app does not keep (the deep read of E3).
            out.append({"kind": "repair", "file": FILE_CORPUS, "frame": FRAME_REPAIR_NEXT_START, "vars": {}})
        done = [r for r in self._repairs if r.get("state") == "done" and r.get("kept_file")]
        if done:
            last = done[-1]
            what = {
                "kept": int(last.get("kept_rows") or 0),
                "lost": int(last.get("unreadable_ids") or 0),
            }
            kept = _kept_file_of(last)
            removed_at = last.get("kept_file_removed_at") if _within_days(last.get("kept_file_removed_at"), KEPT_COPY_DAYS) else None
            if kept is not None or removed_at:
                out.append(
                    {
                        "kind": "repaired",
                        "file": FILE_CORPUS,
                        "frame": FRAME_REPAIRED_OPEN if last.get("open_ended") else FRAME_REPAIRED,
                        "vars": what,
                    }
                )
                out.extend(_orphan_notes(last))
            name = str(last["kept_file"])
            if removed_at:
                out.append(
                    {
                        "kind": "repaired",
                        "file": FILE_CORPUS,
                        "frame": FRAME_KEPT_REMOVED,
                        "vars": {"name": name, "size": _bytes_words(last.get("kept_file_removed_bytes")), "date": str(removed_at)[:10]},
                    }
                )
            elif kept is not None:
                where = {"name": name, "size": _size_words(kept), "folder": str(kept.parent)}
                if last.get("kept_file_removal_withheld"):
                    out.append(
                        {
                            "kind": "repaired",
                            "file": FILE_CORPUS,
                            "frame": FRAME_KEPT_DISK,
                            "vars": {**where, "pages": int(last.get("kept_file_disk_unread_pages") or 0)},
                        }
                    )
                elif last.get("kept_file_removal_refused"):
                    out.append({"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_KEPT_NOT_REMOVED, "vars": where})
                elif not repair_switch_on():
                    # The sweep is off with the repair (``OO_BOOT_REPAIR=0``): a date promised here would never come.
                    out.append({"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_KEPT_SWITCH, "vars": where})
                elif last.get("kept_file_removal_after"):
                    out.append(
                        {
                            "kind": "repaired",
                            "file": FILE_CORPUS,
                            "frame": FRAME_KEPT_UNTIL,
                            "vars": {**where, "date": str(last["kept_file_removal_after"])[:10]},
                        }
                    )
                else:
                    # No date was set (``kept_file_removal_undated``: the drive's reading of that file was never measured), so the sweep never
                    # removes it: said, because R129's promise of a removal after 30 days would otherwise lapse without a word while a second
                    # full copy of the library stays on the drive (the coordinator's check of E3 fold 3, item 5).
                    out.append({"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_KEPT_UNDATED, "vars": where})
        return out

    # -- what a surface shows -------------------------------------------------------------------
    def notes(self) -> list[dict[str, Any]]:
        """The sentences to show, one per latched file, as frames the page translates: ``{kind, file,
        frame, vars}``. No numbers: a size would be a claim about a file this module did not read. With
        the pause switched off (``OO_DAMAGE_GUARD=0``) the damage is still NAMED, and the frame says the
        pause is off, so a silent switch never reads as a healthy file."""
        on = switch_on()
        out: list[dict[str, Any]] = []
        with self._lock:
            ver = self._verifying
            if on and ver is not None and ver.get("state") == "running" and int(ver.get("total") or 0) > 0:
                # Said while it runs, with its own numbers: how far through the tables the check is.
                out.append(
                    {
                        "kind": "verifying",
                        "file": ver.get("file"),
                        "frame": FRAME_VERIFYING,
                        "vars": {"index": int(ver.get("index") or 0), "total": int(ver.get("total") or 0)},
                    }
                )
            for key, st in self._files.items():
                if not st["latched"]:
                    continue
                rc = st.get("rechecking")
                if on and rc and rc.get("auto"):
                    # The re-read of a first failed read, from the moment the latch is set: a provisional pause, said as one and
                    # ONLY as one (the damage sentence beside it would say a start tries again, which a start during the re-read
                    # does not, and the repair note that the file is damaged, which is not known yet).
                    out.append({"kind": "verifying", "file": key, "frame": FRAME_REREADING, "vars": {}})
                    continue
                if on and rc and int(rc.get("total") or 0) > 0:
                    out.append(
                        {
                            "kind": "verifying",
                            "file": key,
                            "frame": FRAME_RECHECKING,
                            "vars": {"index": int(rc.get("index") or 0), "total": int(rc.get("total") or 0)},
                        }
                    )
                if not on:
                    frame = FRAME_PAUSE_OFF
                elif key == FILE_CORPUS:
                    frame = FRAME_SEARCH_INDEX if st.get("scope") == SCOPE_SEARCH_INDEX else FRAME_DATA
                elif key == FILE_WIKI:
                    frame = FRAME_WIKI
                elif key == FILE_LAW:
                    frame = FRAME_LAW
                else:
                    frame = FRAME_RECORDED  # a file with no writer this module pauses: said, not paused
                out.append({"kind": "damage", "file": key, "frame": frame, "vars": {}})
                if on and st.get("auto_stayed"):
                    # Said beside the damage sentence: why this pause was not read again by itself, and what a start does.
                    out.append({"kind": "damage", "file": key, "frame": FRAME_STAYED, "vars": {}})
                if not (on and st.get("check_stopped_after")):
                    continue  # a guard clause, not a bare ``if`` ending the loop (R163; see incident_after_last_check)
                out.append(
                    {
                        "kind": "damage",
                        "file": key,
                        "frame": FRAME_CHECK_STOPPED,
                        "vars": {"tries": int(st["check_stopped_after"])},
                    }
                )
            corpus = self._files.get(FILE_CORPUS)
            provisional = bool(corpus and (corpus.get("rechecking") or {}).get("auto"))
            out.extend(self._repair_notes_locked(bool(on and corpus and corpus["latched"] and not provisional)))
        return out

    def state(self, *, detail: bool = False) -> dict[str, Any]:
        """The honest state: which files are latched, the counts, and the newest incident. ``detail``
        adds the whole record (the diagnostics route's reading; the polled status carries the brief)."""
        self._ensure_loaded()
        with self._lock:
            files = {k: dict(v) for k, v in self._files.items()}
            incidents = list(self._incidents)
            write_error = self._write_error
            prior_unreadable = self._prior_unreadable
            verifying = dict(self._verifying) if self._verifying is not None else None
            verification = {k: dict(v) for k, v in self._verification.items()}
            repairs = [dict(r) for r in self._repairs]
        # ``latched`` is the files whose writers are paused; a file with no writer to pause is NAMED
        # (``recorded_only``, and a note) and nothing waits on it.
        latched = sorted(k for k, v in files.items() if v["latched"] and k in PAUSED_FILES) if switch_on() else []
        recorded_only = sorted(k for k, v in files.items() if v["latched"] and k not in PAUSED_FILES)
        out: dict[str, Any] = {
            "enabled": switch_on(),
            "latched": latched,
            "recorded_only": recorded_only,
            "files": files,
            "incident_count": sum(int(v.get("incidents") or 0) for v in files.values()),
            "last_incident": incidents[-1] if incidents else None,
            "notes": self.notes(),
            "write_error": write_error,
            "prior_record_unreadable": prior_unreadable,
            "record_file": RECORD_FILE,
            "verifying": verifying,
            "verification": verification if detail else {k: _verification_brief(v) for k, v in verification.items()},
            "repairs": repairs if detail else [_repair_brief(r) for r in repairs],
        }
        if detail:
            out["incidents"] = incidents
            out["method"] = METHOD
        return out


def carried_damage(entry: dict[str, Any] | None) -> list[str] | None:
    """The tables an earlier check reported as damaged that nothing has read clean since, from its record: the names a
    finished check read as damaged (``(schema)`` when the record has no table to name) together with the ones a record
    carried through a later skipped, owed or unchecked entry (``earlier_damaged``). ``None`` when there are none."""
    if not entry:
        return None
    from src.database.verify import SCHEMA_ENTRY

    names = {str(n) for n in (entry.get("earlier_damaged") or ())}
    if entry.get("state") == "done" and entry.get("verdict") == VERDICT_DAMAGED:
        read = [t["table"] for t in entry.get("tables") or [] if isinstance(t, dict) and t.get("verdict") == VERDICT_DAMAGED]
        names |= set(read) or {SCHEMA_ENTRY}
    return sorted(names) or None


def fsync_folder(folder: Path) -> None:
    """Make a folder's entries (a rename, a link, an unlink) durable. A platform that cannot open a folder (Windows) has nothing to call."""
    flags = getattr(os, "O_RDONLY", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(folder, flags)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def repair_switch_on() -> bool:
    """``OO_BOOT_REPAIR=0`` turns the repair of a damaged data file off (the file stays paused and named, and nothing is
    copied). Its own switch, never the damage pause's or the check's."""
    return os.getenv("OO_BOOT_REPAIR", "1") != "0"


def _table_words(value: Any) -> str:
    """Table names for a sentence: the keys of a record's dict, or its list, sorted and joined (they are the app's own table names)."""
    names = sorted(str(k) for k in (value.keys() if isinstance(value, dict) else value or ()))
    return ", ".join(names)


def _orphan_notes(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """The sentences about rows whose parent row could not be read (the salvage keeps every one; the deep read of E3, NEW-4): how many were
    kept and in which tables, the tables among them that hold a verdict this install measured, the stand-in rows that stop a new row
    from taking a lost row's number, and the tables where that stand-in could not be written."""
    out: list[dict[str, Any]] = []
    orphans = rec.get("orphans")
    if isinstance(orphans, dict) and orphans:
        count = sum(int(n) for n in orphans.values() if isinstance(n, int))
        out.append({"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_REPAIRED_ORPHANS, "vars": {"count": count, "tables": _table_words(orphans)}})
        if rec.get("orphans_verdict_tables"):
            out.append(
                {"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_REPAIRED_ORPHAN_VERDICTS,
                 "vars": {"tables": _table_words(rec["orphans_verdict_tables"])}}
            )
    if rec.get("stand_ins"):
        out.append({"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_REPAIRED_STAND_INS, "vars": {"tables": _table_words(rec["stand_ins"])}})
    if rec.get("id_reuse_possible"):
        out.append(
            {"kind": "repaired", "file": FILE_CORPUS, "frame": FRAME_REPAIRED_ID_REUSE, "vars": {"tables": _table_words(rec["id_reuse_possible"])}}
        )
    return out


def _check_switch_on() -> bool:
    """Whether the start-up check runs (``OO_BOOT_VERIFY``, read by ``verify.switch_on``)."""
    from src.database import verify

    return verify.switch_on()


def _kept_file_of(rec: dict[str, Any]) -> Path | None:
    """The damaged file a finished repair kept, when it is still where it was put (a stat; ``None`` once it is gone)."""
    try:
        name = rec.get("kept_file")
        if not name:
            return None
        base = Path(str(rec.get("folder") or ""))
        path = base / str(name)
        return path if path.is_file() else None
    except OSError:
        return None


def _within_days(when: Any, days: int) -> bool:
    """Whether the ISO time ``when`` is less than ``days`` days before now (or later than now). ``False`` for anything that is not a time."""
    try:
        then = datetime.fromisoformat(str(when))
    except (TypeError, ValueError):
        return False
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return datetime.now(UTC) - then < timedelta(days=days)


def _size_words(path: Path) -> str:
    """A file's size in SI units for a sentence (``12.4 GB``)."""
    try:
        return _bytes_words(path.stat().st_size)
    except OSError:
        return "?"


def _bytes_words(size: Any) -> str:
    """A number of bytes in SI units for a sentence (``12.4 GB``); ``?`` when it is not a number."""
    try:
        n = float(size)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000.0
    return f"{n:.1f} TB"


def _repair_brief(rec: dict[str, Any]) -> dict[str, Any]:
    """A repair attempt without its per-table lines (the polled status carries this; the bundle carries all)."""
    return {k: v for k, v in rec.items() if k != "tables"}


def _verification_brief(entry: dict[str, Any]) -> dict[str, Any]:
    """A check's result without its per-table list (the polled status carries this; the bundle carries all)."""
    tables = entry.get("tables") or []
    return {
        **{k: v for k, v in entry.items() if k != "tables"},
        "damaged": [t["table"] for t in tables if t.get("verdict") == VERDICT_DAMAGED],
        "unchecked": [t["table"] for t in tables if t.get("verdict") == VERDICT_UNCHECKED],
    }


def diagnostics_member(max_bytes: int) -> dict[str, Any]:
    """The damage record as one diagnostics-bundle member (the slot contract of the single Diagnostics
    zip: ``(max_bytes) -> dict``, never raises, keeps the newest, names the cut).

    The whole record is :meth:`DamageRegistry.state` with detail (counts, times, sizes, the code, the
    statement's shape and the route: no value, no passphrase). When it does not fit, the OLDEST
    incidents go first and the member says how many; the per-file counters and the newest incident
    always stay, because they are what a reader needs first."""
    try:
        budget = max(1024, int(max_bytes))
        out = registry.state(detail=True)
        incidents = list(out.get("incidents") or [])
        total = len(incidents)

        def _size() -> int:
            return len(json.dumps(out, separators=(",", ":"), default=str))

        while incidents and _size() > budget:
            incidents.pop(0)
            out["incidents"] = incidents
        out["incidents"] = incidents
        out["dropped_oldest_to_fit"] = total - len(incidents)
        if _size() > budget:
            # Still over once only the newest incident is left: the per-table lists of the checks go next (the
            # verdict, the damaged and the unchecked names stay), and the member says it did so.
            out["verification"] = {k: _verification_brief(v) for k, v in (out.get("verification") or {}).items()}
            out["verification_tables_dropped_to_fit"] = True
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        return {"error": failure_label(exc)}  # the class only: the member rides the bundle, and what an exception says can be an engine's words


#: The plain sentences. Frames the page translates (each is also a locale key, x12). The damage sentences say
#: nothing of a repair: the repair has its own (the ``FRAME_REPAIR*`` ones below), said only when it is what is
#: happening. None says what is still intact either: a damage sentence comes from an error, and what the per-table
#: check read is in the record, not in the sentence. They say what is true. "Collection will not write to it" holds whether the scheduler is running or stopped;
#: "paused" would claim a state it may not be in.
FRAME_DATA = (
    "Part of your library's data file could not be read: the database reported damage. An unexpected "
    "stop, a failing drive or a copy made while the file was changing can leave that behind. Collection "
    "will not write to it while this stands, so as not to make it worse. The app has deleted nothing "
    "because of it. Starting collection again tries once more: where the start-up check found the damage, "
    "the tables it named are read again and the pause ends only when they read clean; otherwise collection "
    "stops again at the first failed read."
)
FRAME_SEARCH_INDEX = (
    "The database reported damage while reading your library, most likely in its search index (not "
    "confirmed). An unexpected stop or a failing drive can leave that behind. Collection will not write "
    "to the library file while this stands, so as not to make it worse. The app has deleted nothing "
    "because of it. Starting collection again tries once more: where the start-up check found the damage, "
    "the tables it named are read again and the pause ends only when they read clean; otherwise collection "
    "stops again at the first failed read."
)
FRAME_WIKI = (
    "Part of the Wikipedia file could not be read: the database reported damage. The Wikipedia lane's "
    "writing is paused so it does not make it worse; the app has deleted nothing because of it, and "
    "collection of your other sources goes on. Turning Wikipedia fetching off and on again tries once "
    "more."
)
FRAME_LAW = (
    "Part of the file that tracks laws could not be read: the database reported damage. Law tracking is "
    "paused so it does not make it worse; the app has deleted nothing because of it, and collection of "
    "your other sources goes on. Starting collection again tries once more."
)
FRAME_RECORDED = (
    "Part of one of your other data files (not your library and not Wikipedia) could not be read: the "
    "database reported damage. It is recorded in the file database-damage.json in your data folder; the "
    "app has nothing to pause for that file, and has deleted nothing because of it."
)
FRAME_VERIFYING = (
    "The app is checking your data files after an unexpected stop, before collection writes to them again: "
    "table {index} of {total}. The check writes nothing of its own, and the pause ends by itself when it ends."
)
FRAME_RECHECKING = (
    "The app is reading again the part of your data file that the check reported as damaged: table {index} of "
    "{total}. If it reads clean, the pause ends, unless another read failed in the meantime; if it does not, "
    "collection stays paused."
)
FRAME_REREADING = (
    "A read of one of your data files failed a moment ago, so the app will not write to that file until it has read the same table or "
    "tables again on a new connection. If that read comes back clean, the pause ends by itself and the failed read stays in the record "
    "as one that did not repeat; if it does not, or another read fails in the meantime, the pause stays. The app has deleted nothing "
    "because of it."
)
FRAME_STAYED = (
    "The same table failed to read again after the app had read it clean once, so writing to that file stays paused instead of starting "
    "and stopping by itself. The app has deleted nothing because of it. The note above says how to try again, which reads the table "
    "once more; if that read fails again, the pause comes back."
)
FRAME_CHECK_STOPPED = (
    "The app stopped trying to check your data file after {tries} starts in a row that ended before the check "
    "finished. An earlier check had found damage in it, so it stays paused. The pause ends only when the part that was "
    "reported reads clean again; the note above says how to try again."
)
FRAME_PAUSE_OFF = (
    "The database reported damage in one of your data files, and the pause for it is switched off on "
    "this machine (OO_DAMAGE_GUARD=0), so writing carries on. It is recorded in the file "
    "database-damage.json in your data folder."
)

#: The repair of a damaged library file (E3, ``database/repair.py``). Each says what is true and what was NOT done: a refusal
#: says the data files were not changed, and the damaged file a repair set aside is kept for ``repair.KEPT_COPY_DAYS`` days
#: after the new file first reads clean and then removed by the app (R129, the user's answer 35 = b), which the notices say.
FRAME_REPAIR_NEXT_START = (
    "The app repairs a damaged library file by itself at its next start: it copies every row it can still read into a "
    "new file, checks it, and switches to it. The damaged file is kept beside it, and the app removes it 30 days after "
    "the new file first reads clean, unless the drive itself could not read it (it then stays until you remove it); you "
    "can remove it sooner. Until the repair, collection will not write to the damaged file."
)
FRAME_REPAIRING = (
    "The app is repairing your damaged library file: it is copying every row it can still read into a new file, and it "
    "switches to the new file only when that reads clean. Anything the app saves waits until it is done. The damaged "
    "file is kept, and removed 30 days after the new file first reads clean unless the drive itself could not read it."
)
FRAME_REPAIRED = (
    "Your library file was damaged, and the app repaired it: {kept} rows were copied and up to {lost} entries could not "
    "be read. Articles that could not be read are collected again by ordinary collection."
)
FRAME_REPAIRED_OPEN = (
    "Your library file was damaged, and the app repaired it: {kept} rows were copied. The end of the article list could "
    "not be read, so how many entries were lost is not known (at least {lost}). Articles that could not be read are "
    "collected again by ordinary collection."
)
FRAME_KEPT_UNTIL = (
    "The damaged file the repair set aside is kept as {name} ({size}) in {folder}. The app removes it at the first start "
    "on or after {date} (30 days after the repaired file first read clean), unless your library is damaged again then; "
    "you can remove it yourself before that."
)
FRAME_KEPT_REMOVED = (
    "The damaged file the repair set aside ({name}, {size}) was removed on {date}, 30 days after the repaired file "
    "first read clean."
)
FRAME_KEPT_NOT_REMOVED = (
    "The app will not remove the damaged file the repair set aside ({name}, {size}) in {folder}: what is there now is "
    "not the file the repair recorded, or it is a link. It stays until you remove it yourself."
)
FRAME_KEPT_DISK = (
    "The drive could not read {pages} pages of your library file, so the app keeps the damaged file the repair set aside "
    "({name}, {size}) in {folder} and will not remove it. Check the drive (a failing drive is the likeliest reason); once "
    "you no longer need that file, remove it yourself."
)
FRAME_KEPT_SWITCH = (
    "The damaged file the repair set aside is kept as {name} ({size}) in {folder}. Removing it by itself is switched off on "
    "this machine (OO_BOOT_REPAIR=0), so it stays until you remove it yourself."
)
FRAME_KEPT_UNDATED = (
    "The damaged file the repair set aside is kept as {name} ({size}) in {folder}. The app could not work out the date to "
    "remove it (it could not check whether the drive reads that file without errors), so it will not remove it: it stays "
    "until you remove it yourself."
)
FRAME_REPAIRED_ORPHANS = (
    "{count} saved rows ({tables}) belong to rows that could not be read. They were kept, and none was removed."
)
FRAME_REPAIRED_ORPHAN_VERDICTS = (
    "Among them are rows that record a verdict this install measured ({tables}); they stay as they were measured."
)
FRAME_REPAIRED_STAND_INS = (
    "A stand-in row, marked as lost, was added to each of these tables: {tables}. It stops a row saved later from being "
    "given the number of a lost one and seeming to own the rows that belong to it."
)
FRAME_REPAIRED_ID_REUSE = (
    "A row saved later in {tables} could be given the number of a row that was lost, and would then seem to own the saved "
    "rows that belong to it: the stand-in row that stops this could not be written."
)
FRAME_REPAIR_NO_GATE = (
    "The app did not repair your damaged library file: the single-writer gate is switched off on this machine "
    "(OO_WRITE_GATE=0), so a save made while the new file is built could not be held back and would be lost. Switch it "
    "back on and restart the app; the repair then starts by itself. Your data files were not changed."
)
FRAME_REPAIR_WRITTEN = (
    "The app did not repair your damaged library file: something was saved to it while the new file was being made, so "
    "the new file would have missed that and nothing was switched. Your data files were not changed. The repair is tried "
    "again at the next start."
)
FRAME_REPAIR_NO_ROOM = (
    "The app did not repair your damaged library file: the drive has {free} MB free and the repair needs about {needed} "
    "MB. Free some space and restart the app; the repair then starts by itself. Your data files were not changed."
)
FRAME_REPAIR_NO_SCHEMA = (
    "The app cannot repair your damaged library file: the list of its tables cannot be read, so nothing can be copied. "
    "Restore a backup. Your data files were not changed."
)
FRAME_REPAIR_NO_LINKS = (
    "The app did not repair your damaged library file: the drive it is on cannot give a file a second name, which the "
    "safe switch to a repaired file needs. Your data files were not changed. Restore a backup, or move your library to "
    "another drive."
)
FRAME_REPAIR_BUSY = (
    "The app did not repair your damaged library file: another job was still writing to your library when the repaired "
    "file was ready, so nothing was switched. Your data files were not changed. The repair is tried again at the next "
    "start."
)
FRAME_REPAIR_FAILED = (
    "The app could not finish repairing your damaged library file, and it changed nothing. The reason is in the file "
    "database-damage.json in your data folder. The repair is tried again at the next start."
)
FRAME_REPAIR_UNFINISHED = (
    "The app did not repair your damaged library file: two starts in a row ended while it was being repaired (the "
    "computer ran out of memory or power, or the app was ended abruptly), so it is not tried again until the app is "
    "updated. Your data files were not changed."
)

METHOD = (
    "A failed database statement counts only when the DRIVER's own error is SQLITE_CORRUPT (code 11 and "
    "its extended codes); a wrong passphrase (code 26) never does, and SQLAlchemy's wrapper text, which "
    "carries the statement's values, is never read. One record per distinct file, scope and statement "
    "shape per process, repeats counted. The record keeps the statement's shape with every value "
    "removed, never a row. The pause is per file and lives in memory: starting collection again "
    "releases it (the Wikipedia lane's own start releases that file's) and the first failed read puts "
    "it back; a pause the per-table check set is released only when a re-read of the tables the check "
    "reported comes back clean. A 'search-index' scope is a SUSPICION that rests on a virtual-table "
    "corruption code or a statement over the full-text index or its tables that does not also read the "
    "articles table (a damaged index reports plain code 11 through MATCH); anything else is 'data', "
    "and 'data' stays while a file is latched. A BLIND SPOT: damage to the first page of a file, encrypted or "
    "not, reads as code 26, the code a wrong passphrase gives, so it is not named. Noticing reads "
    "nothing. After an unexpected stop the per-table check reads each table of the corpus, Wikipedia "
    "and law files once with PRAGMA quick_check on its own read-only connection (smallest first when the "
    "planner's statistics say which is smallest); a table is damaged when the check reports a problem or "
    "raises SQLITE_CORRUPT, and unchecked, never damaged, when the file is busy, locked, locked by a "
    "passphrase or stopped. It checks the structure of each table and its indexes (that the pages are "
    "well formed and the records readable), not that an index agrees with its table and not every "
    "row's content; the search index (a virtual table) is checked by SQLite's own integrity check for "
    "its inverted index (SQLite 3.44 and later), which does not compare it with the articles. "
    "The repair of a damaged library file is database/repair.py's, at start-up and only on a damaged verdict this "
    "process's check measured: it copies every row the file can still give into a new file, checks the new file with "
    "the same per-table check, and switches to it, keeping the damaged file under a dated name; this record keeps "
    "its attempts (counts, names and id ranges, never a value)."
)


def _log_latched(file_key: str, name: str | None, scope: str, shape: str | None) -> None:
    """The one ERROR line of a latch; what it says about the writers follows the switch."""
    if switch_on():
        consequence = "its writers are paused until they are started again"
    else:
        consequence = "OO_DAMAGE_GUARD=0 switches the pause off, so its writers carry on"
    _LOG.error(
        "database damage: the database reported %s on the %s file (%s scope); %s. Statement shape: %s",
        name or "a malformed database image",
        file_key,
        scope,
        consequence,
        shape,
    )


# Process-wide singleton (no thread, no I/O until the first incident or a state read).
registry = DamageRegistry(rereads=True)


def retry_for_collection_start(reason: str) -> list[str]:
    """The ONE call every way of starting collection makes (``POST /api/scheduler/start`` and
    ``/run-now``, the airplane toggle going online, the unattended start): the operator is trying again,
    so the corpus's and the law file's latches are released, and the Wikipedia lane's is not (its own start
    releases it). The first failed read puts the pause back. Returns the files released. Never raises.

    The ``files`` it hands ``registry.retry`` are the files collection pauses, so a file that is only RECORDED (it
    has no writer to pause) is never "released" by a start that did not pause it."""
    return registry.retry(
        reason=reason, files=tuple(f for f in PAUSED_FILES if f not in NOT_RELEASED_BY_COLLECTION)
    )


_SQLCIPHER = "sqlcipher3"


def _module_root(obj: Any) -> str:
    return type(obj).__module__.split(".")[0]


def _dbapi_of(handle: Any) -> Any:
    """The driver's own connection behind a SQLAlchemy ``Connection`` or a pooled connection, or ``None``. Reads
    what is already there: asking a ``Connection`` that was invalidated for its ``.connection`` would open a new
    one."""
    cur = handle
    # Three hops at most: a ``Connection``, then its pooled connection, then the driver connection. A handle that
    # reaches no driver connection in three hops has none.
    for _ in range(3):
        if getattr(cur, "invalidated", False) is True:
            return None
        inner = getattr(cur, "dbapi_connection", None)
        if inner is not None:
            return inner
        cur = getattr(cur, "connection", None)
        if cur is None:
            return None
    return None


def poisons_connection(exc: BaseException | None, dbapi_connection: Any) -> str | None:
    """Whether ``exc``, raised on ``dbapi_connection``, leaves that connection unusable, and how it knows.

    * ``"corrupt"``: the driver is SQLCipher and its own error is ``SQLITE_CORRUPT`` (primary code 11).
    * ``"memory"``: the error is an empty builtin ``MemoryError`` on a SQLCipher connection. By itself this is
      NOT evidence of damage (a real allocation failure raises the same thing, and field machines do run out of
      memory), so it is a reason to discard the connection and never a reason to name a file.

    ``None`` for everything else: a wrong key (code 26), a plain SQLite file's corruption (it does not poison
    its connection), a ``MemoryError`` with a message, and any connection that is not SQLCipher's."""
    driver = driver_error(exc)
    if driver is not None:
        if _module_root(driver) != _SQLCIPHER:
            return None
        code = getattr(driver, "sqlite_errorcode", None)
        if isinstance(code, int) and (code & 0xFF) == SQLITE_CORRUPT:
            return "corrupt"
        return None
    if (
        type(exc) is MemoryError
        and not str(exc)
        and dbapi_connection is not None
        and _module_root(dbapi_connection) == _SQLCIPHER
    ):
        return "memory"
    return None


def discard_poisoned_connection(context: Any) -> bool:
    """Tell SQLAlchemy to throw away the connection whose statement just failed in a way that poisons it (see
    :func:`poisons_connection`). Returns whether it did. Never raises.

    WHY. After a page that fails its check, SQLCipher leaves the connection answering an empty ``MemoryError``
    to EVERY later page read, healthy tables included; ``rollback``, ``commit``, ``shrink_memory``,
    ``cache_size`` and a second ``PRAGMA key`` do not clear it, only a new connection does (measured on a real
    encrypted store; plain ``sqlite3`` connections are not affected). A pooled connection goes back to the pool
    in that state, so one request that touches a damaged page leaves a connection that fails every later
    request with the text of a real out-of-memory, until the process restarts.

    WHAT. ``is_disconnect = True`` makes SQLAlchemy invalidate this one connection: the driver connection is
    closed and the pool opens a fresh one on the next checkout (one key derivation, 0.2 to 0.4 s). The error
    that is raised is the same error (``connection_invalidated`` is now true on a wrapped one).
    ``invalidate_pool_on_disconnect = False`` keeps the discard to that ONE connection: every connection that
    reads a damaged page is discarded by its own error, so the rest of the pool needs no replacing
    (SQLAlchemy's default would drop every connection older than the moment, and each would then pay a key
    derivation).

    THE FIRST ERROR IS NOT ALWAYS CODE 11. A damaged first or middle page of a long value's overflow chain
    raises code 11 on that read. The LAST overflow page does not: the read returns the whole length with the
    wrong bytes at the tail and the connection is poisoned for the NEXT statement, which raises an empty
    ``MemoryError`` (measured, ``tests/test_poisoned_connection.py``). So an empty ``MemoryError`` on a SQLCipher
    connection is discarded too. It is never latched or recorded on that evidence: it names no file (a real
    allocation failure raises the same) and the observer only reads errors, never the file.

    WHAT HAPPENS TO THE CALLER. The connection is CLOSED, not rolled back and handed on: a session that was in
    a transaction on it loses everything it had flushed (the writes were on the closed connection), and every
    later statement of that session, a ``commit`` included, raises ``PendingRollbackError`` until the caller
    rolls the session back; only then does its next statement check a connection out again. A caller that
    commits after a failed read without rolling back therefore fails loudly and does not persist a partial
    transaction.

    WHAT IT DOES NOT TOUCH. A wrong-key error (code 26), a plain-SQLite corruption error (it does not poison its
    connection), a ``MemoryError`` with a message, and a context whose connection is already closed (SQLAlchemy
    cannot invalidate it, and marking it a disconnect makes its own cleanup fail an assertion that replaces the
    real error)."""
    try:
        connection = getattr(context, "connection", None)
        if connection is None or getattr(connection, "closed", True):
            return False
        exc = getattr(context, "original_exception", None)
        if poisons_connection(exc, _dbapi_of(connection)) is None:
            return False
        context.is_disconnect = True
        context.invalidate_pool_on_disconnect = False
        return True
    except Exception:  # noqa: BLE001 - an observer never replaces the real error
        return False


def note_raw_driver_error(handle: Any, exc: BaseException | None, *, engine: Any = None,
                          file_key: str | None = None, statement: str | None = None) -> bool:
    """What :func:`attach`'s observer does for a failure it never sees: a statement the app ran on the DRIVER's
    own cursor over a connection checked out of a pool (``handle`` is that pooled connection, or the SQLAlchemy
    ``Connection`` it belongs to). SQLAlchemy raises no ``handle_error`` for those, so without this a code 11
    there neither latches nor discards, and the poisoned connection goes back to the pool.

    Invalidates ``handle`` when :func:`poisons_connection` says the failure poisons it, and, independently,
    records and latches a corruption error against the file the engine is attached for (``file_key`` is the
    fallback for an engine that is not attached; with neither, nothing is latched, so a file is never named
    wrongly). The two are separate questions: a plain SQLite file's code 11 does not poison its connection and
    is still damage; an empty ``MemoryError`` discards and names nothing. Returns whether the connection was
    invalidated. Never raises and never replaces ``exc``."""
    discarded = False
    try:
        engine = engine if engine is not None else getattr(handle, "engine", None)
        try:
            if poisons_connection(exc, _dbapi_of(handle)) is not None:
                with contextlib.suppress(Exception):
                    handle.invalidate()
                    discarded = True
        except Exception:  # noqa: BLE001 - a handle that cannot answer (a CLOSED ``Connection`` raises when asked for its driver connection) is not discarded, and its error is still latched below
            pass
        # Latching does not depend on what the connection does afterwards: a plain SQLite file's corruption error
        # does not poison its connection, but it is still damage, and ``registry.note`` itself answers False
        # (and records nothing) for an error that is not corruption, an empty ``MemoryError`` included.
        seen = attached(engine) if engine is not None else None
        key = seen[0] if seen else file_key
        if key is not None:
            path = None
            with contextlib.suppress(Exception):
                database = engine.url.database
                if database and database != ":memory:":
                    path = Path(database)
            registry.note(key, exc, statement=statement, path=path)
    except Exception:  # noqa: BLE001 - an observer never replaces the real error
        pass
    return discarded


@contextlib.contextmanager
def guard_raw_driver(handle: Any, *, engine: Any = None, file_key: str | None = None,
                     statement: str | None = None):
    """``with guard_raw_driver(conn): <statements on conn's driver cursor>``: a failure is passed to
    :func:`note_raw_driver_error` and then raised again unchanged. The ONE guard for every raw driver statement on
    a pooled connection, so no site carries its own copy of the rule."""
    try:
        yield
    except Exception as exc:
        note_raw_driver_error(handle, exc, engine=engine, file_key=file_key, statement=statement)
        raise


#: engine -> (file key, listener): what :func:`attach` registered, so a test (or a status read) can
#: ask which file an engine's errors are filed against, and prove the listener is still on it.
_ATTACHED: weakref.WeakKeyDictionary[Any, tuple[str, Any]] = weakref.WeakKeyDictionary()


def attach(engine: Any, file_key: str) -> None:
    """Register the observer on ``engine`` for the file ``file_key`` names. One call per engine."""
    from sqlalchemy import event

    def _damage_on_corruption(context) -> None:  # noqa: ANN001 - SQLAlchemy's ExceptionContext
        registry.on_engine_error(context, file_key)
        discard_poisoned_connection(context)

    event.listen(engine, "handle_error", _damage_on_corruption)
    _ATTACHED[engine] = (file_key, _damage_on_corruption)


def attached(engine: Any) -> tuple[str, Any] | None:
    """``(file key, listener)`` for an engine :func:`attach` was called on, else ``None``."""
    return _ATTACHED.get(engine)
