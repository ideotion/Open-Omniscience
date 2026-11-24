"""
Row 388 (R813 follow-up): ``open-omniscience panic`` with the marked data drive not there (or another drive at its place)
still erases what the app keeps OUTSIDE the drive, and never touches anything at the drive's path. Run for real, in a fresh
process: the database module cannot be imported there (src/database/session.py reads the data folder at import).

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

from src.api import _panic_precheck
from src.safety import crypto_erase, data_volume

S1 = "The data drive was not present. Nothing on it was checked or erased. The data on that drive still exists."
S5 = "The data drive could not be identified. Nothing on it was checked or erased. The data on that drive still exists."


def _layout(tmp_path: Path, drive: str) -> tuple[dict, Path, dict[Path, bytes], dict[Path, bytes]]:
    """The environment of a CLI run, the data folder, the files on the drive and the files the app keeps outside it."""
    data = tmp_path / "drive" / "OOS data"
    on_drive: dict[Path, bytes] = {}
    if drive != "absent":
        data.mkdir(parents=True)
        on_drive = {data / "open_omniscience.db": os.urandom(8192), data / "keys" / "custody_ed25519.pem": b"PRIVATE"}
        for p, b in on_drive.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        marker = "ffffffffffffffff" if drive == "mismatch" else None
        if marker is not None:
            (data / data_volume.MARKER_NAME).write_text(json.dumps({"id": marker}), encoding="utf-8")
        else:
            (data / data_volume.MARKER_NAME).write_text("{not json", encoding="utf-8")
        on_drive = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    columnar = tmp_path / "internal" / "columnar"
    columnar.mkdir(parents=True)
    outside = {columnar / name: os.urandom(8192) for name in crypto_erase._DUCK_FILES}
    for p, b in outside.items():
        p.write_bytes(b)
    db = tmp_path / "internal" / "main.db"
    con = sqlite3.connect(db)
    con.execute("create table t(x)")
    con.execute("insert into t values ('secret row')")
    con.commit()
    con.close()
    outside[db] = db.read_bytes()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "OO_COLUMNAR_DIR": str(columnar),
                "DATABASE_URL": f"sqlite:///{db}", "PYTHONPATH": os.getcwd(), "HOME": str(tmp_path / "home")})
    return env, data, on_drive, outside


def _run(env: dict, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "src.api.main", "panic", *args], env=env, capture_output=True, text=True,
                          timeout=180, cwd=os.getcwd(), input=stdin)


def _erased(p: Path, before: bytes) -> bool:
    return not p.exists() or p.read_bytes() != before


def _tree(root: Path) -> dict:
    """Every entry under ``root`` (folders too) with its mode and modification time, and the folder's own: a file made, a folder
    made, a mode changed or an entry touched all show."""
    if not root.exists():
        return {}
    out: dict[str, tuple] = {".": (root.stat().st_mode, root.stat().st_mtime_ns)}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        out[str(p.relative_to(root))] = (st.st_mode, st.st_mtime_ns, p.read_bytes() if p.is_file() else None)
    return out


@pytest.mark.parametrize("drive", ["absent", "mismatch", "unreadable"])
def test_what_is_outside_the_drive_is_erased_and_the_drive_is_untouched(tmp_path, drive):
    env, data, on_drive, outside = _layout(tmp_path, drive)
    before = _tree(data)
    run = _run(env, "--yes")
    out = run.stdout
    assert run.returncode == 2, out + run.stderr
    assert "Traceback" not in run.stderr
    assert out.startswith("ERASE FAILED: " + (S5 if drive == "unreadable" else S1)), out
    assert all(_erased(p, b) for p, b in outside.items()), "every store and key file outside the drive is erased"
    assert f"Files erased outside the data drive: {len(outside)} of {len(outside)}." in out
    assert _panic_precheck.ON_THE_DRIVE in out
    assert not any(w in out.lower() for w in ("wiped", "unrecoverable", "destroyed")), out
    if drive == "absent":
        assert not data.exists() and not data.parent.exists(), "nothing is made where the drive should be"
    for p, b in on_drive.items():
        assert p.read_bytes() == b, "nothing at the drive's path is touched"
    assert _tree(data) == before, "nothing at the drive's path is made, changed or removed"
    # No other program holds a store, and this process has no pool of its own: the erase checked, so it says nothing about one.
    assert _panic_precheck.HELD not in out and _panic_precheck.UNKNOWN not in out
    # The store DATABASE_URL names is plaintext: its pages may outlive the unlink, and that is said (second security read).
    assert _panic_precheck.PLAINTEXT in out


def test_asked_first_and_a_no_erases_nothing(tmp_path):
    env, data, _on_drive, outside = _layout(tmp_path, "absent")
    run = _run(env, stdin="no\n")
    assert run.returncode == 2, run.stdout + run.stderr
    assert _panic_precheck.ASK in run.stdout and "Aborted. Nothing was erased." in run.stdout
    assert all(p.read_bytes() == b for p, b in outside.items())
    assert not data.parent.exists()


def test_asked_first_and_wipe_erases_outside(tmp_path):
    env, _data, _on_drive, outside = _layout(tmp_path, "absent")
    run = _run(env, stdin="wipe\n")
    assert run.returncode == 2, run.stdout + run.stderr
    assert all(_erased(p, b) for p, b in outside.items())


def test_nothing_outside_is_said_as_such(tmp_path):
    data = tmp_path / "drive" / "OOS data"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), data_volume.ENV_ID: "a1b2c3d4e5f60718", "PYTHONPATH": os.getcwd(),
                "HOME": str(tmp_path / "home")})
    run = _run(env, "--yes")
    assert run.returncode == 2, run.stdout + run.stderr
    assert _panic_precheck.NOTHING_OUTSIDE in run.stdout and "Files erased outside" not in run.stdout
    assert not data.parent.exists()


def test_main_db_path_names_the_file_without_the_database_module(monkeypatch, tmp_path):
    """The erase reads the main store's path through main_db_path; with the data folder unusable it is named, never made."""
    import builtins

    from src.api import unlock
    from src.paths import DataVolumeMissing

    real_import = builtins.__import__

    def _no_session(name, *a, **k):
        if name == "src.database.session":
            raise DataVolumeMissing("data drive not available")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_session)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "gone"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert unlock.main_db_path(without_the_database_module=True) == tmp_path / "gone" / "open_omniscience.db"
    assert not (tmp_path / "gone").exists()
    monkeypatch.setenv("DATABASE_URL", "postgresql://h/db")
    assert unlock.main_db_path(without_the_database_module=True) is None


_RETURNS = """
import builtins, json, os, runpy, sys
from pathlib import Path

def _plugged_in_while_asked(prompt=""):
    print(prompt)
    d = Path(os.environ["OO_DATA_DIR"])
    (d / "keys").mkdir(parents=True)
    (d / "keys" / "custody_ed25519.pem").write_bytes(b"PRIVATE")
    (d / "open_omniscience.db").write_bytes(b"S" * 4096)
    (d / os.environ["MARKER_NAME"]).write_text(json.dumps({"id": os.environ["OO_DATA_VOLUME_ID"]}), encoding="utf-8")
    return "wipe"

builtins.input = _plugged_in_while_asked
sys.argv = ["open-omniscience", "panic"]
runpy.run_module("src.api.main", run_name="__main__")
"""


def test_a_drive_plugged_in_while_the_question_waits_is_left_whole(tmp_path):
    """Security read, MEDIUM 1: the operator agreed to erase what is OUTSIDE a drive that was not there; the drive plugged in
    meanwhile is never erased (before, the erase read it as there and erased it whole, exit 0)."""
    env, data, _on_drive, outside = _layout(tmp_path, "absent")
    env["MARKER_NAME"] = data_volume.MARKER_NAME
    script = tmp_path / "returns.py"
    script.write_text(_RETURNS, encoding="utf-8")
    run = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=180, cwd=os.getcwd())
    assert run.returncode == 2, run.stdout + run.stderr
    assert _panic_precheck.RETURNED in run.stdout and "Wiped" not in run.stdout, run.stdout
    assert _panic_precheck.ON_THE_DRIVE not in run.stdout, "the drive is there: it is never asked to be connected"
    assert (data / "keys" / "custody_ed25519.pem").read_bytes() == b"PRIVATE"
    assert (data / "open_omniscience.db").read_bytes() == b"S" * 4096
    seen = _tree(data)
    assert set(seen) == {".", "keys", "keys/custody_ed25519.pem", "open_omniscience.db", data_volume.MARKER_NAME}, seen
    assert all(_erased(p, b) for p, b in outside.items()), "what is outside the drive is erased as agreed"


def test_another_program_holding_a_store_outside_the_drive_is_said(tmp_path):
    """Security read, MEDIUM 2: a second program with the off-drive database open during the erase makes it "may be incomplete"."""
    if os.name == "nt":
        pytest.skip("POSIX: the erase cannot find another holder on Windows and says so (unknown)")
    env, _data, _on_drive, _outside = _layout(tmp_path, "absent")
    db = Path(env["DATABASE_URL"].removeprefix("sqlite:///"))
    holder = sqlite3.connect(db, isolation_level=None)
    try:
        holder.execute("begin immediate")
        holder.execute("insert into t values ('held')")
        run = _run(env, "--yes")
    finally:
        holder.close()
    assert run.returncode == 2, run.stdout + run.stderr
    assert _panic_precheck.HELD in run.stdout, run.stdout


def test_only_the_cli_precheck_limits_the_erase_to_what_is_outside_the_drive():
    """The HTTP panic and main.py's own CLI erase run the full erase; only the precheck passes off_drive_only."""
    for path in ("src/api/main.py", "src/api/safety.py"):
        assert "off_drive_only" not in Path(path).read_text(encoding="utf-8"), path
    assert "panic_wipe(confirm=True, off_drive_only=True)" in Path("src/api/_panic_precheck.py").read_text(encoding="utf-8")
    # and only the erase names the main store without the database module
    users = sorted(str(p) for p in Path("src").rglob("*.py") if "without_the_database_module=True" in p.read_text(encoding="utf-8"))
    assert users == ["src/safety/crypto_erase.py"], users


def test_main_db_path_keeps_its_error_for_every_other_caller(monkeypatch, tmp_path):
    import builtins

    from src.api import unlock
    from src.paths import DataVolumeMissing

    real_import = builtins.__import__

    def _no_session(name, *a, **k):
        if name == "src.database.session":
            raise DataVolumeMissing("data drive not available")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_session)
    with pytest.raises(DataVolumeMissing):
        unlock.main_db_path()
