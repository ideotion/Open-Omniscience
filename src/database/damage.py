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
* **Contains, per file.** The latch names the file: the CORPUS latch stops the corpus's writers (collection
  passes, the housekeeping lanes, maintenance: :meth:`StorageGuard.admit`), a WIKI lane latch stops the
  Wikipedia lane's loop (``wiki/runner.py``), and neither stops the other. The latch is memory only: a
  restart is the operator trying again, and the first failed read puts it back.

WHAT IT DOES NOT DO (and the PR says so). It does not verify, repair or salvage: that is E2 (a boot check
after an unclean end) and E3 (a salvage copy). Until they land the latch releases when the operator starts
collection again (:meth:`DamageRegistry.retry`), never by itself, because a damaged file that keeps being
written is the harm and only a check can say it is not damaged.

THE SCOPE FIELD. ``search-index`` is claimed only on EVIDENCE that the full-text index and not the table
itself is what the database could not read: the virtual-table corruption code (extended 267, which FTS5
raises for its own structure) or a statement that reads an index shadow table directly. A statement that
merely NAMES the index is not evidence, because an external-content FTS5 table reads the ``articles`` table
through it (the gotcha ``fts._decide_fts_rebuild`` documents). Everything else is ``data``, and the record
says which basis it rested on. The scope picks the route the record names (``search-index-rebuild`` or
``verify-then-salvage``); E1 only RECORDS the route.

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
#: The files COLLECTION writes: starting collection again releases these (the Wikipedia lane has its own
#: start, and an OSM import is a job the operator starts).
COLLECTION_FILES = (FILE_CORPUS, "law")

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

#: How much of the driver's first line and of a statement's shape a record keeps.
_MESSAGE_KEEP = 160
_SHAPE_KEEP = 240

_DBAPI_MODULES = ("sqlite3", "sqlcipher3")

#: The full-text index's own tables, read DIRECTLY. A statement over these is evidence about the index;
#: one over ``article_fts`` itself is not (see the module docstring).
_SHADOW_TABLE = re.compile(r"\barticle_fts_(?:data|idx|docsize|config|content)\b", re.IGNORECASE)

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
    ``__cause__`` and ``__context__``. SQLAlchemy's wrapper is never read, for its text carries the
    statement and every value bound to it."""
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__module__.split(".")[0] in _DBAPI_MODULES:
            return cur
        cur = getattr(cur, "orig", None) or cur.__cause__ or cur.__context__
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
    low = first.lower()
    if low.startswith("database disk image is malformed") or low.startswith("malformed database schema"):
        return {"code": None, "name": None, "message": first[:_MESSAGE_KEEP]}
    return None


def is_corruption(exc: BaseException | None) -> bool:
    return corruption_of(exc) is not None


def statement_shape(statement: str | None) -> str | None:
    """A statement with every VALUE taken out: whitespace collapsed, string literals ``?``, numbers
    ``N``, a run of placeholders one. Bound parameters are never given to this at all (only the SQL
    text is), so the shape is what is left of a statement that already carried none; the stripping is for
    the SQL that has a literal written into it."""
    if not statement:
        return None
    text = " ".join(str(statement).split())
    text = _STRING_LITERAL.sub("?", text)
    text = _NUMBER.sub("N", text)
    text = _PLACEHOLDER_RUN.sub("?, ?", text)
    return text[:_SHAPE_KEEP]


def scope_of(code: int | None, shape: str | None) -> tuple[str, str]:
    """``(scope, basis)``: ``search-index`` only on evidence (see the module docstring), else ``data``."""
    if code == SQLITE_CORRUPT_VTAB:
        return SCOPE_SEARCH_INDEX, "the driver reported corruption in a virtual table (extended code 267)"
    if shape and _SHADOW_TABLE.search(shape):
        return SCOPE_SEARCH_INDEX, "the failing statement reads an index table directly"
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
    """The route the failing request is serving, when it is one (the pool watcher's own label)."""
    try:
        from src.database import pool_watch

        return pool_watch._endpoint_label()
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
        self._loaded = False
        self._prior_unreadable = False
        self._incidents: deque[dict[str, Any]] = deque(maxlen=INCIDENTS_KEEP)
        self._files: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._last_flush_mono: float | None = None
        self._write_error: str | None = None

    def _reset_for_tests(self, *, path_fn=None) -> None:
        with self._lock:
            self._loaded = True  # a test starts from nothing, never from a file a neighbour wrote
            self._prior_unreadable = False
            self._incidents.clear()
            self._files.clear()
            self._dirty = False
            self._last_flush_mono = None
            self._write_error = None
            self._path_fn = path_fn or record_path

    # -- persistence ------------------------------------------------------------------------------
    def _load_locked(self) -> None:
        """Pick up the record an earlier session wrote, once. A record that cannot be read is said so
        (``prior_record_unreadable``) and replaced by the next incident, never a reason to fail."""
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(Path(self._path_fn()).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self._prior_unreadable = True
            return
        try:
            for inc in raw.get("incidents", [])[-INCIDENTS_KEEP:]:
                if isinstance(inc, dict):
                    self._incidents.append(inc)
            for key, st in (raw.get("files") or {}).items():
                if isinstance(st, dict):
                    # The history carries over; the LATCH does not (a new session is a retry).
                    self._files[str(key)] = {
                        "latched": False,
                        "incidents": int(st.get("incidents") or 0),
                        "first_at": st.get("first_at"),
                        "last_at": st.get("last_at"),
                        "scope": st.get("scope"),
                        "retries": int(st.get("retries") or 0),
                    }
        except (AttributeError, TypeError, ValueError):
            self._prior_unreadable = True

    def _doc_locked(self) -> dict[str, Any]:
        """The record as it stands. Caller holds the lock; the WRITE happens outside it (:meth:`_flush`),
        because ``corpus_latched`` is read on every unit of collection work and must never queue behind
        a slow drive."""
        return {
            "schema": SCHEMA,
            "written_at": datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds"),
            "files": {k: {kk: vv for kk, vv in v.items() if kk != "latched"} for k, v in self._files.items()},
            "incidents": [dict(i) for i in self._incidents],
        }

    def _flush(self, doc: dict[str, Any]) -> None:
        """Atomic: write a sibling and rename. A drive that cannot take it is said in ``write_error``;
        the in-memory latch holds regardless. Never called with the registry lock held."""
        with self._io_lock:
            path = Path(self._path_fn())
            tmp = path.with_name(path.name + ".tmp")
            error: str | None = None
            try:
                tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
                os.replace(tmp, path)
            except OSError as exc:
                first = (str(exc).splitlines() or [""])[0][:120]
                error = f"{type(exc).__name__}: {first}"
                with contextlib.suppress(OSError):
                    tmp.unlink()
        with self._lock:
            self._write_error = error
            if error is None:
                self._dirty = False
                self._last_flush_mono = self._mono()

    # -- noticing ----------------------------------------------------------------------------------
    def on_engine_error(self, context: Any, file_key: str) -> None:
        """The ``handle_error`` listener body for an engine over ``file_key``. Observes only: the error
        still propagates unchanged and nothing here raises."""
        try:
            exc = getattr(context, "original_exception", None)
            if not is_corruption(exc):
                return
            statement = getattr(context, "statement", None)
            if statement and re.search(r"\battach\s+database\b", str(statement), re.IGNORECASE):
                # An ATTACHed file is not this engine's file; the error cannot say which of the two it
                # came from, and a latch on the wrong one would pause the right file for nothing.
                return
            self.note(file_key, exc, statement=statement, path=_engine_path(context))
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            pass

    def _known_locked(self, file_key: str, scope: str, shape: str | None, sid: str | None) -> dict[str, Any] | None:
        """The record of this very incident in this session, if one exists. Caller holds the lock."""
        for inc in reversed(self._incidents):
            if (
                inc.get("file") == file_key
                and inc.get("scope") == scope
                and inc.get("statement_shape") == shape
                and inc.get("session_id") == sid
            ):
                return inc
        return None

    def _count_repeat_locked(self, known: dict[str, Any], at: str) -> dict[str, Any] | None:
        """Count a repeat; the record to write when one is due (at most once per ``FLUSH_EVERY_S``)."""
        known["repeats"] = int(known.get("repeats") or 0) + 1
        known["last_at"] = at
        self._dirty = True
        if self._last_flush_mono is None or (self._mono() - self._last_flush_mono) >= FLUSH_EVERY_S:
            return self._doc_locked()
        return None

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
        was corruption. Never raises."""
        try:
            found = corruption_of(exc)
            if found is None:
                return False
            shape = statement_shape(statement)
            scope, basis = scope_of(found["code"], shape)
            at = datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")
            sid = _current_session_id()
            with self._lock:
                self._load_locked()
                st = self._files.setdefault(
                    file_key,
                    {"latched": False, "incidents": 0, "first_at": at, "last_at": at, "scope": scope, "retries": 0},
                )
                st["incidents"] += 1
                st["last_at"] = at
                st["scope"] = scope
                newly = not st["latched"]
                st["latched"] = True
                known = self._known_locked(file_key, scope, shape, sid)
                due = self._count_repeat_locked(known, at) if known is not None else None
            if known is not None:
                if due is not None:
                    self._flush(due)
                return True
            # The first of its kind this session: gather the facts OUTSIDE the lock (they stat files and
            # read the session ledger), then record.
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
                "thread": threading.current_thread().name,
                "endpoint": _endpoint(),
                "session_id": sid,
                "previous_end": _previous_end(),
                "repeats": 0,
                **_sizes(path),
            }
            with self._lock:
                known = self._known_locked(file_key, scope, shape, sid)  # another thread may have won
                if known is not None:
                    doc = self._count_repeat_locked(known, at)
                else:
                    self._incidents.append(record)
                    doc = self._doc_locked()
            if doc is not None:
                self._flush(doc)
            if newly:
                _LOG.error(
                    "database damage: the database reported %s on the %s file (%s scope); its writers "
                    "are paused until they are started again. Statement shape: %s",
                    found["name"] or "a malformed database image",
                    file_key,
                    scope,
                    shape,
                )
            return True
        except Exception:  # noqa: BLE001 - never raises
            _LOG.debug("database damage: could not record an incident", exc_info=True)
            return False

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

    def retry(self, *, reason: str, files: tuple[str, ...] | None = None) -> list[str]:
        """The operator tries again: release the latch of ``files`` (every file's when ``None``). The
        record stays. Returns the files released. Never raises."""
        released: list[str] = []
        try:
            doc = None
            with self._lock:
                self._load_locked()
                for key, st in self._files.items():
                    if st["latched"] and (files is None or key in files):
                        st["latched"] = False
                        st["retries"] += 1
                        released.append(key)
                if released:
                    self._dirty = True
                    doc = self._doc_locked()
            if doc is not None:
                self._flush(doc)
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
        frame, vars}``. No numbers: a size would be a claim about a file this module did not read."""
        if not switch_on():
            return []
        out: list[dict[str, Any]] = []
        with self._lock:
            for key, st in self._files.items():
                if not st["latched"]:
                    continue
                if key == FILE_CORPUS:
                    frame = FRAME_SEARCH_INDEX if st.get("scope") == SCOPE_SEARCH_INDEX else FRAME_DATA
                elif key == "wiki":
                    frame = FRAME_WIKI
                else:
                    continue  # a lane with no writer this module pauses has no pause to announce
                out.append({"kind": "damage", "file": key, "frame": frame, "vars": {}})
        return out

    def state(self, *, detail: bool = False) -> dict[str, Any]:
        """The honest state: which files are latched, the counts, and the newest incident. ``detail``
        adds the whole record (the diagnostics route's reading; the polled status carries the brief)."""
        with self._lock:
            self._load_locked()
            files = {k: dict(v) for k, v in self._files.items()}
            incidents = list(self._incidents)
            write_error = self._write_error
            prior_unreadable = self._prior_unreadable
        latched = sorted(k for k, v in files.items() if v["latched"]) if switch_on() else []
        out: dict[str, Any] = {
            "enabled": switch_on(),
            "latched": latched,
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
#: the file is being checked or repaired: in E1 nothing is. They say what is true.
FRAME_DATA = (
    "Part of your library's data file could not be read: the database reported damage. An unexpected "
    "stop, a failing drive or a copy made while the file was changing can leave that behind. Collection "
    "is paused so it does not make it worse; nothing was deleted, and what is still readable stays "
    "readable. Starting collection again tries once more, and it pauses again at the first failed read."
)
FRAME_SEARCH_INDEX = (
    "Part of your library's search index could not be read: the database reported damage. An unexpected "
    "stop or a failing drive can leave that behind. Collection is paused so it does not make it worse; "
    "your articles were not changed. Starting collection again tries once more, and it pauses again at "
    "the first failed read."
)
FRAME_WIKI = (
    "Part of the Wikipedia file could not be read: the database reported damage. The Wikipedia lane is "
    "paused so it does not make it worse; nothing was deleted, and collection of your other sources "
    "goes on. Turning Wikipedia fetching off and on again tries once more."
)

METHOD = (
    "A failed database statement counts only when the DRIVER's own error is SQLITE_CORRUPT (code 11 and "
    "its extended codes); a wrong passphrase (code 26) never does, and SQLAlchemy's wrapper text, which "
    "carries the statement's values, is never read. One record per distinct file, scope and statement "
    "shape per session, repeats counted. The record keeps the statement's shape with every value "
    "removed, never a row. The pause is per file and lives in memory: starting collection again "
    "releases it and the first failed read puts it back. A 'search-index' scope rests on a "
    "virtual-table corruption code or a statement over an index table; anything else is 'data'. "
    "Nothing here reads the damaged file, verifies it or repairs it."
)

# Process-wide singleton (no thread, no I/O until the first incident or a state read).
registry = DamageRegistry()


#: engine -> (file key, listener): what :func:`attach` registered, so a test (or a status read) can
#: ask which file an engine's errors are filed against, and prove the listener is still on it.
_ATTACHED: weakref.WeakKeyDictionary[Any, tuple[str, Any]] = weakref.WeakKeyDictionary()


def attach(engine: Any, file_key: str) -> None:
    """Register the observer on ``engine`` for the file ``file_key`` names. One call per engine."""
    from sqlalchemy import event

    def _damage_on_corruption(context) -> None:  # noqa: ANN001 - SQLAlchemy's ExceptionContext
        registry.on_engine_error(context, file_key)

    event.listen(engine, "handle_error", _damage_on_corruption)
    _ATTACHED[engine] = (file_key, _damage_on_corruption)


def attached(engine: Any) -> tuple[str, Any] | None:
    """``(file key, listener)`` for an engine :func:`attach` was called on, else ``None``."""
    return _ATTACHED.get(engine)
