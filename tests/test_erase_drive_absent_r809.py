"""
Row 381 (R809): a marked data drive that is not there when the erase runs is a FAILURE: nothing on it is checked or erased,
the result is never "removed" and never clean, what was erased elsewhere is said apart, and nothing reassures. A drive that goes
away during the erase is "partially erased / could not check". The same holds in the CLI, with a non-zero exit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

import pytest

from src import paths
from src.safety import crypto_erase, data_volume

S1 = "The data drive was not present. Nothing on it was checked or erased. The data on that drive still exists."
S3 = "The data drive disconnected during the erase: it was only partially erased, and what was left on it could not be checked."
S5 = "The data drive could not be identified. Nothing on it was checked or erased. The data on that drive still exists."
S6 = ("Data on that drive may partly still exist. The app no longer remembers this drive, so it will not recognise or erase it on a "
      "later launch unless it is set up again.")


@pytest.fixture(autouse=True)
def _no_pins_left():
    """R812: a drive pinned by one test never keeps another test's connections open."""
    yield
    from src.database import drive_pin

    drive_pin._reset_for_tests()


@pytest.fixture
def marked(tmp_path, monkeypatch):
    """A data folder the first-launch step put on a marked drive (OO_DATA_DIR + OO_DATA_VOLUME_ID), and a columnar store the
    override keeps OUTSIDE it, on the internal disk."""
    data = tmp_path / "drive" / "OOS data"
    outside = tmp_path / "internal" / "columnar"
    outside.mkdir(parents=True)
    for name in crypto_erase._DUCK_FILES:
        (outside / name).write_bytes(b"D" * 8192)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv(data_volume.ENV_ID, "a1b2c3d4e5f60718")
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(outside))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(paths, "_memo", None)
    # The store the app has open is the one the override names, outside the drive (never the suite's own database).
    monkeypatch.setattr("src.database.session.DATABASE_URL", "sqlite:///" + str(tmp_path / "internal" / "none.db"))
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: pytest.fail("the id of a drive not there is kept"))
    # As in the running app: the error journal is installed, so a log line the erase writes would land in the data folder if the
    # erase did not latch it first (the panic's first step, src/safety/panic.py; R802).
    from src.monitoring import errorlog

    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    monkeypatch.setattr(errorlog, "_installed", errorlog._installed)
    errorlog.install()
    return data, outside


def _erase(data: Path) -> dict:
    """The erase as the panic runs it: the folder latched first (R802), then erased."""
    crypto_erase._latch(data)
    return crypto_erase.quick_crypto_erase(confirm=True)


def _app_files(data: Path, marker_id: str | None) -> dict[Path, bytes]:
    data.mkdir(parents=True)
    files = {data / "open_omniscience.db": os.urandom(8192), data / "keys" / "custody_ed25519.pem": b"PRIVATE",
             data / "wiki_dumps" / "part.xml": b"x" * 100}
    for p, b in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    if marker_id is not None:
        (data / data_volume.MARKER_NAME).write_text(json.dumps({"id": marker_id}), encoding="utf-8")
    return files


def _hashes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_drive_not_there_is_a_failure_and_nothing_is_made(marked):
    data, outside = marked
    out = _erase(data)
    assert out["drive_absent"] is True and out["removed"] is False, out
    assert out["limit"] == S1, "the sentence alone: no reassurance of any kind"
    assert "unrecoverable" not in out["limit"]
    assert not data.exists() and not data.parent.exists(), "nothing is made where the drive should be"
    # what was erased elsewhere is counted apart, and is real
    assert out["files_seen"] == len(crypto_erase._DUCK_FILES) and not any((outside / n).exists() for n in crypto_erase._DUCK_FILES)
    assert crypto_erase.settle_removed(out) is False and out["removed"] is False, "never measured as removed"


def test_a_different_drive_at_the_path_is_never_touched(marked):
    data, _outside = marked
    files = _app_files(data, marker_id="ffffffffffffffff")  # another drive's marker
    out = _erase(data)
    assert out["drive_absent"] is True and out["removed"] is False and out["limit"] == S1, out
    for p, b in files.items():
        assert p.read_bytes() == b, f"{p.name} on the other drive is byte-identical"
    assert out["keys_destroyed"] == [] and out["headers_destroyed"] == []


def test_the_marked_drive_there_is_erased_as_before(marked, monkeypatch):
    data, _outside = marked
    forgot = []
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: forgot.append(1))
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    out = _erase(data)
    assert out["drive_absent"] is False and out["drive_lost"] is False and out["removed"] is True, out
    assert not data.exists() and forgot == [1]


def test_a_drive_that_goes_away_during_the_erase_is_partial_and_unchecked(marked, monkeypatch):
    data, _outside = marked
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: None)
    monkeypatch.setattr(crypto_erase, "_drive_lost", lambda anchor: anchor is not None)
    out = _erase(data)
    assert out["drive_lost"] is True and out["removed"] is False and out["unlisted_folders"] == 0, out
    assert out["limit"].startswith(S3) and "permanently unrecoverable" not in out["limit"]
    # R812 (b): the erase had made the app forget the drive's id before it went away, so that is said (never restored).
    assert out["drive_forgotten"] is True and out["limit"].startswith(S3 + " " + S6)
    assert crypto_erase.settle_removed(out) is False


def test_the_device_check_itself(tmp_path):
    folder = tmp_path / "d" / "OOS data"
    folder.mkdir(parents=True)
    anchor = crypto_erase._drive_anchor(folder)
    real_parent = Path(os.path.realpath(folder.parent))
    assert anchor is not None and anchor[0] == real_parent and anchor[2] is False
    assert crypto_erase._drive_lost(anchor) is False
    assert crypto_erase._drive_lost((anchor[0], anchor[1] + 1, False)) is True, "another device at its place"
    assert crypto_erase._drive_lost((tmp_path / "gone", anchor[1], False)) is True, "gone"
    # The folder itself as the anchor (a mount point), removed by the erase: the erase did that, the drive is not lost.
    assert crypto_erase._drive_lost((tmp_path / "gone", anchor[1], True)) is False


def test_the_anchor_follows_a_link_to_the_drive(tmp_path):
    """Security read B (2): a parent that is a link to the drive is followed, so a clean erase is never called a lost drive."""
    drive = tmp_path / "mnt" / "drive"
    drive.mkdir(parents=True)
    (tmp_path / "home").mkdir()
    link = tmp_path / "home" / "link"
    link.symlink_to(drive, target_is_directory=True)
    folder = link / "OOS data"
    folder.mkdir()
    anchor = crypto_erase._drive_anchor(folder)
    assert anchor is not None and anchor[0] == Path(os.path.realpath(drive)) and anchor[2] is False
    import shutil

    shutil.rmtree(Path(os.path.realpath(folder)))
    assert crypto_erase._drive_lost(anchor) is False


def test_a_store_reached_through_a_linked_data_folder_is_inside_it(tmp_path):
    """Security read B (3): the data folder named through a link and a store spelled by the real path are the same place."""
    real = tmp_path / "other" / "data"
    real.mkdir(parents=True)
    link = tmp_path / "drive" / "link"
    link.parent.mkdir()
    link.symlink_to(real, target_is_directory=True)
    assert crypto_erase._under(real / "open_omniscience.db", link)
    assert crypto_erase._under(link / "x.db", real)
    assert not crypto_erase._under(tmp_path / "internal" / "x.db", link)


def test_a_mismatched_drive_through_a_linked_folder_is_untouched(tmp_path, monkeypatch):
    """Security read B (3) end to end: OO_DATA_DIR is a link to another drive's folder, the stores spelled by its real path."""
    real = tmp_path / "other" / "data"
    _app_files(real, marker_id="ffffffffffffffff")
    link = tmp_path / "drive" / "link"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    (real / "open_omniscience.db").write_bytes(b"S" * 8192)
    cols = real / "columnar"
    cols.mkdir()
    for name in crypto_erase._DUCK_FILES:
        (cols / name).write_bytes(b"D" * 8192)
    monkeypatch.setenv("OO_DATA_DIR", str(link))
    monkeypatch.setenv(data_volume.ENV_ID, "a1b2c3d4e5f60718")
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(cols))
    monkeypatch.setattr("src.database.session.DATABASE_URL", "sqlite:///" + str(real / "open_omniscience.db"))
    monkeypatch.setattr(paths, "_memo", None)
    monkeypatch.setattr(data_volume, "forget_volume_id", lambda *a, **k: pytest.fail("the id of a drive not there is kept"))
    before = _hashes(real)
    out = _erase(link)
    assert out["drive_absent"] is True and out["files_wiped"] == 0, out
    assert _hashes(real) == before


def test_an_unanswerable_drive_question_is_could_not_be_identified(monkeypatch, tmp_path):
    """R812 (a): a question that cannot be answered is a drive that could not be identified (a failure, like absent)."""
    monkeypatch.setattr(data_volume, "watched", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert crypto_erase._drive_state(tmp_path) == "unidentified"


def test_the_cli_says_failed_and_exits_2_never_a_traceback(monkeypatch, capsys):
    import src.safety as safety
    from src.api import main

    monkeypatch.setattr(paths, "data_dir", lambda: pytest.fail("data_dir() raises when the drive is not there"))
    monkeypatch.setattr(safety, "panic_wipe", lambda confirm: {"drive_absent": True, "drive_lost": False, "limit": S1,
                                                               "files_wiped": 2, "files_seen": 2, "data_dir": "x"})
    with pytest.raises(SystemExit) as e:
        main._panic_cli(force=True)
    assert e.value.code == 2
    text = capsys.readouterr().out
    assert "ERASE FAILED" in text and S1 in text and "Files erased outside the data drive: 2 of 2." in text
    assert "Wiped" not in text and "unrecoverable" not in text


def test_the_cli_exits_1_when_the_drive_went_away(monkeypatch, capsys):
    import src.safety as safety
    from src.api import main

    monkeypatch.setattr(safety, "panic_wipe", lambda confirm: {"drive_absent": False, "drive_lost": True, "limit": S3,
                                                               "files_wiped": 1, "files_seen": 3, "data_dir": "x",
                                                               "scope": "data-folder", "removed": False, "other_holder": "none"})
    with pytest.raises(SystemExit) as e:
        main._panic_cli(force=True)
    assert e.value.code == 1
    text = capsys.readouterr().out
    assert S3 in text and "could not be removed" not in text


def test_the_panic_page_says_failed_and_offers_no_overwrite():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert 'const driveAbsent = r.drive_absent === true;' in js and "!driveAbsent && !driveLost" in js
    assert 'driveAbsent ? "erase failed"' in js
    assert '"Files erased outside the data drive: {done} of {total}."' in js
    assert S1 in js and S3 in js
    assert '(driveAbsent || driveLost ? "" : `<div class="hint" style="margin-top:8px">${esc(rec)}`' in js


@pytest.mark.parametrize("layout", ["absent", "mismatch"])
def test_the_real_cli_in_a_fresh_process_exits_2_without_a_traceback(tmp_path, layout):
    """Security reads A (1) and B (1): ``open-omniscience panic`` with the drive not there used to die on the database import
    (DataVolumeMissing) with a traceback and exit 1, before the erase ever ran. Run for real, in a fresh process."""
    import subprocess
    import sys

    data = tmp_path / "drive" / "OOS data"
    files = {}
    if layout == "mismatch":
        files = _app_files(data, marker_id="ffffffffffffffff")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "PYTHONPATH": os.getcwd(),
                "HOME": str(tmp_path / "home")})
    run = subprocess.run([sys.executable, "-m", "src.api.main", "panic", "--yes"], env=env, capture_output=True, text=True,
                         timeout=120, cwd=os.getcwd())
    assert run.returncode == 2, run.stdout + run.stderr
    assert "Traceback" not in run.stderr and "ERASE FAILED: " + S1 in run.stdout
    assert "Wiped" not in run.stdout and "unrecoverable" not in run.stdout
    if layout == "absent":
        assert not data.exists() and not data.parent.exists(), "nothing is made where the drive should be"
    for p, b in files.items():
        assert p.read_bytes() == b


def test_the_precheck_leaves_every_other_command_alone(monkeypatch):
    from src.api import _panic_precheck

    monkeypatch.setattr(data_volume, "watched", lambda: True)
    monkeypatch.setattr(data_volume, "probe", lambda: {"state": "missing"})
    assert _panic_precheck.drive_absent_for_panic(["panic", "--yes"]) is True
    assert _panic_precheck.drive_absent_for_panic(["serve"]) is False and _panic_precheck.drive_absent_for_panic([]) is False
    monkeypatch.setattr(data_volume, "probe", lambda: {"state": "ok"})
    assert _panic_precheck.drive_absent_for_panic(["panic"]) is False
    monkeypatch.setattr(data_volume, "watched", lambda: False)
    assert _panic_precheck.drive_absent_for_panic(["panic"]) is False


def test_no_free_space_overwrite_where_the_drive_is_not(marked):
    """Security reads A (2) and B (4): after an erase that found another drive at the path (or an empty mount point), the
    free-space overwrite writes nothing there and never says the corpus is unrecoverable."""
    data, _outside = marked
    files = _app_files(data, marker_id="ffffffffffffffff")
    out = _erase(data)
    assert out["drive_absent"] is True
    scrub = crypto_erase.full_secure_erase(1, _cap_bytes=4096)
    assert scrub["scrub_not_done"] == "drive_absent" and scrub["bytes_written"] == 0 and scrub["scrub_location"] == "none"
    assert "unrecoverable" not in scrub["limit"] and "defence-in-depth only" in scrub["limit"]
    assert _hashes(data) == {str(p.relative_to(data)): b for p, b in files.items()} | {
        data_volume.MARKER_NAME: (data / data_volume.MARKER_NAME).read_bytes()}
    assert "drive_absent" in crypto_erase.SCRUB_NOT_DONE


def test_a_marker_that_cannot_be_read_is_could_not_be_identified(marked):
    """R812 (a): a folder at the drive's path whose marker file is there and cannot be read is not "not present"."""
    data, _outside = marked
    files = _app_files(data, marker_id=None)
    (data / data_volume.MARKER_NAME).write_text("{not json", encoding="utf-8")
    before = _hashes(data)
    out = _erase(data)
    assert out["drive_absent"] is True and out["drive_unidentified"] is True and out["limit"] == S5, out
    assert _hashes(data) == before and files


def test_an_empty_mount_point_stays_not_present(marked):
    """R812 (a): a folder with no marker file at all (an empty mount point) is the drive not being there: S1."""
    data, _outside = marked
    data.mkdir(parents=True)
    out = _erase(data)
    assert out["drive_absent"] is True and out["drive_unidentified"] is False and out["limit"] == S1, out
    assert list(data.iterdir()) == []


def test_a_drive_swapped_between_the_probe_and_the_first_write_gets_zero_writes(marked, monkeypatch):
    """R812 (c): the folder at the drive's path is replaced after the probe (another drive mounted there, carrying even the same
    marker): the re-check before the first write sees another folder, and nothing on either is written."""
    from src.safety import data_scope

    data, _outside = marked
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    real_scope = data_scope.folder_scope
    swapped: dict[str, dict] = {}

    def _swap(base):
        result = real_scope(base)
        original = data.with_name("original drive")
        data.rename(original)
        _app_files(data, marker_id="a1b2c3d4e5f60718")  # the same marker: only the identity tells them apart
        swapped["new"], swapped["original"] = _hashes(data), _hashes(original)
        return result

    monkeypatch.setattr(data_scope, "folder_scope", _swap)
    out = _erase(data)
    assert swapped, "the swap ran between the probe and the erase"
    assert out["drive_absent"] is True and out["drive_unidentified"] is True and out["limit"] == S5, out
    assert out["drive_lost"] is False, "never written on: not also called partially erased (security read C (3))"
    assert _hashes(data) == swapped["new"], "zero writes on the drive now at the path"
    assert _hashes(data.with_name("original drive")) == swapped["original"]
    assert out["headers_destroyed"] == [] and out["keys_destroyed"] == []


def test_a_drive_that_changes_before_the_key_step_is_stopped_and_keeps_its_id(marked, monkeypatch):
    """R812 (c): changed after the first write: nothing more on it is touched (its keys stay), the result is S3, and the id was
    not forgotten yet, so S6 is not said."""
    data, _outside = marked
    files = _app_files(data, marker_id="a1b2c3d4e5f60718")
    real_same = crypto_erase._drive_same
    calls: list[bool] = []

    def _same(hold, want_id, *, marker):
        calls.append(marker)
        # Every re-check up to the one before the first write (each reads the marker) is real; the first later one (the lane
        # dispose, after the first write and before the key step) and every one after it see another drive.
        return real_same(hold, want_id, marker=marker) if all(calls) else False

    monkeypatch.setattr(crypto_erase, "_drive_same", _same)
    out = _erase(data)
    assert out["drive_lost"] is True and out["drive_forgotten"] is False and out["removed"] is False, out
    assert out["limit"].startswith(S3) and S6 not in out["limit"] and "permanently unrecoverable" not in out["limit"]
    key = data / "keys" / "custody_ed25519.pem"
    assert key.read_bytes() == files[key], "the key material on a changed drive is never touched"
    assert (data / "wiki_dumps" / "part.xml").read_bytes() == files[data / "wiki_dumps" / "part.xml"]


def test_the_real_cli_says_could_not_be_identified(tmp_path):
    import subprocess
    import sys

    data = tmp_path / "drive" / "OOS data"
    _app_files(data, marker_id=None)
    (data / data_volume.MARKER_NAME).write_text("{not json", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "PYTHONPATH": os.getcwd(),
                "HOME": str(tmp_path / "home")})
    run = subprocess.run([sys.executable, "-m", "src.api.main", "panic", "--yes"], env=env, capture_output=True, text=True,
                         timeout=120, cwd=os.getcwd())
    assert run.returncode == 2 and "ERASE FAILED: " + S5 in run.stdout and "Traceback" not in run.stderr, run.stdout + run.stderr


def test_the_page_says_r812():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert S5 in js and S6 in js and "r.drive_unidentified === true" in js and "r.drive_forgotten === true" in js


# --------------------------------------------------------------------------- #
#  R812 (coordinator decision 1): connections on a drive that is not there, not identifiable or changed are never closed
# --------------------------------------------------------------------------- #

_CHILD = r"""
import json, os, subprocess, sys
from pathlib import Path
data = Path(os.environ["OO_DATA_DIR"])
mount_point = data.parent
scen = sys.argv[1]
from sqlalchemy import text
from src.database import session
with session.engine.begin() as c:  # a WAL store with a log on the drive, its connection back in the pool, open
    c.execute(text("create table if not exists t(a)"))
    for i in range(40):
        c.execute(text("insert into t values(:a)"), {"a": "x" * 400})
assert (data / "open_omniscience.db-wal").exists()

def swap():
    # Another drive mounted over the path. The open connections still reach the old drive's files; the path reaches the new
    # drive's. SQLite's "has the file moved" test compares the INODE NUMBER only, and a fresh drive's first files get the same
    # numbers, so it reads "not moved", checkpoints and deletes the log files by path (measured; a rename on one file system
    # gets a new inode and never shows it, which is why this test mounts).
    subprocess.check_call(["mount", "-t", "tmpfs", "-o", "size=20m", "tmpfs", str(mount_point)])
    data.mkdir()
    (data / ".oos-volume").write_text(json.dumps({"id": "ffffffffffffffff"}), encoding="utf-8")
    for n in ("open_omniscience.db", "open_omniscience.db-wal", "open_omniscience.db-shm", "other.txt"):
        (data / n).write_bytes(b"FOREIGN " + n.encode() * 40)

from src.safety import crypto_erase
if scen in ("absent", "absent-unpinned"):
    swap()
    if scen == "absent-unpinned":  # the control: without the pin, the close deletes the other drive's log files
        import src.database.drive_pin as dp
        dp.pin_drive = lambda base: 0
elif scen == "mid":
    real_same, calls = crypto_erase._drive_same, []
    def same(hold, want_id, *, marker):
        calls.append(1)
        if len(calls) == 2:
            swap()
        return real_same(hold, want_id, marker=marker)
    crypto_erase._drive_same = same
from src.safety import panic_wipe
rep = panic_wipe(confirm=True)
print("REPORT " + json.dumps({k: rep.get(k) for k in ("drive_absent", "drive_lost", "drive_key_in_memory",
                                                      "drive_connections_kept", "limit")}))
sys.stdout.flush()
"""  # then a NORMAL exit: interpreter teardown, atexit (the engine dispose at exit) and all


def _can_mount(tmp_path) -> bool:
    import subprocess

    probe = tmp_path / "mount-probe"
    probe.mkdir()
    try:
        ok = subprocess.run(["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", str(probe)], capture_output=True).returncode == 0
    except OSError:
        return False
    if ok:
        subprocess.run(["umount", str(probe)], capture_output=True)
    return ok


def _run_child(tmp_path, scen):
    import subprocess
    import sys

    if not _can_mount(tmp_path):
        pytest.skip("needs to mount a drive over the path (root); the unit test below covers the pin itself")
    mount_point = tmp_path / "drive"
    mount_point.mkdir()
    subprocess.check_call(["mount", "-t", "tmpfs", "-o", "size=20m", "tmpfs", str(mount_point)])
    data = mount_point / "OOS data"
    data.mkdir()
    (data / data_volume.MARKER_NAME).write_text(json.dumps({"id": "a1b2c3d4e5f60718"}), encoding="utf-8")
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "OO_DB_PLAINTEXT": "1",
                "OO_NO_SCHEDULER": "1", "OO_AUTOSEED": "0", "OO_LLM_AUTOSTART": "0", "OO_STORAGE_GUARD": "0",
                "PYTHONPATH": os.getcwd(), "HOME": str(tmp_path / "home")})
    try:
        run = subprocess.run([sys.executable, str(script), scen], env=env, capture_output=True, text=True, timeout=240,
                             cwd=os.getcwd())
        assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
        line = next(ln for ln in run.stdout.splitlines() if ln.startswith("REPORT "))
        files = {p.name: p.read_bytes() for p in data.iterdir() if p.is_file()}  # read after the process has exited
    finally:
        for _ in range(3):
            subprocess.run(["umount", "-l", str(mount_point)], capture_output=True)
    return files, json.loads(line.removeprefix("REPORT "))


_FOREIGN = {n: b"FOREIGN " + n.encode() * 40 for n in ("open_omniscience.db", "open_omniscience.db-wal",
                                                       "open_omniscience.db-shm", "other.txt")}


def test_without_the_pin_the_close_deletes_the_other_drives_log_files(tmp_path):
    """The control: what the pin prevents is real (SQLite removes <db>-wal/-shm BY PATH when the last connection closes)."""
    files, _report = _run_child(tmp_path, "absent-unpinned")
    assert files.get("open_omniscience.db-wal") != _FOREIGN["open_omniscience.db-wal"], (
        "the control did not reproduce the deletion: the test below would prove nothing")


@pytest.mark.parametrize("scen", ["absent", "mid"])
def test_another_drive_at_the_path_keeps_its_log_files_after_panic_and_exit(tmp_path, scen):
    files, report = _run_child(tmp_path, scen)
    for name, body in _FOREIGN.items():
        assert files.get(name) == body, f"{name} on the other drive is byte-identical after panic and process exit"
    assert report["drive_key_in_memory"] is True and report["drive_connections_kept"] >= 1, report
    assert crypto_erase._DRIVE_KEY_IN_MEMORY_SENTENCE in report["limit"]
    if scen == "absent":
        assert report["drive_absent"] is True
    else:
        assert report["drive_lost"] is True and report["drive_absent"] is False


def test_a_pinned_connection_is_never_closed(tmp_path):
    """Without a mount (CI): a pool connection on the drive survives every close the pool makes once the drive is pinned, and one
    elsewhere is closed as before."""
    from sqlalchemy import text

    from src.database import drive_pin
    from tests._app_engine import app_sqlite_engine

    on, off = tmp_path / "drive" / "OOS data", tmp_path / "internal"
    on.mkdir(parents=True)
    off.mkdir()
    engines = [app_sqlite_engine(d / "x.db") for d in (on, off)]
    raws = []
    for eng in engines:
        with eng.connect() as c:
            c.execute(text("pragma journal_mode=wal"))
            c.execute(text("create table t(a)"))
            c.commit()
            raws.append(c.connection.dbapi_connection)
    try:
        assert drive_pin.pin_drive(on) >= 1
        for eng in engines:
            eng.dispose()
        raws[0].execute("select count(*) from t").fetchall()  # still open: never closed
        with pytest.raises(sqlite3.ProgrammingError):
            raws[1].execute("select 1")  # closed as before
        assert (on / "x.db-wal").exists(), "the log of a pinned store is never removed by a close"
    finally:
        drive_pin._reset_for_tests()


# --- R813 (the security read of d6954606e): the DuckDB serves and their offload folders on a frozen drive ----------------------


class _FakeDuck:
    """A stand-in for a DuckDB connection: the files it has ATTACHed, and whether it was closed."""

    def __init__(self, files):
        self.files, self.closed = list(files), False

    def execute(self, _sql):
        files = self.files

        class _R:
            def fetchall(self):
                return [(f,) for f in files]

        return _R()

    def close(self):
        self.closed = True


def test_a_serve_on_a_frozen_drive_is_kept_and_its_offload_folder_stays(tmp_path):
    from src.analytics import rollup_serve
    from src.database import drive_pin
    from src.scheduler import release

    base = tmp_path / "drive" / "OOS data"
    spill = base / "duckdb_tmp" / "x"
    spill.mkdir(parents=True)
    (spill / "t.tmp").write_bytes(b"other drive")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    off = _FakeDuck([str(elsewhere / "c.duckdb")])
    on_file = _FakeDuck([str(base / "columnar.duckdb")])
    on_spill = _FakeDuck([])
    assert drive_pin.close_or_keep(on_file) is False and on_file.closed, "nothing frozen: an ordinary close"
    on_file.closed = False
    drive_pin.pin_drive(base)
    assert drive_pin.close_or_keep(off) is False and off.closed
    assert drive_pin.close_or_keep(on_file) is True and not on_file.closed
    assert drive_pin.close_or_keep(on_spill, str(spill)) is True and not on_spill.closed
    rollup_serve._remove_spill(str(spill))
    assert (spill / "t.tmp").read_bytes() == b"other drive", "an offload folder on a frozen drive is never removed"
    # The close the erase makes, and the one once free, take it out of the state and keep it open.
    saved = dict(rollup_serve._STATE)
    try:
        rollup_serve._STATE.update(con=on_spill, spill=str(spill), persisted=False)
        out = release._close_serves(wait=True)
        assert "rollup_serve" in out["closed"] and rollup_serve._STATE["con"] is None and not on_spill.closed
        assert (spill / "t.tmp").exists()
        rollup_serve._STATE.update(con=on_file, spill=None, persisted=True)
        release._close_when_free("rollup_serve", on_file, "cleared-key", 1 << 62)
        assert rollup_serve._STATE["con"] is None and not on_file.closed
    finally:
        rollup_serve._STATE.clear()
        rollup_serve._STATE.update(saved)


def test_pinning_takes_a_serve_under_its_own_lock_and_leaves_a_busy_one_to_its_later_close(tmp_path):
    from src.analytics import rollup_serve
    from src.database import drive_pin

    base = tmp_path / "drive" / "OOS data"
    base.mkdir(parents=True)
    con = _FakeDuck([str(base / "columnar.duckdb")])
    saved = dict(rollup_serve._STATE)
    try:
        rollup_serve._STATE.update(con=con, spill=None, persisted=True)
        with rollup_serve._LOCK:  # a query is using it: pinning never touches it from another thread
            drive_pin.pin_drive(base)
            assert rollup_serve._STATE["con"] is con
        drive_pin.pin_drive(base)  # free now
        assert rollup_serve._STATE["con"] is None and rollup_serve._STATE["persisted"] is False and not con.closed
    finally:
        rollup_serve._STATE.clear()
        rollup_serve._STATE.update(saved)


def test_a_folder_on_another_file_system_at_the_same_device_and_inode_is_a_change(marked, monkeypatch):
    data, _outside = marked
    _app_files(data, marker_id="a1b2c3d4e5f60718")
    fds: list[int] = []
    hold = crypto_erase._drive_hold(data, fds)
    try:
        assert hold is not None and crypto_erase._drive_same(hold, "a1b2c3d4e5f60718", marker=True)
        if hold[2] is None or not hasattr(os, "fstatvfs"):
            pytest.skip("no held descriptor on this platform")
        real_statvfs = os.statvfs

        class _Other:
            def __init__(self, st):
                self._st = st

            def __getattr__(self, name):
                return getattr(self._st, name) if name != "f_fsid" else self._st.f_fsid + 1

        from tests.os_scope import scope_os

        scope_os(monkeypatch, crypto_erase, statvfs=lambda p: _Other(real_statvfs(p)))
        assert crypto_erase._drive_same(hold, "a1b2c3d4e5f60718", marker=False) is False
    finally:
        for fd in fds:
            os.close(fd)


def test_a_build_with_its_offload_folder_on_a_frozen_drive_is_never_served(tmp_path):
    """A build that ends after the drive was found changed is not swapped in (left in the state it would be freed at shutdown,
    and DuckDB would delete its offload files by path, on the other drive): it is kept, and its folder stays."""
    from src.analytics import rollup_serve
    from src.database import drive_pin

    base = tmp_path / "drive" / "OOS data"
    spill = base / "duckdb_tmp" / "y"
    spill.mkdir(parents=True)
    drive_pin.pin_drive(base)
    assert rollup_serve._on_frozen_drive(str(spill)) and rollup_serve._on_frozen_drive(True)
    assert not rollup_serve._on_frozen_drive(str(tmp_path / "elsewhere"))
    src = Path("src/analytics/rollup_serve.py").read_text(encoding="utf-8")
    assert "if spill and (_corpus_encrypted() or _on_frozen_drive(spill)):" in src
    assert "_on_frozen_drive(True)" in src
    assert "rollup_serve._on_frozen_drive(spill)" in Path("src/analytics/map_serve.py").read_text(encoding="utf-8")


def test_an_in_memory_pool_connection_is_on_no_drive_and_tracking_keeps_nothing_alive(tmp_path):
    """CI found the absent-drive result saying the key stays in memory because another test's in-memory pool connection (its main
    file "") was counted as on the drive. And tracking holds only a weak reference to the pool record, so an engine let go of
    still closes its connections as before."""
    import gc

    from sqlalchemy import text

    from src.database import drive_pin
    from tests._app_engine import app_sqlite_engine

    eng = app_sqlite_engine(":memory:")
    with eng.connect() as c:
        c.execute(text("select 1"))
    base = tmp_path / "drive" / "OOS data"
    base.mkdir(parents=True)
    assert drive_pin.pin_drive(base) == 0
    eng2 = app_sqlite_engine(tmp_path / "x.db")
    with eng2.connect() as c:
        c.execute(text("select 1"))
    n = len(drive_pin._LIVE)
    del eng2, c
    gc.collect()
    assert drive_pin.pin_drive(tmp_path) == 0, "a freed engine's connection is never pinned"
    assert len(drive_pin._LIVE) <= n
    eng.dispose()
