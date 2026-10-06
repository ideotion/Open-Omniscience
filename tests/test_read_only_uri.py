"""The read-only URI never reads a file NAME as syntax (src/database/read_only_uri.py).

The spelling it replaced -- ``file:{path}?mode=ro`` with the path unencoded -- opened a different
path READ-WRITE whenever the path held a ``?`` or a ``#``, leaving an empty file behind, and decoded
a ``%41`` into ``A``. These tests pin the strings (for both platforms' paths, since CI does not run
on both) and the real opens, on a directory whose name carries every character that is URI syntax.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

from src.database.read_only_uri import open_plain_read_only, read_only_uri

ODD_DIRS = ["data#frag%41 dir"] + ([] if sys.platform == "win32" else ["data?x#frag%41 dir"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/tmp/a b/c.db", "file:///tmp/a%20b/c.db?mode=ro"),
        ("/tmp/a?b#c%41/d.db", "file:///tmp/a%3Fb%23c%2541/d.db?mode=ro"),
        ("/tmp/données.db", "file:///tmp/donn%C3%A9es.db?mode=ro"),
    ],
)
def test_posix_paths_are_percent_encoded(raw, expected) -> None:
    assert read_only_uri(raw, windows=False) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:\\data\\a b\\x.db", "file:///C:/data/a%20b/x.db?mode=ro"),
        ("D:\\a?b#c\\x.db", "file:///D:/a%3Fb%23c/x.db?mode=ro"),
        # a share is an empty authority and a //server/share path, never a host: SQLite refuses
        # "file://server/share" ("invalid uri authority")
        ("\\\\srv\\share\\dir x\\x.db", "file:////srv/share/dir%20x/x.db?mode=ro"),
        # the extended-length spellings of both
        ("\\\\?\\C:\\data\\x.db", "file:///C:/data/x.db?mode=ro"),
        ("\\\\?\\UNC\\srv\\share\\x.db", "file:////srv/share/x.db?mode=ro"),
    ],
)
def test_windows_paths_are_drive_unc_and_extended_length_safe(raw, expected) -> None:
    assert read_only_uri(raw, windows=True) == expected


def test_the_uri_names_the_same_path_it_was_given() -> None:
    raw = "/tmp/a?b#c%41 d/x.db"
    uri = read_only_uri(raw, windows=False)
    assert unquote(uri.split("?mode=ro")[0].removeprefix("file://")) == raw


def _db(path: Path, *, stamped: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE alembic_version (version_num TEXT)")
    if stamped:
        con.execute("INSERT INTO alembic_version VALUES ('rev-1')")
    con.commit()
    con.close()


@pytest.mark.parametrize("dirname", ODD_DIRS)
def test_a_path_with_uri_characters_opens_that_file_and_creates_nothing(tmp_path, dirname) -> None:
    db = tmp_path / dirname / "staged.db"
    _db(db)
    before = sorted(p.name for p in tmp_path.iterdir()) + sorted(p.name for p in db.parent.iterdir())
    con = open_plain_read_only(db)
    try:
        assert con.execute("SELECT version_num FROM alembic_version").fetchone() == ("rev-1",)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("INSERT INTO alembic_version VALUES ('x')")
    finally:
        con.close()
    after = sorted(p.name for p in tmp_path.iterdir()) + sorted(p.name for p in db.parent.iterdir())
    assert after == before, "the open left a stray file behind"


def test_the_old_spelling_is_the_bug_this_replaces(tmp_path) -> None:
    """The control: it opens read-write at a DIFFERENT path and leaves a stray file."""
    if sys.platform == "win32":
        pytest.skip("a '#' only, and the directory it makes needs a POSIX path")
    db = tmp_path / "a#b" / "staged.db"
    _db(db)
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return  # the driver now refuses it: also not the silent stray file
    con.close()
    stray = tmp_path / "a"
    assert stray.exists(), "the old spelling no longer misbehaves: re-read the premise of this module"


def test_a_missing_file_is_refused_and_not_created(tmp_path) -> None:
    gone = tmp_path / "gone.db"
    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        open_plain_read_only(gone)
    assert not gone.exists()


@pytest.mark.parametrize("dirname", ODD_DIRS)
def test_every_caller_reads_a_staged_file_under_an_odd_directory(tmp_path, dirname) -> None:
    from src.database.migrate import file_revision

    db = tmp_path / dirname / "staged.db"
    _db(db)
    assert file_revision(db) == "rev-1"
    assert sorted(p.name for p in db.parent.iterdir()) == ["staged.db"]


@pytest.mark.parametrize("dirname", ODD_DIRS)
def test_the_validator_and_the_corpus_stats_read_under_an_odd_directory(tmp_path, dirname) -> None:
    from src.backup.artifact import _corpus_stats
    from src.backup.sqlite_backup import validate_sqlite_file

    db = tmp_path / dirname / "staged.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, hash TEXT)")
    con.execute("INSERT INTO articles VALUES (1, 'h1')")
    con.commit()
    con.close()
    assert validate_sqlite_file(db) == 2
    assert _corpus_stats(db)["tables"]["articles"] == 1
    assert sorted(p.name for p in db.parent.iterdir()) == ["staged.db"]


def test_no_module_builds_a_read_only_uri_by_hand() -> None:
    """The class, not the four instances: any f-string that splices a path into a ``file:`` URI is
    this bug again. ``src/database/connect.py`` has its own encoded builder (``_read_only_target``)."""
    import re

    root = Path(__file__).resolve().parent.parent / "src"
    pattern = re.compile(r"""f["']file:\{|["']file:["']\s*\+""")
    hits = [
        f"{p.relative_to(root.parent)}:{n}"
        for p in root.rglob("*.py")
        if p.name != "read_only_uri.py"  # its docstring quotes the spelling it replaced
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not hits, f"build the URI with src.database.read_only_uri.read_only_uri: {hits}"
