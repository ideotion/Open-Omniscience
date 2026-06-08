"""
Portable path resolution -- the single source of truth for *where data lives*.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app must behave correctly whether it is run from a source checkout (the
developer / Qubes ``pip install -e .`` case) or installed as a wheel into a
read-only location (pipx / system package). Historically every module computed
``REPO_ROOT / "data"`` independently, which meant an installed copy tried to
write its database *inside its own install tree* -- often read-only, and always
polluting the package. This module centralises the decision with a clear,
documented precedence:

    1. ``OO_DATA_DIR``         -- explicit override, always wins.
    2. source checkout         -- if we are importing from a writable tree that
                                  contains ``pyproject.toml`` (dev / editable
                                  install / Qubes ``$HOME`` install), keep data
                                  alongside the code in ``<repo>/data`` so the
                                  existing developer workflow is unchanged.
    3. per-user data directory -- otherwise follow the XDG Base Directory spec:
                                  ``$XDG_DATA_HOME/open-omniscience`` or
                                  ``~/.local/share/open-omniscience``. This is
                                  the correct, portable home for an installed app.

Nothing here reaches the network or imports heavy deps; it is safe to import
anywhere, including at module load.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = "open-omniscience"

# src/paths.py -> parents[1] is the repo root (where pyproject.toml lives).
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    # Lock the data dir to the owner (S-011): the corpus, signing keys, custody log and
    # caches live here; on a shared host this stops other local users reading them.
    # Best-effort — POSIX only; full at-rest encryption remains the host's (Qubes/LUKS) job.
    try:
        path.chmod(0o700)
    except (OSError, NotImplementedError):  # pragma: no cover - non-POSIX / odd FS
        pass
    return path


def _is_source_checkout() -> bool:
    """True when we are running from a writable tree that looks like the repo."""
    return (_REPO_ROOT / "pyproject.toml").is_file() and os.access(_REPO_ROOT, os.W_OK)


def repo_root() -> Path:
    """The repository root as seen by the importing code (for tests/tooling)."""
    return _REPO_ROOT


def data_dir() -> Path:
    """Return the writable data directory, creating it if necessary.

    See the module docstring for the precedence rules.
    """
    override = os.getenv("OO_DATA_DIR")
    if override:
        return _ensure(Path(override).expanduser())

    if _is_source_checkout():
        return _ensure(_REPO_ROOT / "data")

    xdg = os.getenv("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return _ensure(base / APP_DIRNAME)


def default_sqlite_url() -> str:
    """The default SQLite URL rooted in :func:`data_dir`."""
    return f"sqlite:///{data_dir() / 'open_omniscience.db'}"
