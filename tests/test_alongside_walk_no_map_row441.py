"""Row 441: the integrity walk BESIDE the merge never memory-maps the staged copy.

``merge._quick_check_alongside`` runs ``validate_sqlite_file(..., alongside=True)`` in the stdlib driver while the merge
holds the same file through sqlcipher3; neither library sees the other's locks. With the validation's ~2 GiB map on, a
change to the file under the live map ends the whole process with SIGBUS (lane F hit it at 200k articles). Without the
map, the same change is a read error the import refuses on. The pre-merge validation (not alongside) keeps its map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.backup import sqlite_backup
from src.backup.sqlite_backup import validate_sqlite_file

_ROOT = Path(__file__).resolve().parents[1]

#: Builds a plaintext corpus, then walks it with a progress handler that truncates the file once the walk has started:
#: a stand-in for anything that changes the staged file while the walk reads it.
_SCRIPT = r'''
import sqlite3, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from src.backup.sqlite_backup import BackupError, validate_sqlite_file
p = Path(sys.argv[2]); alongside = sys.argv[3] == "1"
con = sqlite3.connect(p)
con.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT)")
con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INT, body TEXT)")
con.execute("CREATE INDEX ix ON articles(source_id)")
con.executemany("INSERT INTO articles (source_id, body) VALUES (?, ?)", [(i % 50, f"body {i} " * 20) for i in range(40000)])
con.commit(); con.close()
done = []
def cb(conn):
    def h():
        if not done:
            done.append(1)
            with open(p, "r+b") as fh:
                fh.truncate(8192)
        return 0
    conn.set_progress_handler(h, 2000)
try:
    validate_sqlite_file(p, connection_cb=cb, alongside=alongside)
    print("passed")
except BackupError:
    print("refused")
'''


def _run(tmp_path: Path, alongside: bool) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "OO_VALIDATE_WARM"}
    return subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(_ROOT), str(tmp_path / f"t{int(alongside)}.db"), "1" if alongside else "0"],
        capture_output=True, text=True, timeout=300, env=env, check=False,
    )


def test_a_file_changed_under_the_walk_beside_the_merge_is_refused_not_a_crash(tmp_path):
    out = _run(tmp_path, alongside=True)
    assert out.returncode == 0, (out.returncode, out.stderr[-2000:])
    assert out.stdout.strip() == "refused"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the premise is the Linux SIGBUS")
def test_the_premise_with_the_map_the_same_change_ends_the_process():
    """The control, asserted rather than remembered: the pre-merge validation's map turns the same change into SIGBUS. If a
    future SQLite stops faulting here, this goes red and the reason above can be re-read."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), alongside=False)
    assert out.returncode == -signal.SIGBUS, (out.returncode, out.stdout, out.stderr[-2000:])


def _pragmas(path: Path, alongside: bool) -> list[str]:
    seen: list[str] = []
    validate_sqlite_file(path, connection_cb=lambda c: c.set_trace_callback(seen.append), alongside=alongside)
    return [s.lower().replace(" ", "") for s in seen if "mmap_size" in s.lower()]


def test_the_walk_beside_the_merge_asks_for_no_map_and_the_pre_merge_walk_keeps_its_own(tmp_path, monkeypatch):
    monkeypatch.delenv("OO_VALIDATE_WARM", raising=False)
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, body TEXT)")
    con.commit()
    con.close()
    beside = _pragmas(p, alongside=True)
    assert not any(s != "pragmammap_size=0" and "mmap_size=" in s for s in beside), beside
    before = _pragmas(p, alongside=False)
    assert f"pragmammap_size={sqlite_backup._VALIDATE_MMAP_BYTES}" in before, before
