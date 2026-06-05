"""
Tests for portable data-dir resolution (src/paths.py).

The three branches must each be exercised: explicit override, source checkout,
and an installed (non-checkout) layout that must fall back to the XDG user dir
instead of writing into its own install tree.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import src.paths as paths


def _reload():
    return importlib.reload(paths)


def test_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "custom"))
    p = _reload()
    assert p.data_dir() == tmp_path / "custom"
    assert (tmp_path / "custom").is_dir()  # created


def test_source_checkout_uses_repo_data(monkeypatch):
    monkeypatch.delenv("OO_DATA_DIR", raising=False)
    p = _reload()
    # We are running from the real checkout, which has pyproject.toml and is writable.
    assert p.data_dir() == p.repo_root() / "data"


def test_installed_layout_falls_back_to_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("OO_DATA_DIR", raising=False)
    p = _reload()
    # Simulate a wheel install: the "repo root" has no pyproject.toml.
    fake_install = tmp_path / "site-packages"
    fake_install.mkdir()
    monkeypatch.setattr(p, "_REPO_ROOT", fake_install)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert p.data_dir() == tmp_path / "xdg" / "open-omniscience"
    assert (tmp_path / "xdg" / "open-omniscience").is_dir()


def test_installed_without_xdg_uses_home_local_share(tmp_path, monkeypatch):
    monkeypatch.delenv("OO_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    p = _reload()
    fake_install = tmp_path / "site-packages"
    fake_install.mkdir()
    monkeypatch.setattr(p, "_REPO_ROOT", fake_install)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert p.data_dir() == tmp_path / "home" / ".local" / "share" / "open-omniscience"


def test_default_sqlite_url_is_rooted_in_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "d"))
    p = _reload()
    assert p.default_sqlite_url() == f"sqlite:///{tmp_path / 'd' / 'open_omniscience.db'}"


def teardown_module(_module):
    # Leave the module in its natural (un-monkeypatched) state for other tests.
    importlib.reload(paths)
