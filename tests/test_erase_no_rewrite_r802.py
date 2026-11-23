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
                lambda: (paths.data_dir() / "settings.json").write_text("{}"),
                lambda: paths.diagnostics_dir(),
                lambda: held.parent.mkdir(parents=True, exist_ok=True),
                lambda: (data / "late.txt").write_text("late"),
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
    (data / "my-notes.txt").write_text("the operator's")
    monkeypatch.setattr(data_scope, "folder_scope", lambda base: {"broad": True, "reason": "test"})
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["scope"] == "app-only", report
    # What the writer put there BEFORE the erase is not the app's by name, so the erase left it as the operator's: cleared here by the
    # test (an operator's own removal), then nothing may come back.
    with paths.erase_owned():
        for p in data.iterdir():
            if p.name != "my-notes.txt":
                p.unlink()
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
    (tmp_path / "beside" / "f").write_text("ok")
    assert (tmp_path / "beside" / "f").read_text() == "ok"


def test_the_latch_refuses_writes_into_a_folder_that_is_still_there(tmp_path):
    data = tmp_path / "kept"
    data.mkdir()
    (data / "old.txt").write_text("old")
    paths.latch_erased(data)
    for write in (
        lambda: (data / "new.txt").write_text("x"),
        lambda: open(data / "old.txt", "a").close(),  # noqa: SIM115
        lambda: os.close(os.open(data / "n2", os.O_CREAT | os.O_WRONLY)),
        lambda: os.rename(tmp_path / "src.txt", data / "moved.txt"),
        lambda: os.symlink("old.txt", data / "link"),
    ):
        (tmp_path / "src.txt").write_text("s")
        with pytest.raises(paths.DataFolderErased):
            write()
    assert (data / "old.txt").read_text() == "old"
    assert sorted(p.name for p in data.iterdir()) == ["old.txt"]
    with paths.erase_owned():  # the erase's own work, on its own thread
        (data / "scrub").write_text("s")
    (data / "scrub").unlink()


def test_the_journal_never_makes_a_missing_data_folder(tmp_path, monkeypatch, capsys):
    """R802 (1), with no erase at all: the folder gone means stderr only."""
    from src.monitoring import errorlog

    data = tmp_path / "gone"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    errorlog._append({"level": "WARNING", "message": "with no folder"})
    assert not data.exists()
    assert "with no folder" in capsys.readouterr().err


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
        (data / "app_errors.jsonl").write_text("x")


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
_rt = shutil.rmtree
def _again(p, *a, **k):
    _rt(p, *a, **k)
    if os.path.basename(os.fspath(p)) == "oo-data":
        os.mkdir(p)   # what a server still running would do
shutil.rmtree = _again
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
    assert "was there again after the wipe removed it" in text and "salt pages destroyed" not in text, text


def test_the_panic_page_and_the_cli_never_call_a_folder_that_came_back_clean():
    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert "&& !back" in js and "r.folder_back === true" in js
    from tests.js_source_helper import python_function_source

    main = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(encoding="utf-8")
    cli = python_function_source(main, "_panic_cli")
    assert 'report.get("folder_back")' in cli
