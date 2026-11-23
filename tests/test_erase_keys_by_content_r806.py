"""
Row 362 (R806): the erase never makes anything in the folder it erases, and ``keys`` is the app's by its CONTENT, never by its name.

Before this row, ``crypto_erase._resolve`` asked ``src.custody.signing._keys_dir()`` for the keys folder, which MAKES it, and
``src.paths.data_dir()`` for the data folder, which makes that too; and a ``keys`` folder holding a file of the operator's was walked
and removed whole with the rest of a data folder of the app's own. Now every target is named, never made, and a ``keys`` folder that
holds anything the app does not write there (or is a link) is "foreign": only the app's key files in it go, the rest is left byte for
byte, and the data folder is kept and said to be kept, with a count and no names.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from src import paths
from src.safety import crypto_erase, data_scope


def _app_folder(data: Path, *, keys: bool = True) -> None:
    data.mkdir(parents=True)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    (data / "app_settings.json").write_text("{}", encoding="utf-8")
    (data / "wiki_dumps").mkdir()
    (data / "wiki_dumps" / "part.xml").write_bytes(b"x" * 100)
    if keys:
        (data / "keys").mkdir()
        (data / "keys" / "custody_ed25519.pem").write_bytes(b"PRIVATE-ED")
        (data / "keys" / "custody_ml_dsa_65.key").write_bytes(b"PRIVATE-ML")
        (data / "keys" / "evidence_ed25519.pem").write_bytes(b"PRIVATE-EV")


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    """A data folder the app chose (its own name), pointed at the way the app points at it."""
    data = tmp_path / "OOS data"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.delenv("OO_COLUMNAR_DIR", raising=False)
    monkeypatch.setattr(paths, "_memo", None)
    return data


def _erase(data_dir=None) -> dict:
    return crypto_erase.quick_crypto_erase(confirm=True, data_dir=data_dir)


# --- (5) the four cases the ruling names ---------------------------------------------------------------------------------------- #
def test_only_app_items_the_folder_is_removed(app_data):
    _app_folder(app_data)
    out = _erase()
    assert out["removed"] is True and not app_data.exists(), out
    assert out["keys_folder"] == "app" and out["folder_kept_foreign"] is False and out["kept_items"] == 0
    assert set(out["keys_destroyed"]) == {"custody_ed25519.pem", "custody_ml_dsa_65.key"}


def test_a_user_file_at_the_top_level_keeps_the_folder(tmp_path, monkeypatch):
    """A folder that also holds an operator's file at its top level is not the app's own (R711): kept, the file untouched."""
    data = tmp_path / "projects"
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "_memo", None)
    _app_folder(data)
    (data / "thesis.odt").write_bytes(b"MY THESIS")
    out = _erase()
    assert data.is_dir() and (data / "thesis.odt").read_bytes() == b"MY THESIS"
    assert out["scope"] == "app-only" and out["folder_kept_foreign"] is True and out["kept_items"] == 1, out
    assert not (data / "open_omniscience.db").exists() and not (data / "keys" / "custody_ed25519.pem").exists()
    assert "thesis.odt" not in str(out.get("limit")), "a kept item's name is never in the result's words"


def test_a_user_file_inside_keys_keeps_the_folder_and_only_the_app_keys_go(app_data):
    _app_folder(app_data)
    mine = app_data / "keys" / "my_gpg_backup.asc"
    payload = os.urandom(4096)
    mine.write_bytes(payload)
    (app_data / "keys" / ".pending").mkdir()
    staged = app_data / "keys" / ".pending" / "custody_ed25519.pem.4242.140000.0123456789ab.new"
    staged.write_bytes(b"PRIVATE-COPY")
    out = _erase()
    assert out["keys_folder"] == "foreign", out
    for name in ("custody_ed25519.pem", "custody_ml_dsa_65.key", "evidence_ed25519.pem"):
        assert not (app_data / "keys" / name).exists(), name
    assert not staged.exists() and not (app_data / "keys" / ".pending").exists()
    assert mine.read_bytes() == payload, "the operator's file is byte-identical"
    assert app_data.is_dir() and sorted(os.listdir(app_data)) == ["keys"], "every other entry of the data folder goes"
    assert out["folder_kept_foreign"] is True and out["kept_items"] == 1 and out["removed"] is False, out
    assert set(out["keys_destroyed"]) == {"custody_ed25519.pem", "custody_ml_dsa_65.key"}
    assert "folder_back" not in out and "could not be removed" not in out["limit"], "kept on purpose, never 'could not be removed'"


def test_keys_as_a_symlink_is_not_followed_and_kept(app_data, tmp_path):
    _app_folder(app_data, keys=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "custody_ed25519.pem").write_bytes(b"NOT THROUGH A LINK")
    (elsewhere / "notes.txt").write_bytes(b"mine")
    os.symlink(elsewhere, app_data / "keys")
    out = _erase()
    assert out["keys_folder"] == "foreign", out
    assert (app_data / "keys").is_symlink(), "the link is kept"
    assert (elsewhere / "custody_ed25519.pem").read_bytes() == b"NOT THROUGH A LINK", "never written through"
    assert (elsewhere / "notes.txt").read_bytes() == b"mine"
    assert out["folder_kept_foreign"] is True and out["kept_items"] == 1 and sorted(os.listdir(app_data)) == ["keys"]


def test_keys_as_a_symlink_to_a_file_is_kept_too(app_data, tmp_path):
    _app_folder(app_data, keys=False)
    target = tmp_path / "a_file"
    target.write_bytes(b"theirs")
    os.symlink(target, app_data / "keys")
    out = _erase()
    assert (app_data / "keys").is_symlink() and target.read_bytes() == b"theirs"
    assert out["folder_kept_foreign"] is True, out


# --- (1) nothing made in the folder ------------------------------------------------------------------------------------------- #
def test_nothing_appears_in_the_folder_before_the_scope_decision(app_data, monkeypatch):
    _app_folder(app_data, keys=False)
    before = sorted(os.listdir(app_data))
    seen: dict[str, list[str]] = {}
    real_scope = data_scope.folder_scope

    def spy(base):
        seen["at_scope"] = sorted(os.listdir(base))
        return real_scope(base)

    monkeypatch.setattr(data_scope, "folder_scope", spy)
    _erase()
    assert seen["at_scope"] == before, "no keys folder (or anything else) made before the scope decision"


def test_a_missing_data_folder_is_never_made(app_data):
    out = _erase()
    assert not app_data.exists(), out


def test_resolve_names_and_makes_nothing(app_data):
    got = crypto_erase._resolve(None)
    assert got["base"] == app_data and got["keys_dir"] == app_data / "keys"
    assert not app_data.exists()


# --- (2) ownership by content ---------------------------------------------------------------------------------------------- #
def test_keys_state_reads_the_content(tmp_path):
    k = tmp_path / "keys"
    assert data_scope.keys_folder_state(k) == "absent"
    k.mkdir()
    assert data_scope.keys_folder_state(k) == "app"
    for name in data_scope.APP_KEY_NAMES:
        (k / name).write_bytes(b"x")
    assert data_scope.keys_folder_state(k) == "app"
    (k / ".pending").mkdir()
    (k / ".pending" / "evidence_ed25519.pem.1.2.abcdef012345.rewrap").write_bytes(b"x")
    assert data_scope.keys_folder_state(k) == "app"
    (k / ".pending" / "other").write_bytes(b"x")
    assert data_scope.keys_folder_state(k) == "foreign"
    (k / ".pending" / "other").unlink()
    (k / "sub").mkdir()
    assert data_scope.keys_folder_state(k) == "foreign"
    (k / "sub").rmdir()
    (k / "custody_ed25519.pem").unlink()
    (k / "custody_ed25519.pem").mkdir()  # an app name that is not a file is not the app's
    assert data_scope.keys_folder_state(k) == "foreign"


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="root reads any folder")
def test_a_keys_folder_that_cannot_be_listed_is_could_not_check(app_data):
    _app_folder(app_data)
    os.chmod(app_data / "keys", 0)
    try:
        out = _erase()
        assert out["keys_folder"] == "unlisted" and out["unlisted_folders"] >= 1, out
        assert out["folder_kept_foreign"] is True and app_data.is_dir()
    finally:
        os.chmod(app_data / "keys", 0o700)


def test_the_app_key_names_match_where_the_app_writes_them():
    """The list is the app's own: every name the code writes into keys (each file:line in data_scope) is in it, and nothing else."""
    from src.backup.merge import _APP_KEY_FILES
    from src.custody.keyfile import PENDING
    from src.reporting.evidence import RESTORED_KEY_MARKER_SUFFIX

    assert set(_APP_KEY_FILES) | {"evidence_ed25519.pem" + RESTORED_KEY_MARKER_SUFFIX} == data_scope.APP_KEY_NAMES
    assert PENDING == data_scope.KEYS_PENDING
    sample = f"custody_ed25519.pem.{os.getpid()}.{1234}.{'a' * 12}.rewrap"
    assert re.fullmatch(data_scope.KEYS_PENDING_RE, sample)


# --- (4) the words -------------------------------------------------------------------------------------------------------- #
def test_the_panic_says_folder_kept_never_removed_by_hand(app_data):
    """Plan's note on string 6: a folder kept on purpose never gets 'could not be removed ... remove it by hand'."""
    src = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert "folder_kept_foreign" in src
    assert re.search(r"notRemoved\s*=\s*[^;]*!r\.folder_kept_foreign", src), "string 6 is gated off for a folder kept on purpose"
    assert "The data folder was kept because it holds {n} items the app did not create." in src
    assert "The data folder was removed." in src


# --- the secure uninstall's watcher: the same rule, after the app has gone ------------------------------------------------------ #
def _watch(tmp_path: Path, data: Path) -> str:
    import json
    import subprocess
    import sys

    from src.safety.uninstall import _WATCHER_SRC, _keys_spec

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    log = tmp_path / "audit.log"
    plan = {"files": [], "venv": None, "app_folder": None, "wipe_data_dir": str(data), "audit_log": str(log),
            "keys_spec": _keys_spec()}
    subprocess.run([sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)], check=True, timeout=120)
    return log.read_text(encoding="utf-8")


def test_the_watcher_removes_a_folder_of_only_app_items(tmp_path):
    data = tmp_path / "OOS data"
    _app_folder(data)
    text = _watch(tmp_path, data)
    assert not data.exists() and "kept the data folder" not in text and "remove it by hand" not in text, text


def test_the_watcher_keeps_a_user_file_in_keys_and_says_kept(tmp_path):
    data = tmp_path / "OOS data"
    _app_folder(data)
    mine = data / "keys" / "my_gpg_backup.asc"
    payload = os.urandom(2048)
    mine.write_bytes(payload)
    text = _watch(tmp_path, data)
    assert mine.read_bytes() == payload
    for name in ("custody_ed25519.pem", "custody_ml_dsa_65.key", "evidence_ed25519.pem"):
        assert not (data / "keys" / name).exists(), name
    assert sorted(os.listdir(data)) == ["keys"]
    assert "kept the data folder" in text and "1 item(s) the app did not create" in text, text
    assert "remove it by hand" not in text and "my_gpg_backup" not in text, "kept on purpose; no user file name in the log"


def test_the_watcher_never_follows_a_keys_link(tmp_path):
    data = tmp_path / "OOS data"
    _app_folder(data, keys=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "custody_ed25519.pem").write_bytes(b"NOT THROUGH A LINK")
    os.symlink(elsewhere, data / "keys")
    text = _watch(tmp_path, data)
    assert (data / "keys").is_symlink() and (elsewhere / "custody_ed25519.pem").read_bytes() == b"NOT THROUGH A LINK"
    assert "kept the data folder" in text and "remove it by hand" not in text, text
