"""
Row 333 (R798): a folder an erase walk could not list is recorded, in every walk of both erase paths.

Before this row the panic wipe named a folder ``os.walk`` could not list among its overwrite failures but still reported a
clean erase ("the corpus key is destroyed"), and its top-level listings (the app's own entries of a shared data folder, the
copies beside each database, the keys folder of a shared folder) returned nothing in silence. The uninstall watcher's walk had
no error handler at all and wrote "crypto-erase: DB salt pages destroyed" whatever it had reached. Now any folder it could not
list makes the result "may be incomplete", the log says "could not check" with the count and the paths masked (R734/R736), and
"destroyed" is said only when every folder was listed and every targeted file was handled.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.safety import crypto_erase
from tests.js_source_helper import python_function_source
from tests.os_scope import scope_os


def _refusing_scandir(refused: set[Path]):
    real = os.scandir

    def scandir(path="."):
        if Path(path) in refused:
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)

    return scandir


def _refusing_walk(refused: Path):
    def walk(top, *a, onerror=None, **k):  # the listing of ``refused`` fails, as an unreadable folder's does
        for root, dirs, names in os.walk(top, *a, onerror=onerror, **k):
            for d in list(dirs):
                if Path(root, d) == refused:
                    dirs.remove(d)
                    if onerror is not None:
                        onerror(PermissionError(13, "Permission denied", str(refused)))
            yield root, dirs, names

    return walk


def test_a_folder_the_walk_cannot_list_makes_the_erase_may_be_incomplete(tmp_path, monkeypatch, caplog):
    data = tmp_path / "home" / "jane.doe" / "OOS data"
    locked = data / "snapshots-private"
    locked.mkdir(parents=True)
    (locked / "pre-restore-1.db").write_bytes(b"S" * 8192)
    (data / "app_settings.json").write_text("{}", encoding="utf-8")
    scope_os(monkeypatch, crypto_erase, walk=_refusing_walk(locked))
    with caplog.at_level(logging.WARNING, logger=crypto_erase._LOG.name):
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["unlisted_folders"] == 1, report
    assert "may be incomplete" in report["limit"] and "unrecoverable regardless" not in report["limit"], report
    assert report["overwrite_failures"].count(str(locked)) == 1  # the report (never a log) still names it
    logged = caplog.text
    assert "could not check 1 folder(s)" in logged, logged
    assert "snapshots-private" in logged  # by its role and its name
    for leak in (str(tmp_path), "jane.doe", str(locked)):
        assert leak not in logged, (leak, logged)


def test_a_shared_data_folder_it_cannot_list_is_recorded_not_skipped_in_silence(tmp_path, monkeypatch):
    """The app's own entries of a folder it does not own come from one top-level listing; one that fails reached nothing."""
    from src.safety import data_scope

    folder = tmp_path / "OOS data"
    folder.mkdir()
    (folder / "open_omniscience.db").write_bytes(b"S" * 8192)
    (folder / "thesis.docx").write_bytes(b"years of work")
    monkeypatch.setattr(data_scope, "folder_scope", lambda base: {"broad": True, "reason": "test"})
    scope_os(monkeypatch, crypto_erase, scandir=_refusing_scandir({folder}))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=folder)
    assert report["unlisted_folders"] >= 1, report
    assert "may be incomplete" in report["limit"], report
    assert (folder / "thesis.docx").read_bytes() == b"years of work"


def test_a_folder_that_is_not_there_is_not_an_unlisted_one(tmp_path):
    assert crypto_erase._listing(tmp_path / "gone", lambda exc: (_ for _ in ()).throw(AssertionError(exc))) == []


def test_a_clean_erase_still_reads_clean(tmp_path):
    data = tmp_path / "OOS data"
    (data / "sub").mkdir(parents=True)
    (data / "sub" / "x.json").write_text("{}", encoding="utf-8")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["unlisted_folders"] == 0, report


def test_a_held_store_and_an_unlisted_folder_are_both_said(monkeypatch):
    monkeypatch.setattr(crypto_erase, "shut_out_held", lambda g: None)
    monkeypatch.setattr(crypto_erase, "settle_other_holders", lambda g: crypto_erase.HOLDER_HELD)
    report = {"unlisted_folders": 2, "limit": crypto_erase._LIMIT_NOTE_UNLISTED}
    assert crypto_erase.finish_holder_check(report, 1) == crypto_erase.HOLDER_HELD
    assert report["limit"].startswith(crypto_erase._LIMIT_NOTE_NOT_CLEAN)
    assert crypto_erase._UNLISTED_SENTENCE in report["limit"]


def test_the_masking_withholds_a_path_when_it_fails(monkeypatch):
    import src.monitoring.path_tokens as pt

    def boom(text):
        raise RuntimeError("no")

    monkeypatch.setattr(pt, "tokenise_paths", boom)
    assert crypto_erase._masked(["/home/jane/x", "/srv/y"]) == ["(path withheld)", "(path withheld)"]


def test_the_panic_page_never_calls_an_erase_with_an_unlisted_folder_clean():
    src = open("src/static/app-backup.js", encoding="utf-8").read()
    clean = [line for line in src.splitlines() if "const clean = " in line and "holder ===" in line]
    assert len(clean) == 1 and 'holder === "none"' in clean[0] and "unlisted === 0" in clean[0], clean
    assert "The erase could not list {n} of the folders it was to erase" in src


def test_the_cli_says_it_too():
    import src.api.main as main

    cli = python_function_source(open(main.__file__, encoding="utf-8").read(), "_panic_cli")
    assert 'report.get("unlisted_folders")' in cli


# ---- the uninstall watcher (a detached script: the listing is made to fail by a prelude run before it, as an unreadable
# folder's does, so the test runs as any user, root included)
_PRELUDE = r"""
import os
_real_scandir, _real_listdir = os.scandir, os.listdir
def _refuse(path):
    if os.path.basename(os.fspath(path)) == "locked":
        raise PermissionError(13, "Permission denied", os.fspath(path))
os.scandir = lambda path=".": (_refuse(path), _real_scandir(path))[1]
os.listdir = lambda path=".": (_refuse(path), _real_listdir(path))[1]
"""


def _watch(tmp_path, plan: dict) -> str:
    import json
    import subprocess
    import sys

    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    home = tmp_path / "home" / "jane.doe"
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    subprocess.run([sys.executable, "-c", _PRELUDE + _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=60, check=True,
                   env=env)
    return (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_the_watcher_never_says_destroyed_when_a_folder_could_not_be_listed(tmp_path):
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    (data / "locked").mkdir(parents=True)
    (data / "locked" / "pre-restore-1.db").write_bytes(b"S" * 8192)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")})
    assert "salt pages destroyed" not in text, text
    assert "could not check 1 folder(s) it could not list: <data>/.../locked" in text, text
    assert "THE ERASE MAY BE INCOMPLETE" in text, text
    for leak in (str(tmp_path), "jane.doe"):
        assert leak not in text, (leak, text)


def test_the_watcher_records_an_unlisted_shared_folder_too(tmp_path):
    """A data folder the app does not own is reached by one top-level listing; one that fails reached nothing."""
    data = tmp_path / "locked"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    only = {"names": ["open_omniscience.db"], "prefixes": [], "suffixes": [], "strip": "^$", "reason": "test"}
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "app_only": only, "audit_log": str(tmp_path / "audit.log")})
    assert "salt pages destroyed" not in text and "could not check 1 folder(s)" in text, text


def test_the_watcher_still_says_destroyed_when_it_reached_everything(tmp_path):
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    (data / "sub").mkdir(parents=True)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")})
    assert "crypto-erase: DB salt pages destroyed" in text and "could not check" not in text, text
