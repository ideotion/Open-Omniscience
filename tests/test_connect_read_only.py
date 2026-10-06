"""``connect(read_only=True)``: a read that cannot consume the log a crash left (E1, the unlock probe's check).

``PRAGMA query_only`` stops a connection's own writes and nothing else: the LAST connection on a file that
closes checkpoints a leftover ``-wal`` into the file and deletes it, with the right key and with a wrong
one (measured on a real encrypted store: 65 KB of log folded into the file by a read that closed). The unlock
page's "the held key typed again" question and the damage check's re-read are reads, and they must not be the
thing that destroys what a crash left for whoever reads it next. What is pinned, on REAL stores (plaintext and
SQLCipher) whose last session died with an uncheckpointed log:

  * a read-only open and close leaves the file and its log byte for byte as they were, for the right key, for a
    wrong key and for a plaintext file, and the read still SEES the log's rows (the ``-shm`` beside them is the
    log's index in shared memory, rebuilt by any reader and not data: only its presence is compared);
  * the connection cannot write; a missing or empty file raises ``FileNotFoundError`` and creates nothing;
  * a directory name with a space, a ``?`` or a ``#`` in it is not read as URI syntax;
  * the default open is unchanged, and on the same files DOES fold the log (why the option exists);
  * on a file that had no log, the open changes no byte of the file and leaves at most an empty log beside it.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_KEY = "read only connect test key"

_CHILD = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from src.database.connect import connect
key = sys.argv[3] or None
c = connect(sys.argv[2], key=key, create_encrypted=bool(key), check_same_thread=False)
c.execute("PRAGMA journal_mode=WAL")
c.execute("PRAGMA wal_autocheckpoint=0")
c.execute("CREATE TABLE x(a)")
c.commit()
c.executemany("INSERT INTO x VALUES (?)", [(i,) for i in range(500)])
c.commit()
os._exit(0)  # no close(): the log stays as a crash leaves it
"""


def _crashed(folder: Path, key: str | None) -> Path:
    """A real store in ``folder`` whose last session died with its committed rows only in the log."""
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "t.db"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if key is None:
        env["OO_DB_PLAINTEXT"] = "1"
    subprocess.run([sys.executable, "-c", _CHILD, str(_ROOT), str(db), key or ""], check=True, env=env, timeout=120)
    assert Path(str(db) + "-wal").stat().st_size > 0, "the fixture left no log"
    return db


def _fingerprint(db: Path) -> dict[str, tuple[int, str] | bool | None]:
    """Size and digest of the file and its log; for the shared-memory index only whether it exists."""
    out: dict[str, tuple[int, str] | bool | None] = {}
    for suffix in ("", "-wal"):
        p = Path(str(db) + suffix)
        out[suffix] = (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) if p.exists() else None
    out["-shm"] = Path(str(db) + "-shm").exists()
    return out


@pytest.fixture(params=["encrypted", "plaintext"])
def crashed(request, tmp_path):
    if request.param == "encrypted":
        pytest.importorskip("sqlcipher3")
        return _crashed(tmp_path / "enc", _KEY), _KEY
    return _crashed(tmp_path / "plain", None), None


def test_a_read_only_open_and_close_leaves_the_file_and_its_log_as_they_were_and_still_sees_the_log(crashed):
    from src.database.connect import connect

    db, key = crashed
    before = _fingerprint(db)
    conn = connect(db, key=key, check_same_thread=False, read_only=True)
    assert conn.execute("SELECT count(*) FROM x").fetchone()[0] == 500, "the rows that are only in the log were not read"
    conn.close()
    assert _fingerprint(db) == before


def test_a_wrong_key_read_only_leaves_the_log_alone_and_is_refused_as_any_wrong_key_is(tmp_path):
    pytest.importorskip("sqlcipher3")
    from src.database.connect import WrongPassphraseError, connect

    db = _crashed(tmp_path, _KEY)
    before = _fingerprint(db)
    with pytest.raises(WrongPassphraseError):
        connect(db, key="not the key", check_same_thread=False, read_only=True)
    assert _fingerprint(db) == before


def test_the_default_open_folds_the_leftover_log_which_is_why_read_only_exists(crashed):
    """The measured fact the option answers (a canary: if SQLite stops doing this, the reasoning in
    ``connect``'s docstring is out of date). ``query_only`` does not prevent it either."""
    from src.database.connect import connect

    db, key = crashed
    conn = connect(db, key=key, check_same_thread=False)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("SELECT count(*) FROM x").fetchone()
    conn.close()
    assert not Path(str(db) + "-wal").exists(), "the last close no longer folds a leftover log"


def test_a_read_only_connection_cannot_write(crashed):
    from src.database.connect import connect

    db, key = crashed
    conn = connect(db, key=key, check_same_thread=False, read_only=True)
    try:
        with pytest.raises(Exception) as err:  # sqlite3.OperationalError or the sqlcipher3 twin
            conn.execute("INSERT INTO x VALUES (-1)")
        assert "readonly" in str(err.value).lower()
    finally:
        conn.close()


@pytest.mark.parametrize("how", ["missing", "empty"])
def test_a_read_only_open_never_creates_a_file(tmp_path, how):
    from src.database.connect import connect

    db = tmp_path / "t.db"
    if how == "empty":
        db.write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        connect(db, key=_KEY, check_same_thread=False, read_only=True)
    assert (not db.exists()) if how == "missing" else db.stat().st_size == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ([] if how == "missing" else ["t.db"])


def test_a_directory_name_with_uri_syntax_in_it_is_opened_as_a_path(tmp_path):
    from src.database.connect import connect

    folder = tmp_path / "a b#c d%20e"
    db = _crashed(folder, None)
    before = _fingerprint(db)
    conn = connect(db, check_same_thread=False, read_only=True)
    assert conn.execute("SELECT count(*) FROM x").fetchone()[0] == 500
    conn.close()
    assert _fingerprint(db) == before


def test_on_a_file_that_had_no_log_no_byte_of_the_file_changes(tmp_path):
    """The stated price: a read-only connection may create an empty ``-wal`` and a ``-shm`` beside a file that
    had none. The file itself is untouched, and an empty log is none."""
    pytest.importorskip("sqlcipher3")
    from src.database.connect import connect

    db = tmp_path / "t.db"
    c = connect(db, key=_KEY, create_encrypted=True, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE x(a)")
    c.commit()
    c.close()  # the last close checkpoints: no log is left
    assert not Path(str(db) + "-wal").exists() or Path(str(db) + "-wal").stat().st_size == 0
    main_before = hashlib.sha256(db.read_bytes()).hexdigest()
    conn = connect(db, key=_KEY, check_same_thread=False, read_only=True)
    conn.execute("SELECT count(*) FROM x").fetchone()
    conn.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == main_before
    wal = Path(str(db) + "-wal")
    assert (not wal.exists()) or wal.stat().st_size == 0
