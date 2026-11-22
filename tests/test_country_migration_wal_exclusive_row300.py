"""Row 300 (R782): the country migration's exclusivity check holds on a WAL store.

The app opens its store in WAL mode (``src.database.session._sqlite_pragmas``), and WAL readers do not block writers, so
the question R782 asked was whether ``take_exclusive`` (``locking_mode=EXCLUSIVE``, then ``BEGIN IMMEDIATE``) could
miss an app that still holds the store. Measured on both engine legs, in this process and from another one, it does
not: every holder, idle, reading or writing, is refused within the busy timeout, and once taken the store stays
closed to everyone else across committed windows. The other direction holds too: a closed store, and one a crash left
with an un-checkpointed ``-wal``, is taken, and the rows only that ``-wal`` held are kept.

What makes a WAL store refuse where a rollback-journal one did not: an idle open connection on a WAL store keeps its
shared-memory lock, so a test that leaves a ``sqlite3`` connection open (``with sqlite3.connect(db) as c`` commits but
does NOT close) is refused, rightly. Every connection here is closed explicitly. sqlite3mc is not measured.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from src.backup.country_migration import AppStillRunning, take_exclusive
from src.database import connect as connect_mod
from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parents[1]
_TEST_KEY = "row300-throwaway-test-key"  # a test's own store; handed to a child through its environment, never argv
_LEGS = [
    pytest.param("plain", id="plaintext"),
    pytest.param(
        "enc",
        id="encrypted",
        marks=pytest.mark.skipif(not connect_mod.have_driver(), reason="sqlcipher3 not installed"),
    ),
]
# The child opens the store exactly as the parent does (the app's connect factory, WAL), then holds it as asked.
_HOLDER = textwrap.dedent(
    """
    import os, sys, time
    from src.database.connect import connect
    key = os.environ.get("ROW300_KEY") or None
    c = connect(sys.argv[1], key=key, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("SELECT count(*) FROM t").fetchone()
    if sys.argv[2] == "read":
        c.execute("BEGIN")
        c.execute("SELECT * FROM t").fetchall()
    elif sys.argv[2] == "write":
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO t VALUES (7)")
    print("held", flush=True)
    sys.stdin.read()  # held until the parent closes our stdin
    c.close()
    """
)
_READER = textwrap.dedent(
    """
    import os, sys
    from src.database.connect import connect
    key = os.environ.get("ROW300_KEY") or None
    try:
        c = connect(sys.argv[1], key=key, check_same_thread=False, timeout=0.5)
        try:
            c.execute("SELECT count(*) FROM t").fetchone()
            print("read")
        finally:
            c.close()
    except Exception as exc:
        from src.database.connect import StoreHeldError
        from src.database.write import is_locked_error
        # only a refusal BECAUSE the store is held counts; any other failure (a lost key, a damaged file) says so
        held = isinstance(exc, StoreHeldError) or is_locked_error(exc)
        print("refused-held" if held else "failed-otherwise", type(exc).__name__)
    """
)


def _key(leg: str) -> str | None:
    return _TEST_KEY if leg == "enc" else None


def _open(path: Path, leg: str, *, timeout: float = 0.5):
    return connect_mod.connect(path, key=_key(leg), create_encrypted=(leg == "enc"), check_same_thread=False, timeout=timeout)


def _store(tmp_path: Path, leg: str) -> Path:
    """A WAL store with one table and two rows, every connection closed."""
    path = tmp_path / "store.db"
    if leg == "plain":
        eng = app_sqlite_engine(path)
        try:
            with eng.begin() as c:
                c.exec_driver_sql("CREATE TABLE t (x INTEGER)")
                c.exec_driver_sql("INSERT INTO t VALUES (1), (2)")
        finally:
            eng.dispose()
    else:
        con = _open(path, leg)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE t (x INTEGER)")
            con.execute("INSERT INTO t VALUES (1), (2)")
            con.commit()
        finally:
            con.close()
        assert connect_mod.is_encrypted_file(path) is True
    with contextlib.closing(_open(path, leg)) as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    return path


def _refused(path: Path, leg: str, *, timeout: float = 0.5) -> bool:
    """True when the take is refused; a take that wrongly succeeds is closed before the test fails on it."""
    con = _try_take(path, leg, timeout=timeout)
    if con is None:
        return True
    con.close()
    return False


def _try_take(path: Path, leg: str, *, timeout: float = 0.5):
    """The migration's own steps (``migrate`` opens with ``connect`` and autocommit off, then ``take_exclusive``)."""
    con = _open(path, leg, timeout=timeout)
    con.isolation_level = None
    try:
        take_exclusive(con)
    except AppStillRunning:
        con.close()
        return None
    return con


def _child_env(leg: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("ROW300_KEY", None)
    if leg == "enc":
        env["ROW300_KEY"] = _TEST_KEY
    else:
        env["OO_DB_PLAINTEXT"] = "1"
    return env


@contextlib.contextmanager
def _holder_process(path: Path, leg: str, mode: str):
    with subprocess.Popen(  # the context closes stdin, stdout and stderr, and waits
        [sys.executable, "-c", _HOLDER, str(path), mode],
        cwd=ROOT, env=_child_env(leg), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as proc:
        try:
            line = proc.stdout.readline().strip()
            if line != "held":
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=30)
                pytest.fail(f"the holder did not start: {line!r} {proc.stderr.read()[-500:]!r}")
            yield
        finally:
            with contextlib.suppress(Exception):
                proc.stdin.close()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _other_process_reads(path: Path, leg: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _READER, str(path)], cwd=ROOT, env=_child_env(leg), capture_output=True, text=True, timeout=60
    )
    return done.stdout.strip() + done.stderr.strip()[-300:]


# --------------------------------------------------------------------------------------------------------------------
# (b) under-detection: every holder is refused
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("leg", _LEGS)
@pytest.mark.parametrize("mode", ["idle", "read", "write"])
def test_a_holder_in_this_process_is_refused(tmp_path, leg, mode):
    path = _store(tmp_path, leg)
    holder = _open(path, leg)
    try:
        holder.execute("SELECT count(*) FROM t").fetchone()
        if mode == "read":
            holder.execute("BEGIN")
            holder.execute("SELECT * FROM t").fetchall()
        elif mode == "write":
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("INSERT INTO t VALUES (3)")
        assert _refused(path, leg), f"taken while this process held the store ({mode})"
    finally:
        holder.close()


@pytest.mark.parametrize("leg", _LEGS)
def test_the_apps_own_pooled_engine_is_a_holder(tmp_path, leg):
    """The app's engine keeps an idle pooled connection after a request: that is the app still running."""
    if leg == "enc":
        pytest.skip("the app's engine factory with a key is the connect() holder above")
    path = _store(tmp_path, leg)
    eng = app_sqlite_engine(path)
    try:
        with eng.connect() as c:
            c.exec_driver_sql("SELECT count(*) FROM t").fetchone()
        # the connection went back to the pool, idle and open
        assert _refused(path, leg)
    finally:
        eng.dispose()
    con = _try_take(path, leg)
    assert con is not None, "still refused after the engine was disposed"
    con.close()


@pytest.mark.parametrize("leg", _LEGS)
@pytest.mark.parametrize("mode", ["idle", "read", "write"])
def test_a_holder_in_another_process_is_refused(tmp_path, leg, mode):
    path = _store(tmp_path, leg)
    with _holder_process(path, leg, mode):
        assert _refused(path, leg), f"taken while another process held the store ({mode})"
    con = _try_take(path, leg, timeout=5)
    assert con is not None, "still refused after the other process closed the store"
    con.close()


@pytest.mark.parametrize("leg", _LEGS)
def test_a_refusal_comes_back_within_the_busy_timeout(tmp_path, leg):
    path = _store(tmp_path, leg)
    holder = _open(path, leg)
    try:
        holder.execute("SELECT count(*) FROM t").fetchone()
        started = time.monotonic()
        assert _refused(path, leg, timeout=1.0)
        # the busy wait plus the key derivation of an encrypted open; never a hang
        assert time.monotonic() - started < 20
    finally:
        holder.close()


def test_the_refusal_says_why_and_what_to_do(tmp_path):
    path = _store(tmp_path, "plain")
    holder = _open(path, "plain")
    con = _open(path, "plain")
    con.isolation_level = None
    try:
        holder.execute("SELECT count(*) FROM t").fetchone()
        with pytest.raises(AppStillRunning) as caught:
            take_exclusive(con)
        assert "open" in str(caught.value) and "Close it and run this again" in str(caught.value)
    finally:
        con.close()
        holder.close()


@pytest.mark.parametrize("leg", _LEGS)
def test_once_taken_nobody_else_gets_in_across_committed_windows(tmp_path, leg):
    path = _store(tmp_path, leg)
    con = _try_take(path, leg, timeout=5)
    assert con is not None
    try:
        for i in range(3):  # the migration's windows: each its own committed transaction
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT INTO t VALUES (?)", (10 + i,))
            con.execute("COMMIT")
        seen = _other_process_reads(path, leg)
        assert seen.startswith("refused-held"), f"another process was not refused BECAUSE the store is held: {seen}"
        other = None
        with contextlib.suppress(Exception):
            other = _open(path, leg)
        if other is not None:  # plaintext opens lazily: the read itself must be refused
            try:
                with pytest.raises(sqlite3.OperationalError):
                    other.execute("SELECT count(*) FROM t").fetchone()
            finally:
                other.close()
    finally:
        con.close()


# --------------------------------------------------------------------------------------------------------------------
# (a) over-refusal: a closed store and a crash-left -wal are taken, and the -wal's rows are kept
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("leg", _LEGS)
def test_a_closed_store_is_taken(tmp_path, leg):
    path = _store(tmp_path, leg)
    con = _try_take(path, leg, timeout=5)
    assert con is not None
    try:
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    finally:
        con.close()


_CRASH = textwrap.dedent(
    """
    import os, sys
    from src.database.connect import connect
    key = os.environ.get("ROW300_KEY") or None
    c = connect(sys.argv[1], key=key, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit()
    os._exit(0)  # no close, no checkpoint: the row lives only in the -wal
    """
)


@pytest.mark.parametrize("leg", _LEGS)
def test_a_crash_left_wal_is_taken_and_its_rows_are_kept(tmp_path, leg):
    path = _store(tmp_path, leg)
    subprocess.run([sys.executable, "-c", _CRASH, str(path)], cwd=ROOT, env=_child_env(leg), check=True, timeout=60)
    wal = Path(str(path) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "the crash left no -wal to keep"
    con = _try_take(path, leg, timeout=5)
    assert con is not None, "a store a crash left is refused as if the app were running"
    try:
        assert sorted(r[0] for r in con.execute("SELECT x FROM t").fetchall()) == [1, 2, 42], "the -wal's row was lost"
    finally:
        con.close()


#: What the audit hook below records: the paths watched, whether the held window is open, and the opens seen inside it.
_WATCH: dict = {"live": set(), "held": False, "hits": []}


def _audit_open(event: str, args: tuple) -> None:
    """Observes every ``open`` audit event (``builtins.open``, ``io.open``, ``os.open``) of the process without replacing
    anything (R351: no os function is swapped for every caller). Inert outside the held window of the one test using it."""
    if event != "open" or not _WATCH["held"] or not args:
        return
    p = args[0]
    if isinstance(p, (str, bytes, os.PathLike)):
        with contextlib.suppress(Exception):
            if os.path.realpath(os.fsdecode(p)) in _WATCH["live"]:
                _WATCH["hits"].append(os.fsdecode(p))


_AUDIT_ADDED = [False]


def test_nothing_in_python_reopens_the_live_file_while_it_is_held(tmp_path, monkeypatch):
    """POSIX file locks belong to the process: closing ANY descriptor on the store drops the lock SQLite took.

    Measured (security read 1, row 300): a Python open()/close() of the live file after take_exclusive silently let
    another process write, and its committed row was lost. Nothing in migrate() does that today; this pins it, so a
    future helper that sniffs the header (is_encrypted_file, a size read, a checksum) inside the held window fails here.
    SQLite's own opens are in C and raise no audit event; every Python route to the file does.
    """
    from src.backup import country_migration as cm
    from tests.test_country_migration import _new_store

    db = _new_store(tmp_path / "s.db", articles=30)
    with contextlib.closing(sqlite3.connect(db)) as c:
        assert c.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    if not _AUDIT_ADDED[0]:
        sys.addaudithook(_audit_open)  # cannot be removed; inert while _WATCH["held"] is False
        _AUDIT_ADDED[0] = True
    _WATCH.update(live={os.path.realpath(db)}, held=False, hits=[])
    monkeypatch.setattr(cm, "BATCH_ROWIDS", 9)  # several committed windows inside the held span

    def _progress(event) -> None:
        if event.get("phase") == "locked":
            _WATCH["held"] = True

    try:
        # The hook sees this process's opens: prove it does before trusting its silence.
        _WATCH["held"] = True
        with open(db, "rb"):  # noqa: PTH123 - the very route the guard watches for
            pass
        assert _WATCH["hits"], "the audit hook saw no open of the live file; the guard below would prove nothing"
        _WATCH.update(held=False, hits=[])
        rep = cm.migrate(db, backup_dir=tmp_path / "bk", progress=_progress)
        saw_lock = _WATCH["held"]
    finally:
        _WATCH["held"] = False
    assert saw_lock, "migrate() no longer reports the 'locked' phase this guard keys on"
    assert rep.state == "done", rep.message
    assert _WATCH["hits"] == [], f"Python opened the live store while holding it (drops the POSIX lock): {_WATCH['hits']}"
