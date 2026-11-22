"""
R789/R792 (row 315): what a crypto-erase leaves when ANOTHER process has the store open.

Measured on real SQLCipher stores (2026-11-22): a second process holding its own keyed connection cannot write into the
erased store afterwards -- page 1's salt is gone and the -shm header is zeroed, so its next write is refused -- whether it
sat idle, held a write transaction, had page 1 dirty or had already spilled pages to the log, with or without the panic
wipe's kept descriptors. This file pins that half: the write is refused, the data folder is gone, and the store's salt is
in none of the files the other process still holds.

The other half (a process that keeps writing THROUGH the erase commits into the unlinked log and leaves the salt there) is
R792's product change and is pinned with it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

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


def _store(tmp_path: Path) -> tuple[Path, bytes]:
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
            ce.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=held, hold_generation=generation)
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
    # The scan really read what the other process holds, so an empty result is not a scan that read nothing.
    assert any(t.startswith(str(db)) for t in read), f"none of the store's files was read: {read}"
    assert survivors == [], f"the salt survives in files the other process still holds: {survivors}"
