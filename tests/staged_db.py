"""Compare a staged copy with the database it came from (R829 A, row 410-A).

An import keeps its staged corpus and custody log encrypted (``src.backup.staged_key``): the staged file's BYTES are
SQLCipher pages now, never the plaintext the backup carried, so a test that once compared bytes compares CONTENT --
every schema object and every row, read through the staged file's own key. A file that never opened as a database
(several tests stage a fake one) is never sealed and is still compared byte for byte.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from src.backup.staged_key import is_keyed, open_staged


def _content(conn) -> tuple:
    objects = sorted(
        (str(t), str(n), str(s or ""))
        for t, n, s in conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    )
    rows = {}
    for typ, name, sql in objects:
        if typ != "table" or sql.upper().startswith("CREATE VIRTUAL TABLE"):
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        rows[name] = sorted(repr(r) for r in conn.execute(f"SELECT * FROM {quoted}"))  # noqa: S608 - a test's own names
    return tuple(objects), tuple(sorted(rows.items()))


def _is_database(path: Path) -> bool:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            c.close()
        return True
    except sqlite3.DatabaseError:
        return False


def same_database(staged: os.PathLike[str] | str, original: os.PathLike[str] | str | bytes) -> bool:
    """True when the staged copy holds exactly what ``original`` (a path or the bytes of one) holds."""
    staged = Path(staged)
    with tempfile.TemporaryDirectory() as d:
        if isinstance(original, bytes):
            p = Path(d) / "original.db"
            p.write_bytes(original)
            original = p
        original = Path(original)
        if not is_keyed(staged):
            return staged.read_bytes() == original.read_bytes()
        assert _is_database(original), "a sealed staged copy of a file that is not a database"
        a = open_staged(staged)
        try:
            mine = _content(a)
        finally:
            a.close()
        b = sqlite3.connect(f"file:{original}?mode=ro", uri=True)
        try:
            theirs = _content(b)
        finally:
            b.close()
        return mine == theirs
