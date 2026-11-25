"""
R789/R792 (row 315): what a crypto-erase leaves when ANOTHER process has the store open.

Measured on real SQLCipher stores (2026-11-22): a second process holding its own keyed connection cannot write into the
erased store afterwards -- page 1's salt is gone and the -shm header is zeroed, so its next write is refused -- whether it
sat idle, held a write transaction, had page 1 dirty or had already spilled pages to the log, with or without the panic
wipe's kept descriptors. This file pins that half: the write is refused, the data folder is gone, and the store's salt is
in none of the files the other process still holds.

The other half (R792): a process that keeps writing THROUGH the erase commits into the unlinked log and can leave the salt
there. The erase now looks for such a process (the locks SQLite holds), rewrites through its kept descriptors while one is
seen, for at most two seconds, and its result says ``other_holder``: never "none" while the salt survives in what the other
process holds -- either no salt survives, or the result says the erase may be incomplete.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from src.database.connect import have_driver

pytestmark = [
    pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed"),
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads the other process's descriptors under /proc"),
]

_KEY = "row315-test-only-passphrase"  # a test constant; handed to the other process through its environment, never argv
_REPO = Path(__file__).resolve().parent.parent

# The other process: opens its own keyed connection, gets into the requested state, says READY, waits for the erase, tries
# one write, reports how it ended, then waits (descriptors still open) until it is told to close.
_OTHER = r"""
import os, sys
sys.path.insert(0, os.getcwd())
from src.database import connect as cm
db, mode = sys.argv[1], sys.argv[2]
con = cm.connect(db, key=os.environ["ROW315_KEY"], check_same_thread=False)
con.isolation_level = None
con.execute("PRAGMA busy_timeout=2000")
if mode == "idle":
    con.execute("SELECT count(*) FROM t").fetchone()
else:
    if mode == "spill":
        con.execute("PRAGMA cache_size=10")
    con.execute("BEGIN IMMEDIATE")
    if mode in ("page1", "spill"):
        con.execute("CREATE TABLE u(x)")
    con.execute("INSERT INTO t(x) SELECT hex(randomblob(3000)) FROM t" + ("" if mode == "spill" else " LIMIT 1"))
print("READY", flush=True)
sys.stdin.readline()
try:
    if mode == "idle":
        con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO t(x) SELECT hex(randomblob(3000)) FROM t LIMIT 200")
    con.execute("COMMIT")
    print("WROTE", flush=True)
except Exception as exc:
    print("REFUSED " + type(exc).__name__ + ": " + str(exc), flush=True)
sys.stdin.readline()
"""


_HELD_OPEN: list = []


@pytest.fixture(autouse=True)
def _close_held_open():
    yield
    while _HELD_OPEN:
        with contextlib.suppress(Exception):
            _HELD_OPEN.pop().close()


def _store(tmp_path: Path, *, hold: bool = True) -> tuple[Path, bytes]:
    from src.database import connect as cm
    from src.safety import crypto_erase as ce

    data = tmp_path / "data"
    data.mkdir()
    db = data / ce._MAIN_DB
    con = cm.connect(db, key=_KEY, create_encrypted=True, check_same_thread=False)
    try:
        assert str(con.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE t(x TEXT)")
        con.executemany("INSERT INTO t VALUES (?)", [("a" * 3000,) for _ in range(300)])
        con.commit()
    finally:
        con.close()
    if hold:  # R819 (1): read back under its key and held, as the pool does; never for a test where this process is "another program"
        _HELD_OPEN.append(cm.connect(db, key=_KEY, check_same_thread=False))
    # The salt SQLCipher keeps in plaintext at the start of page 1: with the passphrase, it is what makes the body readable.
    # Read with os.pread on a descriptor no SQLite connection of this process shares (nothing of this process holds the store).
    fd = os.open(db, os.O_RDONLY)
    try:
        salt = os.pread(fd, 16, 0)
    finally:
        os.close(fd)
    return data, salt


# What the measured refusals said (2026-11-22). A busy or unrelated error is not a refusal by the erase.
_REFUSALS = ("file is not a database", "locking protocol", "malformed")


def _line(proc: subprocess.Popen, timeout: float = 60.0) -> str:
    """One line from the other process, or a failure naming the wait -- never a hang of the whole run."""
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    assert ready, f"the other process said nothing for {timeout:.0f} s"
    return proc.stdout.readline().strip()


def _salt_in_held_files(pid: int, salt: bytes) -> tuple[list[str], list[str]]:
    """(every held file containing the salt, every held file actually read); pipes and sockets skipped."""
    hits, read = [], []
    for name in os.listdir(f"/proc/{pid}/fd"):
        link = f"/proc/{pid}/fd/{name}"
        try:
            target = os.readlink(link)
            if not target.startswith("/"):
                continue
            with open(link, "rb") as f:  # the other process's descriptor, after the erase: the store is gone from this one
                body = f.read()
            read.append(target)
            if salt in body:
                hits.append(target)
        except OSError:
            continue
    return hits, read


@pytest.mark.parametrize("held", [False, True], ids=["uninstall-path", "panic-hold"])
@pytest.mark.parametrize("mode", ["idle", "in-transaction", "page1", "spill"])
def test_a_write_begun_after_the_erase_is_refused_and_leaves_no_salt(tmp_path, mode, held):
    from src.safety import crypto_erase as ce

    data, salt = _store(tmp_path)
    db = data / ce._MAIN_DB
    env = {**os.environ, "ROW315_KEY": _KEY}
    wal = data / (ce._MAIN_DB + "-wal")
    wal_before = os.stat(wal).st_size if wal.exists() else 0
    errlog = tmp_path / "other.stderr"
    generation = ce.new_hold_generation()
    with open(errlog, "w", encoding="utf-8") as err, subprocess.Popen(
        [sys.executable, "-c", _OTHER, str(db), {"in-transaction": "txn"}.get(mode, mode)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, cwd=_REPO, env=env,
    ) as other:
        try:
            ready = _line(other)
            assert ready == "READY", f"{ready!r}; stderr: {errlog.read_text(encoding="utf-8", errors="replace")[-2000:]}"
            if mode == "spill":  # the spill really reached the log before the erase (a size, read with stat: R789)
                assert os.stat(wal).st_size > wal_before
            report = ce.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=held, hold_generation=generation)
            if held:
                ce.rescrub_held(close=False, generation=generation)
                ce.rescrub_held(close=True, generation=generation)
            other.stdin.write("go\n")
            other.stdin.flush()
            outcome = _line(other)
            survivors, read = _salt_in_held_files(other.pid, salt)
            other.stdin.write("done\n")
            other.stdin.flush()
            other.wait(timeout=30)
        finally:
            ce.rescrub_held(close=True, generation=generation)  # a failure above never leaves kept descriptors open
            if other.poll() is None:
                other.kill()

    assert outcome.startswith("REFUSED") and any(r in outcome for r in _REFUSALS), (
        f"the other process's write was not refused by the erase: {outcome!r}"
    )
    assert not data.exists()
    # It still had the store open (a connection holds SQLite's shared locks): the result never calls this a clean erase.
    assert report["other_holder"] == ce.HOLDER_HELD, report.get("other_holder")
    # The scan really read what the other process holds, so an empty result is not a scan that read nothing.
    assert any(t.startswith(str(db)) for t in read), f"none of the store's files was read: {read}"
    assert survivors == [], f"the salt survives in files the other process still holds: {survivors}"


# R792: the other process keeps committing, each transaction dirtying page 1, until it is told to stop; then it says how many
# commits it made and waits (descriptors still open) until it is told to close.
_LOOPER = r"""
import os, sys, threading
sys.path.insert(0, os.getcwd())
from src.database import connect as cm
con = cm.connect(sys.argv[1], key=os.environ["ROW315_KEY"], check_same_thread=False)
con.isolation_level = None
con.execute("PRAGMA busy_timeout=50")
stop = threading.Event()
done = [0]
def loop():
    i = 0
    while not stop.is_set():
        i += 1
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(f"CREATE TABLE IF NOT EXISTS z{i % 3}(x)")
            con.execute(f"DROP TABLE IF EXISTS z{(i + 1) % 3}")
            con.execute("INSERT INTO t(x) VALUES (hex(randomblob(500)))")
            con.execute("COMMIT")
            done[0] += 1
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
th = threading.Thread(target=loop)
th.start()
print("READY", flush=True)
sys.stdin.readline()
stop.set()
th.join()
print("COMMITS " + str(done[0]), flush=True)
sys.stdin.readline()
"""


@pytest.mark.parametrize("held", [False, True], ids=["unheld-variant", "panic-hold"])
def test_a_process_writing_through_the_erase_never_leaves_a_clean_report_with_a_surviving_salt(tmp_path, held):
    """R792 (7): a second process committing in a loop through the erase. Either no salt survives in anything it still
    holds, or the erase result says another program still had the database open -- never a clean result beside a salt."""
    from src.safety import crypto_erase as ce

    data, salt = _store(tmp_path)
    db = data / ce._MAIN_DB
    env = {**os.environ, "ROW315_KEY": _KEY}
    errlog = tmp_path / "looper.stderr"
    generation = ce.new_hold_generation()
    with open(errlog, "w", encoding="utf-8") as err, subprocess.Popen(
        [sys.executable, "-c", _LOOPER, str(db)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, cwd=_REPO, env=env,
    ) as other:
        try:
            ready = _line(other)
            assert ready == "READY", f"{ready!r}; stderr: {errlog.read_text(encoding="utf-8", errors="replace")[-2000:]}"
            report = ce.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=held, hold_generation=generation)
            if held:  # the panic wipe's two later passes, the closing one bounded like the inline one
                ce.rescrub_held(close=False, generation=generation)
                ce.rescrub_held(close=True, generation=generation)
            other.stdin.write("stop\n")
            other.stdin.flush()
            commits = _line(other)
            survivors, read = _salt_in_held_files(other.pid, salt)
            other.stdin.write("done\n")
            other.stdin.flush()
            other.wait(timeout=30)
        finally:
            ce.rescrub_held(close=True, generation=generation)
            if other.poll() is None:
                other.kill()

    assert commits.startswith("COMMITS"), commits
    assert any(t.startswith(str(db)) for t in read), f"none of the store's files was read: {read}"
    assert report["other_holder"] in (ce.HOLDER_NONE, ce.HOLDER_HELD, ce.HOLDER_UNKNOWN)
    if survivors:
        assert report["other_holder"] == ce.HOLDER_HELD, (
            f"the salt survives in {survivors} but the erase result says {report['other_holder']!r}"
        )
    # The looper never closed its connection: the erase must have seen it and said so.
    assert report["other_holder"] == ce.HOLDER_HELD


def test_with_no_other_process_the_erase_is_clean_and_does_not_wait(tmp_path):
    """R792 (3): the user-visible erase is not slower when no second process exists -- one probe per kept file, no wait."""
    import time

    from src.safety import crypto_erase as ce

    data, _salt = _store(tmp_path)
    generation = ce.new_hold_generation()
    for name in (ce._MAIN_DB, ce._MAIN_DB + "-wal"):
        if (data / name).exists():
            assert ce._hold(data / name, whole=name.endswith("-wal"), generation=generation)
    try:
        t0 = time.monotonic()
        state = ce.settle_other_holders(generation)
        elapsed = time.monotonic() - t0
    finally:
        ce.rescrub_held(close=True, generation=generation, settle=False)
    assert state == ce.HOLDER_NONE
    assert elapsed < ce._HOLDER_STEP_S, f"the check waited {elapsed:.3f} s with no other process"
    report = ce.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["other_holder"] == ce.HOLDER_NONE


def test_an_erase_that_cannot_check_says_so(tmp_path, monkeypatch):
    """R792 + the coordinator's addition: when the probe cannot run (here: a platform whose lock record is not read), the
    result is "could not check", never clean and never held."""
    from src.safety import crypto_erase as ce

    data, _salt = _store(tmp_path)
    monkeypatch.setattr(ce, "_flock_layout", lambda: None)
    report = ce.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["other_holder"] == ce.HOLDER_UNKNOWN
    assert not data.exists()


def test_the_probe_sees_another_process_and_stops_seeing_it_once_it_closes(tmp_path):
    """The probe itself: one F_GETLK on a kept descriptor shows another process's SQLite locks while it has the store open,
    and nothing once it has closed it."""
    from src.safety import crypto_erase as ce

    data, _salt = _store(tmp_path)
    db = data / ce._MAIN_DB
    env = {**os.environ, "ROW315_KEY": _KEY}
    generation = ce.new_hold_generation()
    errlog = tmp_path / "idle.stderr"
    try:
        with open(errlog, "w", encoding="utf-8") as err, subprocess.Popen(
            [sys.executable, "-c", _OTHER, str(db), "idle"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, cwd=_REPO, env=env,
        ) as other:
            try:
                assert _line(other) == "READY"
                # Kept only now: a kept main file takes SQLite's lock bytes when it can, and a process opening the store
                # afterwards would then be refused before it said READY.
                assert ce._hold(db, whole=False, generation=generation)
                assert ce._holder_state(list(ce._HELD[generation])) == ce.HOLDER_HELD
            finally:
                other.kill()
                other.wait(timeout=30)
        assert ce._holder_state(list(ce._HELD[generation])) == ce.HOLDER_NONE
    finally:
        ce.rescrub_held(close=True, generation=generation, settle=False)


_PEEK = r"""
import fcntl, os, struct, sys
fd = os.open(sys.argv[1], os.O_RDWR)
got = fcntl.fcntl(fd, fcntl.F_GETLK, struct.pack("hhqqi", fcntl.F_RDLCK, os.SEEK_SET, 0x40000002, 510, 0))
print("LOCKED" if struct.unpack("hhqqi", got[:struct.calcsize("hhqqi")])[0] != fcntl.F_UNLCK else "FREE", flush=True)
"""


def test_the_lock_bytes_are_taken_after_the_overwrites_and_kept_until_the_descriptors_go(tmp_path):
    """R792 (2): POSIX locks belong to the process, so the erase's own overwrite of a path (an open and a close) drops any lock
    taken on it before. Taken after them, the lock bytes stay held: another process asking for SQLite's shared range on the
    erased main file is refused until the panic wipe's closing pass lets the descriptors go."""
    from src.safety import crypto_erase as ce

    data, _salt = _store(tmp_path)
    db = data / ce._MAIN_DB
    kept = tmp_path / "kept-db"
    os.link(db, kept)  # a name for the erased file, so another process can ask about it
    generation = ce.new_hold_generation()
    try:
        report = ce.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=True, hold_generation=generation)
        assert report["other_holder"] == ce.HOLDER_NONE
        peek = subprocess.run([sys.executable, "-c", _PEEK, str(kept)], capture_output=True, text=True, timeout=60)
        assert peek.stdout.strip() == "LOCKED", peek.stdout + peek.stderr
    finally:
        ce.rescrub_held(close=True, generation=generation)
    peek = subprocess.run([sys.executable, "-c", _PEEK, str(kept)], capture_output=True, text=True, timeout=60)
    assert peek.stdout.strip() == "FREE", peek.stdout + peek.stderr


def test_a_store_file_that_could_not_be_kept_makes_the_result_could_not_check(tmp_path, monkeypatch):
    from src.safety import crypto_erase as ce

    data, _salt = _store(tmp_path)
    real = ce._hold
    monkeypatch.setattr(ce, "_hold", lambda p, **k: False if p.name == ce._MAIN_DB else real(p, **k))
    report = ce.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["other_holder"] == ce.HOLDER_UNKNOWN
    assert report["files_not_kept"] == 1
    assert report["limit"] == ce._LIMIT_NOTE_NOT_CLEAN and "unrecoverable regardless" not in report["limit"]


def test_a_kept_file_grown_by_its_holder_is_rewritten_only_up_to_its_cap_and_a_pass_stops_at_its_bound(tmp_path, monkeypatch):
    """A holder that grows the file it shares with the erase (a sparse ftruncate) cannot make a rewrite fill the disk, and a
    pass past its deadline writes nothing more."""
    import time

    from src.safety import crypto_erase as ce

    monkeypatch.setattr(ce, "_HELD_GROWTH", 1024 * 1024)
    f = tmp_path / "x-wal"
    f.write_bytes(b"\x00" * 4096)
    generation = ce.new_hold_generation()
    assert ce._hold(f, whole=True, generation=generation)
    try:
        with open(f, "r+b") as grow:
            grow.truncate(1024 ** 3)  # 1 GiB, sparse: what a hostile holder could do
        assert ce.rescrub_held(close=False, generation=generation, deadline=time.monotonic() - 1) == 0
        assert ce.rescrub_held(close=False, generation=generation) == 1
        assert os.stat(f).st_blocks * 512 <= 4096 + 1024 * 1024 + 64 * 1024, "the rewrite went past the cap"
    finally:
        ce.rescrub_held(close=True, generation=generation, settle=False)
