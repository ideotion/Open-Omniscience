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
    then = psutil.Process(int(folder.name.removeprefix(rollup_serve._STAGING_PREFIX).split("-", 1)[0])).create_time() - seconds_before
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


@pytest.fixture
def owner_holder(tmp_path):
    """Another process that holds a folder's owner lock (as the app does for each folder it makes), until killed."""
    fcntl = pytest.importorskip("fcntl")  # noqa: F841 - POSIX only
    folder = tmp_path / "duckdb_tmp" / "held"
    folder.mkdir(parents=True)
    ready = tmp_path / "ready"
    code = (
        "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600); "
        "fcntl.flock(fd, fcntl.LOCK_EX); open(sys.argv[2], 'w').close(); time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(folder / rollup_serve._OWNER_FILE), str(ready)])
    deadline = time.time() + 10
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.02)
    named = folder.with_name(f"{proc.pid}-abcd1234")
    folder.rename(named)
    try:
        yield proc, named
    finally:
        proc.kill()
        proc.wait()


def test_a_held_owner_lock_keeps_the_folder_whatever_the_clock_says(root, owner_holder):
    """The folder looks an hour older than its live owner (a clock step on a box with no hardware clock moves psutil's start
    time): the lock it holds still proves it is in use."""
    proc, folder = owner_holder
    target = root / folder.name
    folder.rename(target)
    _aged(target, 3600)
    rollup_serve._sweep_spill_folders(root)
    assert target.exists(), "a live process's folder was removed on a timing guess"
    proc.kill()
    proc.wait()
    rollup_serve._sweep_spill_folders(root)
    assert not target.exists(), "an owner lock nobody holds left its folder behind"


def test_a_free_owner_lock_under_a_live_reused_pid_goes(root, live_pid):
    """The pid is alive, the folder is fresh by the clock, but nobody holds its lock: its owner is gone."""
    pytest.importorskip("fcntl")
    folder = root / f"{live_pid}-abcd1234"
    folder.mkdir()
    (folder / rollup_serve._OWNER_FILE).write_bytes(b"")
    rollup_serve._sweep_spill_folders(root)
    assert not folder.exists()


def test_each_folder_is_handed_out_locked_and_let_go_on_removal(tmp_path, monkeypatch):
    fcntl = pytest.importorskip("fcntl")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    folder = rollup_serve._persisted_spill_setting()
    assert folder and folder in rollup_serve._SPILL_OWNERS
    fd = os.open(os.path.join(folder, rollup_serve._OWNER_FILE), os.O_RDONLY)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
    assert [p.name for p in (tmp_path / "duckdb_tmp").iterdir()] == [os.path.basename(folder)], "a staging folder was left"
    rollup_serve._remove_spill(folder)
    assert folder not in rollup_serve._SPILL_OWNERS and not os.path.exists(folder)


def test_closing_the_serves_lets_go_of_the_owner_lock(tmp_path, monkeypatch):
    pytest.importorskip("fcntl")
    from src.scheduler import release

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    folder = rollup_serve._spill_setting()

    class _Con:
        def close(self):
            pass

    monkeypatch.setitem(rollup_serve._STATE, "con", _Con())
    monkeypatch.setitem(rollup_serve._STATE, "spill", folder)
    monkeypatch.delitem(sys.modules, "src.analytics.map_serve", raising=False)
    release._close_serves(wait=False)
    assert folder not in rollup_serve._SPILL_OWNERS and not os.path.exists(folder)


def test_a_folder_still_being_made_is_left_to_its_maker(root, live_pid):
    """Its ``new-`` name keeps it out of the pid rule until it is locked and renamed; a dead maker's goes."""
    making = root / f"{rollup_serve._STAGING_PREFIX}{live_pid}-abcd1234"
    making.mkdir()
    _aged(making, 3600)
    dead = 2**22 + 7
    assert not psutil.pid_exists(dead)
    abandoned = root / f"{rollup_serve._STAGING_PREFIX}{dead}-abcd1234"
    abandoned.mkdir()
    rollup_serve._sweep_spill_folders(root)
    assert making.exists() and not abandoned.exists()


def test_a_folder_under_this_pid_whose_lock_is_held_is_not_taken_for_an_earlier_process(root, owner_holder, monkeypatch):
    """Two containers, both pid 1, sharing one data directory: a folder named for this pid may be the other one's, live."""
    proc, folder = owner_holder
    target = root / f"{os.getpid()}-abcd1234"
    folder.rename(target)
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    rollup_serve._sweep_spill_folders(root)
    assert target.exists(), "a live folder was removed as an earlier process's"
    proc.kill()
    proc.wait()
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    rollup_serve._sweep_spill_folders(root)
    assert not target.exists()


def test_a_staging_folder_under_this_pid_left_by_an_earlier_process_goes_once(root, monkeypatch):
    """A container restarted as the same pid after a crash mid-staging: the first sweep removes that folder, a later one
    (when this process may be staging its own) does not."""
    left = root / f"{rollup_serve._STAGING_PREFIX}{os.getpid()}-abcd1234"
    left.mkdir()
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", True)
    rollup_serve._sweep_spill_folders(root)
    assert left.exists(), "a later sweep took this process's own folder in the making"
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    rollup_serve._sweep_spill_folders(root)
    assert not left.exists()


def test_a_staging_folder_whose_lock_is_held_is_kept_whatever_its_pid(root, owner_holder):
    """Its maker may live in another pid namespace sharing this data directory, where its pid means nothing here."""
    proc, folder = owner_holder
    dead = 2**22 + 11
    assert not psutil.pid_exists(dead)
    staged = root / f"{rollup_serve._STAGING_PREFIX}{dead}-abcd1234"
    folder.rename(staged)
    rollup_serve._sweep_spill_folders(root)
    assert staged.exists(), "a staging folder whose maker holds its lock was removed"
    proc.kill()
    proc.wait()
    rollup_serve._sweep_spill_folders(root)
    assert not staged.exists()
