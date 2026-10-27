"""Every GET operation of the app is driven once and what it DOES beyond reading is accounted for (audit 0.5.0 item 35 follow-on, P3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/SECURITY.md`` ("The local API") names what stands between a cross-site page and a state-changing request. A ``GET`` is not
state-changing to the Origin middleware, so the Host guard alone stands in front of it, and a page the person visits can fire any GET
with an ``<img src>``. What a GET may then do is therefore a security fact, and a name-based net does not find it (an AST scan for
side-effect call names matched all 470 handlers). So this file MEASURES it, the way ``test_destructive_surfaces.py`` reads instead of
trusting names: every ``GET`` operation in the app's own OpenAPI schema is driven once, with the network kill switch engaged (the
state the app boots in), while four monitors record

* a socket connect or a DNS lookup (blocked and recorded; loopback is told apart from the rest),
* a thread started (the rate limiter's own expiry timer, found by its stack, and the server's worker threads are not counted),
* a file created or changed under the data directory,
* a change to a database file.

and each observed effect must be in a table below with the reason it is acceptable. A NEW GET that opens a socket, starts a thread,
writes a file or touches the database fails here by name until it is guarded or listed; the way out is to add a line with a reason that
a reviewer then reads. The table of 2026-10-27 is ``audit-0.5.0/get-side-effects-2026-10-27.md`` (its findings are routed, not fixed here).

What this proves, stated: with the kill switch engaged no GET reaches a non-loopback address (a per-call refusal; the socket guard is
the net beneath it and is not installed in a test). What it does not: effects behind data (a real id, a corpus with articles) were not
driven, the 65 routes that answer 4xx on an empty corpus never reached their handler body, and the monitors see the process's own
threads, files and sockets, not a subprocess.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
import traceback
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# The number of GET operations the schema listed on 2026-10-27. A floor: new routes are driven by the same loop; fewer means the walk
# went blind (a framework change in how the schema is built) and every assertion below would loop over nothing.
_OPERATIONS_FLOOR = 467

# --------------------------------------------------------------------------------------------------------------- #
# What a GET may do, with the reason. A file is matched by its NAME (the data directory is the suite's, and a few
# routes write under a sub-folder), a thread by its name.
# --------------------------------------------------------------------------------------------------------------- #

# Local telemetry and logs any request may touch (a background sampler or the error log), bounded files that carry no
# secret and are never transmitted.
_AMBIENT_FILES = frozenset(
    {
        "app_errors.jsonl",  # a 4xx/5xx answer appends one line to the local error log
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
        "FINDING F2 (routed to RC2, R278): the first export mints the annotations signing key; a GET should not create a key",
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
        "FINDING F1 (routed to RC2, R278): collector threads and diagnostics files from one GET; the cross-site guard is the fix",
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


class _Monitor:
    """Context manager: records connects, lookups, thread starts and file changes while a request runs."""

    def __init__(self, dirs: list[Path]) -> None:
        self.dirs = dirs
        self.connects: list[str] = []
        self.lookups: list[str] = []
        self.threads: list[str] = []
        self.files: set[str] = set()
        self.sql_writes: list[str] = []
        self._saved: dict[str, object] = {}

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

    def __enter__(self) -> _Monitor:
        self._before = self._snapshot()
        monitor = self
        self._saved["connect"] = socket.socket.connect
        self._saved["getaddrinfo"] = socket.getaddrinfo
        self._saved["start"] = threading.Thread.start
        real_start = threading.Thread.start

        def connect(sock, address, *a, **k):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else str(address)
            monitor.connects.append(str(host))
            raise OSError(f"blocked by the side-effect monitor: {address!r}")

        real_gai = socket.getaddrinfo

        def getaddrinfo(host, *a, **k):  # noqa: ANN001
            if isinstance(host, str) and _is_loopback(host):
                return real_gai(host, *a, **k)
            monitor.lookups.append(str(host))
            raise OSError(f"blocked by the side-effect monitor: {host!r}")

        def start(thread, *a, **k):  # noqa: ANN001
            stack = "".join(f.filename for f in traceback.extract_stack(limit=12))
            if "limits/storage/memory" not in stack.replace("\\", "/"):  # the rate limiter's own expiry timer
                monitor.threads.append(thread.name)
            return real_start(thread, *a, **k)

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        def before_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            word = statement.lstrip()[:7].upper()
            if word.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")):
                m = re.search(r"(?:INTO|UPDATE|FROM|TABLE|INDEX|REPLACE)\s+(?:IF (?:NOT )?EXISTS\s+)?[\"`\[]?(\w+)", statement, re.I)
                monitor.sql_writes.append(f"{word.split()[0]} {m.group(1) if m else '?'}")

        self._sql_listener = before_execute
        event.listen(Engine, "before_cursor_execute", before_execute)
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
        threading.Thread.start = start  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        socket.socket.connect = self._saved["connect"]  # type: ignore[method-assign]
        socket.getaddrinfo = self._saved["getaddrinfo"]  # type: ignore[assignment]
        threading.Thread.start = self._saved["start"]  # type: ignore[method-assign]
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        event.remove(Engine, "before_cursor_execute", self._sql_listener)
        after = self._snapshot()
        for p, sig in after.items():
            if self._before.get(p) != sig:
                self.files.add(p.name)


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


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    """Drive every GET once, kill switch engaged; ``{path: _Monitor}``. Module-scoped: it is the one expensive step."""
    import os

    data = tmp_path_factory.mktemp("get-effects")
    saved = {k: os.environ.get(k) for k in ("OO_DATA_DIR", "OO_NO_SCHEDULER")}
    os.environ["OO_DATA_DIR"] = str(data)
    os.environ["OO_NO_SCHEDULER"] = "1"
    try:
        from src.api.main import app
        from src.database import session as dbsession
        from src.ingest import activate_kill_switch, clear_kill_switch

        dirs = [data]
        suite_dir = Path(str(dbsession.DATA_DIR))
        if suite_dir.resolve() != data.resolve():
            dirs.append(suite_dir)
        ops = _get_operations(app)
        seen: dict[str, _Monitor] = {}
        statuses: dict[str, int] = {}
        with TestClient(app) as client:
            activate_kill_switch()
            try:
                for path, url in ops:
                    with _Monitor(dirs) as mon:
                        statuses[path] = client.get(url, headers={"Host": "testserver"}).status_code
                    seen[path] = mon
            finally:
                clear_kill_switch()
        yield seen, statuses
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_walk_still_sees_the_routes(observed):
    seen, statuses = observed
    assert len(seen) >= _OPERATIONS_FLOOR, (
        f"the schema lists {len(seen)} GET operations, fewer than the {_OPERATIONS_FLOOR} it listed on 2026-10-27: routes were "
        "removed (lower the floor, with a reason) or the walk went blind"
    )
    assert sum(1 for s in statuses.values() if 200 <= s < 300) >= 350, "most GETs should answer 2xx on an empty corpus"


def test_no_get_reaches_a_non_loopback_address_with_the_kill_switch_engaged(observed):
    seen, _ = observed
    bad = {
        p: m.lookups + [c for c in m.connects if not _is_loopback(c)]
        for p, m in seen.items()
        if m.lookups or any(not _is_loopback(c) for c in m.connects)
    }
    assert not bad, f"these GETs tried to reach the network with the kill switch engaged (per-call refusal missing): {bad}"


def test_only_the_listed_routes_open_a_loopback_socket(observed):
    seen, _ = observed
    bad = sorted(p for p, m in seen.items() if m.connects and not _LOOPBACK_ROUTES.match(p))
    assert not bad, f"these GETs opened a socket and are not in _LOOPBACK_ROUTES (the local model servers): {bad}"


def test_every_started_thread_and_written_file_is_accounted_for(observed):
    seen, _ = observed
    problems = []
    for path, m in seen.items():
        files_ok, threads_ok, _reason = _ROUTES.get(path, (frozenset(), frozenset(), ""))
        for name in sorted(m.files - _AMBIENT_FILES - files_ok):
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
        "these GETs wrote a file or started a thread that no table accounts for (add a line to _ROUTES with the reason, or guard the "
        f"route): {problems}"
    )


def test_no_get_issues_a_write_statement_through_the_engine(observed):
    seen, _ = observed
    bad = {p: sorted(set(m.sql_writes) - _SQL_WRITES_ALLOWED.get(p, frozenset())) for p, m in seen.items()}
    bad = {p: w for p, w in bad.items() if w}
    assert not bad, f"these GETs wrote to the database (INSERT/UPDATE/DELETE/DDL): {bad}"


def test_the_table_names_real_routes_with_reasons(observed):
    seen, _ = observed
    missing = sorted(set(_ROUTES) - set(seen))
    assert not missing, f"_ROUTES names routes the schema no longer lists: {missing}"
    assert all(reason.strip() for _, _, reason in _ROUTES.values())


def test_the_monitors_see_a_get_that_reaches_the_network_when_the_switch_is_off(tmp_path, monkeypatch):
    """Liveness of the four monitors, so a green run is not a blind one: with the kill switch CLEARED, ``/api/hazards`` goes for its two
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


def test_the_monitors_see_a_thread_a_file_and_a_write_statement(tmp_path):
    from sqlalchemy import text

    from src.database import session as dbsession

    with _Monitor([tmp_path]) as mon:
        t = threading.Thread(target=lambda: None, name="probe-thread")
        t.start()
        t.join()
        (tmp_path / "probe.txt").write_text("x")
        with dbsession.engine.connect() as conn:  # a TEMP table: nothing outlives the connection
            conn.execute(text("CREATE TEMP TABLE oo_monitor_probe (x INTEGER)"))
            conn.execute(text("INSERT INTO oo_monitor_probe (x) VALUES (1)"))
    assert "probe-thread" in mon.threads and "probe.txt" in mon.files
    assert {"CREATE oo_monitor_probe", "INSERT oo_monitor_probe"} <= set(mon.sql_writes), mon.sql_writes
