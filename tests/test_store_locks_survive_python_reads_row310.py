"""Row 310 (R789): a Python read of the store never drops this process's SQLite locks on it.

On POSIX a lock belongs to the process and the file, and closing ANY descriptor on the file drops all of them. The header
read every ``connect()`` makes (``is_encrypted_file``) did ``open``/``close`` on the store, and so did the restore's and the
stream backup's byte copy, the status probes and the page reads: once a running app had done any of them, its idle pooled
connection no longer kept another process out. Measured before this row: the country migration took the store under a
live app, the app's next write left an alpha-3 marker over alpha-2 rows, and with two writers on one WAL some runs zeroed
the header. The encrypted leg refused only because its key check happened to read the store before taking the lock,
joining the WAL through the ``-shm`` whose locks survived: an ordering, not a design. These tests take the store both
ways (the lock first, and a read first) on both legs.

The key reaches a child process through its environment only, never argv.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.database import connect as connect_mod

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="fcntl locks are POSIX; Windows keeps its own read path"
)

ROOT = Path(__file__).resolve().parents[1]
_TEST_KEY = "row310-throwaway-test-key"
_LEGS = [
    pytest.param("plain", id="plaintext"),
    pytest.param(
        "enc",
        id="encrypted",
        marks=pytest.mark.skipif(not connect_mod.have_driver(), reason="sqlcipher3 not installed"),
    ),
]

# The taker, in another process. "lock-first" sets locking_mode=EXCLUSIVE before its first access (the migration's
# plaintext order); "read-first" reads the schema first (the encrypted connect's key check does that).
_TAKER = textwrap.dedent(
    """
    import os, sys
    path, leg, order, page_size = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    if leg == "enc":
        import sqlcipher3 as drv
    else:
        import sqlite3 as drv
    c = drv.connect(path, timeout=1, isolation_level=None)
    try:
        if leg == "enc":
            key = os.environ["ROW310_KEY"].replace("'", "''")
            c.execute(f"PRAGMA key = '{key}'")
            c.execute(f"PRAGMA cipher_page_size = {page_size}")
        if order == "read-first":
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
        c.execute("PRAGMA locking_mode=EXCLUSIVE")
        c.execute("BEGIN IMMEDIATE")
        c.execute("COMMIT")
        print("TOOK")
    except Exception as exc:
        print("REFUSED", type(exc).__name__)
    finally:
        c.close()
    """
)


def _env(leg: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for name in ("ROW310_KEY", "OO_DB_PASSPHRASE"):
        env.pop(name, None)
    if leg == "enc":
        env["ROW310_KEY"] = _TEST_KEY
    return env


def _take(path: Path, leg: str, order: str) -> str:
    out = subprocess.run(
        [sys.executable, "-c", _TAKER, str(path), leg, order, str(connect_mod._FRESH_PAGE_SIZE)],
        cwd=ROOT,
        env=_env(leg),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return (out.stdout.strip() or out.stderr.strip()[-300:]).splitlines()[-1]


def _store(tmp_path: Path, leg: str) -> Path:
    path = tmp_path / "s.db"
    con = connect_mod.connect(
        path, key=_TEST_KEY if leg == "enc" else None, create_encrypted=(leg == "enc")
    )
    try:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (1),(2)")
        con.commit()
    finally:
        con.close()
    assert connect_mod.is_encrypted_file(path) is (leg == "enc")
    return path


@contextlib.contextmanager
def _idle_holder(path: Path, leg: str):
    """An idle connection of THIS process on the store, as a pooled connection of the running app is."""
    con = connect_mod.connect(
        path, key=_TEST_KEY if leg == "enc" else None, check_same_thread=False
    )
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("SELECT count(*) FROM t").fetchone()
        yield con
    finally:
        con.close()


def _every_python_read(path: Path, leg: str) -> None:
    """What a running app does to its own store from Python, each of which used to close a descriptor on it."""
    from src.database import at_rest_state, page_auth, repair
    from src.monitoring import page_reading

    connect_mod.is_encrypted_file(path)
    connect_mod.invalidate_header_cache()
    connect_mod.main_header_state(path)
    page_reading.read_header(path)
    at_rest_state._read_header(path)
    with page_auth._raw_open(path) as fh:
        fh.read(100)
    with repair._raw_open(path) as fh:
        fh.read(100)
    with connect_mod.store_file(path) as fh:
        fh.read()
    # a second connection opened and closed: its header read happens on the way in
    other = connect_mod.connect(
        path, key=_TEST_KEY if leg == "enc" else None, check_same_thread=False
    )
    other.execute("SELECT count(*) FROM t").fetchone()
    other.close()


@pytest.mark.parametrize("order", ["lock-first", "read-first"])
@pytest.mark.parametrize("leg", _LEGS)
def test_an_idle_holder_still_keeps_a_taker_out_after_every_python_read(tmp_path, leg, order):
    path = _store(tmp_path, leg)
    with _idle_holder(path, leg):
        assert _take(path, leg, order).startswith("REFUSED"), (
            "the idle holder did not keep the taker out to begin with"
        )
        _every_python_read(path, leg)
        seen = _take(path, leg, order)
        assert seen.startswith("REFUSED"), (
            f"after the app's own reads another process took the store: {seen}"
        )
    assert _take(path, leg, order) == "TOOK", "with the holder closed the store must be taken"


@pytest.mark.parametrize("order", ["lock-first", "read-first"])
@pytest.mark.parametrize("leg", _LEGS)
def test_an_idle_holder_still_keeps_a_taker_out_after_a_backup_snapshot(
    tmp_path, leg, order, monkeypatch
):
    """The stream backup's and the restore's safety copy (``snapshot_preserving``, the byte copy where it applies)."""
    path = _store(tmp_path, leg)
    if leg == "enc":
        monkeypatch.setattr(connect_mod, "_passphrase", _TEST_KEY)
    with _idle_holder(path, leg):
        connect_mod.snapshot_preserving(path, tmp_path / "snap.db", allow_file_copy=True)
        seen = _take(path, leg, order)
        assert seen.startswith("REFUSED"), (
            f"after a snapshot another process took the store: {seen}"
        )


def test_the_byte_copy_ran_on_the_encrypted_leg(tmp_path, monkeypatch):
    """The test above is about the byte copy: prove the encrypted snapshot took that path and not the codec fallback."""
    if not connect_mod.have_driver():
        pytest.skip("sqlcipher3 not installed")
    path = _store(tmp_path, "enc")
    monkeypatch.setattr(connect_mod, "_passphrase", _TEST_KEY)
    used: list[Path] = []
    real = connect_mod._copy_from_held
    monkeypatch.setattr(
        connect_mod, "_copy_from_held", lambda s, d, **kw: used.append(Path(s)) or real(s, d, **kw)
    )
    connect_mod.snapshot_preserving(path, tmp_path / "snap.db", allow_file_copy=True)
    assert used == [path]
    assert (tmp_path / "snap.db").read_bytes() == path.read_bytes()


@pytest.mark.parametrize("use_sendfile", [True, False], ids=["sendfile", "pread-loop"])
@pytest.mark.parametrize("leg", _LEGS)
def test_the_held_copy_is_byte_identical_to_the_old_copy(tmp_path, leg, use_sendfile):
    path = _store(tmp_path, leg)
    shutil.copyfile(path, tmp_path / "old.db")
    connect_mod._copy_from_held(path, tmp_path / "new.db", chunk=4096, use_sendfile=use_sendfile)
    assert (tmp_path / "new.db").read_bytes() == (tmp_path / "old.db").read_bytes()


def test_a_short_read_fails_the_copy_and_leaves_no_partial(tmp_path, monkeypatch):
    path = _store(tmp_path, "plain")
    calls = [0]
    real = connect_mod.read_at

    def short(fd, n, offset):
        calls[0] += 1
        return b"" if calls[0] == 2 else real(fd, n, offset)

    monkeypatch.setattr(connect_mod, "read_at", short)
    with pytest.raises(connect_mod.StoreCopyRefused, match="ended after"):
        connect_mod._copy_from_held(path, tmp_path / "new.db", chunk=4096, use_sendfile=False)
    assert not (tmp_path / "new.db").exists()


def test_a_replaced_or_linked_store_is_refused_not_copied(tmp_path):
    path = _store(tmp_path, "plain")
    other = tmp_path / "other.db"
    shutil.copyfile(path, other)
    link = tmp_path / "link.db"
    link.symlink_to(other)
    with pytest.raises(connect_mod.StoreCopyRefused, match="not the file this process holds"):
        connect_mod._copy_from_held(link, tmp_path / "new.db")
    assert not (tmp_path / "new.db").exists()


def _key(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino)


def test_a_file_nothing_holds_is_not_kept_open(tmp_path):
    # Backup members, exports, candidates on a removable drive: read and let go, never pinned for the process's life.
    paths = []
    for i in range(50):
        f = tmp_path / f"member-{i}.bin"
        f.write_bytes(b"x" * 100)
        paths.append(f)
        connect_mod.is_encrypted_file(f)
        with connect_mod.store_file(f) as fh:
            fh.read(10)
    assert not {_key(f) for f in paths} & set(connect_mod._hdr_fds), (
        "a file nothing holds was kept open"
    )


def test_a_descriptor_is_closed_only_once_no_connection_holds_the_file(tmp_path):
    path = _store(tmp_path, "plain")
    other = tmp_path / "other.bin"
    other.write_bytes(b"y" * 100)
    holder = connect_mod.connect(path, check_same_thread=False)
    try:
        holder.execute("SELECT count(*) FROM sqlite_master").fetchone()
        connect_mod.is_encrypted_file(path)
        key = _key(path)
        assert key in connect_mod._hdr_fds, (
            "a descriptor was closed while a connection of this process held the file"
        )
        replacement = tmp_path / "new.db"
        shutil.copyfile(path, replacement)
        os.replace(
            replacement, path
        )  # the held file is now unreachable, but the connection is still open on it
        connect_mod.is_encrypted_file(other)
        assert key in connect_mod._hdr_fds, (
            "a descriptor was closed while a connection of this process held the file"
        )
        assert not os.get_inheritable(connect_mod._hdr_fds[key][0])
    finally:
        holder.close()
    connect_mod.is_encrypted_file(other)
    assert key not in connect_mod._hdr_fds, (
        "the descriptor of a file nothing holds any more was kept"
    )


def test_a_log_is_held_while_a_connection_is_open_on_its_store(tmp_path):
    path = _store(tmp_path, "plain")
    holder = connect_mod.connect(path, check_same_thread=False)
    try:
        holder.execute("PRAGMA journal_mode=WAL").fetchone()
        holder.execute("CREATE TABLE IF NOT EXISTS w(x)")
        holder.commit()
        wal = Path(str(path) + "-wal")
        assert wal.exists()
        with connect_mod.store_file(wal) as fh:
            fh.read(32)
        assert _key(wal) in connect_mod._hdr_fds, (
            "the -wal descriptor was closed while a connection held its store"
        )
    finally:
        holder.close()


def test_a_descriptor_in_use_is_never_closed_by_another_read(tmp_path):
    # A reader keeps its file while other reads (another thread's) let theirs go: the number is never closed and reused
    # under it for another file.
    path = tmp_path / "s.db"
    path.write_bytes(b"A" * 4096)
    other = tmp_path / "other.bin"
    other.write_bytes(b"z" * 64)
    with connect_mod.store_file(path) as fh:
        before = os.fstat(fh.fileno())
        new = tmp_path / "new.db"
        new.write_bytes(b"B" * 4096)
        os.replace(new, path)
        connect_mod.is_encrypted_file(other)
        connect_mod.is_encrypted_file(path)
        now = os.fstat(fh.fileno())
        assert (now.st_dev, now.st_ino) == (before.st_dev, before.st_ino)
        assert fh.read(4) == b"AAAA"
    connect_mod.is_encrypted_file(other)
    assert (before.st_dev, before.st_ino) not in connect_mod._hdr_fds


def test_a_fifo_at_a_store_path_is_refused_not_waited_on(tmp_path):
    fifo = tmp_path / "s.db"
    os.mkfifo(fifo)
    with pytest.raises(OSError), connect_mod.store_file(fifo):
        pass
    assert connect_mod.is_encrypted_file(fifo) is None


# The app, end to end: a pooled connection stays open, the app does what it does on every request (a settings read opens a
# new connection, whose header read used to close a descriptor on the store), then the country migration runs in another
# process. It must be refused, and the app's next write must land in the form the store has.
_APP = textwrap.dedent(
    """
    import json, os, subprocess, sys
    key = os.environ.get("ROW310_KEY")
    from src.database import connect as C
    if key:
        C.set_passphrase(key)
    from src.database.session import DB_FILE, SessionLocal, engine, init_db
    from src.database.models import Base, Source
    from src.database.country_form import KEY
    from src.config import kv_store
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("DELETE FROM app_state WHERE key = ?", (KEY,))
    init_db()
    s = SessionLocal()
    s.add(Source(name="a", domain="a.example", rss_url="http://a.example/rss", country="fr"))
    s.commit()  # the session's connection goes back to the pool and stays open
    kv_store.kv_invalidate()
    kv_store.kv_get_json_checked(KEY)  # a settings read: a connection of its own, opened and closed
    C.is_encrypted_file(DB_FILE)
    child = (
        "import os, sys\\n"
        "from pathlib import Path\\n"
        "from src.database import connect as C\\n"
        "k = os.environ.get('ROW310_KEY')\\n"
        "C.set_passphrase(k) if k else None\\n"
        "from src.backup import country_migration as cm\\n"
        "try:\\n"
        "    r = cm.migrate(Path(sys.argv[1]), backup_dir=Path(sys.argv[1]).parent / 'bk')\\n"
        "    print(r.state)\\n"
        "except Exception as exc:\\n"
        "    print(type(exc).__name__)\\n"
    )
    mig = subprocess.run([sys.executable, "-c", child, DB_FILE], env=os.environ, capture_output=True, text=True, timeout=240)
    s.add(Source(name="b", domain="b.example", rss_url="http://b.example/rss", country="de"))
    s.commit()
    s.close()
    from sqlalchemy import text
    with engine.connect() as c:
        rows = sorted(tuple(r) for r in c.execute(text("SELECT name, country FROM sources")).fetchall())
        ok = c.execute(text("PRAGMA quick_check")).scalar()
    print(json.dumps({"migration": (mig.stdout.strip().splitlines() or [mig.stderr.strip()[-300:]])[-1], "rows": rows, "quick_check": ok}))
    """
)


@pytest.mark.parametrize("leg", _LEGS)
def test_the_migration_cannot_take_the_store_under_a_running_app(tmp_path, leg):
    env = {**_env(leg), "OO_DATA_DIR": str(tmp_path), "OO_NO_SCHEDULER": "1"}
    env.pop("DATABASE_URL", None)
    if leg == "enc":
        env.pop("OO_DB_PLAINTEXT", None)
    else:
        env["OO_DB_PLAINTEXT"] = "1"
    done = subprocess.run(
        [sys.executable, "-c", _APP], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["migration"] == "AppStillRunning", out
    assert [tuple(r) for r in out["rows"]] == [("a", "fr"), ("b", "de")], out
    assert out["quick_check"] == "ok", out


# The stress run the coordinator asked for (R789): a close of ours and a SQLite open in this process on the same file must
# never interleave so that a lock the open took is dropped. Threads hammer Python reads of the store and its logs and open
# and close connections (pool growth) while the main thread, over and over, opens a NEW connection, takes the write lock,
# and asks a second process to take it too; that process must be refused every time.
_STRESS_TAKER = textwrap.dedent(
    """
    import sqlite3, sys
    con = sqlite3.connect(sys.argv[1], timeout=0, isolation_level=None)
    for line in sys.stdin:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            print("REFUSED" if "locked" in str(exc) or "busy" in str(exc) else f"ERROR {exc}", flush=True)
            continue
        con.execute("ROLLBACK")
        print("TOOK", flush=True)
    """
)


@pytest.mark.parametrize("journal", ["wal", "delete"])
def test_no_close_of_ours_drops_a_lock_a_concurrent_open_took(tmp_path, journal):
    import threading
    import time

    path = tmp_path / "s.db"
    con = connect_mod.connect(path, create_encrypted=False)
    try:
        assert con.execute(f"PRAGMA journal_mode={journal}").fetchone()[0] == journal
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
    finally:
        con.close()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _reads():
        names = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")]
        while not stop.is_set():
            try:
                connect_mod.is_encrypted_file(path)
                for name in names:
                    with contextlib.suppress(FileNotFoundError), connect_mod.store_file(name) as fh:
                        fh.read(64)
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)
                return

    def _churn():
        while not stop.is_set():
            try:
                c = connect_mod.connect(path, check_same_thread=False)
                c.execute("SELECT count(*) FROM t").fetchone()
                c.close()
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)
                return

    workers = [threading.Thread(target=_reads, daemon=True) for _ in range(2)]
    workers += [threading.Thread(target=_churn, daemon=True) for _ in range(2)]
    taker = subprocess.Popen(
        [sys.executable, "-c", _STRESS_TAKER, str(path)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    answers: list[str] = []
    try:
        for w in workers:
            w.start()
        for i in range(150):
            holder = connect_mod.connect(path, check_same_thread=False)
            holder.isolation_level = None
            try:
                holder.execute("BEGIN IMMEDIATE")
                for _ in range(2):
                    taker.stdin.write("try\n")
                    taker.stdin.flush()
                    answers.append(taker.stdout.readline().strip())
                    if i % 3 == 0:
                        time.sleep(0.002)
                holder.execute("ROLLBACK")
            finally:
                holder.close()
    finally:
        stop.set()
        for w in workers:
            w.join(timeout=30)
        taker.stdin.close()
        taker.wait(timeout=30)
    assert not errors, errors[:3]
    assert answers and set(answers) == {"REFUSED"}, f"a second process took the store under a held lock: {answers.count('TOOK')} of {len(answers)}"


def test_a_sqlite_open_already_under_way_is_never_raced_by_a_close(tmp_path, monkeypatch):
    # The interleave a stress run is too coarse to hit, forced: an open has counted itself in (``sqlite_opening``), a read of
    # ours checks the process's descriptors and finds none on the file, and the open's file and lock land right then, before
    # our close. The close must not happen: the open in flight is what keeps the descriptor.
    import sqlite3

    path = tmp_path / "s.db"
    con = connect_mod.connect(path, create_encrypted=False)
    try:
        con.execute("PRAGMA journal_mode=delete").fetchone()
        con.execute("CREATE TABLE t(x)")
        con.commit()
    finally:
        con.close()
    landed: list[sqlite3.Connection] = []
    real = connect_mod._foreign_fd_keys

    def _the_open_lands():
        if not landed:
            c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            c.execute("BEGIN IMMEDIATE")
            landed.append(c)

    def _check_then_the_open_lands(ours):
        found = real(ours)
        _the_open_lands()  # between our check and our close, if we ever got that far with an open under way
        return found

    monkeypatch.setattr(connect_mod, "_foreign_fd_keys", _check_then_the_open_lands)
    try:
        with connect_mod.sqlite_opening():
            with connect_mod.store_file(path) as fh:
                fh.read(16)
            _the_open_lands()  # otherwise right after our read gave the descriptor back
            answer = subprocess.run(
                [sys.executable, "-c", _STRESS_TAKER, str(path)], cwd=ROOT, input="try\n", capture_output=True, text=True,
                timeout=60,
            ).stdout.strip()
            assert answer == "REFUSED", f"a close raced an open under way and dropped its lock: {answer}"
    finally:
        for c in landed:
            c.close()


def test_the_old_file_of_a_replaced_store_is_let_go_while_the_new_one_is_held(tmp_path):
    # Restore, encryption, repair and the migration swap the store's name onto a new file: the descriptor we kept on the
    # old one must not stay open (with the old file's disk space) because the NEW file is held.
    path = _store(tmp_path, "plain")
    other = tmp_path / "other.bin"
    other.write_bytes(b"y" * 100)
    holder = connect_mod.connect(path, check_same_thread=False)
    try:
        holder.execute("SELECT 1").fetchone()
        connect_mod.is_encrypted_file(path)
        old = _key(path)
        assert old in connect_mod._hdr_fds
        holder.close()
        new = tmp_path / "new.db"
        shutil.copyfile(path, new)
        os.replace(new, path)
        holder = connect_mod.connect(path, check_same_thread=False)
        holder.execute("SELECT 1").fetchone()
        connect_mod.is_encrypted_file(other)
        assert old not in connect_mod._hdr_fds, "the replaced file's descriptor was kept because its successor is held"
    finally:
        holder.close()


def test_the_library_is_kept_open_while_its_name_leads_to_it(tmp_path):
    path = _store(tmp_path, "plain")
    other = tmp_path / "other.bin"
    other.write_bytes(b"y" * 100)
    connect_mod.pin_store(path)
    try:
        connect_mod.is_encrypted_file(path)
        connect_mod.is_encrypted_file(other)
        assert _key(path) in connect_mod._hdr_fds, "the library's descriptor was closed although its name still leads to it"
        old = _key(path)
        new = tmp_path / "new.db"
        shutil.copyfile(path, new)
        os.replace(new, path)
        connect_mod.is_encrypted_file(other)
        assert old not in connect_mod._hdr_fds, "the library's replaced file was kept"
    finally:
        from src.database import store_pins

        store_pins.PINNED.discard(os.path.realpath(path))


_WARM_TAKER = textwrap.dedent(
    """
    import sqlite3, sys
    con = sqlite3.connect(sys.argv[1], timeout=0, isolation_level=None)
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()  # its -wal and -shm now exist and stay while it lives
    print("READY", flush=True)
    for line in sys.stdin:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            print("REFUSED" if "locked" in str(exc) or "busy" in str(exc) else f"ERROR {exc}", flush=True)
            continue
        con.execute("ROLLBACK")
        print("TOOK", flush=True)
    """
)


def test_a_log_a_connection_has_not_opened_yet_is_held_with_its_store(tmp_path, monkeypatch):
    # A connection opens its store's -wal and -shm lazily, at its first statement. A read of ours on the -shm that finds no
    # descriptor of this process on the -shm itself must still keep it while a connection is open on the STORE: forced here,
    # the connection's first statement (which opens the -shm and takes the write lock there) lands between our check and our
    # close. A close then would drop that lock, and another process would take the write lock.
    path = tmp_path / "s.db"
    con = connect_mod.connect(path, create_encrypted=False)
    try:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        con.execute("CREATE TABLE t(x)")
        con.commit()
    finally:
        con.close()
    taker = subprocess.Popen(
        [sys.executable, "-c", _WARM_TAKER, str(path)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    holder = None
    try:
        assert taker.stdout.readline().strip() == "READY"
        shm = Path(str(path) + "-shm")
        assert shm.exists()
        holder = connect_mod.connect(path, check_same_thread=False)
        holder.isolation_level = None
        assert _key(shm) not in (connect_mod._foreign_fd_keys(set()) or set()), "the connection opened its -shm already"
        started: list[bool] = []
        real = connect_mod._foreign_fd_keys

        def _first_statement():
            if not started:
                holder.execute("BEGIN IMMEDIATE")
                started.append(True)

        def _check_then_the_statement_lands(ours):
            found = real(ours)
            _first_statement()
            return found

        monkeypatch.setattr(connect_mod, "_foreign_fd_keys", _check_then_the_statement_lands)
        with connect_mod.store_file(shm) as fh:
            fh.read(8)
        _first_statement()
        taker.stdin.write("try\n")
        taker.stdin.flush()
        answer = taker.stdout.readline().strip()
        assert answer == "REFUSED", f"a close of ours dropped the lock a connection took on its store's -shm: {answer}"
    finally:
        if holder is not None:
            with contextlib.suppress(Exception):
                holder.execute("ROLLBACK")
            holder.close()
        taker.stdin.close()
        taker.wait(timeout=30)


def test_an_open_that_starts_between_the_listing_and_the_close_stops_the_close(tmp_path, monkeypatch):
    # Not wrapped in sqlite_opening: a plain stdlib sqlite3.connect, counted by the audit hook alone. It starts after our
    # listing of the process's descriptors and takes its lock before our close would run; the open generation it bumps
    # must make that sweep close nothing.
    import sqlite3

    path = tmp_path / "s.db"
    con = connect_mod.connect(path, create_encrypted=False)
    try:
        con.execute("PRAGMA journal_mode=delete").fetchone()
        con.execute("CREATE TABLE t(x)")
        con.commit()
    finally:
        con.close()
    landed: list[sqlite3.Connection] = []
    real = connect_mod._group_of

    def _groups_then_an_open_lands(name):
        if not landed:
            c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            c.execute("BEGIN IMMEDIATE")
            landed.append(c)
        return real(name)

    monkeypatch.setattr(connect_mod, "_group_of", _groups_then_an_open_lands)
    try:
        with connect_mod.store_file(path) as fh:
            fh.read(16)
        assert landed, "the sweep never reached the step between its listing and its close"
        answer = subprocess.run(
            [sys.executable, "-c", _STRESS_TAKER, str(path)], cwd=ROOT, input="try\n", capture_output=True, text=True,
            timeout=60,
        ).stdout.strip()
        assert answer == "REFUSED", f"a close raced an open that started after the listing: {answer}"
    finally:
        for c in landed:
            c.close()


# Openers the audit hook cannot see (sqlcipher3 is not audited, under any alias; ATTACH opens a file through a connection
# already made), and the sqlite_opening wrappers that cover some of them. Each file's count is pinned with the reason no
# Python read of ours can race it, so a new opener, or a wrapper removed, is classified by whoever makes the change.
_UNAUDITED_OPENERS = {
    ("sqlcipher-connect", "src/database/connect.py"): (6, "four inside _connect/_try_open_encrypted, under connect()'s "
        "sqlite_opening; reencrypt_plain_to and copy_at_current_settings wrap theirs"),
    ("sqlcipher-connect", "src/database/verify.py"): (1, ":memory: probe, no file"),
    ("sqlcipher-connect", "src/monitoring/machine_record.py"): (2, ":memory: probes, no file"),
    ("sqlcipher-connect", "src/backup/lane_merge.py"): (1, ":memory: host for the ATTACHed staged lanes"),
    ("sqlcipher-connect", "src/monitoring/merge_diag.py"): (3, "the diagnostic's :memory: probe and its own scratch "
        "copies (drv.connect)"),
    ("attach", "src/database/connect.py"): (8, "attach() wraps its two; the other six ATTACH a snapshot, rebuild or "
        "re-encryption destination: a new file Python reads only after that connection closed"),
    ("attach", "src/backup/lane_merge.py"): (2, "both wrapped in sqlite_opening"),
    ("attach", "src/backup/merge.py"): (1, "the merge's own scratch database"),
    ("attach", "src/backup/newsletter_export.py"): (2, "a docstring, and the export's own new file"),
    ("attach", "src/backup/stream_backup.py"): (1, "a snapshot destination in the backup's work folder"),
    ("attach", "src/monitoring/merge_diag.py"): (1, "the diagnostic's own scratch database"),
    ("attach", "src/monitoring/diagnostics_runs.py"): (1, "a comment about scrubbing keys"),
    ("attach", "src/monitoring/secret_scrub.py"): (1, "a docstring about scrubbing keys"),
    ("wrapped", "src/database/connect.py"): (5, "connect(), attach(), snapshot_to_plaintext, reencrypt_plain_to, "
        "copy_at_current_settings"),
    ("wrapped", "src/database/read_only_uri.py"): (1, "open_plain_read_only"),
    ("wrapped", "src/backup/lane_merge.py"): (2, "the two ATTACHes"),
}


def test_every_opener_the_audit_hook_cannot_see_is_classified():
    import re

    patterns = {
        "sqlcipher-connect": re.compile(
            r"\b(sqc|sqlcipher3|dbapi2|drv|mod)\.connect\(|from\s+sqlcipher3[\w.]*\s+import\s+[^\n]*\bconnect\b"
        ),
        "attach": re.compile(r"ATTACH\s+(DATABASE\b|\?|')", re.IGNORECASE),
        "wrapped": re.compile(r"with sqlite_opening\(\)"),
    }
    found: dict[tuple[str, str], int] = {}
    for f in sorted((ROOT / "src").rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        text = f.read_text(encoding="utf-8")
        for kind, pat in patterns.items():
            n = len(pat.findall(text))
            if n:
                found[(kind, rel)] = n
    pinned = {k: v[0] for k, v in _UNAUDITED_OPENERS.items()}
    assert found == pinned, (
        "an opener the audit hook cannot see, or a sqlite_opening wrapper, was added, moved or removed: classify it in "
        f"_UNAUDITED_OPENERS (wrap a live store's open in connect.sqlite_opening): found {found}"
    )


def test_a_descriptor_or_a_group_member_that_cannot_be_read_keeps_everything(tmp_path, monkeypatch):
    # EIO or ESTALE on a network mount: a connection's descriptor that cannot be fstat'ed, or a store file that cannot be
    # stat'ed, is not "nothing holds it". The sweep keeps its descriptors.
    import errno as _errno

    from tests.os_scope import scope_os

    path = tmp_path / "s.db"
    path.write_bytes(b"A" * 4096)
    real_fstat, real_stat = os.fstat, os.stat

    def _fstat(n):
        if n not in {fd for fds in connect_mod._hdr_fds.values() for fd in fds} and n > 2:
            st = real_fstat(n)
            if (st.st_dev, st.st_ino) == _key(path):
                raise OSError(_errno.EIO, "unreadable")
        return real_fstat(n)

    other = os.open(path, os.O_RDONLY)  # a descriptor of "a connection" on the file
    try:
        with monkeypatch.context() as m:
            scope_os(m, connect_mod, fstat=_fstat)
            assert connect_mod._foreign_fd_keys(set()) is None
        assert connect_mod._group_of(str(path))[2] is False

        def _stat(name, *a, **k):
            if os.fspath(name) == str(path):
                raise OSError(_errno.ESTALE, "stale")
            return real_stat(name, *a, **k)

        with monkeypatch.context() as m:
            scope_os(m, connect_mod, stat=_stat)
            assert connect_mod._group_of(str(path) + "-shm")[2] is True, "a store that cannot be stat'ed left the group"
    finally:
        os.close(other)
