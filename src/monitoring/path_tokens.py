r"""Paths in a diagnostic text, as the app's own relative name or a token (2026-10-07).

A path under the user's home names the user, and a record the debug bundle carries (a stack frame of a crashed session, a
thread's name, an error's text) can hold one. ``tokenise_paths`` rewrites every absolute path in a text so that none is left whole:

* a path inside the app's own directory becomes the path relative to it (``src/monitoring/session_hwm.py``);
* one inside the data directory becomes ``<data>/…/<file name>``, one under the home directory ``<home>/…/<file name>``;
* any other absolute path (POSIX, Windows drive, UNC) becomes ``…/<file name>``.

THE ROOTS THIS PROCESS KNOWS are replaced first, as literal text, in every form they are written in: with either slash, with
the backslash doubled (the form ``repr`` and JSON write), and without regard to case where the path is a Windows one. They are
the app's directory, the data directory and EVERY home directory the process can name (``HOME``, ``USERPROFILE``,
``HOMEDRIVE``+``HOMEPATH``, ``expanduser("~")``, ``Path.home()`` and the account database's), so a home that is not the one
``HOME`` says is still the one that is replaced, and a user name with a space in it is inside the root and not a stopping place.
THEN the shapes any user's profile takes (``C:\Users\<name with spaces>``, ``/home/<name>``, ``/var/home/<name>`` (Fedora's atomic desktops), ``/Users/<name>``, a profile directory on a UNC share,
``~name``) and UNC paths (``\\?\UNC\...`` too), and then every other absolute path. A known root ends only where a name cannot go on
(a space ends a POSIX one; a Windows one ends at a separator or a quote, because a Windows name holds spaces and dots). The three roots are read when it is called, so a changed ``HOME`` or data
directory is followed. Never raises. WHAT IT DOES NOT DO: a path written relative, or a user name written with no path around it; a directory-only
path under a root the process does not know, that is no profile shape, keeps its last segment, and a UNC directory with a space in its
name is partly kept (the generic rule stops at the space).
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from pathlib import Path

_SEG = r"[^\s\\/:'\"<>|*?]+"
_SEP = r"[\\/]+"
#: A run of backslashes opening a UNC path: bounded, because an unbounded run restarts the match at every backslash of a long run
#: and costs the square of its length (8,000 took 1.8 s, 20,000 took 13 s); ``repr`` and JSON write at most four, a doubled doubling.
_UNC_LEAD = r"\\{2,8}"
#: A profile name: a segment that may hold spaces (Windows) and an apostrophe followed by a letter (``O'Brien``); a quote that ends a
#: path (``cwd='/home/al'``) is followed by no word character, and so ends the name.
_NAME_WIN = r"(?:[^\\/\r\n:'\"<>|*?]|'(?=\w))+"
_NAME_POSIX = r"(?:[^\s\\/:'\"<>|*?]|'(?=\w))+"
#: An absolute path of at least two segments: POSIX, a Windows drive, or UNC (``\\server\share\...``, in either slash and
#: with the backslashes doubled as ``repr`` and JSON write them).
_ABS = re.compile(rf"(?<![\w.<>~$…])(?:[A-Za-z]:{_SEP}|{_UNC_LEAD}(?:[?.]\\+)?|/)(?:{_SEG}{_SEP})*{_SEG}")
#: ``<tok>`` and what follows it.
_TOKENISED = re.compile(rf"<(app|data|home)>((?:{_SEP}{_SEG})*)")
#: A user's profile directory, whoever's, with the name taken up to the next separator (a Windows name may hold spaces).
_PROFILE_WIN = re.compile(rf"(?i)(?<![\w.<>~$…])[A-Za-z]:{_SEP}(?:Users|Documents and Settings){_SEP}{_NAME_WIN}")
_PROFILE_POSIX = re.compile(rf"(?<![\w.<>~$…])/(?:var/home|home|Users){_SEP}{_NAME_POSIX}")
#: A profile directory on a UNC share: ``\\server\Users\name``, ``\\server\share\home\name``, ``\\?\UNC\server\home\name``.
_PROFILE_UNC = re.compile(
    rf"(?i)(?<![\w.<>~$…]){_UNC_LEAD}(?:[?.]\\+(?:UNC\\+)?)?{_SEG}{_SEP}(?:{_SEG}{_SEP})?(?:Users|home|Documents and Settings){_SEP}{_NAME_WIN}"
)
#: ``~`` and ``~name``, when a path follows or the text ends.
_TILDE = re.compile(r"(?<![\w.$])~[\w.-]*(?=[\\/]|$)")


def _homes() -> list[str]:
    """Every home directory the process can name, each once."""
    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value and value not in {"~", "/", "\\"} and value not in found:
            found.append(value)

    for name in ("HOME", "USERPROFILE"):
        add(os.environ.get(name))
    drive, path = os.environ.get("HOMEDRIVE"), os.environ.get("HOMEPATH")
    if drive and path:
        add(drive + path)
    add(os.path.expanduser("~"))
    with contextlib.suppress(RuntimeError, KeyError, OSError):
        add(str(Path.home()))
    try:
        import pwd

        add(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001 - no account database (Windows), or the uid has no entry
        pass
    return found


def _roots() -> list[tuple[str, str]]:
    """``(root, how)``, longest first: the app's directory, the data directory, every home directory."""
    roots: list[tuple[str, str]] = [(str(Path(__file__).resolve().parents[2]), "app")]
    try:
        from src.paths import data_dir

        roots.append((str(data_dir()), "data"))
    except Exception:  # noqa: BLE001 - a diagnostic never fails for want of a directory
        pass
    roots.extend((home, "home") for home in _homes())
    return sorted(roots, key=lambda r: -len(r[0]))


def _root_pattern(root: str) -> re.Pattern[str]:
    """The root as literal text in every form it is written in: segments joined by any run of slashes, backslashes doubled or
    not, and case-insensitive when it is a Windows path (a drive letter or UNC) or this is Windows."""
    windows = bool(re.match(r"^(?:[A-Za-z]:|[\\]{2})", root)) or sys.platform == "win32"
    parts = [p for p in re.split(r"[\\/]+", root) if p]
    lead = rf"(?:{_UNC_LEAD}|[\\/]+)" if root.startswith(("\\\\", "//")) else ("" if re.match(r"^[A-Za-z]:", root) else r"[\\/]+")
    body = _SEP.join(re.escape(p) for p in parts)
    # the root ends where its last segment does: not inside a longer name
    # The root ends only where a name cannot go on: the complement of a segment's characters for a POSIX root (a space ends it), and a
    # separator, a quote or the end for a Windows one, whose profile names hold spaces and dots (``Al Ice``, ``Al.DOMAIN``): a
    # longer name is another user's, and ``_PROFILE_WIN`` takes it whole.
    end = r"(?!'\w)" + (r"(?![^\s\\/:'\"<>|*?])" if not windows else r"(?![^\\/:'\"<>|*?])")
    # a root starts at the first separator of a run, never inside one: from every separator of a long run the match would restart
    return re.compile(rf"(?<![\w.<>~$…\\/]){lead}{body}{end}", re.IGNORECASE if windows else 0)


def _collapse(match: re.Match[str]) -> str:
    how, rest = match.group(1), match.group(2)
    names = [p for p in re.split(r"[\\/]+", rest) if p]
    if how == "app":
        return "/".join(names) if names else "."
    return f"<{how}>/…/{names[-1]}" if names else f"<{how}>"


def tokenise_paths(text: str) -> str:
    """``text`` with every absolute path rewritten as in the module docstring."""
    try:
        for root, how in _roots():
            text = _root_pattern(root).sub(f"<{how}>", text)
        text = _TOKENISED.sub(_collapse, text)
        text = _PROFILE_UNC.sub("<home>", text)
        text = _PROFILE_WIN.sub("<home>", text)
        text = _PROFILE_POSIX.sub("<home>", text)
        text = _TILDE.sub("<home>", text)
        text = _TOKENISED.sub(_collapse, text)

        def one(match: re.Match[str]) -> str:
            name = re.split(r"[\\/]+", match.group(0).rstrip("\\/"))[-1]
            return f"…/{name}"

        return _ABS.sub(one, text)
    except Exception:  # noqa: BLE001
        return "(path withheld)"
