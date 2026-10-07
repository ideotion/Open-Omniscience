"""Paths in a diagnostic text, as the app's own relative name or a token (2026-10-07).

A path under the user's home names the user, and a record the debug bundle carries (a stack frame of a crashed session, a
thread's name) can hold one. ``tokenise_paths`` rewrites every absolute path in a text so that none is left whole:

* a path inside the app's own directory becomes the path relative to it (``src/monitoring/session_hwm.py``);
* one inside the data directory becomes ``<data>/…/<file name>``, one under the home directory ``<home>/…/<file name>``;
* any other absolute path (POSIX or Windows) becomes ``…/<file name>``.

The three roots are read when it is called, so a changed ``HOME`` or data directory is followed. Never raises.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: A POSIX absolute path of at least two segments, or a Windows drive path; a run of characters that cannot end one.
_ABS = re.compile(
    r"(?<![\w.<>~$])(?:[A-Za-z]:[\\/]|/)(?:[^\s\\/:'\"<>|*?]+[\\/])*[^\s\\/:'\"<>|*?]+"
)


def _roots() -> list[tuple[str, str]]:
    """``(root, how)`` longest first: the app's directory, the data directory, the home directory."""
    roots: list[tuple[str, str]] = []
    app = Path(__file__).resolve().parents[2]
    roots.append((str(app), "app"))
    try:
        from src.paths import data_dir

        roots.append((str(data_dir()), "data"))
    except Exception:  # noqa: BLE001 - a diagnostic never fails for want of a directory
        pass
    home = os.path.expanduser("~")
    if home and home != "~":
        roots.append((home, "home"))
    return sorted(roots, key=lambda r: -len(r[0]))


def tokenise_paths(text: str) -> str:
    """``text`` with every absolute path rewritten as in the module docstring."""
    try:
        roots = _roots()

        def one(match: re.Match[str]) -> str:
            raw = match.group(0)
            path = raw.replace("\\", "/")
            name = path.rsplit("/", 1)[-1]
            for root, how in roots:
                root = root.replace("\\", "/").rstrip("/")
                if root and (path == root or path.startswith(root + "/")):
                    rest = path[len(root) + 1:]
                    if how == "app":
                        return rest or "."
                    return f"<{how}>/…/{name}"
            return f"…/{name}"

        return _ABS.sub(one, text)
    except Exception:  # noqa: BLE001
        return "(path withheld)"
