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

import pytest

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


# ---- a folder that can be listed but not searched (mode r--): its names are read, nothing in it can be looked at, opened or
# removed. The security reads of this PR: before the fix such a folder was never counted as unlisted, the panic wipe called the
# keys in it destroyed-or-absent and crashed in steps 5b/6, and the watcher counted its files as handled.
_SKIP_PERMS = pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs file permissions that bind (POSIX, not root)"
)


def _locked_os(locked: Path):
    """``lstat``/``stat``/``open`` as a folder of mode r-- answers them for the entries in it, as any user, root included."""
    def refuse(fn):
        def call(path, *a, **k):
            if Path(os.fspath(path)).parent == locked:
                raise PermissionError(13, "Permission denied", os.fspath(path))
            return fn(path, *a, **k)
        return call

    return {"lstat": refuse(os.lstat), "stat": refuse(os.stat), "open": refuse(os.open)}


def test_a_keys_folder_that_cannot_be_searched_is_never_reported_clean(tmp_path, monkeypatch):
    from src.safety import data_scope

    data = tmp_path / "OOS data"
    keys = data / "keys"
    keys.mkdir(parents=True)
    (keys / "custody_ed25519.pem").write_bytes(b"PRIVATE")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    monkeypatch.setattr(data_scope, "folder_scope", lambda base: {"broad": True, "reason": "test"})
    scope_os(monkeypatch, crypto_erase, **_locked_os(keys))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["keys_destroyed"] == [], report
    assert report["unlisted_folders"] >= 1 and "may be incomplete" in report["limit"], report
    assert str(keys / "custody_ed25519.pem") in report["overwrite_failures"], report


def test_an_app_folder_that_cannot_be_searched_never_stops_the_erase(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    locked = data / "bulletin"
    locked.mkdir(parents=True)
    (locked / "x.db").write_bytes(b"S" * 8192)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    scope_os(monkeypatch, crypto_erase, **_locked_os(locked))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)  # never raises
    assert report["unlisted_folders"] == 1 and "may be incomplete" in report["limit"], report
    assert str(locked / "x.db") in report["overwrite_failures"], report


@_SKIP_PERMS
@pytest.mark.parametrize("shared", [False, True])
def test_a_real_unsearchable_folder_in_the_panic_wipe(tmp_path, monkeypatch, shared):
    from src.safety import data_scope

    data = tmp_path / "OOS data"
    keys = data / "keys"
    keys.mkdir(parents=True)
    (keys / "custody_ed25519.pem").write_bytes(b"PRIVATE")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    if shared:
        monkeypatch.setattr(data_scope, "folder_scope", lambda base: {"broad": True, "reason": "test"})
    keys.chmod(0o400)
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    finally:
        keys.chmod(0o700)
    assert report["keys_destroyed"] == [] and report["unlisted_folders"] >= 1, report
    assert (keys / "custody_ed25519.pem").exists() and "may be incomplete" in report["limit"], report


def _with_the_error_file_log(monkeypatch) -> None:
    """The app's error-file handler (src/monitoring/errorlog.py) writes every warning into the data folder while it is there; with it
    installed, as in the running app, the erase's last log lines must still leave the folder gone (R802, which restored it here)."""
    from src.monitoring import errorlog

    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))  # whatever install() adds goes when the test ends
    monkeypatch.setattr(errorlog, "_installed", errorlog._installed)
    errorlog.install()


def test_the_erase_never_makes_again_the_folder_it_removed(tmp_path, monkeypatch):
    """The last log lines mask their paths; the masking must not ask src.paths.data_dir, which makes a missing folder again."""
    data = tmp_path / "OOS data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    _with_the_error_file_log(monkeypatch)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["removed"] is True and not data.exists(), report


def test_the_masking_can_be_given_the_data_folder(monkeypatch):
    import src.paths
    from src.monitoring.path_tokens import tokenise_paths

    monkeypatch.setattr(src.paths, "data_dir", lambda: (_ for _ in ()).throw(AssertionError("asked")))
    assert tokenise_paths("/srv/oo/data/keys/x.pem", data_root="/srv/oo/data") == "<data>/…/x.pem"


_PRELUDE_SEARCH = r"""
import os
def _refuse(fn):
    def call(path, *a, **k):
        if os.path.basename(os.path.dirname(os.fspath(path))) == "locked":
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return fn(path, *a, **k)
    return call
os.lstat, os.stat, os.open = _refuse(os.lstat), _refuse(os.stat), _refuse(os.open)
"""


def _watch_with(tmp_path, plan: dict, prelude: str) -> str:
    import json
    import subprocess
    import sys

    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    home = tmp_path / "home" / "jane.doe"
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    subprocess.run([sys.executable, "-c", prelude + _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=60, check=True,
                   env=env)
    return (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_the_watcher_never_counts_a_file_it_could_not_look_at_as_handled(tmp_path):
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    (data / "locked").mkdir(parents=True)
    (data / "locked" / "pre-restore-1.db").write_bytes(b"SALTSALT" * 1024)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    text = _watch_with(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, _PRELUDE_SEARCH)
    assert "salt pages destroyed" not in text and "THE ERASE MAY BE INCOMPLETE" in text, text
    assert "could not check 1 folder(s) it could not list: <data>/.../locked" in text, text
    for leak in (str(tmp_path), "jane.doe"):
        assert leak not in text, (leak, text)


@_SKIP_PERMS
def test_the_watcher_with_a_real_unsearchable_folder(tmp_path):
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    locked = data / "bulletin"
    locked.mkdir(parents=True)
    (locked / "x.db").write_bytes(b"SALTSALT" * 1024)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    locked.chmod(0o400)
    try:
        text = _watch_with(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, "")
    finally:
        if locked.exists():
            locked.chmod(0o700)
    assert "salt pages destroyed" not in text and "THE ERASE MAY BE INCOMPLETE" in text, text


def test_a_link_that_loops_in_the_keys_folder_is_no_folder_it_could_not_check(tmp_path):
    data = tmp_path / "OOS data"
    (data / "keys").mkdir(parents=True)
    os.symlink("kloop", data / "keys" / "kloop")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["unlisted_folders"] == 0, report


def test_a_failed_overwrite_never_makes_the_configured_data_folder_again(tmp_path, monkeypatch):
    """The helpers' own log lines are masked against the erase's data folder too, never through src.paths.data_dir."""
    other = tmp_path / "configured"
    monkeypatch.setenv("OO_DATA_DIR", str(other))
    data = tmp_path / "OOS data"
    data.mkdir()
    (data / "stuck.bin").write_bytes(b"x" * 100)
    real_open = os.open

    def refuse(path, *a, **k):
        if os.fspath(path).endswith("stuck.bin"):
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_open(path, *a, **k)

    scope_os(monkeypatch, crypto_erase, open=refuse)
    _with_the_error_file_log(monkeypatch)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert str(data / "stuck.bin") in report["overwrite_failures"], report
    assert not other.exists()


_PRELUDE_KEYS = _PRELUDE_SEARCH.replace('== "locked"', '== "keys"')


def test_the_watcher_names_key_files_in_an_unsearchable_keys_folder_of_a_shared_folder(tmp_path):
    data = tmp_path / "shared"
    (data / "keys").mkdir(parents=True)
    (data / "keys" / "custody_ed25519.pem").write_bytes(b"PRIVATE")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    only = {"names": ["open_omniscience.db"], "prefixes": [], "suffixes": [], "strip": "^$", "reason": "test"}
    # R807 (3): the app's key files by their exact names, never a suffix
    from src.safety.uninstall import _keys_spec

    text = _watch_with(tmp_path, {"wipe_data_dir": str(data), "app_only": only, "keys_spec": _keys_spec(),
                                  "audit_log": str(tmp_path / "audit.log")}, _PRELUDE_KEYS)
    assert "salt pages destroyed" not in text and "could not check 1 folder(s)" in text, text


def test_the_watcher_names_a_columnar_store_it_could_not_look_into(tmp_path):
    data = tmp_path / "oo-data"
    data.mkdir()
    store = tmp_path / "locked"
    store.mkdir()
    (store / "analytics.duckdb").write_bytes(b"D" * 8192)
    plan = {"wipe_data_dir": str(data), "wipe_store_dir": str(store), "audit_log": str(tmp_path / "audit.log")}
    text = _watch_with(tmp_path, plan, _PRELUDE_SEARCH)
    line = next(ln for ln in text.splitlines() if "wiped columnar store" in ln)
    assert "not overwritten, THE ERASE MAY BE INCOMPLETE" in line, text  # each name it could not look at counts
