"""What a FAILED encrypted open does to a pending -wal, pinned against real sqlcipher3.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``connect._try_open_encrypted`` closes the connection it just failed with. The unlock step's verify
connection learned that sqlcipher3's ``close()`` of the LAST connection runs the checkpoint under the
GIL (so it is written back through ``execute`` first, ``src/api/unlock.py``). The obvious next thought
is to do the same for a failed candidate. It cannot be done, and these are the measured reasons
(2026-10-01, 300 MiB log, ticker thread timing its own wake-ups; the numbers are in
``/mnt/project-files/wal-disk-pool/unlock-recovery-measure.md``), pinned deterministically so a later
session does not "fix" a failed open the wrong way, and so a change in the library that makes a fix
possible fails here and says so:

1. a WRONG PASSPHRASE at the store's right page size: the failed connection's ``close()`` still
   checkpoints the pending log into the database file (the raw frames are copied, no key is needed)
   and removes it. That is the stall under the GIL, once per log;
2. a wrong PAGE SIZE with the right key: the failed connection never gets as far as the log, so the
   log is left exactly as it was;
3. ``execute("PRAGMA wal_checkpoint(...)")`` on the failed connection raises (the codec is in its
   sticky error state), so there is nothing to run before ``close()``;
4. a keyless stdlib ``sqlite3`` connection cannot run the checkpoint either (the first page does not
   read as a database);
5. none of this costs data: the right key reopens the store with every row.

The log is built by a subprocess that exits without closing (a crash-shaped log, as the field's
were), so this process holds no connection to the file.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.database import connect as C

pytestmark = pytest.mark.skipif(not C.have_driver(), reason="needs the sqlcipher3 driver")

KEY = "failed open facts 12345"
WRONG = "not the passphrase 123"
ROOT = Path(__file__).resolve().parent.parent
_MAKE = """
import os, sys
from src.database.connect import connect
path = sys.argv[1]
c = connect(path, key={key!r}, create_encrypted=True, check_same_thread=False)
c.execute("PRAGMA journal_mode=WAL")
c.execute("PRAGMA wal_autocheckpoint=0")
c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v BLOB)")
c.commit()
c.execute("BEGIN")
for _ in range(600):
    c.execute("INSERT INTO t(v) VALUES (?)", (os.urandom(3000),))
c.execute("COMMIT")
os._exit(0)
"""


@pytest.fixture()
def pending_log(tmp_path):
    """An encrypted store (the ruled 16384 page size) whose last session left a log behind."""
    path = tmp_path / "x.db"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("OO_DB_PLAINTEXT", None)
    subprocess.run(
        [sys.executable, "-c", _MAKE.format(key=KEY), str(path)], check=True, cwd=ROOT, env=env
    )
    wal = Path(str(path) + "-wal")
    assert wal.exists() and wal.stat().st_size > 1_000_000, "the setup must leave a real log"
    return path, wal


def _rows(path: Path) -> int:
    c = C.connect(path, key=KEY, check_same_thread=False)
    try:
        return c.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        c.close()


def test_a_wrong_passphrase_at_the_right_page_size_checkpoints_the_log_on_close(pending_log):
    path, wal = pending_log
    err: list = []
    assert C._try_open_encrypted(path, WRONG, False, 5.0, 16384, last_error=err) is None
    assert err, "the failure is kept for the caller to chain"
    assert not wal.exists(), (
        "the failed connection's close() no longer checkpoints the log: if this fails, a "
        "checkpoint-before-close for a failed candidate may now be possible (see the module docstring)"
    )
    assert _rows(path) == 600, "the checkpoint on close copies the frames raw: nothing is lost"


def test_a_wrong_page_size_with_the_right_key_leaves_the_log_alone(pending_log):
    path, wal = pending_log
    before = wal.stat().st_size
    assert C._try_open_encrypted(path, KEY, False, 5.0, 4096) is None
    assert wal.exists() and wal.stat().st_size == before
    assert _rows(path) == 600


def test_the_failed_connection_cannot_run_the_checkpoint_itself(pending_log):
    path, wal = pending_log
    from sqlcipher3 import dbapi2 as sqc

    c = sqc.connect(str(path), check_same_thread=False, timeout=5.0)
    try:
        C._apply_key(c, WRONG)
        c.execute("PRAGMA cipher_page_size = 16384")
        with pytest.raises(Exception):  # noqa: B017 - the library raises MemoryError here
            c.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        with pytest.raises(Exception):  # noqa: B017 - and again for the checkpoint
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert wal.exists(), "the checkpoint through execute did not run: only close() does it"
    finally:
        c.close()


def test_a_keyless_stdlib_connection_cannot_checkpoint_an_encrypted_log(pending_log):
    path, wal = pending_log
    p = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            p.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        p.close()
    assert wal.exists()
    assert _rows(path) == 600
