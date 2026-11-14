"""The offload-folder sweep tells a reused pid from a live owner, and the folder root is owner-only (open-on-main rows 51, 52).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 51: the sweep kept every folder whose pid was alive. A crashed build's folder (plaintext, if the library was plaintext then)
whose pid a later, unrelated process happened to get stayed for as long as that process lived. A live pid now keeps its folder
only while the folder is not older than the process; when the start time cannot be read, the folder is kept and reported.
Row 52: ``mkdir(mode=0o700, exist_ok=True)`` left a ``duckdb_tmp`` an older version had made with the default mask as it was.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time

import pytest

from src.analytics import rollup_serve

psutil = pytest.importorskip("psutil")


@pytest.fixture
def live_pid():
    """A real, unrelated live process: its pid is what a reused pid looks like to the sweep."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                psutil.Process(proc.pid).create_time()
                break
            except psutil.Error:
                time.sleep(0.05)
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", True)  # this process's own folders are live ones
    r = tmp_path / "duckdb_tmp"
    r.mkdir()
    return r


def _aged(folder, seconds_before: float) -> None:
    then = psutil.Process(int(folder.name.split("-", 1)[0])).create_time() - seconds_before
    os.utime(folder, (then, then))


def test_a_folder_older_than_the_live_process_holding_its_pid_is_removed(root, live_pid):
    orphan = root / f"{live_pid}-abcd1234"
    orphan.mkdir()
    (orphan / "duckdb_temp_storage-1.tmp").write_bytes(b"rows a crashed plaintext build left")
    _aged(orphan, 3600)
    rollup_serve._sweep_spill_folders(root)
    assert not orphan.exists(), "a reused pid kept a crashed build's folder alive"


def test_a_folder_made_after_its_live_process_started_is_kept(root, live_pid):
    mine = root / f"{live_pid}-abcd1234"
    mine.mkdir()
    rollup_serve._sweep_spill_folders(root)
    assert mine.exists(), "a live process's own folder was removed"


def test_an_unreadable_start_time_keeps_the_folder_and_says_so(root, live_pid, monkeypatch, caplog):
    folder = root / f"{live_pid}-abcd1234"
    folder.mkdir()
    _aged(folder, 3600)

    class _Denied:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil, "Process", _Denied)
    with caplog.at_level("WARNING", logger=rollup_serve._LOG.name):
        rollup_serve._sweep_spill_folders(root)
    assert folder.exists(), "a folder a live process may be using was removed on a guess"
    assert folder.name in caplog.text


def test_a_dead_pid_folder_still_goes_and_other_names_stay(root):
    dead = 2**22 + 7  # above Linux's pid_max default ceiling: no such process
    assert not psutil.pid_exists(dead)
    gone = root / f"{dead}-abcd1234"
    gone.mkdir()
    other = root / "not-ours"
    other.mkdir()
    rollup_serve._sweep_spill_folders(root)
    assert not gone.exists() and other.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_an_existing_folder_root_is_tightened_to_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    root = tmp_path / "duckdb_tmp"
    root.mkdir()
    os.chmod(root, 0o755)  # what an older version made under the default mask
    folder = rollup_serve._persisted_spill_setting()
    try:
        assert folder
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    finally:
        rollup_serve._remove_spill(folder)
