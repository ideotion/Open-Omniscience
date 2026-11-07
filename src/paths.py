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


class DataVolumeMissing(OSError):
    """The chosen data folder (on a drive the first-launch step marked) is not there.

    Raised INSTEAD of creating it: a folder made where an unplugged drive's mount point
    sits would boot the app as an empty fresh install beside nothing (R86, 2026-09-29;
    see ``src/safety/data_volume.py``)."""


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


# Memo for :func:`data_dir` (F3, 2026-11-07): the oo-wiki-stream thread reaches it through
# load_settings() once per firehose event, and the full path (mkdir + chmod + is_file +
# os.access) made it one of the busiest threads in the process. Keyed on every environment
# input the resolution reads, so changing OO_DATA_DIR / XDG_DATA_HOME / HOME in-process
# (tests do) simply misses the memo; guarded by ONE stat so a deleted folder is re-created.
_memo: tuple[tuple[str | None, ...], Path] | None = None


def _memo_key() -> tuple[str | None, ...]:
    return (
        os.getenv("OO_DATA_DIR"),
        os.getenv("XDG_DATA_HOME"),
        os.getenv("HOME"),
        os.getenv("USERPROFILE"),
        str(_REPO_ROOT),  # tests re-point it to simulate an installed (non-checkout) layout
    )


def data_dir() -> Path:
    """Return the writable data directory, creating it if necessary.

    See the module docstring for the precedence rules. Repeat calls are cheap: the result
    is memoised per resolved environment and revalidated with a single ``stat`` (a data
    folder that vanished is created again, exactly as before).
    """
    global _memo
    override = os.getenv("OO_DATA_DIR")
    if override and os.getenv("OO_DATA_VOLUME_ID"):
        # A folder the first-launch step marked: never recreated when it is missing, and
        # the check must run every time (the drive can be unplugged mid-session).
        from src.safety.data_volume import guard_data_dir

        guard_data_dir(Path(override).expanduser())

    key = _memo_key()
    memo = _memo
    if memo is not None and memo[0] == key and memo[1].is_dir():
        return memo[1]

    if override:
        chosen = _ensure(Path(override).expanduser())
    elif _is_source_checkout():
        chosen = _ensure(_REPO_ROOT / "data")
    else:
        xdg = os.getenv("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        chosen = _ensure(base / APP_DIRNAME)
    _memo = (key, chosen)
    return chosen


def default_sqlite_url() -> str:
    """The default SQLite URL rooted in :func:`data_dir`."""
    return f"sqlite:///{data_dir() / 'open_omniscience.db'}"
