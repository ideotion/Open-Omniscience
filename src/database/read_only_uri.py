"""The URI that opens a plain SQLite file read-only, built so the PATH is never read as syntax.

``sqlite3.connect(f"file:{path}?mode=ro", uri=True)`` -- the spelling this replaces in four
places -- puts a file name into a URI without encoding it. A ``?`` ends the path there and starts
the query, a ``#`` starts the fragment (and everything after it, ``mode=ro`` included, is
ignored), and ``%41`` is decoded to ``A``. The staging tree sits under the data directory the
operator chose, so any of those characters can be in it, and the failure is not an error: the
open lands on a DIFFERENT path, read-WRITE, and quietly creates an empty file there.

``os.path.abspath`` is used, not ``Path.resolve``: resolving a mapped drive turns it into its UNC
form, which is a different spelling of the same file and one SQLite reads differently.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

__all__ = ["open_plain_read_only", "read_only_uri"]


def read_only_uri(path: os.PathLike[str] | str, *, windows: bool | None = None) -> str:
    """``file:`` URI of ``path`` with ``mode=ro``, percent-encoded.

    ``windows`` says which flavour of path to expect; the default is the running platform, and a
    test passes it to cover the other. A drive path becomes ``file:///C:/dir/x``; a UNC path
    ``\\\\server\\share\\x`` becomes ``file:////server/share/x`` (an empty authority, then the
    path ``//server/share/x``), the spelling SQLite reads on Windows.
    """
    win = os.name == "nt" if windows is None else windows
    raw = os.fspath(path)
    if win:
        p = raw.replace("\\", "/")
        if p.startswith("//?/"):  # an extended-length path: \\?\C:\x or \\?\UNC\server\share\x
            p = p[4:]
            if p[:4].upper() == "UNC/":
                p = "//" + p[4:]
        if not (p.startswith("//") or (len(p) > 1 and p[1] == ":")):
            # a relative path: make it absolute the Windows way before encoding it
            p = os.path.abspath(raw).replace("\\", "/")
        if p.startswith("//"):  # UNC: \\server\share\x -> an empty authority, path //server/share/x
            return "file://" + quote(p, safe="/:") + "?mode=ro"
        return "file:///" + quote(p, safe="/:") + "?mode=ro"
    p = os.path.abspath(raw)
    return "file://" + quote(p, safe="/") + "?mode=ro"


def open_plain_read_only(path: os.PathLike[str] | str) -> sqlite3.Connection:
    """A stdlib read-only connection to a plaintext SQLite file.

    A missing file is refused with the driver's own error (``mode=ro`` would not create it either),
    never created.
    """
    if not Path(path).is_file():
        raise sqlite3.OperationalError("unable to open database file")
    return sqlite3.connect(read_only_uri(path), uri=True)
