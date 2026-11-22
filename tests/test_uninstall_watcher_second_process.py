"""
R792 part B (row 315): the uninstall's detached watcher and ANOTHER process that has the store open.

Measured before the change (2026-11-22): a process committing in a loop through the watcher's erase kept the salt in a file it
still held in 5 runs of 5, and the audit log said nothing. The watcher now keeps a descriptor on each SQLite file of an
encrypted database through its unlink, looks for another holder by the locks SQLite holds, rewrites while one is seen (at most
two seconds), and says in the audit log whether another program still had the database open or that it could not check.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.database.connect import have_driver
from tests.test_crypto_erase_second_process import _KEY, _REPO, _line, _salt_in_held_files, _store

pytestmark = [
    pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed"),
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads the other process's descriptors under /proc"),
]

# The other process: commits in a loop, each transaction dirtying page 1, until told to stop; then waits, descriptors open.
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

_INCOMPLETE = "THE ERASE MAY BE INCOMPLETE"
_CHECKED = "Checked: no other program was seen holding the database"


def _run_watcher(tmp_path: Path, data: Path) -> list[str]:
    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    log = tmp_path / "audit.log"
    plan = {"files": [], "venv": None, "app_folder": None, "wipe_data_dir": str(data), "audit_log": str(log)}
    subprocess.run([sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)], check=True, timeout=120)
    return log.read_text(encoding="utf-8").splitlines()


def test_a_process_writing_through_the_uninstall_erase_is_named_in_the_audit_log(tmp_path):
    """R792 (4)+(7): never a silent log beside a surviving salt -- either none survives, or the log says the erase may be
    incomplete. The looper never closes its connection, so the watcher must have seen it."""
    data, salt = _store(tmp_path)
    db = data / "open_omniscience.db"
    env = {**os.environ, "ROW315_KEY": _KEY}
    errlog = tmp_path / "looper.stderr"
    with open(errlog, "w", encoding="utf-8") as err, subprocess.Popen(
        [sys.executable, "-c", _LOOPER, str(db)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, cwd=_REPO, env=env,
    ) as other:
        try:
            ready = _line(other)
            assert ready == "READY", f"{ready!r}; stderr: {errlog.read_text(encoding="utf-8", errors="replace")[-2000:]}"
            lines = _run_watcher(tmp_path, data)
            other.stdin.write("stop\n")
            other.stdin.flush()
            commits = _line(other)
            survivors, read = _salt_in_held_files(other.pid, salt)
            other.stdin.write("done\n")
            other.stdin.flush()
            other.wait(timeout=30)
        finally:
            if other.poll() is None:
                other.kill()

    assert commits.startswith("COMMITS"), commits
    assert any(t.startswith(str(db)) for t in read), f"none of the store's files was read: {read}"
    said = [ln for ln in lines if _INCOMPLETE in ln]
    if survivors:
        assert said, f"the salt survives in {survivors} and the audit log does not say the erase may be incomplete"
    assert said, lines
    assert not any(_CHECKED in ln for ln in lines)
    assert not data.exists()


def test_with_no_other_process_the_watcher_says_checked_and_does_not_wait(tmp_path):
    data, _salt = _store(tmp_path)
    t0 = time.monotonic()
    lines = _run_watcher(tmp_path, data)
    elapsed = time.monotonic() - t0
    assert any(_CHECKED in ln for ln in lines), lines
    assert not any(_INCOMPLETE in ln or "could not check" in ln for ln in lines)
    assert elapsed < 2.0, f"the watcher took {elapsed:.2f} s with no other process (the bound is only for a holder)"


def test_the_holder_lines_carry_no_process_id_and_no_path():
    """R734/R736: the lines this check writes name neither a process nor a file."""
    from src.safety.uninstall import _WATCHER_SRC

    body = _WATCHER_SRC[_WATCHER_SRC.index("def check_other_holders"):_WATCHER_SRC.index('rec("uninstall watcher start')]
    recs = [ln for ln in body.splitlines() if "rec(" in ln]
    assert len(recs) == 3, recs
    assert all("%" not in ln and "+" not in ln for ln in recs), recs
