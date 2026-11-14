"""R711: a data folder the app does not own is never removed whole, and that is said at every start.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The erase's behaviour in each scope is pinned in tests/test_crypto_erase.py; this file pins the scope itself, the name list it
rests on (a RATCHET: every ``data_dir() / "name"`` in ``src`` must be a name the module knows), and the startup notice.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.safety import data_scope
from src.safety.data_scope import folder_scope, is_app_owned, startup_warning
from tests.os_scope import scope_os_path

_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR_CALLS = frozenset({"data_dir", "_data_dir", "_dd", "_default_dir"})


def _literal_top_level_names() -> dict[str, str]:
    """Every literal name joined straight onto a ``data_dir()`` call in ``src``, or onto it through a module-level string constant."""
    found: dict[str, str] = {}
    for f in (_ROOT / "src").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        consts = {
            n.targets[0].id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
        }
        for n in ast.walk(tree):
            if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)):
                continue
            left = n.left
            if not (isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id in _DATA_DIR_CALLS):
                continue
            right = n.right
            name = right.value if isinstance(right, ast.Constant) else consts.get(right.id) if isinstance(right, ast.Name) else None
            if isinstance(name, str):
                found[name.split("/")[0]] = str(f.relative_to(_ROOT))
    return found


def test_every_name_the_app_writes_at_the_top_of_its_folder_is_known():
    """A new ``data_dir() / "x"`` must be added to src/safety/data_scope.py, or an erase in a shared folder would leave it."""
    found = _literal_top_level_names()
    assert len(found) > 40, "the scan stopped finding the app's names"
    unknown = {name: where for name, where in found.items() if not is_app_owned(name)}
    assert not unknown, f"add these to APP_FILES / APP_DIRS in src/safety/data_scope.py: {unknown}"


def test_names_the_app_does_not_write_are_not_claimed():
    for name in ("Documents", ".bashrc", "notes.db", "thesis.salvage-20261114T101010Z.db", "pre-restore.txt", "wiki"):
        assert not is_app_owned(name), name
    for name in ("open_omniscience.db-wal", "wiki.db-shm", "law.salvage-20261114T101010Z.db", "pre-encrypt-20261114T101010Z-open_omniscience.db",
                 ".restore-abc", "x.oopart", "keys", "session_state.json"):
        assert is_app_owned(name), name


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "home" / "me"
    h.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: h))
    return h


def test_the_home_folder_and_its_neighbours_are_broad(home):
    (home / "Documents").mkdir()
    assert folder_scope(home)["reason"] == "home"
    assert folder_scope(home.parent)["reason"] == "above_home"
    assert folder_scope(home / "Documents")["reason"] == "home_folder"
    assert folder_scope(Path(home.anchor))["reason"] == "drive_root"


def test_a_mount_point_is_broad(home, monkeypatch):
    target = home.parent.parent / "usb"
    target.mkdir()
    scope_os_path(monkeypatch, data_scope, ismount=lambda p: Path(p) == target)
    assert folder_scope(target)["reason"] == "mount_point"


def test_the_app_s_own_folder_is_not_broad(home):
    folder = home / "OOS data"
    folder.mkdir()
    assert folder_scope(folder)["broad"] is False, "an empty folder (a first launch) is not broad"
    (folder / "something-new.bin").write_bytes(b"x")
    assert folder_scope(folder)["reason"] == "not_app_folder", "other files and no marker"
    (folder / "legal_consent.json").write_text("{}", encoding="utf-8")
    assert folder_scope(folder)["broad"] is False, "a marker makes it the app's"


def test_the_startup_warning_names_the_folder_and_what_a_wipe_does(home):
    assert startup_warning(home / "nothing-here") is None
    note = startup_warning(home)
    assert str(home) in note and "your home folder" in note and "only the app's own files" in note


def test_both_pages_are_told_and_the_lifespan_logs_it():
    from src.api import unlock

    unlock._data_folder_scope.cache_clear()
    js = (_ROOT / "src/static/data-volume.js").read_text(encoding="utf-8")
    assert "renderScope(s.data_folder_scope)" in js
    en = json.loads((_ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    for reason in data_scope.REASON_TEXT:
        assert f"{reason}:" in js, reason
    for key in ("Your data folder is your home folder.", "Hide",
                "An emergency wipe or a secure uninstall removes only this app’s own files there, and leaves the folder and everything else in it."):
        assert key in en
    main = (_ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert main.count("startup_warning(_scope_dir())") == 2, "the lifespan's log and the terminal line"
    for page in ("index.html", "unlock.html"):
        assert '<script src="/static/data-volume.js"></script>' in (_ROOT / "src/static" / page).read_text(encoding="utf-8")


def test_the_watchdog_endpoint_carries_the_scope(home, monkeypatch):
    from src.api import unlock

    monkeypatch.setenv("OO_DATA_DIR", str(home))
    unlock._data_folder_scope.cache_clear()
    out = unlock.data_volume_state()
    assert out["data_folder_scope"] == {"broad": True, "reason": "home", "data_dir": str(home)}
    unlock._data_folder_scope.cache_clear()
