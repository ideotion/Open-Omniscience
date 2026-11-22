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
    print("REFUSED " + type(exc).__name__, flush=True)
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


def _salt_in_held_files(pid: int, salt: bytes) -> list[str]:
    """Every file the other process still holds open that contains the salt (pipes and sockets skipped)."""
    hits = []
    for name in os.listdir(f"/proc/{pid}/fd"):
        link = f"/proc/{pid}/fd/{name}"
        try:
            target = os.readlink(link)
            if not target.startswith("/"):
                continue
            with open(link, "rb") as f:  # the other process's descriptor, after the erase: the store is gone from this one
                if salt in f.read():
                    hits.append(target)
        except OSError:
            continue
    return hits


@pytest.mark.parametrize("held", [False, True], ids=["uninstall-path", "panic-hold"])
@pytest.mark.parametrize("mode", ["idle", "in-transaction", "page1", "spill"])
def test_a_write_begun_after_the_erase_is_refused_and_leaves_no_salt(tmp_path, mode, held):
    from src.safety import crypto_erase as ce

    data, salt = _store(tmp_path)
    db = data / ce._MAIN_DB
    env = {**os.environ, "ROW315_KEY": _KEY}
    other = subprocess.Popen(
        [sys.executable, "-c", _OTHER, str(db), {"in-transaction": "txn"}.get(mode, mode)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=_REPO, env=env,
    )
    try:
        assert other.stdout.readline().strip() == "READY"
        generation = ce.new_hold_generation()
        ce.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=held, hold_generation=generation)
        if held:
            ce.rescrub_held(close=False, generation=generation)
            ce.rescrub_held(close=True, generation=generation)
        other.stdin.write("go\n")
        other.stdin.flush()
        outcome = other.stdout.readline().strip()
        survivors = _salt_in_held_files(other.pid, salt)
    finally:
        try:
            other.stdin.write("done\n")
            other.stdin.flush()
        except OSError:
            pass
        other.wait(timeout=30)

    assert outcome.startswith("REFUSED"), f"the other process wrote into the erased store: {outcome!r}"
    assert not data.exists()
    assert survivors == [], f"the salt survives in files the other process still holds: {survivors}"
