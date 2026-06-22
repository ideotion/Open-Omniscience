"""Server-side directory browser — pick a local folder without typing a path (P1 #8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The folder-backup destination and the .eml folder import take a SERVER-SIDE path
the user otherwise had to type by hand (field test 2026-06-22: "Browse buttons,
never manual path typing"). A browser's native file dialog cannot return a host
path, so this endpoint lists a directory's SUBDIRECTORIES so the SPA can offer a
"Browse…" picker.

Honesty / safety:
  * This is a LOOPBACK-ONLY single-user app — browsing the user's OWN filesystem
    to choose a backup destination is the point, and it is consistent with the
    existing local trust model (the unlock screen already lists key-file names).
  * It returns ONLY directory NAMES — never file contents, never even file names.
  * Traversal-safe by construction: the path is resolved to its real absolute
    form; an unreadable directory lists nothing (never errors); a non-existent or
    non-directory path falls back to the user's home rather than leaking an error.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/fs", tags=["fs"])

# Bound the listing so a pathological directory (a download dir with 100k files)
# can never produce an unbounded response; the picker shows folders only.
_MAX_ENTRIES = 2000


def _safe_resolve(path: str | None) -> Path:
    """Resolve ``path`` to a real existing directory, falling back to home."""
    home = Path.home()
    if not path:
        return home
    try:
        base = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return home
    return base if base.is_dir() else home


def list_directory(path: str | None, *, show_hidden: bool = False) -> dict:
    """List the immediate SUBDIRECTORIES of ``path`` (for a folder picker)."""
    base = _safe_resolve(path)
    entries: list[dict] = []
    truncated = False
    try:
        children = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        children = []  # an unreadable dir lists nothing — never an error
    for child in children:
        try:
            if not child.is_dir():
                continue  # folders only (never expose file names)
        except OSError:
            continue  # a broken symlink etc. is simply skipped
        if not show_hidden and child.name.startswith("."):
            continue
        entries.append({"name": child.name, "path": str(child)})
        if len(entries) >= _MAX_ENTRIES:
            truncated = True
            break
    parent = str(base.parent) if base.parent != base else None
    return {
        "path": str(base),
        "parent": parent,  # None at the filesystem root
        "home": str(Path.home()),
        "entries": entries,
        "truncated": truncated,
        # So the picker can honestly enable/disable "use this folder" for a
        # destination (a backup target must be writable).
        "writable": os.access(str(base), os.W_OK),
    }


@router.get("/list")
def fs_list(
    path: str | None = Query(None, description="Directory to list (default: home)"),
    show_hidden: bool = Query(False, description="Include dot-directories"),
) -> dict:
    """List a directory's subdirectories for the server-side folder picker."""
    return list_directory(path, show_hidden=show_hidden)
