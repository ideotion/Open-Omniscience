"""Every GET operation of the app is driven once and what it DOES beyond reading is accounted for (audit 0.5.0 item 35 follow-on, P3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/SECURITY.md`` ("The local API") names what stands between a cross-site request and a state-changing request. A ``GET`` is not
state-changing to the Origin middleware, so the Host guard alone stands in front of it, and a page the person visits can fire any GET
with an ``<img src>``. What a GET may then do is therefore a security fact, and a name-based net does not find it (an AST scan for
side-effect call names matched all 470 handlers). So this file MEASURES it, the way ``test_destructive_surfaces.py`` reads instead of
trusting names: every ``GET`` operation in the app's own OpenAPI schema, plus the hidden GETs pinned below, is driven once, with the
network kill switch engaged (the state the app boots in), while the monitors record

* a socket connect, ``connect_ex`` or UDP ``sendto``, and a DNS lookup (``getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``): blocked
  and recorded, loopback told apart from the rest,
* a thread started (the rate limiter's own expiry timer, found by its stack, is not counted),
* a program started (only three local queries are listed),
* a file created, changed or REMOVED under the data directories,
* a write statement through the app's engine (INSERT, UPDATE, DELETE, REPLACE, DDL, a ``WITH ... DELETE``, a ``PRAGMA x = y``), and
* a change to the main database file as seen by a SECOND connection (``PRAGMA data_version``), which also catches a write that does not
  go through the engine (a raw ``sqlite3`` connection).

and each observed effect must be in a table below with the reason it is acceptable. A NEW GET that opens a socket, starts a thread,
writes a file or touches the database fails here by name until it is guarded or listed; the way out is to add a line with a reason that
a reviewer then reads. The table of 2026-10-27 is ``get-side-effects-2026-10-27.md`` in the project's audit folder (outside the repo;
its findings are routed, not fixed here).

What this proves, stated: with the kill switch engaged no GET reaches a non-loopback address through the calls listed above (a per-call
refusal; the socket guard is the net beneath it and is not installed in a test). What it does not, stated:

* effects behind data (a real id, a corpus with articles) were not driven, and the routes that answer 4xx never reached their handler
  body (74 on the full install on 2026-10-27); the database is the suite's shared one, whatever earlier tests left in it;
* a file CREATED AND REMOVED inside one request is not seen: ``GET /api/database/backup`` writes ``snapshot.db`` into the data folder and
  removes it after streaming (it has its own cross-site guard, R214);
* effects are attributed by the request's time window, so work from a long-running background thread lands on a later route (the
  ambient tables absorb the known writers) and an effect after the last request is lost;
* a file allowance matches the file's basename anywhere under the data folders, a REMOVED file is accounted for like a changed one, and a
  thread allowance matches by name only;
* the app's local-model autostart is off in the suite (``OO_LLM_AUTOSTART=0``), so a GET that would start a model server in production
  is not run; programs are caught through ``subprocess.Popen``, ``os.system`` and ``os.posix_spawn`` (not a raw ``os.fork``);
* the monitors see this process's own threads, files and sockets, not a subprocess.
"""

from __future__ import annotations

import _thread
import errno
import importlib.util
import ipaddress
import os
import re
import shlex
import socket
import sqlite3
import subprocess
import threading
import traceback
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.database.statement_kind import is_plain_read
from src.safety.file_lock import temp_name

# The number of GET operations the schema listed on 2026-10-27. A floor: new routes are driven by the same loop; fewer means the walk
# went blind (a framework change in how the schema is built) and every assertion below would loop over nothing. The Core-only
# install (no [analysis] extra) mounts 3 fewer GETs, because the commodity, statistical-analysis and article-similarity routes are
# disabled there: 464, reproduced by blocking numpy/pandas/scipy/sklearn/statsmodels (R283: a floor states both install profiles).
_OPERATIONS_FLOOR_FULL = 467
_OPERATIONS_FLOOR_CORE_ONLY = 464


def _analysis_extra_installed() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("numpy", "pandas", "scipy", "sklearn", "statsmodels"))


_OPERATIONS_FLOOR = _OPERATIONS_FLOOR_FULL if _analysis_extra_installed() else _OPERATIONS_FLOOR_CORE_ONLY

# --------------------------------------------------------------------------------------------------------------- #
# What a GET may do, with the reason. A file is matched by its NAME (the data directory is the suite's, and a few
# routes write under a sub-folder), a thread by its name.
# --------------------------------------------------------------------------------------------------------------- #

# Local telemetry and logs any request may touch (a background sampler or the error log), bounded files that carry no
# secret and are never transmitted.
_AMBIENT_FILES = frozenset(
    {
        "app_errors.jsonl",  # a 4xx/5xx answer appends one line to the local error log
        "app_errors.jsonl.lock",  # its lock file, created by the first write in the process (which request that is depends on test order)
        "native_inflight.bin",  # the crash black box (a fixed-size mmap), created by its first use in the process
        "session_hwm.json",  # the session high-water-mark sampler
        "session_liveness.json",
        "session_pressure.json",
        "criteria_calibration_cursor.json",
        "vitals_history.json",  # the vitals sampler's history
        "storage_events.json",
        "briefing_cache.json",  # derived: the briefing refresh thread writes it whenever a request started one
    }
)
# The main database file (and its WAL) is touched by a checkpoint or a connection close without any write statement, so a file change
# is not evidence of a write: the SQL monitor is the write detector.
_MAIN_DB = re.compile(r"open_omniscience\.db(-wal|-shm)?")
# Threads the server itself runs: its worker pool, the boot sequence, the poll refresher and the served caches that several routes share
# (derived data, rebuilt from what is stored).
_AMBIENT_THREAD = re.compile(r"AnyIO worker thread|oo-boot-sequence|alerts-poll-refresh|served-cache-.*")

# Route -> (files it may create or change, thread names it may start, reason). A route can appear only if the effect was
# MEASURED on 2026-10-27; the reason says why it is acceptable or names the finding that routes it.
_DIAG_THREADS = frozenset({"dbg:*", "ThreadPoolExecutor-*", "all-diag-member"})
_ROUTES: dict[str, tuple[frozenset[str], frozenset[str], str]] = {
    "/api/annotations/export": (
        frozenset({"annotations_ed25519.pem"}), frozenset(),
        "FINDING F2 (routed to RC2, R278): the first export mints the annotations signing key; a GET should not create a key (a cross-site request is refused since #1526; a same-origin one still mints it)",
    ),
    "/api/custody/export": (
        frozenset({"custody_log.db", "custody_log.db-wal", "custody_log.db-shm", "custody_ed25519.pem"}), frozenset(),
        "FINDING F2 (routed to RC2, R278): the first export creates the custody signing key and writes the custody log",
    ),
    "/api/articles": (
        frozenset({"search_timing_browse.jsonl"}), frozenset(),
        "appends one timing line to the local search-timing log (bounded, never transmitted)",
    ),
    "/api/briefing": (frozenset(), frozenset({"oo-briefing-refresh"}), "starts the briefing refresh in a daemon thread: derived data, de-duplicated by its slot"),
    "/api/scheduler/activity": (frozenset(), frozenset({"oo-plan-preview"}), "computes the plan preview in a daemon thread: derived, cached by its key"),
    "/api/diagnostics/all": (
        frozenset({"keyword-coverage.json"}), _DIAG_THREADS,
        "FINDING F1 (routed to RC2, R278): collector threads and diagnostics files from one GET; #1526's cross-site guard now stops another site triggering it; a same-origin call still does",
    ),
    "/api/diagnostics/debug-bundle": (frozenset(), _DIAG_THREADS, "FINDING F1 (routed): the bundle's collectors, one thread each"),
    "/api/diagnostics/keyword-engine": (frozenset({"keyword-coverage.json"}), frozenset(), "writes the keyword coverage record it reports"),
    "/api/diagnostics/llm-throughput-selftest": (
        frozenset(), _DIAG_THREADS, "FINDING F1 (routed): a thread pool against the local model, loopback only",
    ),
    "/api/diagnostics/recursive-loop": (
        frozenset(), _DIAG_THREADS, "FINDING F1 (routed): a thread pool against the local model, loopback only",
    ),
}
# Routes allowed to attempt a LOOPBACK connect (the local model servers: Ollama 11434, vLLM 8001). Nothing else may open a socket,
# and no route may reach a non-loopback address with the kill switch engaged.
_LOOPBACK_ROUTES = re.compile(r"^/api/(llm/.*|diagnostics/(ai|all|debug-bundle|llm-bench|llm-throughput|llm-throughput-selftest|recursive-loop))$")
# A GET issues no write statement through the app's engine (INSERT, UPDATE, DELETE, REPLACE, CREATE, DROP, ALTER). Measured on
# 2026-10-27: none does. (The custody log is a file of its own, written outside the engine, and is accounted for above.)
_SQL_WRITES_ALLOWED: dict[str, frozenset[str]] = {}


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _final_names(name: str) -> set[str]:
    """The files a temp file may be the atomic write of. ``src.safety.file_lock.temp_name`` names a temp ``<name>.tmp.<pid>.<thread>``
    and some writers use a bare ``<name>.tmp``; either is accounted for by the same line as the file it becomes. Candidates are
    returned (``.json`` and a ``.<token>`` look alike), and the name itself is always one."""
    out = {name}
    m = re.fullmatch(r"(.+?)\.tmp(?:\.\d+){0,2}", name)
    if m:
        bare = m.group(1)
        out |= {bare, re.sub(r"\.[0-9A-Za-z_-]+$", "", bare)}
    return out


_TRANSACTION_CONTROL = frozenset({"COMMIT", "END", "ROLLBACK", "BEGIN", "SAVEPOINT", "RELEASE"})


def _write_kind(statement: str) -> str | None:
    """The kind of write a SQL statement is (``INSERT items``), or None for a read. Comments are stripped, then the repo's own allow-list
    classifier (``is_plain_read``, which treats an unknown statement as not a read) decides, so VACUUM [INTO], REINDEX, ATTACH,
    ``wal_checkpoint`` and the ``PRAGMA x(v)`` setter are writes here. ``WITH`` is a read to that classifier, so a write verb is
    searched for outside string literals and function calls."""
    s = re.sub(r"/\*.*?\*/|--[^\n]*", " ", statement, flags=re.S).strip()
    if not s:
        return None
    head = s.split(None, 1)[0].upper().rstrip(";(")
    if head in _TRANSACTION_CONTROL:
        return None
    if head == "WITH":
        bare = re.sub(r"'(?:[^']|'')*'|\"[^\"]*\"", "''", s)
        m = re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b(?!\s*\()", bare, re.I)
        if not m:
            return None
        head = m.group(1).upper()
    elif is_plain_read(s):
        return None
    m = re.search(r"(?:INTO|UPDATE|FROM|TABLE|INDEX|REPLACE)\s+(?:IF (?:NOT )?EXISTS\s+)?[\"`\[]?(\w+)", s, re.I)
    return f"{head} {m.group(1) if m else '?'}"


class _Monitor:
    """Context manager: records connects, lookups, thread starts, file changes, write statements and database-file changes while a
    request runs. ``watchers`` are long-lived read-only connections to the main database, opened by the caller: ``PRAGMA data_version``
    is only comparable on one connection, so the monitor reads it before and after."""

    def __init__(self, dirs: list[Path], watchers: tuple[sqlite3.Connection, ...] = ()) -> None:
        self.dirs = dirs
        self.watchers = watchers
        self.connects: list[str] = []
        self.lookups: list[str] = []
        self.threads: list[str] = []
        self.files: set[str] = set()
        self.sql_writes: list[str] = []
        self.processes: list[str] = []
        self.db_changed = False
        self._saved: dict[tuple[object, str], object] = {}

    def _snapshot(self) -> dict[Path, tuple[int, int]]:
        out: dict[Path, tuple[int, int]] = {}
        for base in self.dirs:
            for p in base.rglob("*"):
                try:
                    if p.is_file():
                        st = p.stat()
                        out[p] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
        return out

    def _versions(self) -> list[int]:
        return [w.execute("PRAGMA data_version").fetchone()[0] for w in self.watchers]

    def _patch(self, owner: object, name: str, replacement) -> None:  # noqa: ANN001
        self._saved[(owner, name)] = getattr(owner, name)
        setattr(owner, name, replacement)

    def __enter__(self) -> _Monitor:
        self._before = self._snapshot()
        self._dv_before = self._versions()
        monitor = self
        real_start = threading.Thread.start
        real_gai = socket.getaddrinfo

        def host_of(address) -> str:  # noqa: ANN001
            return str(address[0]) if isinstance(address, tuple) else str(address)

        def connect(sock, address, *a, **k):  # noqa: ANN001
            monitor.connects.append(host_of(address))
            raise OSError(f"blocked by the side-effect monitor: {address!r}")

        def connect_ex(sock, address, *a, **k):  # noqa: ANN001
            monitor.connects.append(host_of(address))
            return errno.ECONNREFUSED

        def sendto(sock, data, *args):  # noqa: ANN001
            address = args[-1] if args else None
            monitor.connects.append(host_of(address))
            raise OSError(f"blocked by the side-effect monitor: {address!r}")

        def getaddrinfo(host, *a, **k):  # noqa: ANN001
            if isinstance(host, str) and _is_loopback(host):
                return real_gai(host, *a, **k)
            monitor.lookups.append(str(host))
            raise OSError(f"blocked by the side-effect monitor: {host!r}")

        def gethostbyname(host, *a, **k):  # noqa: ANN001
            if isinstance(host, str) and _is_loopback(host):
                return "127.0.0.1"
            monitor.lookups.append(str(host))
            raise OSError(f"blocked by the side-effect monitor: {host!r}")

        def start(thread, *a, **k):  # noqa: ANN001
            stack = "".join(f.filename for f in traceback.extract_stack(limit=12))
            if "limits/storage/memory" not in stack.replace("\\", "/"):  # the rate limiter's own expiry timer
                monitor.threads.append(thread.name)
            return real_start(thread, *a, **k)

        real_raw_start = _thread.start_new_thread

        def raw_start(function, args, kwargs=None):  # noqa: ANN001
            monitor.threads.append("<_thread.start_new_thread>")
            return real_raw_start(function, args) if kwargs is None else real_raw_start(function, args, kwargs)

        def program_of(args) -> str:  # noqa: ANN001
            first = args if isinstance(args, (str, bytes, os.PathLike)) else (list(args) or [""])[0]
            if isinstance(first, str) and " " in first and not os.path.exists(first):
                first = (shlex.split(first) or [""])[0]
            return os.path.basename(os.fsdecode(first))

        real_popen_init = subprocess.Popen.__init__

        def popen_init(proc, args, *a, **k):  # noqa: ANN001
            monitor.processes.append(program_of(args))
            return real_popen_init(proc, args, *a, **k)

        real_system = os.system
        real_posix_spawn = getattr(os, "posix_spawn", None)

        def system(command):  # noqa: ANN001
            monitor.processes.append("os.system:" + program_of(command))
            return real_system(command)

        def posix_spawn(path, *a, **k):  # noqa: ANN001
            monitor.processes.append(program_of(path))
            return real_posix_spawn(path, *a, **k)

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        def before_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            kind = _write_kind(statement)
            if kind:
                monitor.sql_writes.append(kind)

        self._sql_listener = before_execute
        event.listen(Engine, "before_cursor_execute", before_execute)
        self._patch(socket.socket, "connect", connect)
        self._patch(socket.socket, "connect_ex", connect_ex)
        self._patch(socket.socket, "sendto", sendto)
        self._patch(socket, "getaddrinfo", getaddrinfo)
        self._patch(socket, "gethostbyname", gethostbyname)
        self._patch(socket, "gethostbyname_ex", lambda host, *a, **k: ([host], [], [gethostbyname(host)]))
        self._patch(threading.Thread, "start", start)
        self._patch(_thread, "start_new_thread", raw_start)
        self._patch(subprocess.Popen, "__init__", popen_init)
        self._patch(os, "system", system)
        if real_posix_spawn is not None:
            self._patch(os, "posix_spawn", posix_spawn)
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        for (owner, name), original in self._saved.items():
            setattr(owner, name, original)
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        event.remove(Engine, "before_cursor_execute", self._sql_listener)
        after = self._snapshot()
        for p, sig in after.items():
            if self._before.get(p) != sig:
                self.files.add(p.name)
        for p in self._before.keys() - after.keys():  # removed
            self.files.add(p.name)
        self.db_changed = self._versions() != self._dv_before


# Hidden from the schema, so the walk below would never see them: pinned to the source by test_the_hidden_gets_are_the_ones_driven.
_HIDDEN_GETS = ("/favicon.ico", "/unlock", "/desk", "/static/oo.js", "/metrics/")
_HIDDEN_FROM_SCHEMA = {"/favicon.ico", "/unlock", "/desk"}
_MOUNTS = {"/static", "/metrics"}


def _get_operations(app) -> list[tuple[str, str]]:
    """(schema path, concrete url) for every GET operation; ``{id}`` becomes 1 and a required query parameter becomes 1."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        op = ops.get("get")
        if op is None:
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        required = [p["name"] for p in op.get("parameters", []) if p.get("required") and p.get("in") == "query"]
        out.append((path, concrete + ("?" + "&".join(f"{n}=1" for n in required) if required else "")))
    return sorted(out)


class _Walk:
    def __init__(self, seen: dict[str, _Monitor], statuses: dict[str, int], schema_paths: set[str], watch_note: str | None) -> None:
        self.seen = seen
        self.statuses = statuses
        self.schema_paths = schema_paths
        self.watch_note = watch_note  # None when the main database file was watched; else why not


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    """Drive every GET once, kill switch engaged; a ``_Walk``. Module-scoped: it is the one expensive step."""
    import os

    data = tmp_path_factory.mktemp("get-effects")
    saved = {k: os.environ.get(k) for k in ("OO_DATA_DIR", "OO_NO_SCHEDULER")}
    os.environ["OO_DATA_DIR"] = str(data)
    os.environ["OO_NO_SCHEDULER"] = "1"
    watchers: list[sqlite3.Connection] = []
    watch_note: str | None = "the main database is not a SQLite file"
    try:
        from src.api.main import app
        from src.database import session as dbsession
        from src.ingest import activate_kill_switch, clear_kill_switch

        dirs = [data]
        suite_dir = Path(str(dbsession.DATA_DIR))
        if suite_dir.resolve() != data.resolve():
            dirs.append(suite_dir)
        ops = _get_operations(app)
        schema_paths = {path for path, _ in ops}
        ops += [(h, h) for h in _HIDDEN_GETS]
        seen: dict[str, _Monitor] = {}
        statuses: dict[str, int] = {}
        # raise_server_exceptions=False: a handler that raises answers 500 and is NAMED by test_no_get_answers_a_server_error, instead of
        # killing the walk and every test that shares it.
        with TestClient(app, raise_server_exceptions=False) as client:
            db_file = getattr(dbsession, "DB_FILE", None)
            if db_file and not Path(db_file).exists():
                watch_note = f"MISSING: the main database file {db_file} does not exist after the app started"
            elif db_file:
                try:
                    watchers.append(sqlite3.connect(f"file:{db_file}?mode=ro", uri=True))
                    watchers[0].execute("PRAGMA data_version").fetchone()
                    watch_note = None
                except sqlite3.DatabaseError as exc:  # an encrypted store is not readable without its key
                    watchers.clear()
                    watch_note = f"the main database could not be opened for watching ({exc}); the file check is skipped"
            # Warm up outside any monitor: the first 4xx of the process creates the error log's lock file, and which request first
            # creates the crash black box (a diagnostics GET) depends on the tests that ran before this file; that file has its own ambient row.
            client.get("/api/no-such-route-warm-up", headers={"Host": "testserver"})
            activate_kill_switch()
            try:
                for path, url in ops:
                    with _Monitor(dirs, tuple(watchers)) as mon:
                        statuses[path] = client.get(url, headers={"Host": "testserver"}).status_code
                    seen[path] = mon
            finally:
                clear_kill_switch()
        yield _Walk(seen, statuses, schema_paths, watch_note)
    finally:
        for w in watchers:
            w.close()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_walk_still_sees_the_routes(observed):
    assert len(observed.schema_paths) >= _OPERATIONS_FLOOR, (
        f"the schema lists {len(observed.schema_paths)} GET operations, fewer than the {_OPERATIONS_FLOOR} it listed on 2026-10-27: "
        "routes were removed (lower the floor, with a reason) or the walk went blind"
    )
    assert set(_HIDDEN_GETS) <= set(observed.seen), "a hidden GET was not driven"
    # 393 of 467 answered 2xx on 2026-10-27 (391 of 464 Core-only); 350 leaves room for routes that start answering 4xx on a database a
    # earlier test left in an odd state, and still fails a walk that drives nothing.
    assert sum(1 for s in observed.statuses.values() if 200 <= s < 300) >= 350, "most GETs should answer 2xx"


# A GET that raises answers 500 and is named here. Empty: none does on 2026-10-27.
_SERVER_ERRORS_ALLOWED: frozenset[str] = frozenset()


def test_no_get_answers_a_server_error(observed):
    bad = sorted(p for p, s in observed.statuses.items() if s >= 500 and p not in _SERVER_ERRORS_ALLOWED)
    assert not bad, f"these GETs answered a 5xx (a handler raised, or the app refused it): {bad}"


def test_no_get_reaches_a_non_loopback_address_with_the_kill_switch_engaged(observed):
    bad = {
        p: m.lookups + [c for c in m.connects if not _is_loopback(c)]
        for p, m in observed.seen.items()
        if m.lookups or any(not _is_loopback(c) for c in m.connects)
    }
    assert not bad, f"these GETs tried to reach the network with the kill switch engaged (per-call refusal missing): {bad}"


def test_only_the_listed_routes_open_a_loopback_socket(observed):
    bad = sorted(p for p, m in observed.seen.items() if m.connects and not _LOOPBACK_ROUTES.match(p))
    assert not bad, f"these GETs opened a socket and are not in _LOOPBACK_ROUTES (the local model servers): {bad}"


def test_every_started_thread_and_written_file_is_accounted_for(observed):
    problems = []
    for path, m in observed.seen.items():
        files_ok, threads_ok, _reason = _ROUTES.get(path, (frozenset(), frozenset(), ""))
        for name in sorted(n for n in m.files if not _final_names(n) & (_AMBIENT_FILES | files_ok)):
            if _MAIN_DB.fullmatch(name):
                continue
            problems.append((path, "file", name))
        for name in sorted(set(m.threads)):
            if _AMBIENT_THREAD.fullmatch(name):
                continue
            if any(re.fullmatch(pat.replace("*", ".*"), name) for pat in threads_ok):
                continue
            problems.append((path, "thread", name))
    assert not problems, (
        "these GETs wrote, changed or removed a file or started a thread that no table accounts for (add a line to _ROUTES with the "
        f"reason, or guard the route): {problems}"
    )


def test_no_get_issues_a_write_statement_through_the_engine(observed):
    bad = {p: sorted(set(m.sql_writes) - _SQL_WRITES_ALLOWED.get(p, frozenset())) for p, m in observed.seen.items()}
    bad = {p: w for p, w in bad.items() if w}
    assert not bad, f"these GETs wrote to the database (INSERT/UPDATE/DELETE/DDL/PRAGMA x = y): {bad}"


def test_no_get_changes_the_main_database_file(observed):
    """The write detector above sees statements through the engine; this sees the file change from a second connection, so a raw
    ``sqlite3`` write is found too. Skipped when the suite's database is not a readable SQLite file; FAILS if the file is missing."""
    if observed.watch_note:
        assert not observed.watch_note.startswith("MISSING"), observed.watch_note
        pytest.skip(observed.watch_note)
    bad = sorted(p for p, m in observed.seen.items() if m.db_changed and p not in _SQL_WRITES_ALLOWED)
    assert not bad, (
        f"these GETs changed the main database file (seen from a second connection, PRAGMA data_version): {bad}. A "
        "wal_checkpoint(TRUNCATE) with no content change also moves it (src/database/repair.py), so a background thread's checkpoint can "
        "be reported against an innocent route: look at the route's own statements first"
    )


# Programs a GET may start, by basename, with the reason. Measured on 2026-10-27: about 30 GETs start one of these three.
_PROGRAMS_ALLOWED = {
    "nvidia-smi": "reads the GPU's name and memory (the /api/llm/*, /api/bulletin/* and diagnostics routes); a local query, no network",
    "uname": "reads the processor name; a local query",
    "xdg-user-dir": "reads the user's folders; a local query",
}


def test_every_started_program_is_a_listed_local_query(observed):
    bad = {p: sorted(set(m.processes) - set(_PROGRAMS_ALLOWED)) for p, m in observed.seen.items()}
    bad = {p: v for p, v in bad.items() if v}
    assert not bad, (
        "these GETs started a program that is not listed in _PROGRAMS_ALLOWED (a GET that shells out can reach the network past the kill "
        f"switch; list it with its reason, or guard the route): {bad}"
    )


def test_the_hidden_gets_are_the_ones_driven():
    """A GET hidden from the OpenAPI schema is not in the walk; so the walk drives a pinned list, and this reads the source so a hidden
    route or mount added later fails here instead of going unmeasured (the app's ``.routes`` is not read, per CLAUDE.md)."""
    api = Path(__file__).resolve().parent.parent / "src" / "api"
    hidden: set[str] = set()
    for f in api.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        hidden |= set(re.findall(r'@\w+\.get\(\s*"([^"]+)"[^)]*include_in_schema=False', text))
        assert text.count("include_in_schema=False") == len(re.findall(r'@\w+\.get\(\s*"[^"]+"[^)]*include_in_schema=False', text)), (
            f"{f.name}: a route hidden from the schema that is not a plain @x.get(...) decorator, which this test does not pin"
        )
    assert hidden == _HIDDEN_FROM_SCHEMA, f"routes hidden from the schema are {sorted(hidden)}: drive the new one in _HIDDEN_GETS"
    mounts = set(re.findall(r'app\.mount\(\s*"([^"]+)"', (api / "main.py").read_text(encoding="utf-8")))
    assert mounts == _MOUNTS, f"main.py mounts {sorted(mounts)}: drive the new one in _HIDDEN_GETS"


# FINDING rows whose GET does work a foreign page could trigger and that do NOT yet refuse a cross-site request (R278 routes the guard
# to RC2; each leaves this set in the PR that guards it). Empty on 2026-10-27, after #1526.
_FINDINGS_NOT_YET_GUARDED: frozenset[str] = frozenset()


def test_every_finding_route_refuses_a_cross_site_request():
    """The FINDING rows are GETs that do work on the machine (heavy compute, a signing key minted). The measured effect stays listed
    above, because a same-origin caller may still cause it; what changed with ``refuse_cross_site_get`` is that another site's page
    cannot. This keeps that true route by route, so a guard dropped in a refactor fails here by name."""
    from src.api.main import app

    routes = sorted(p for p, (_f, _t, reason) in _ROUTES.items() if reason.startswith("FINDING") and p not in _FINDINGS_NOT_YET_GUARDED)
    assert routes, "no FINDING row left to pin"
    with TestClient(app, raise_server_exceptions=False) as client:
        bad = {}
        for path in routes:
            r = client.get(path, headers={"Host": "testserver", "Sec-Fetch-Site": "cross-site"})
            if r.status_code != 403:
                bad[path] = r.status_code
    assert not bad, f"these FINDING routes served a cross-site request (add refuse_cross_site_get, or list them in _FINDINGS_NOT_YET_GUARDED): {bad}"


def test_the_table_names_real_routes_with_reasons(observed):
    missing = sorted(set(_ROUTES) - set(observed.seen))
    assert not missing, f"_ROUTES names routes the schema no longer lists: {missing}"
    assert all(reason.strip() for _, _, reason in _ROUTES.values())


def test_the_monitors_see_a_get_that_reaches_the_network_when_the_switch_is_off(tmp_path, monkeypatch):
    """Liveness of the monitors, so a green run is not a blind one: with the kill switch CLEARED, ``/api/hazards`` goes for its two
    hosts, and the monitor must record both lookups. (With the switch engaged, the test above asserts it does not.)"""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from src.api.main import app
    from src.ingest import clear_kill_switch

    with TestClient(app) as client:
        clear_kill_switch()
        with _Monitor([tmp_path]) as mon:
            client.get("/api/hazards", headers={"Host": "testserver"})
    assert {"earthquake.usgs.gov", "www.gdacs.org"} <= set(mon.lookups), mon.lookups


def test_the_monitors_see_every_socket_call_they_patch(tmp_path):
    with _Monitor([tmp_path]) as mon:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(OSError):
            s.connect(("192.0.2.1", 9))
        assert s.connect_ex(("192.0.2.2", 9)) == errno.ECONNREFUSED
        s.close()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(OSError):
            u.sendto(b"x", ("192.0.2.3", 9))
        u.close()
        with pytest.raises(OSError):
            socket.gethostbyname("probe-a.invalid")
        with pytest.raises(OSError):
            socket.gethostbyname_ex("probe-b.invalid")
        with pytest.raises(OSError):
            socket.getaddrinfo("probe-c.invalid", 80)
    assert mon.connects == ["192.0.2.1", "192.0.2.2", "192.0.2.3"], mon.connects
    assert mon.lookups == ["probe-a.invalid", "probe-b.invalid", "probe-c.invalid"], mon.lookups


def test_the_monitors_see_a_thread_a_file_a_removal_and_a_write(tmp_path):
    from sqlalchemy import text

    from src.database import session as dbsession

    (tmp_path / "doomed.txt").write_text("x")
    db = tmp_path / "probe.db"
    sqlite3.connect(db).close()
    watcher = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    watcher.execute("PRAGMA data_version").fetchone()
    with _Monitor([tmp_path], (watcher,)) as mon:
        t = threading.Thread(target=lambda: None, name="probe-thread")
        t.start()
        t.join()
        _thread.start_new_thread(lambda: None, ())
        (tmp_path / "probe.txt").write_text("x")
        (tmp_path / "doomed.txt").unlink()
        with dbsession.engine.connect() as conn:  # a TEMP table: nothing outlives the connection
            conn.execute(text("CREATE TEMP TABLE oo_monitor_probe (x INTEGER)"))
            conn.execute(text("INSERT INTO oo_monitor_probe (x) VALUES (1)"))
            conn.execute(text("/* c */ WITH s AS (SELECT 1) DELETE FROM oo_monitor_probe"))
        raw = sqlite3.connect(db)  # a write that does not pass through the engine
        raw.execute("CREATE TABLE t (x)")
        raw.commit()
        raw.close()
    watcher.close()
    assert {"probe-thread", "<_thread.start_new_thread>"} <= set(mon.threads), mon.threads
    assert not mon.processes
    assert {"probe.txt", "doomed.txt"} <= mon.files, mon.files
    assert {"CREATE oo_monitor_probe", "INSERT oo_monitor_probe", "DELETE oo_monitor_probe"} <= set(mon.sql_writes), mon.sql_writes
    assert mon.db_changed


def test_the_monitors_see_a_program_start(tmp_path):
    with _Monitor([tmp_path]) as mon:
        subprocess.run(["uname", "-p"], capture_output=True, check=False)
        os.system("true")
    assert mon.processes == ["uname", "os.system:true"], mon.processes


def test_write_kind_reads_what_it_should():
    assert _write_kind("SELECT 1") is None
    assert _write_kind("PRAGMA journal_mode") is None
    assert _write_kind("PRAGMA journal_mode = WAL") == "PRAGMA ?"
    assert _write_kind("/* x */ -- y\nINSERT INTO a (x) VALUES (1)") == "INSERT a"
    assert _write_kind("WITH s AS (SELECT 1) DELETE FROM a") == "DELETE a"
    assert _write_kind("WITH s AS (SELECT 1) SELECT * FROM s") is None
    assert _write_kind("WITH s AS (SELECT replace('a','b','c'), 'delete' AS \"update\") SELECT * FROM s") is None
    assert _write_kind("WITH s AS (SELECT 1) INSERT INTO a SELECT * FROM s") == "INSERT a"
    for write in ("VACUUM INTO '/tmp/x.db'", "REINDEX", "ATTACH 'x.db' AS y", "PRAGMA wal_checkpoint(TRUNCATE)", "PRAGMA user_version(3)",
                  "PRAGMA journal_mode\n= WAL", "INSERT OR REPLACE INTO a (x) VALUES (1)", "REPLACE INTO a (x) VALUES (1)", "ANALYZE"):
        assert _write_kind(write), write
    for read in ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT s", "PRAGMA table_info(note)", "EXPLAIN SELECT 1", "SELECT 1"):
        assert _write_kind(read) is None, read


def test_an_atomic_write_temp_file_is_accounted_for_by_the_file_it_becomes():
    real = temp_name(Path("/data/session_hwm.json")).name  # the form the app's atomic writers produce: <name>.tmp.<pid>.<thread>
    assert "session_hwm.json" in _final_names(real), real
    assert "storage_events.json" in _final_names("storage_events.json.tmp")
    assert _final_names("app_errors.jsonl") == {"app_errors.jsonl"}
    assert not _final_names("unlisted.tmp.12.34") & _AMBIENT_FILES
