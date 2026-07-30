"""The two whole-corpus costs a restore used to pay ONCE PER IMPORTED BACKUP.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-30: importing 16 backups (~130 GB cumulative) on an 8-core box
was tracking to about a week, with CPU, RAM and disk all under-utilised -- the
signature of single-threaded, corpus-scaled work. Two stages account for most of it,
and BOTH are O(live corpus) PER ITEM, so an N-item queue pays them N times over a
corpus that grows with every item:

  * ``verify_copy`` ran an unconditional FTS5 ``'rebuild'`` -- the exact operation
    ``ensure_fts`` was fixed to stop doing on every boot (P0.4), whose measured cost on
    the field's own 130 GB corpus is recorded in ``src/database/fts.py`` as 981-1645 s
    PER RUN. It was also redundant (the ``article_fts_ai`` trigger indexes the merged
    rows as they insert) and the check it fed was tautological (see ``_verify_fts``).

  * ``snapshot_preserving`` re-encrypts the whole corpus row by row through the
    SQLCipher codec, and a restore takes TWO of them (the merge's working copy and the
    pre-restore safety net).

Measured while building this, on a 0.52-0.58 GB encrypted synthetic store:
``sqlcipher_export`` 9.6 s vs a byte copy 2.3 s; FTS ``'rebuild'`` 6.2 s (which
extrapolates to ~23 min at 130 GB -- consistent with the 16-27 min the field actually
measured, which is what makes the linear extrapolation trustworthy here).

What these tests pin is the BEHAVIOUR, never a speed: a rebuild happens only when the
index is genuinely incomplete, and the byte copy is taken only when it can be PROVEN
complete (and degrades to the always-correct codec path when it cannot).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from src.backup.merge import _verify_fts
from src.database.connect import (
    connect,
    have_driver,
    is_encrypted_file,
    set_passphrase,
    snapshot_preserving,
)

sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")

_PW = "correct horse battery staple"

_FTS_SCHEMA = """
CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT, content TEXT);
CREATE VIRTUAL TABLE article_fts USING fts5(
    title, content, content='articles', content_rowid='id');
CREATE TRIGGER article_fts_ai AFTER INSERT ON articles BEGIN
  INSERT INTO article_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""


def _fts_db(path: Path, n: int = 5) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.executescript(_FTS_SCHEMA)
    con.executemany(
        "INSERT INTO articles VALUES(?,?,?)",
        [(i, f"t{i}", f"body {i} climate policy") for i in range(n)],
    )
    con.commit()
    return con


# --------------------------------------------------------------------------- #
#  The FTS rebuild: only when the index is genuinely incomplete
# --------------------------------------------------------------------------- #
def test_a_complete_index_is_verified_without_a_rebuild(tmp_path):
    """THE import-speed fix. The merge inserts through ``INSERT INTO articles ...
    SELECT``, so the sync trigger has already indexed every merged row by the time
    verification runs -- a corpus-scaled rebuild here buys nothing."""
    con = _fts_db(tmp_path / "c.db")
    try:
        out = _verify_fts(con, True, 5)
        assert out["fts_matches_articles"] is True
        assert out["fts_indexed"] == 5
        assert out["fts_rebuilt"] is False, "a complete index must not be rebuilt"
    finally:
        con.close()


def test_an_incomplete_index_is_still_repaired(tmp_path):
    """The restore keeps its "the swapped-in corpus has a complete index" property --
    it just stops paying for it when it already holds. Without this the fix would trade
    a real guarantee for speed."""
    con = _fts_db(tmp_path / "c.db")
    try:
        con.execute("INSERT INTO article_fts(article_fts) VALUES('delete-all')")
        con.commit()
        assert con.execute("SELECT COUNT(*) FROM article_fts_docsize").fetchone()[0] == 0

        out = _verify_fts(con, True, 5)
        assert out["fts_rebuilt"] is True
        assert out["fts_indexed"] == 5
        assert out["fts_matches_articles"] is True
    finally:
        con.close()


def test_a_partial_index_is_detected_which_the_old_check_could_not(tmp_path):
    """The old check compared ``COUNT(*) FROM article_fts`` -- which on an
    external-content FTS5 table reads the CONTENT table -- against
    ``COUNT(*) FROM articles``, i.e. a table against itself. It could not fail, so it
    could not detect a partial index either. This one can."""
    con = _fts_db(tmp_path / "c.db")
    try:
        # Index 5 docs, then add a 6th article with the trigger dropped: 5 indexed, 6 rows.
        con.execute("DROP TRIGGER article_fts_ai")
        con.execute("INSERT INTO articles VALUES(9, 't9', 'body 9')")
        con.commit()
        tautological = con.execute("SELECT COUNT(*) FROM article_fts").fetchone()[0]
        assert tautological == 6, "the old probe reads the content table, not the index"

        out = _verify_fts(con, True, 6)
        assert out["fts_rebuilt"] is True, "a genuinely partial index must be repaired"
        assert out["fts_indexed"] == 6
    finally:
        con.close()


def test_no_fts_table_is_a_pass_not_a_probe(tmp_path):
    con = sqlite3.connect(str(tmp_path / "c.db"))
    try:
        assert _verify_fts(con, False, 0) == {"fts_matches_articles": True}
    finally:
        con.close()


def test_an_unprobeable_build_is_reported_not_asserted(tmp_path):
    """fts.py's own precedent: when index population cannot be probed cheaply, trust the
    triggers and SKIP rather than risk a corpus-scaled rebuild on a false negative -- and
    say so, rather than presenting the unprovable state as a verified pass."""
    con = sqlite3.connect(str(tmp_path / "c.db"))
    con.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY)")
    try:
        out = _verify_fts(con, True, 3)  # no article_fts_docsize exists at all
        assert out["fts_rebuilt"] is False
        assert out["fts_indexed"] is None
        assert out["fts_note"], "the unprovable state carries its reason, not silence"
        assert out["fts_matches_articles"] is True
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  The snapshot fast path
# --------------------------------------------------------------------------- #
def _encrypted_corpus(path: Path, n: int = 200) -> None:
    # An EXPLICIT key: the test suite runs with the plaintext opt-out set, and this
    # fast path exists specifically for the encrypted store.
    con = connect(path, key=_PW, check_same_thread=False)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, content TEXT)")
        con.executemany(
            "INSERT INTO articles VALUES(?,?)", [(i, f"body {i} " * 200) for i in range(n)]
        )
        con.commit()
    finally:
        con.close()


@sqlcipher_only
def test_the_fast_path_produces_a_readable_byte_identical_encrypted_copy(tmp_path, monkeypatch):
    """A byte copy cannot get ``page_size``/``auto_vacuum`` wrong the way a
    re-created target can (the documented ``_match_source_pragmas`` hazard) -- it does
    not re-create anything. It must still be openable under the same key."""
    monkeypatch.setattr("src.database.connect._passphrase", _PW, raising=False)
    set_passphrase(_PW)
    src = tmp_path / "live.db"
    _encrypted_corpus(src)
    assert is_encrypted_file(src)

    dest = tmp_path / "working.db"
    snapshot_preserving(src, dest, allow_file_copy=True)

    assert dest.read_bytes() == src.read_bytes(), "the fast path copies bytes"
    con = connect(dest, check_same_thread=False)
    try:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        con.close()


@sqlcipher_only
def test_a_stale_wal_beside_the_destination_is_removed(tmp_path, monkeypatch):
    """A snapshot is a lone file. A ``-wal`` inherited from whatever previously lived at
    that path would be read as THIS database's log -- silently wrong data, not an error."""
    monkeypatch.setattr("src.database.connect._passphrase", _PW, raising=False)
    set_passphrase(_PW)
    src = tmp_path / "live.db"
    _encrypted_corpus(src)
    dest = tmp_path / "working.db"
    dest.with_name(dest.name + "-wal").write_bytes(b"stale garbage")

    snapshot_preserving(src, dest, allow_file_copy=True)
    assert not dest.with_name(dest.name + "-wal").exists()


@sqlcipher_only
def test_an_undrainable_wal_falls_back_instead_of_copying_something_unproven(
    tmp_path, monkeypatch
):
    """The failure direction is "slower", never "wrong": when the checkpoint cannot
    prove every committed page reached the main file, the fast path REFUSES and the
    always-correct codec path runs instead. A torn copy is never the outcome."""
    monkeypatch.setattr("src.database.connect._passphrase", _PW, raising=False)
    set_passphrase(_PW)
    src = tmp_path / "live.db"
    _encrypted_corpus(src)

    import src.database.connect as C

    real_connect = C.connect
    calls: dict[str, int] = {"checkpoint": 0}

    class _BusyCheckpoint:
        """Reports the checkpoint as BUSY -- a reader still needs the log."""

        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *a):
            if "wal_checkpoint" in sql:
                calls["checkpoint"] += 1
                return _Row((1, 0, 0))
            return self._inner.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _Row:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    def _wrapped(path, *a, **kw):
        con = real_connect(path, *a, **kw)
        return _BusyCheckpoint(con) if Path(path) == src else con

    monkeypatch.setattr(C, "connect", _wrapped)
    dest = tmp_path / "working.db"
    C.snapshot_preserving(src, dest, allow_file_copy=True)

    assert calls["checkpoint"] == 1, "the fast path was attempted"
    assert dest.exists()
    monkeypatch.setattr(C, "connect", real_connect)
    con = real_connect(dest, check_same_thread=False)
    try:  # the codec path ran and produced a sound, complete copy
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
    finally:
        con.close()


@sqlcipher_only
def test_the_default_is_the_unchanged_codec_path(tmp_path, monkeypatch):
    """Every pre-existing caller keeps the old behaviour: the fast path is OPT-IN
    because it holds the single-writer gate for the copy, which is free during an import
    and rude during ordinary operation."""
    monkeypatch.setattr("src.database.connect._passphrase", _PW, raising=False)
    set_passphrase(_PW)
    src = tmp_path / "live.db"
    _encrypted_corpus(src)

    import src.database.connect as C

    seen: list[str] = []
    real_export = C._export

    def _spy(conn, alias):
        seen.append(alias)
        return real_export(conn, alias)

    monkeypatch.setattr(C, "_export", _spy)
    C.snapshot_preserving(src, tmp_path / "a.db")
    assert seen == ["snap"], "the default must still re-encrypt via sqlcipher_export"


@sqlcipher_only
def test_a_failed_fast_path_never_leaves_a_partial_copy_behind(tmp_path, monkeypatch):
    """A half-written destination that a later stage mistook for a good snapshot would
    be the worst possible outcome of an optimisation -- so the fallback clears it first."""
    monkeypatch.setattr("src.database.connect._passphrase", _PW, raising=False)
    set_passphrase(_PW)
    src = tmp_path / "live.db"
    _encrypted_corpus(src)

    import src.database.connect as C

    def _boom(a, b):
        Path(b).write_bytes(b"half a database")
        raise OSError("disk hiccup mid-copy")

    monkeypatch.setattr(shutil, "copyfile", _boom)
    dest = tmp_path / "working.db"
    C.snapshot_preserving(src, dest, allow_file_copy=True)

    con = connect(dest, check_same_thread=False)
    try:  # the codec fallback produced a real database, not the truncated bytes
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
    finally:
        con.close()
