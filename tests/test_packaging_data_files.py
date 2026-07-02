"""Packaging carries the app's runtime data (RC gate, 2026-07-02).

The 0.1 release audit found the built wheel/sdist held ZERO data files — no
``src/static`` (the whole UI), no ``configs/`` (source catalog, stoplists,
rings), no locales — so the published, checksummed artifacts could not actually
run while the release notes said ``pip install *.whl``. These are config-shape
guards so the hole cannot silently reopen: they pin the pyproject/MANIFEST
packaging declarations (cheap, no build). The real end-to-end proof (build →
fresh venv → install → boot to HTTP 200) was run at fix time and belongs to the
release procedure, not the unit suite.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_packages_include_the_runtime_data_trees():
    """configs/ + migrations/ resolve as siblings of src/ (repo root ==
    site-packages on a wheel install), so they MUST ship as top-level packages."""
    find = _pyproject()["tool"]["setuptools"]["packages"]["find"]
    include = find.get("include", [])
    for needed in ("src*", "configs", "migrations*"):
        assert needed in include, f"packages.find.include lost {needed!r} — wheel installs break"
    assert find.get("namespaces") is True, "configs/migrations/docs have no __init__.py — namespaces=true required"


def test_package_data_covers_static_configs_and_docs():
    pkg_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert any("static/**" in p for p in pkg_data.get("src", [])), (
        "src package-data must carry static/** (the entire UI: html/js/css/fonts/locales)"
    )
    cfg_pats = " ".join(pkg_data.get("configs", []))
    for ext in ("*.yml", "*.txt", "*.json"):
        assert ext in cfg_pats, f"configs package-data must include {ext} (catalog/stoplists/rings)"
    assert _pyproject()["tool"]["setuptools"].get("include-package-data") is True


def test_manifest_grafts_the_same_trees_for_the_sdist():
    manifest = (_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for line in ("graft src/static", "graft configs", "graft migrations"):
        assert line in manifest, f"MANIFEST.in lost {line!r} — sdist installs break"


def test_alembic_config_tolerates_a_missing_ini():
    """A wheel install has migrations/ but no repo-root alembic.ini; the staged
    cross-version restore upgrade must still work (Config() without a file)."""
    src = (_ROOT / "src" / "database" / "migrate.py").read_text(encoding="utf-8")
    assert re.search(r"_ALEMBIC_INI\.is_file\(\)\s+else\s+Config\(\)", src), (
        "migrate._alembic_config must fall back to a file-less alembic Config "
        "when alembic.ini is absent (wheel installs)"
    )
