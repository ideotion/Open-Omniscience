"""Row 390 (R813, outside any erase): when the marked data drive is not the one at the data folder, an ordinary close never runs
SQLite's (or DuckDB's) close on a connection with a file there, since that close deletes ``<db>-wal``/``-shm`` BY PATH: the other
drive's files. src/database/drive_pin.py says how.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from src.database import drive_pin
from src.safety import data_volume


@pytest.fixture(autouse=True)
def _no_pins_left():
    yield
    drive_pin._reset_for_tests()


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """A watched data folder whose drive state the test sets (``state["now"]``: what the marker check answers)."""
    folder = tmp_path / "drive" / "OOS data"
    folder.mkdir(parents=True)
    state = {"now": "ok"}
    monkeypatch.setattr(data_volume, "watched", lambda: True)
    monkeypatch.setattr(data_volume, "configured_folder", lambda: folder)
    monkeypatch.setattr(data_volume, "probe", lambda: {"state": state["now"]})
    return folder, state


def _wal_store(path: Path):
    from tests._app_engine import app_sqlite_engine

    eng = app_sqlite_engine(path)
    with eng.connect() as c:
        c.execute(text("pragma journal_mode=wal"))
        c.execute(text("create table t(a)"))
        c.execute(text("insert into t values('x')"))
        c.commit()
        raw = c.connection.dbapi_connection
    return eng, raw


@pytest.mark.parametrize("now", ["missing", "mismatch"])
def test_a_close_while_the_drive_is_not_the_marked_one_pins_instead(drive, now):
    folder, state = drive
    eng, raw = _wal_store(folder / "x.db")
    state["now"] = now
    before = drive_pin.pinned_count()
    eng.dispose()  # the pool's close: the lifespan's shutdown disposal and the atexit one go the same way
    raw.execute("select count(*) from t").fetchall()  # still open: never closed
    assert drive_pin.pinned_count() == before + 1
    assert (folder / "x.db-wal").exists(), "no close ran, so no log was removed by path"
    assert not drive_pin._FROZEN, "a finding outside an erase is not kept: the next close asks again"


def test_a_close_while_the_drive_is_there_closes_as_before(drive, tmp_path):
    folder, _state = drive
    eng, raw = _wal_store(folder / "x.db")
    eng.dispose()
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("select 1")
    assert not (folder / "x.db-wal").exists(), "the last close wrote the log back and removed it, as SQLite does"


def test_a_store_off_the_drive_closes_whatever_the_drive_is(drive, tmp_path):
    _folder, state = drive
    off = tmp_path / "internal"
    off.mkdir()
    eng, raw = _wal_store(off / "x.db")
    state["now"] = "missing"
    eng.dispose()
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("select 1")


def test_an_in_memory_connection_with_a_file_on_the_drive_attached_is_pinned(drive):
    from tests._app_engine import app_sqlite_engine

    folder, state = drive
    eng = app_sqlite_engine(":memory:")
    with eng.connect() as c:
        c.execute(text("attach database :p as side"), {"p": str(folder / "side.db")})
        c.execute(text("create table side.t(a)"))
        c.commit()
        raw = c.connection.dbapi_connection
    state["now"] = "missing"
    eng.dispose()
    assert raw is not None
    raw.execute("select 1").fetchall()  # its ATTACHed file is on the drive: read on the connection being closed, so pinned


def test_an_unwatched_folder_is_never_asked_about(tmp_path, monkeypatch):
    monkeypatch.setattr(data_volume, "watched", lambda: False)
    monkeypatch.setattr(data_volume, "probe", lambda: pytest.fail("no drive is marked: nothing to ask"))
    eng, raw = _wal_store(tmp_path / "x.db")
    eng.dispose()
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("select 1")


def test_a_folder_an_erase_latched_is_the_erases_to_decide(drive, monkeypatch):
    folder, state = drive
    eng, raw = _wal_store(folder / "x.db")
    state["now"] = "missing"  # the erase removed the marker with the rest
    monkeypatch.setattr("src.paths.erased_folder_of", lambda p: True)
    eng.dispose()
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("select 1")


def test_a_marker_check_that_raises_counts_as_changed(drive, monkeypatch):
    folder, _state = drive
    eng, raw = _wal_store(folder / "x.db")

    def _boom():
        raise OSError("io")

    monkeypatch.setattr(data_volume, "probe", _boom)
    eng.dispose()
    raw.execute("select 1").fetchall()


def test_the_write_back_before_the_shutdown_disposal_is_skipped(drive):
    from src.database.shutdown_checkpoint import checkpoint_before_dispose
    from src.monitoring import forensics

    folder, state = drive
    eng, _raw = _wal_store(folder / "x.db")
    state["now"] = "missing"
    out = checkpoint_before_dispose(folder / "x.db")
    assert out["outcome"] == "skipped" and out["why"] == "drive-changed", out
    assert forensics.dispose_facts({"checked_out": 0}, out)["dispose"]["step"] == "drive"
    eng.dispose()


def test_a_serve_on_the_drive_is_kept_and_its_offload_folder_left(drive, tmp_path):
    duckdb = pytest.importorskip("duckdb")
    folder, state = drive
    con = duckdb.connect()
    con.execute(f"ATTACH '{folder / 'store.duckdb'}' AS s")
    spill = folder / "spill"
    spill.mkdir()
    state["now"] = "missing"
    assert drive_pin.on_frozen_drive(spill)
    assert drive_pin.close_or_keep(con, None) is True
    con.execute("select 1").fetchall()  # kept open
    state["now"] = "ok"
    assert not drive_pin.on_frozen_drive(spill)
    assert drive_pin.close_or_keep(duckdb.connect(), None) is False


def test_only_already_closed_counts_as_closed_for_duckdb():
    class ConnectionException(Exception):
        pass

    class Con:
        def __init__(self, msg):
            self.msg = msg

        def execute(self, *_a):
            raise ConnectionException(self.msg)

    assert drive_pin._serve_files(Con("Connection Error: Connection already closed!")) == []
    assert drive_pin._serve_files(Con("Connection Error: something else")) == [None]


def test_a_cached_persisted_serve_on_a_gone_drive_is_taken_out_and_never_refreshed(drive, monkeypatch):
    from src.analytics import rollup_serve

    folder, state = drive

    class Con:
        def execute(self, *_a):
            raise RuntimeError("unreadable")  # its files cannot be read: on the drive

        def close(self):
            pytest.fail("never closed")

    con = Con()
    monkeypatch.setitem(rollup_serve._STATE, "con", con)
    monkeypatch.setitem(rollup_serve._STATE, "persisted", True)
    monkeypatch.setitem(rollup_serve._STATE, "spill", str(folder / "spill"))
    state["now"] = "missing"
    assert rollup_serve._refresh_persisted_build() is False
    assert rollup_serve._PERSISTED_DECLINE["why"] == rollup_serve.DRIVE_CHANGED
    assert rollup_serve._STATE["con"] is None and rollup_serve._STATE["persisted"] is False
    rollup_serve._PERSISTED_DECLINE["why"] = None


def test_the_refusal_reasons_name_the_drive():
    src = Path("src/analytics/rollup_serve.py").read_text(encoding="utf-8")
    assert 'DRIVE_CHANGED = "drive-changed"' in src
    assert "_persisted_declined(DRIVE_CHANGED if gone else \"no-passphrase\")" in src
    assert "refused = DRIVE_CHANGED" in src
    m = Path("src/analytics/map_serve.py").read_text(encoding="utf-8")
    assert "offload folder is on a data drive that is not the marked one" in m


# --------------------------------------------------------------------------- #
#  The real thing: another drive mounted over the path while the app runs, then an ordinary exit (no erase)
# --------------------------------------------------------------------------- #

_CHILD = r"""
import json, os, subprocess, sys
from pathlib import Path
data = Path(os.environ["OO_DATA_DIR"])
from sqlalchemy import text
from src.database import session
with session.engine.begin() as c:  # a WAL store with a log on the drive, its connection back in the pool, open
    c.execute(text("create table if not exists t(a)"))
    for i in range(40):
        c.execute(text("insert into t values(:a)"), {"a": "x" * 400})
assert (data / "open_omniscience.db-wal").exists()
subprocess.check_call(["mount", "-t", "tmpfs", "-o", "size=20m", "tmpfs", str(data.parent)])
data.mkdir()
if sys.argv[1] != "absent":
    (data / ".oos-volume").write_text(json.dumps({"id": "ffffffffffffffff"}), encoding="utf-8")
for n in ("open_omniscience.db", "open_omniscience.db-wal", "open_omniscience.db-shm", "other.txt"):
    (data / n).write_bytes(b"FOREIGN " + n.encode() * 40)
if sys.argv[1] == "unguarded":  # the control: the close as it was before row 390
    import src.database.drive_pin as dp
    dp._gone_bases = lambda: []
from src.database.shutdown_checkpoint import checkpoint_before_dispose
print("STEP " + json.dumps(checkpoint_before_dispose()))
session.dispose_engine()  # the lifespan's shutdown disposal
print("DONE")
"""  # then a normal exit: interpreter teardown and the atexit disposal


def _can_mount(tmp_path) -> bool:
    probe = tmp_path / "mount-probe"
    probe.mkdir()
    try:
        ok = subprocess.run(["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", str(probe)], capture_output=True).returncode == 0
    except OSError:
        return False
    if ok:
        subprocess.run(["umount", str(probe)], capture_output=True)
    return ok


_FOREIGN = {n: b"FOREIGN " + n.encode() * 40 for n in ("open_omniscience.db", "open_omniscience.db-wal",
                                                       "open_omniscience.db-shm", "other.txt")}


def _run_child(tmp_path, scen):
    if sys.platform == "win32" or not _can_mount(tmp_path):
        pytest.skip("needs to mount a drive over the path (root); the unit tests above cover the close itself")
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
        assert run.returncode == 0 and "DONE" in run.stdout, run.stdout[-3000:] + run.stderr[-3000:]
        step = json.loads(next(ln for ln in run.stdout.splitlines() if ln.startswith("STEP ")).removeprefix("STEP "))
        files = {p.name: p.read_bytes() for p in data.iterdir() if p.is_file()}  # read after the process has exited
    finally:
        for _ in range(3):
            subprocess.run(["umount", "-l", str(mount_point)], capture_output=True)
    return files, step


def test_without_the_check_the_ordinary_close_deletes_the_other_drives_log_files(tmp_path):
    files, _step = _run_child(tmp_path, "unguarded")
    assert files.get("open_omniscience.db-wal") != _FOREIGN["open_omniscience.db-wal"], (
        "the control did not reproduce the deletion: the test below would prove nothing")


@pytest.mark.parametrize("scen", ["absent", "mismatch"])
def test_another_drive_at_the_path_keeps_its_files_through_an_ordinary_shutdown(tmp_path, scen):
    files, step = _run_child(tmp_path, scen)
    for name, body in _FOREIGN.items():
        assert files.get(name) == body, f"{name} on the other drive is byte-identical after the shutdown and the process exit"
    assert step["outcome"] == "skipped" and step["why"] == "drive-changed", step
