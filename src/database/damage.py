"""A damaged database file is NOTICED, NAMED and CONTAINED (damaged-database plan, slice E1).

WHY THIS EXISTS. The Asus bundle of 2026-10-06 held a corpus SQLite itself called malformed from
2026-10-02, and collection went on for a day and a half: about 300 "batched collect commit failed;
redoing N article(s) one at a time" lines, each a pass that wrote into a file the database could not
fully read. Nothing in the app named the word: ``grep malformed src`` found one reader, the FTS health
probe. This module is the missing sentence.

WHAT IT DOES, AND ALL IT DOES.

* **Notices.** A ``handle_error`` observer on the corpus engine and on every lane engine
  (:func:`attach`) asks one question of each failed statement: is the DRIVER's own exception
  ``SQLITE_CORRUPT`` (primary code 11, any extended code)? It reads the code off the driver's exception,
  never the SQLAlchemy wrapper's text, which carries the statement and its bound values (the lesson of
  #1306's ``is_disk_full``). ``SQLITE_NOTADB`` (26, "file is not a database") NEVER counts: it is what a
  wrong passphrase produces under SQLCipher, measured on the real driver (``tests/test_database_damage.py``).
* **Names.** One incident record per distinct (file, scope, statement shape) per process, in
  ``data/database-damage.json`` (atomic, the newest 20 kept, survives restarts): when, which FILE, the
  driver's code and first line, the statement's SHAPE with every value stripped, the thread and the route,
  how the previous session ended, and the sizes of the file, its log and the drive. A repeat of a known
  incident is counted, not re-recorded. NO value from any row, no passphrase and no URL reaches the record.
* **Contains, per file.** The latch names the file: the CORPUS latch stops collection's writes to the
  corpus (passes, the housekeeping lanes, maintenance: :meth:`StorageGuard.admit`), the LAW latch stops the
  law step of the housekeeping lane, a WIKI latch stops the Wikipedia lane's writing (``wiki/runner.py``),
  and none stops another; any other file is recorded and NAMED, with nothing to pause. The latch is memory
  only: a restart is the operator trying again, and the first failed read puts it back.

* **Discards a poisoned connection.** On an ENCRYPTED file a read of a page that fails its check leaves that
  connection answering an empty ``MemoryError`` to every later read, healthy tables included, until it is closed
  (measured). The observer therefore marks a SQLCipher ``SQLITE_CORRUPT`` as a disconnect for that ONE connection
  (:func:`discard_poisoned_connection`), so the pool opens a fresh one instead of handing the poisoned one to the
  next request. It does the same for an empty ``MemoryError`` raised on a SQLCipher connection, because the LAST
  overflow page of a long value fails silently (the read returns the right length with wrong tail bytes and the
  poison arrives on the NEXT statement, measured), and it NEVER latches or records on that: an empty
  ``MemoryError`` is also what a real allocation failure raises, so by itself it names no file. A wrong key and a
  plain SQLite file's corruption are never reclassified. A statement the driver runs for the app on a pooled
  connection WITHOUT going through SQLAlchemy raises past this observer, so those sites go through
  :func:`guard_raw_driver`, which does the same for them.

WHAT IT DOES NOT DO (and the PR says so). It does not verify, repair or salvage: that is E2 (a boot check
after an unclean end) and E3 (a salvage copy). Until they land the latch releases only when the operator
starts collection again (:func:`retry_for_collection_start`: the corpus's and the law file's; going online
and the unattended start are the operator starting it), or starts the Wikipedia lane (its own start
releases its own file), never by itself and never by a courtesy resume after a backup or a restore,
because a damaged file that keeps being written is the harm and only a check can say it is not damaged.

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

Nothing here touches a database: an observer on a damaged file must not read it, and it never raises.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
import weakref
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

#: How much of the driver's first line and of a statement's shape a record keeps.
_MESSAGE_KEEP = 160
_SHAPE_KEEP = 240

_DBAPI_MODULES = ("sqlite3", "sqlcipher3")

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


def corruption_of(exc: BaseException | None) -> dict[str, Any] | None:
    """What the driver said, when it said ``SQLITE_CORRUPT`` (primary code 11, any extended code); else
    ``None``. ``{"code", "name", "message"}``, the message being the driver's own FIRST line.

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
            "message": first[:_MESSAGE_KEEP],
        }
    if low.startswith("database disk image is malformed") or low.startswith("malformed database schema"):
        return {"code": None, "name": None, "message": first[:_MESSAGE_KEEP]}
    return None


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


class DamageRegistry:
    """The per-file latch and the incident record. Thread-safe; every method that an observer reaches
    never raises."""

    def __init__(self, *, path_fn=None, clock=time.time, mono=time.monotonic) -> None:
        self._path_fn = path_fn or record_path
        self._clock = clock
        self._mono = mono
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()  # one writer of the record at a time; never held with _lock
        self._load_lock = threading.Lock()  # one reader of the record file; never held with _lock
        #: Tells this process's incidents from an earlier process's in the record (the session id can be
        #: unknown, and two unknowns must not read as the same incident).
        self._process = uuid.uuid4().hex[:12]
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
                    cur["retries"] = int(cur.get("retries") or 0) + int(st.get("retries") or 0)
                    first = st.get("first_at")
                    if isinstance(first, str) and first and (not cur.get("first_at") or first < cur["first_at"]):
                        cur["first_at"] = first
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
            "files": {k: {kk: vv for kk, vv in v.items() if kk != "latched"} for k, v in self._files.items()},
            "incidents": [dict(i) for i in self._incidents],
        }

    def _flush(self, doc: dict[str, Any]) -> None:
        """Atomic: write a sibling and rename. A drive that cannot take it is said in ``write_error``;
        the in-memory latch holds regardless. Never called with the registry lock held."""
        with self._io_lock:
            if doc.get("write_seq", 0) <= self._flushed_seq:
                return  # a newer snapshot already landed (two threads raced): never write an older one over it
            path = Path(self._path_fn())
            tmp = path.with_name(path.name + ".tmp")
            error: str | None = None
            try:
                tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
                os.replace(tmp, path)
                self._flushed_seq = doc.get("write_seq", 0)
            except OSError as exc:
                first = (str(exc).splitlines() or [""])[0][:120]
                error = f"{type(exc).__name__}: {first}"
                with contextlib.suppress(OSError):
                    tmp.unlink()
        with self._lock:
            self._write_error = error
            self._last_flush_mono = self._mono()  # every attempt: a failing drive is tried once per window

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
                known = self._known_locked(file_key, scope, shape)
                due = self._count_repeat_locked(known, at) if known is not None else False
            if newly:
                _log_latched(file_key, found["name"], scope, shape)
            if known is not None:
                if due:
                    self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
                return True
            # The first of its kind in this process. What belongs to the CALLING thread is taken here (a
            # context variable does not follow into another thread); the rest, including the one read of
            # an earlier session's record, is gathered and written off it.
            thread_name = threading.current_thread().name
            endpoint = _endpoint()
            self._single_flight(
                ("record", file_key, scope, shape),
                lambda: self._record_new(
                    file_key, found, shape, scope, basis, at, path, thread_name=thread_name, endpoint=endpoint
                ),
            )
            return True
        except Exception:  # noqa: BLE001 - never raises
            _LOG.debug("database damage: could not record an incident", exc_info=True)
            return False

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
                _LOG.warning("database damage: the record could not be written", exc_info=True)
                with self._lock:
                    first = (str(exc).splitlines() or [""])[0][:120]
                    self._write_error = f"{type(exc).__name__}: {first}"
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
            "statement_shape": shape,
            "thread": thread_name,
            "endpoint": endpoint,
            "session_id": _current_session_id(),
            "process": self._process,
            "previous_end": _previous_end(),
            "repeats": 0,
            **_sizes(path),
        }
        with self._lock:
            known = self._known_locked(file_key, scope, shape)  # a record thread that ended just before may have won
            if known is not None:
                due = self._count_repeat_locked(known, at)
                doc = self._doc_locked() if due else None
            else:
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
        self, *, reason: str, files: tuple[str, ...] | None = None, except_files: tuple[str, ...] = ()
    ) -> list[str]:
        """The operator tries again: release the latch of ``files`` (every file's when ``None``) except
        ``except_files``. The record stays. Returns the files released. Never raises."""
        released: list[str] = []
        try:
            self._ensure_loaded()
            with self._lock:
                for key, st in self._files.items():
                    if st["latched"] and (files is None or key in files) and key not in except_files:
                        st["latched"] = False
                        st["retries"] += 1
                        released.append(key)
            if released:
                self._single_flight(_FLUSH_JOB, self._flush_latest, rerun=True)
            if released:
                _LOG.warning(
                    "database damage: the %s file's writers are released (%s); the first failed read "
                    "pauses them again",
                    ", ".join(released),
                    reason,
                )
        except Exception:  # noqa: BLE001
            _LOG.debug("database damage: retry failed", exc_info=True)
        return released

    # -- what a surface shows -------------------------------------------------------------------
    def notes(self) -> list[dict[str, Any]]:
        """The sentences to show, one per latched file, as frames the page translates: ``{kind, file,
        frame, vars}``. No numbers: a size would be a claim about a file this module did not read. With
        the pause switched off (``OO_DAMAGE_GUARD=0``) the damage is still NAMED, and the frame says the
        pause is off, so a silent switch never reads as a healthy file."""
        on = switch_on()
        out: list[dict[str, Any]] = []
        with self._lock:
            for key, st in self._files.items():
                if not st["latched"]:
                    continue
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
        }
        if detail:
            out["incidents"] = incidents
            out["method"] = METHOD
        return out


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
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        first = (str(exc).splitlines() or [""])[0][:160]
        return {"error": f"{type(exc).__name__}: {first}"}


#: The plain sentences. Frames the page translates (each is also a locale key, x12). None of them says
#: the file is being checked or repaired: in E1 nothing is. None says what is still intact either: E1
#: has not looked. They say what is true. "Collection will not write to it" holds whether the scheduler
#: is running or stopped; "paused" would claim a state it may not be in.
FRAME_DATA = (
    "Part of your library's data file could not be read: the database reported damage. An unexpected "
    "stop, a failing drive or a copy made while the file was changing can leave that behind. Collection "
    "will not write to it while this stands, so as not to make it worse. The app has deleted nothing "
    "because of it. Starting collection again tries once more, and it stops again at the first failed "
    "read."
)
FRAME_SEARCH_INDEX = (
    "The database reported damage while reading your library, most likely in its search index (not "
    "confirmed). An unexpected stop or a failing drive can leave that behind. Collection will not write "
    "to the library file while this stands, so as not to make it worse. The app has deleted nothing "
    "because of it. Starting collection again tries once more, and it stops again at the first failed "
    "read."
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
FRAME_PAUSE_OFF = (
    "The database reported damage in one of your data files, and the pause for it is switched off on "
    "this machine (OO_DAMAGE_GUARD=0), so writing carries on. It is recorded in the file "
    "database-damage.json in your data folder."
)

METHOD = (
    "A failed database statement counts only when the DRIVER's own error is SQLITE_CORRUPT (code 11 and "
    "its extended codes); a wrong passphrase (code 26) never does, and SQLAlchemy's wrapper text, which "
    "carries the statement's values, is never read. One record per distinct file, scope and statement "
    "shape per process, repeats counted. The record keeps the statement's shape with every value "
    "removed, never a row. The pause is per file and lives in memory: starting collection again "
    "releases it (the Wikipedia lane's own start releases that file's) and the first failed read puts "
    "it back. A 'search-index' scope is a SUSPICION that rests on a virtual-table corruption code or a "
    "statement over the full-text index or its tables (a damaged index reports plain code 11 through "
    "MATCH); anything else is 'data', and 'data' stays while a file is latched. A BLIND SPOT: damage to the first page of a file, encrypted or "
    "not, reads as code 26, the code a wrong passphrase gives, so it is not named. Nothing here "
    "reads the damaged file, verifies it or repairs it."
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
registry = DamageRegistry()


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

    Invalidates ``handle`` when :func:`poisons_connection` says the failure poisons it, and records and latches
    the corruption error against the file the engine is attached for (``file_key`` is the fallback for an engine
    that is not attached; with neither, nothing is latched, so a file is never named wrongly). An empty
    ``MemoryError`` discards and names nothing. Returns whether the connection was invalidated. Never raises and
    never replaces ``exc``."""
    discarded = False
    try:
        engine = engine if engine is not None else getattr(handle, "engine", None)
        kind = poisons_connection(exc, _dbapi_of(handle))
        if kind is not None:
            with contextlib.suppress(Exception):
                handle.invalidate()
                discarded = True
        if kind == "corrupt":
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
