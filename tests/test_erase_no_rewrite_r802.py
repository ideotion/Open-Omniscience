"""
Row 343 (R802): from the moment an erase starts, and for the rest of the process, nothing in the app writes into the folder being
erased or makes it again.

Measured before this row: the app's error-file handler (src/monitoring/errorlog.py) wrote the erase's own last warnings into
``data_dir()/app_errors.jsonl``, and ``data_dir()`` makes a missing folder again, so a panic wipe reported ``removed=False`` and left
a data folder holding ``app_errors.jsonl`` and its ``.lock``. Now the erase latches the folder (``src.paths.latch_erased``) while the
journal's lock is held: ``data_dir()`` refuses it, an audit hook refuses every Python open for writing, folder creation, rename and
link into it (a writer holding a path from before the erase included), the journal writes to stderr when its folder is not there,
and ``removed`` is measured after the erase's last log line and said truthfully.

These run the erase paths with the error journal INSTALLED and a background thread logging warnings and writing throughout.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from src import paths
from src.safety import crypto_erase


def _fill(data: Path) -> None:
    (data / "keys").mkdir(parents=True)
    (data / "keys" / "custody_ed25519.pem").write_bytes(b"PRIVATE")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    (data / "wiki_dumps").mkdir()
    (data / "wiki_dumps" / "part.xml").write_bytes(b"x" * 100)


@pytest.fixture
def running_app(tmp_path, monkeypatch):
    """A data folder the app points at, the error journal installed, and a thread that logs a warning and tries every kind of write
    the app's writers make, without pause, until the test ends."""
    from src.monitoring import errorlog

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    monkeypatch.setattr(errorlog, "_installed", errorlog._installed)
    errorlog.install()
    logging.getLogger("oo.test.r802").warning("before the erase")
    assert (data / "app_errors.jsonl").exists(), "the journal writes into the data folder while it is there"
    held = data / "wiki_dumps" / "later" / "part.bin"  # a path a writer kept from before the erase
    stop = threading.Event()
    counts = {"warnings": 0}

    def writer() -> None:
        log = logging.getLogger("oo.test.r802.bg")
        while not stop.is_set():
            log.warning("a background warning")
            counts["warnings"] += 1
            for attempt in (
                lambda: (paths.data_dir() / "settings.json").write_text("{}", encoding="utf-8"),
                lambda: paths.diagnostics_dir(),
                lambda: held.parent.mkdir(parents=True, exist_ok=True),
                lambda: (data / "late.txt").write_text("late", encoding="utf-8"),
                lambda: os.close(os.open(data / "late.bin", os.O_CREAT | os.O_WRONLY, 0o600)),
            ):
                with contextlib.suppress(Exception):
                    attempt()
            time.sleep(0.001)

    thread = threading.Thread(target=writer, name="oo-test-r802-writer", daemon=True)
    thread.start()
    try:
        yield data
    finally:
        stop.set()
        thread.join(10)
    assert counts["warnings"] > 0


def _settle() -> None:
    time.sleep(0.3)  # the writer goes on after the erase returns


def _no_journal_anywhere(data: Path) -> None:
    found = [p for p in data.parent.rglob("*") if p.name in ("app_errors.jsonl", "app_errors.jsonl.lock")]
    assert found == [], found


def test_the_quick_erase_leaves_the_folder_gone_with_the_journal_installed(running_app):
    data = running_app
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    _settle()
    assert report["removed"] is True and not report.get("folder_back"), report
    assert not os.path.lexists(data), sorted(p.name for p in data.iterdir())
    _no_journal_anywhere(data)


def test_the_panic_wipe_leaves_the_folder_gone_with_the_journal_installed(running_app, monkeypatch):
    import src.database.session as session
    import src.ingest as ingest
    import src.scheduler.runner as runner
    from src.database import after_shutdown
    from src.safety import panic_wipe

    # This process's own collector, jobs and pool are the suite's: the wipe's closing steps are stood in for, the erase is real.
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0, **_k: None)
    monkeypatch.setattr(after_shutdown, "stop_jobs_and_close", lambda timeout: [])
    monkeypatch.setattr(session, "dispose_engine", lambda: {})
    monkeypatch.setattr(ingest, "activate_kill_switch", lambda *a, **k: None)
    data = running_app
    report = panic_wipe(data_dir=data, confirm=True)
    _settle()
    assert report["removed"] is True and not report.get("folder_back"), report
    assert not os.path.lexists(data)
    _no_journal_anywhere(data)


def test_a_folder_the_erase_keeps_is_never_written_into_after_it(running_app, monkeypatch):
    """R711's app-only scope keeps the folder (it holds the operator's files): nothing of the app's goes back into it."""
    from src.safety import data_scope

    data = running_app
    (data / "my-notes.txt").write_text("the operator's", encoding="utf-8")
    monkeypatch.setattr(data_scope, "folder_scope", lambda base: {"broad": True, "reason": "test"})
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["scope"] == "app-only", report
    # What the writer put there BEFORE the erase is not the app's by name, so the erase left it as the operator's: cleared here by the
    # test (an operator's own removal), then nothing may come back.
    with paths.erase_owned():
        for p in data.iterdir():
            if p.name != "my-notes.txt":
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    _settle()
    assert sorted(p.name for p in data.iterdir()) == ["my-notes.txt"]
    _no_journal_anywhere(data)


def test_data_dir_refuses_the_latched_folder_and_never_makes_it(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    paths.data_dir()
    paths.latch_erased(data)
    data.rmdir()
    with pytest.raises(paths.DataFolderErased):
        paths.data_dir()
    for make in (lambda: data.mkdir(), lambda: os.makedirs(data / "a" / "b"), lambda: (data / "x").mkdir(parents=True)):
        with pytest.raises(OSError):
            make()
    assert not data.exists()
    # Reading is never refused, and a folder beside it is untouched.
    (tmp_path / "beside").mkdir()
    (tmp_path / "beside" / "f").write_text("ok", encoding="utf-8")
    assert (tmp_path / "beside" / "f").read_text(encoding="utf-8") == "ok"


def test_the_latch_refuses_writes_into_a_folder_that_is_still_there(tmp_path):
    data = tmp_path / "kept"
    data.mkdir()
    (data / "old.txt").write_text("old", encoding="utf-8")
    paths.latch_erased(data)
    for write in (
        lambda: (data / "new.txt").write_text("x", encoding="utf-8"),
        lambda: open(data / "old.txt", "a", encoding="utf-8").close(),  # noqa: SIM115
        lambda: os.close(os.open(data / "n2", os.O_CREAT | os.O_WRONLY)),
        lambda: os.rename(tmp_path / "src.txt", data / "moved.txt"),
        lambda: os.symlink("old.txt", data / "link"),
    ):
        (tmp_path / "src.txt").write_text("s", encoding="utf-8")
        with pytest.raises(paths.DataFolderErased):
            write()
    assert (data / "old.txt").read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in data.iterdir()) == ["old.txt"]
    with paths.erase_owned():  # the erase's own work, on its own thread
        (data / "scrub").write_text("s", encoding="utf-8")
    (data / "scrub").unlink()


def test_the_journal_never_makes_a_missing_data_folder(tmp_path, monkeypatch, capsys):
    """R802 (1), with no erase at all: the folder gone means stderr only."""
    from src.monitoring import errorlog

    data = tmp_path / "gone"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    errorlog._append({"level": "WARNING", "logger": "oo.test.nofolder", "message": "with no folder"})
    assert not data.exists()
    assert "oo.test.nofolder" in capsys.readouterr().err


def test_the_journal_lock_is_never_made_without_its_folder(tmp_path):
    from src.safety.file_lock import locked_append

    target = tmp_path / "gone" / "app_errors.jsonl"
    with pytest.raises(OSError):
        locked_append(target, "x\n", create_folder=False)
    assert not (tmp_path / "gone").exists()


def test_a_second_erase_in_the_process_never_makes_the_folder_again(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    first = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert first["removed"] is True
    from src.api import unlock
    from src.custody import signing

    second = crypto_erase.quick_crypto_erase(confirm=True)  # the default folder: the latched one, named, never made
    assert unlock and signing  # imported so the default resolution has what it needs
    assert second["removed"] is True and not data.exists(), second


def test_the_free_space_scrub_never_makes_the_erased_folder_again(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert out["bytes_written"] == 1 << 16 and out["scrub_location"] == "above-data-folder", out
    assert not data.exists()
    assert [p.name for p in tmp_path.iterdir()] == [], "the scrub's private folder is removed"


def test_removed_is_measured_last_and_said_truthfully(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    report = {"scope": "data-folder", "data_dir": str(data), "removed": True, "limit": crypto_erase._LIMIT_NOTE}
    assert crypto_erase.settle_removed(report) is False
    assert report["removed"] is False and report["folder_back"] is True
    assert report["limit"].startswith(crypto_erase._FOLDER_BACK_SENTENCE) and "may be incomplete" in report["limit"]
    kept = {"scope": "app-only", "data_dir": str(data), "removed": False, "limit": crypto_erase._LIMIT_NOTE}
    assert crypto_erase.settle_removed(kept) is False and "folder_back" not in kept and kept["limit"] == crypto_erase._LIMIT_NOTE


def test_the_secure_uninstall_latches_the_folder_when_it_is_scheduled(tmp_path, monkeypatch):
    from src.safety import uninstall

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    venv = tmp_path / "venv"
    venv.mkdir()
    monkeypatch.setattr(uninstall, "plan_uninstall", lambda *_a, **_k: {
        "mode": "secure", "venv": str(venv), "launchers": [], "app_folder": None, "data_dir": str(data),
        "wipe_data_dir": str(data), "removable": True, "audit_log": str(tmp_path / "audit.log")})
    spawned = []
    out = uninstall.request_uninstall(confirm=True, wipe_data=True, _spawn=lambda plan, pid: spawned.append(plan),
                                      _arm_shutdown=lambda: None)
    assert out["scheduled"] and spawned
    with pytest.raises(paths.DataFolderErased):
        paths.data_dir()
    with pytest.raises(OSError):
        (data / "app_errors.jsonl").write_text("x", encoding="utf-8")


def test_a_minimal_uninstall_latches_nothing(tmp_path, monkeypatch):
    from src.safety import uninstall

    data = tmp_path / "OOS data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    monkeypatch.setattr(uninstall, "plan_uninstall", lambda *_a, **_k: {
        "mode": "minimal", "venv": str(tmp_path), "launchers": [], "app_folder": None, "data_dir": str(data),
        "wipe_data_dir": None, "removable": True, "audit_log": str(tmp_path / "audit.log")})
    uninstall.request_uninstall(confirm=True, _spawn=lambda plan, pid: None, _arm_shutdown=lambda: None)
    assert paths.data_dir() == data


_PRELUDE_BACK = r"""
import os, shutil
_rt, _ls, _armed = shutil.rmtree, os.lstat, []
def _again(p, *a, **k):
    _rt(p, *a, **k)
    if os.path.basename(os.fspath(p)) == "oo-data":
        _armed.append(os.fspath(p))
def _lstat(p, *a, **k):
    if _armed and os.fspath(p) == _armed[0]:
        os.mkdir(_armed.pop())   # what a server still running would do, just after the wipe looked
        raise FileNotFoundError(p)
    return _ls(p, *a, **k)
shutil.rmtree, os.lstat = _again, _lstat
"""


def test_the_watcher_says_when_the_data_folder_is_there_again(tmp_path):
    import json
    import subprocess
    import sys

    from src.safety.uninstall import _WATCHER_SRC

    data = tmp_path / "home" / "oo-data"
    data.mkdir(parents=True)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "home")}
    plan = {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}
    subprocess.run([sys.executable, "-c", _PRELUDE_BACK + _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=60, check=True,
                   env=env)
    text = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "existed again after the wipe had removed it" in text and "salt pages destroyed" not in text, text


def test_the_panic_page_and_the_cli_never_call_a_folder_that_came_back_clean():
    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert "&& !back" in js and "r.folder_back === true" in js
    from tests.js_source_helper import python_function_source

    main = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(encoding="utf-8")
    cli = python_function_source(main, "_panic_cli")
    assert 'report.get("folder_back")' in cli


# ---- R805 (the coordinator's conditions on R802's limits) and the security reads ----


def test_a_data_folder_the_erase_could_not_remove_is_never_said_to_have_come_back(tmp_path):
    """A link as the data folder survives the erase: that is "could not be removed", never "something recreated it"."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "open_omniscience.db").write_bytes(b"S" * 8192)
    link = tmp_path / "OOS data"
    link.symlink_to(real, target_is_directory=True)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=link)
    if report["scope"] != "data-folder":
        pytest.skip("a link judged shared keeps the folder by design")
    assert report["removed"] is False and not report.get("folder_back"), report
    assert report["limit"].startswith(crypto_erase._NOT_REMOVED_SENTENCE), report


def test_settle_removed_reads_the_erase_s_own_first_measure(tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    never = {"scope": "data-folder", "data_dir": str(data), "removed": False, "limit": crypto_erase._LIMIT_NOTE}
    crypto_erase.settle_removed(never)
    assert "folder_back" not in never and never["limit"].startswith(crypto_erase._NOT_REMOVED_SENTENCE)


def test_stdlib_sqlite_and_sqlite_uris_are_refused_in_a_latched_folder(tmp_path):
    import sqlite3

    data = tmp_path / "kept"
    data.mkdir()
    paths.latch_erased(data)
    with pytest.raises(paths.DataFolderErased):
        sqlite3.connect(data / "fresh.db")
    with pytest.raises(paths.DataFolderErased):
        sqlite3.connect(f"file:{data / 'u.db'}?mode=rwc", uri=True)
    with pytest.raises(paths.DataFolderErased):
        sqlite3.connect(f"file://localhost{data / 'h%20x.db'}", uri=True)  # an authority and an escape are read as SQLite reads them
    from src.database.connect import connect

    with pytest.raises(paths.DataFolderErased):
        connect(f"file:{data / 'c.db'}?mode=rwc")
    assert list(data.iterdir()) == []
    sqlite3.connect(":memory:").close()  # never refused


def test_an_erase_outside_the_panic_closes_its_own_pool_on_the_store_first(tmp_path, monkeypatch):
    """R805 (a): this process's own connections are invisible to the lock probe, so the bare erase closes the pool on a store in the
    folder it erases, and one still checked out makes the result "held", never clean."""
    import src.database.session as session

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setattr(session, "DB_FILE", str(data / "open_omniscience.db"))
    seen = []
    monkeypatch.setattr(session, "dispose_engine", lambda: seen.append("dispose") or {"checked_out": 1})
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert seen == ["dispose"]
    assert report["own_connections_open"] == 1 and report["other_holder"] == "held", report
    assert "may still be recoverable" in report["limit"] or "may have written" in report["limit"], report


def test_an_erase_of_another_folder_leaves_the_app_pool_alone(tmp_path, monkeypatch):
    import src.database.session as session

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setattr(session, "dispose_engine", lambda: pytest.fail("the suite's own pool was closed"))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["own_connections_open"] == 0 and report["other_holder"] == "none", report


def test_unknown_own_connections_are_never_clean(tmp_path, monkeypatch):
    import src.database.session as session

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setattr(session, "DB_FILE", str(data / "open_omniscience.db"))
    monkeypatch.setattr(session, "dispose_engine", lambda: {"checked_out": None})
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["other_holder"] == "unknown", report


def _erased(tmp_path, monkeypatch) -> Path:
    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    return data


def test_the_scrub_never_writes_on_another_drive(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "erased_device", lambda _f: -12345)  # the data folder was a mount point of its own
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert out["scrub_not_done"] == "other_drive" and out["bytes_written"] == 0 and out["scrub_folder"] is None, out
    assert list(tmp_path.iterdir()) == []


def test_the_scrub_never_writes_when_the_drive_could_not_be_read(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "erased_device", lambda _f: None)
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert out["scrub_not_done"] == "drive_unread" and out["bytes_written"] == 0, out


def test_the_scrub_says_where_and_keeps_the_reserve(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    free = [crypto_erase._DISK_RESERVE + 5000]

    def _free(_f):  # the disk fills as the overwrite writes
        return free[0]

    real_urandom = os.urandom

    def _write(n):
        free[0] -= n
        return real_urandom(n)

    monkeypatch.setattr(crypto_erase, "_free_bytes", _free)
    from tests.os_scope import scope_os

    scope_os(monkeypatch, crypto_erase, urandom=_write)
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert out["bytes_written"] == 5000 and out["scrub_folder"] == str(tmp_path) and out["reserve_bytes"], out


def test_the_scrub_folder_goes_even_when_the_fill_is_interrupted(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)

    def boom(_p, _cap):
        raise KeyboardInterrupt

    monkeypatch.setattr(crypto_erase, "_fill_free_space", boom)
    with pytest.raises(KeyboardInterrupt):
        crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert list(tmp_path.iterdir()) == []


def test_a_crash_left_scrub_folder_is_swept_only_when_it_is_the_app_s_own(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    (tmp_path / ".oo_scrub_left").mkdir()
    (tmp_path / ".oo_scrub_left" / "scrub_0.bin").write_bytes(b"x")
    (tmp_path / "theirs").mkdir()
    (tmp_path / ".oo_scrub_link").symlink_to(tmp_path / "theirs", target_is_directory=True)
    crypto_erase.full_secure_erase(1, _cap_bytes=1 << 12)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".oo_scrub_link", "theirs"]


def test_the_scrub_never_goes_through_a_link(tmp_path, monkeypatch):
    real = tmp_path / "elsewhere"
    real.mkdir()
    holder = tmp_path / "holder"
    holder.symlink_to(real, target_is_directory=True)
    data = holder / "OOS data"
    _fill(data)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 12)
    assert out["scrub_not_done"] == "no_folder" and list(real.iterdir()) == [], out


def test_health_says_plainly_that_the_data_was_erased_and_stays_200(tmp_path, monkeypatch):
    import asyncio

    import src.api.main as main

    _erased(tmp_path, monkeypatch)
    out = asyncio.run(main.health_check())
    assert out["data_erased"] is True and out["status"] == "data-erased" and "Restart the app" in out["detail"], out


# ---- the security reads' gaps ----


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="a folder handle is placed through /proc/self/fd")
def test_a_write_relative_to_a_folder_handle_is_placed_and_refused(tmp_path):
    data = tmp_path / "kept"
    data.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    paths.latch_erased(data)
    fd = os.open(data, os.O_RDONLY)
    ofd = os.open(other, os.O_RDONLY)
    try:
        with pytest.raises(paths.DataFolderErased):
            os.mkdir("sub", dir_fd=fd)
        with pytest.raises(paths.DataFolderErased):
            os.symlink("/nowhere", "ln", dir_fd=fd)
        (other / "f").write_text("x", encoding="utf-8")
        with pytest.raises(paths.DataFolderErased):
            os.rename("f", "f", src_dir_fd=ofd, dst_dir_fd=fd)
        os.mkdir("fine", dir_fd=ofd)  # a folder handle elsewhere is let through
    finally:
        os.close(fd)
        os.close(ofd)
    assert list(data.iterdir()) == [] and (other / "fine").is_dir()


def test_a_replace_into_the_latched_folder_is_refused(tmp_path):
    data = tmp_path / "kept"
    data.mkdir()
    src = tmp_path / "tmp.json"
    src.write_text("{}", encoding="utf-8")
    paths.latch_erased(data)
    with pytest.raises(paths.DataFolderErased):
        os.replace(src, data / "settings.json")
    assert list(data.iterdir()) == []


def test_a_second_default_erase_keeps_the_overrides_and_makes_no_keys_folder(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    _fill(data)
    store = tmp_path / "columnar"
    store.mkdir()
    (store / "analytics.duckdb").write_bytes(b"D" * 4096)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(store))
    monkeypatch.setattr(paths, "_memo", None)
    paths.latch_erased(data)
    resolved = crypto_erase._resolve(None)
    assert resolved["store_dir"] == store and resolved["keys_dir"] == data / "keys"
    import shutil as _sh

    with paths.erase_owned():
        _sh.rmtree(data / "keys")
    crypto_erase._resolve(None)
    assert not (data / "keys").exists(), "the keys folder is named, never made, under the latch"


def test_a_store_an_override_puts_outside_the_folder_is_latched_by_its_files(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    _fill(data)
    store = tmp_path / "columnar"
    store.mkdir()
    (store / "mine.txt").write_text("the operator's", encoding="utf-8")
    crypto_erase._latch_outside({"main_db": None, "store_dir": store}, data)
    with pytest.raises(paths.DataFolderErased):
        (store / "analytics.duckdb").write_bytes(b"again")
    (store / "mine.txt").write_text("still the operator's to write", encoding="utf-8")  # the folder itself is never latched whole


def test_a_record_never_waits_on_the_journal_once_the_folder_is_latched(tmp_path, monkeypatch, capsys):
    from src.monitoring import errorlog

    data = tmp_path / "OOS data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    paths.latch_erased(data)
    errorlog._LOCK.acquire()  # a journal write that never ends
    try:
        t0 = time.monotonic()
        errorlog._append({"level": "WARNING", "logger": "oo.test.after", "message": "after the erase"})
        assert time.monotonic() - t0 < 1.0
    finally:
        errorlog._LOCK.release()
    assert "oo.test.after" in capsys.readouterr().err
    assert not data.joinpath("app_errors.jsonl").exists()


def test_a_record_waits_on_a_stuck_journal_only_so_long(tmp_path, monkeypatch, capsys):
    from src.monitoring import errorlog

    data = tmp_path / "OOS data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    monkeypatch.setattr(errorlog, "_LOCK_WAIT_S", 0.05)
    errorlog._LOCK.acquire()
    try:
        errorlog._append({"level": "WARNING", "logger": "oo.test.stuck", "message": "behind a stuck write"})
    finally:
        errorlog._LOCK.release()
    assert "oo.test.stuck" in capsys.readouterr().err


def test_an_uninstall_planned_after_a_panic_still_wipes_a_folder_that_is_there(tmp_path, monkeypatch):
    from src.safety import uninstall

    data = tmp_path / "OOS data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    paths.latch_erased(data)
    plan = uninstall.plan_uninstall(wipe_data=True)
    assert plan["data_dir"] == str(data) and plan["wipe_data_dir"] == str(data), plan
    with paths.erase_owned():
        data.rmdir()
    plan = uninstall.plan_uninstall(wipe_data=True)
    assert plan["wipe_data_dir"] is None and not data.exists(), plan


def test_the_panic_latches_from_its_first_step(tmp_path, monkeypatch):
    from src.safety import panic

    data = tmp_path / "OOS data"
    _fill(data)
    seen = []
    monkeypatch.setattr(panic, "_close_database_now", lambda: seen.append(paths.erased_folder_of(data)))
    panic.panic_wipe(data, confirm=True)
    assert seen == [True]


# ---- the second pair of security reads ----


def test_the_panic_counts_its_own_connections_still_open_as_a_holder(tmp_path, monkeypatch):
    """R805 (a) on the panic path: a connection a request thread still holds when the pool is closed is a holder the probe cannot see."""
    from src.database import session
    from src.safety import panic

    data = tmp_path / "OOS data"
    _fill(data)
    monkeypatch.setattr(session, "DB_FILE", str(data / "oo.db"))  # the pool is on the store being erased
    monkeypatch.setattr(session, "dispose_engine", lambda: {"checked_out": 1})
    report = panic.panic_wipe(data, confirm=True)
    assert report["own_connections_open"] == 1 and report["other_holder"] == "held", report
    monkeypatch.setattr(session, "dispose_engine", lambda: {"checked_out": None})
    data2 = tmp_path / "OOS data 2"
    _fill(data2)
    monkeypatch.setattr(session, "DB_FILE", str(data2 / "oo.db"))
    report = panic.panic_wipe(data2, confirm=True)
    assert report["other_holder"] in ("held", "unknown"), report
    # A pool on a store ELSEWHERE is closed too, but holds nothing of this folder: it counts 0, never "unknown".
    data3 = tmp_path / "OOS data 3"
    _fill(data3)
    monkeypatch.setattr(session, "DB_FILE", str(tmp_path / "elsewhere" / "oo.db"))
    report = panic.panic_wipe(data3, confirm=True)
    assert report["own_connections_open"] == 0, report


def test_the_scrub_never_says_overwritten_when_it_wrote_nothing(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    monkeypatch.setattr(crypto_erase, "_free_bytes", lambda _f: crypto_erase._DISK_RESERVE)  # a full drive
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 16)
    assert out["bytes_written"] == 0 and out["scrub_not_done"] == "nothing_written", out
    assert out["scrub_not_done"] in crypto_erase.SCRUB_NOT_DONE


def test_a_scrub_folder_that_could_not_be_removed_is_named(tmp_path, monkeypatch):
    _erased(tmp_path, monkeypatch)
    real_rmtree = crypto_erase.shutil.rmtree
    monkeypatch.setattr(crypto_erase.shutil, "rmtree", lambda *_a, **_k: None)
    out = crypto_erase.full_secure_erase(1, _cap_bytes=1 << 10)
    left = out["scrub_folder_left"]
    assert left and os.path.basename(left).startswith(".oo_scrub_"), out
    with paths.erase_owned():
        real_rmtree(left)


def test_a_folder_made_again_before_the_erase_s_own_log_lines_reads_came_back(tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    report = {"scope": "data-folder", "data_dir": str(data), "removed": False, "removed_at_rmtree": True,
              "limit": crypto_erase._LIMIT_NOTE}
    crypto_erase.settle_removed(report)
    assert report.get("folder_back") is True and report["limit"].startswith(crypto_erase._FOLDER_BACK_SENTENCE), report


def test_an_uninstall_after_a_panic_never_says_the_data_is_kept(tmp_path, monkeypatch):
    from src.safety import uninstall

    data = tmp_path / "OOS data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    paths.latch_erased(data)  # the panic removed it
    plan = uninstall.plan_uninstall(wipe_data=True)
    assert plan["data_erased_earlier"] is True and plan["wipe_data_dir"] is None, plan
    monkeypatch.setattr(uninstall, "plan_uninstall", lambda *_a, **_k: {**plan, "removable": True,  # a core-only install has no venv to find
                                                                      "audit_log": str(tmp_path / "audit.log")})
    out = uninstall.request_uninstall(confirm=True, wipe_data=True, _spawn=lambda p, pid: None, _arm_shutdown=lambda: None)
    assert out["data_kept"] is False and "KEPT" not in out["note"] and "already erased" in out["note"], out
    assert not data.exists()


def test_the_watcher_says_incomplete_when_the_app_had_not_stopped():
    from src.safety.uninstall import _WATCHER_SRC

    assert "or not server_gone:" in _WATCHER_SRC


_PRELUDE_DISK = r"""
import shutil, collections
_U = collections.namedtuple("usage", "total used free")
_calls = []
def _usage(p):
    _calls.append(p)
    return _U(1 << 40, 0, (64 * 1024 * 1024 + 1000) if len(_calls) == 1 else 64 * 1024 * 1024)
shutil.disk_usage = _usage
"""


def test_the_watcher_scrub_keeps_the_reserve_and_writes_in_a_private_folder(tmp_path):
    import json
    import subprocess
    import sys

    from src.safety.uninstall import _WATCHER_SRC

    data = tmp_path / "home" / "oo-data"
    data.mkdir(parents=True)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "USERPROFILE": str(tmp_path / "home")}
    plan = {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log"), "passes": 1}
    subprocess.run([sys.executable, "-c", _PRELUDE_DISK + _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=60, check=True,
                   env=env)
    text = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "free disk space overwritten: 1000 bytes" in text and "left unwritten" in text, text
    assert not data.exists() and not list((tmp_path / "home").glob(".oo_scrub*")), text


def test_a_record_on_stderr_carries_none_of_its_text(tmp_path, monkeypatch, capsys):
    from src.monitoring import errorlog

    data = tmp_path / "gone"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    private_place = "/srv/private/case-files/witness.txt"
    errorlog._append({"level": "ERROR", "logger": "oo.test.text", "message": f"could not read {private_place}",
                      "traceback": "Traceback: frame in /srv/x.py"})
    err = capsys.readouterr().err
    assert "oo.test.text" in err and "could not read" not in err and "/srv" not in err and "Traceback" not in err, err
