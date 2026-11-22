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
