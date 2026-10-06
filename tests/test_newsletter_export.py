"""Leaving newsletters out of an ENCRYPTED backup copy without VACUUM (src/backup/newsletter_export.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``VACUUM`` on a SQLCipher copy builds its whole new file in the connection's MEMORY temp store (a
file there would be plaintext), so the encrypted copy is rewritten with ``sqlcipher_export`` into a
fresh keyed file instead. Every rule that rewrite carries has a test here that fails without it:
the key is bound and never in SQL text, an exception, a log line or a note; every cipher setting is
copied and read back through the production open path; any failure takes the secure-delete path and
leaves no partial file; the search index forgets the deleted words (measured: neither VACUUM nor the
export removes them).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("sqlcipher3")

import src.database.connect as connect_mod  # noqa: E402
from src.backup import newsletter_export as ne  # noqa: E402
from src.backup.artifact import _NEWSLETTER_DOMAINS  # noqa: E402

_KEY = "correct horse battery staple"
_MARK = b"zzsecretnewsletterterm"


def _build(path: Path, *, newsletters: int = 3, kept: int = 3, via_column: bool = True) -> None:
    con = connect_mod.connect(path, key=_KEY)
    con.executescript(
        """
        CREATE TABLE alembic_version (version_num TEXT);
        INSERT INTO alembic_version VALUES ('rev-1');
        CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT);
        CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER, title TEXT, content TEXT,
                               newsletter_attached_via TEXT);
        CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, article_id INTEGER, term TEXT);
        CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', content_rowid='id');
        CREATE TRIGGER article_fts_ai AFTER INSERT ON articles BEGIN
          INSERT INTO article_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        CREATE TRIGGER article_fts_ad AFTER DELETE ON articles BEGIN
          INSERT INTO article_fts(article_fts, rowid, title, content)
          VALUES ('delete', old.id, old.title, old.content);
        END;
        """
    )
    con.execute("INSERT INTO sources VALUES (1, ?)", (_NEWSLETTER_DOMAINS[0],))
    con.execute("INSERT INTO sources VALUES (2, 'wire.example')")
    for i in range(newsletters):
        text = f"{_MARK.decode()}{i} " * 30
        con.execute("INSERT INTO articles (id, source_id, title, content) VALUES (?,1,?,?)", (100 + i, f"nl{i}", text))
        con.execute("INSERT INTO keyword_mentions (article_id, term) VALUES (?, 'nlterm')", (100 + i,))
    for i in range(kept):
        con.execute(
            "INSERT INTO articles (id, source_id, title, content) VALUES (?,2,?,?)",
            (200 + i, f"keep{i}", f"keepword{i} " * 30),
        )
        con.execute("INSERT INTO keyword_mentions (article_id, term) VALUES (?, 'kept')", (200 + i,))
    con.commit()
    con.close()


@pytest.fixture
def corpus(tmp_path):
    before = connect_mod.get_passphrase()
    connect_mod.set_passphrase(_KEY)
    path = tmp_path / "corpus.db.sqlcipher"
    _build(path)
    try:
        yield path
    finally:
        connect_mod.set_passphrase(before)


def _clear_text(path: Path, tmp_path: Path) -> bytes:
    """The decrypted pages of ``path`` as a plaintext file's bytes: what a reader of the copy sees."""
    out = tmp_path / "clear.db"
    connect_mod.snapshot_to_plaintext(path, out)
    return out.read_bytes()


def _rows(path: Path, sql: str):
    con = connect_mod.connect(path, key=_KEY, check_same_thread=False)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


class _Recorder:
    """A connection (or cursor) that remembers every statement and parameter it was asked to run."""

    def __init__(self, inner, log):
        self._inner, self._log = inner, log

    def execute(self, sql, params=()):
        self._log.append((sql, tuple(params)))
        return self._inner.execute(sql, params)

    def cursor(self):
        return _Recorder(self._inner.cursor(), self._log)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def statements(monkeypatch):
    log: list[tuple[str, tuple]] = []
    real = connect_mod.connect
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: _Recorder(real(*a, **k), log))
    return log


# ---------------------------------------------------------------------------------------------- #
#  the happy path: the survivors are rewritten into a fresh file
# ---------------------------------------------------------------------------------------------- #
def test_the_newsletters_go_and_the_rest_is_rewritten_into_a_fresh_file(corpus, tmp_path):
    notes: list[str] = []
    assert ne.drop_newsletters_encrypted(corpus, notes) == 3
    assert notes == [ne.NOTE_EXPORT]
    assert _rows(corpus, "SELECT id FROM articles ORDER BY id") == [(200,), (201,), (202,)]
    assert _rows(corpus, "SELECT DISTINCT article_id FROM keyword_mentions ORDER BY 1") == [(200,), (201,), (202,)]
    assert _rows(corpus, "SELECT version_num FROM alembic_version") == [("rev-1",)]
    assert not list(tmp_path.glob("*.fresh*")), "the fresh file was renamed over the copy"
    assert connect_mod.is_encrypted_file(corpus) is True


def test_the_survivors_stay_searchable(corpus):
    ne.drop_newsletters_encrypted(corpus, [])
    assert _rows(corpus, "SELECT rowid FROM article_fts WHERE article_fts MATCH 'keepword1'") == [(201,)]


def test_the_cipher_settings_of_the_source_carry_over(corpus):
    before = dict(ne._read_settings(connect_mod.connect(corpus, key=_KEY)))
    ne.drop_newsletters_encrypted(corpus, [])
    con = connect_mod.connect(corpus, key=_KEY)
    try:
        assert ne._read_settings(con) == before
    finally:
        con.close()
    assert before["cipher_page_size"] == 16384, "the fixture is the app's own page size"


def test_a_copy_with_no_newsletters_is_left_exactly_as_it_was(tmp_path):
    connect_mod.set_passphrase(_KEY)
    try:
        path = tmp_path / "c.db.sqlcipher"
        _build(path, newsletters=0)
        before = path.read_bytes()
        notes: list[str] = []
        assert ne.drop_newsletters_encrypted(path, notes) == 0
        assert notes == [] and path.read_bytes() == before
        assert not list(tmp_path.glob("*.fresh*"))
    finally:
        connect_mod.set_passphrase(None)


# ---------------------------------------------------------------------------------------------- #
#  the search index forgets the words (MUTATION TARGET: the ``_merge_fts_index`` call)
# ---------------------------------------------------------------------------------------------- #
def test_no_deleted_word_survives_in_the_decrypted_copy(corpus, tmp_path):
    assert _MARK in _clear_text(corpus, tmp_path), "the control: the words are in the copy before"
    ne.drop_newsletters_encrypted(corpus, [])
    assert _MARK not in _clear_text(corpus, tmp_path)


def test_no_deleted_word_survives_on_the_secure_delete_path_either(corpus, tmp_path, monkeypatch):
    def refuse(*_a, **_k):
        raise RuntimeError("no room")

    monkeypatch.setattr(ne, "_export_to", refuse)
    notes: list[str] = []
    ne.drop_newsletters_encrypted(corpus, notes)
    assert notes and "secure delete" in notes[0]
    assert _MARK not in _clear_text(corpus, tmp_path)


# ---------------------------------------------------------------------------------------------- #
#  condition 1: the key is bound, and appears in no statement text, exception, log line or note
# ---------------------------------------------------------------------------------------------- #
def test_the_key_is_bound_and_never_in_the_text_of_a_statement(corpus, statements):
    ne.drop_newsletters_encrypted(corpus, [])
    assert statements, "the spy saw nothing"
    assert not [s for s, _p in statements if _KEY in s], "the key is in SQL text"
    attach = [(s, p) for s, p in statements if s.lstrip().upper().startswith("ATTACH")]
    assert len(attach) == 1 and attach[0][1][1] == _KEY and "?" in attach[0][0]


def test_a_failure_that_quotes_the_key_reaches_no_log_note_or_exception(corpus, caplog, monkeypatch):
    def leaky(*_a, **_k):
        raise RuntimeError(f"the driver said: ATTACH ... KEY '{_KEY}' failed")

    monkeypatch.setattr(ne, "_export_to", leaky)
    notes: list[str] = []
    with caplog.at_level(logging.DEBUG):
        ne.drop_newsletters_encrypted(corpus, notes)  # no exception: the other path ran
    assert _KEY not in caplog.text and _KEY not in " ".join(notes)
    assert "RuntimeError" in notes[0], "the note names the class so the path that ran is visible"
    assert caplog.text, "the failure was logged at all"


# ---------------------------------------------------------------------------------------------- #
#  condition 2: every setting is copied, and the result is read back before it replaces the copy
# ---------------------------------------------------------------------------------------------- #
def test_every_setting_the_source_declares_is_applied_to_the_new_file(tmp_path):
    """A source at non-default settings, exported by ``_export_to`` alone: the result opens only with
    the SAME settings, so a setting left off would read as a wrong key."""
    from sqlcipher3 import dbapi2 as sqc

    src, out = tmp_path / "src.db", tmp_path / "out.db"
    con = sqc.connect(str(src))
    con.execute(f"PRAGMA key = '{_KEY}'")
    for pragma in ("cipher_page_size = 8192", "kdf_iter = 64000", "cipher_hmac_algorithm = 'HMAC_SHA256'"):
        con.execute(f"PRAGMA {pragma}")
    con.execute("CREATE TABLE t (a)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    settings = ne._read_settings(con)
    assert settings["kdf_iter"] == 64000 and settings["cipher_hmac_algorithm"] == "HMAC_SHA256"
    ne._export_to(con, out, _KEY, settings)
    con.close()

    new = sqc.connect(str(out))
    new.execute(f"PRAGMA key = '{_KEY}'")
    for pragma in ("cipher_page_size = 8192", "kdf_iter = 64000", "cipher_hmac_algorithm = 'HMAC_SHA256'"):
        new.execute(f"PRAGMA {pragma}")
    assert new.execute("SELECT a FROM t").fetchall() == [(1,)]
    assert ne._read_settings(new) == settings
    new.close()


def test_a_new_file_whose_settings_differ_from_the_source_is_refused(corpus):
    con = connect_mod.connect(corpus, key=_KEY)
    settings = ne._read_settings(con)
    shape = ne._shape(con)
    con.close()
    with pytest.raises(ne._ExportRefused, match="cipher_page_size"):
        ne._read_back(corpus, _KEY, {**settings, "cipher_page_size": 4096}, shape)


def test_a_new_file_that_is_not_the_filtered_copy_is_refused(corpus):
    con = connect_mod.connect(corpus, key=_KEY)
    settings = ne._read_settings(con)
    shape = ne._shape(con)
    con.close()
    with pytest.raises(ne._ExportRefused, match="articles"):
        ne._read_back(corpus, _KEY, settings, {**shape, "articles": shape["articles"] + 1})


def test_a_plaintext_header_is_refused_rather_than_exported_without_its_salt(corpus, monkeypatch):
    real = ne._pragma
    monkeypatch.setattr(ne, "_pragma", lambda con, n: 32 if n == "cipher_plaintext_header_size" else real(con, n))
    con = connect_mod.connect(corpus, key=_KEY)
    try:
        with pytest.raises(ne._ExportRefused, match="plaintext header"):
            ne._read_settings(con)
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------- #
#  condition 3: any failure takes the secure-delete path, leaves no partial file, and says so
# ---------------------------------------------------------------------------------------------- #
def test_a_failed_export_leaves_the_filtered_copy_and_no_partial_file(corpus, tmp_path, monkeypatch):
    def half_written(_con, out, _key, _settings):
        out.write_bytes(b"half a file")
        Path(str(out) + "-journal").write_bytes(b"x")
        raise OSError("disk full")

    monkeypatch.setattr(ne, "_export_to", half_written)
    notes: list[str] = []
    assert ne.drop_newsletters_encrypted(corpus, notes) == 3
    assert len(notes) == 1 and notes[0].startswith("newsletters excluded by secure delete") and "OSError" in notes[0]
    assert not list(tmp_path.glob("*.fresh*")), "a partial file was left"
    assert _rows(corpus, "SELECT id FROM articles ORDER BY id") == [(200,), (201,), (202,)]


def test_a_read_back_that_refuses_leaves_the_copy_as_it_was(corpus, tmp_path, monkeypatch):
    def refuse(*_a, **_k):
        raise ne._ExportRefused("differs")

    monkeypatch.setattr(ne, "_read_back", refuse)
    notes: list[str] = []
    ne.drop_newsletters_encrypted(corpus, notes)
    assert "secure delete" in notes[0] and "_ExportRefused" in notes[0]
    assert not list(tmp_path.glob("*.fresh*"))
    assert _rows(corpus, "SELECT COUNT(*) FROM articles") == [(3,)], "the refused file did not replace the copy"


def test_the_deleting_runs_with_secure_delete_on(corpus, statements):
    ne.drop_newsletters_encrypted(corpus, [])
    texts = [s for s, _p in statements]
    on = next(i for i, s in enumerate(texts) if "secure_delete" in s and "ON" in s.upper())
    first_delete = next(i for i, s in enumerate(texts) if s.lstrip().upper().startswith("DELETE"))
    assert on < first_delete


def test_a_search_index_that_cannot_be_merged_stops_the_backup_instead_of_keeping_the_words(
    corpus, monkeypatch
):
    import src.backup.artifact as art

    def boom(_con):
        raise RuntimeError("index busy")

    monkeypatch.setattr(art, "_merge_fts_index", boom)
    with pytest.raises(RuntimeError, match="index busy"):
        ne.drop_newsletters_encrypted(corpus, [])


# ---------------------------------------------------------------------------------------------- #
#  the wiring in stream_backup, and condition 4 (the space check counts the copy AND its rewrite)
# ---------------------------------------------------------------------------------------------- #
def test_stream_backup_sends_an_encrypted_copy_to_the_rewrite_and_a_plain_one_to_vacuum(
    corpus, tmp_path, monkeypatch
):
    import sqlite3

    from src.backup import stream_backup as sb

    notes: list[str] = []
    assert sb._drop_newsletters_in_file(corpus, notes) == 3
    assert notes == [ne.NOTE_EXPORT]

    plain = tmp_path / "plain.db"
    con = sqlite3.connect(plain)
    con.executescript(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER);"
    )
    con.execute("INSERT INTO sources VALUES (1, ?)", (_NEWSLETTER_DOMAINS[0],))
    con.execute("INSERT INTO articles VALUES (1, 1)")
    con.commit()
    con.close()
    notes = []
    assert sb._drop_newsletters_in_file(plain, notes) == 1 and notes == []


@pytest.mark.parametrize("side", [0, 40 * 2**20, 10 * 2**30])
@pytest.mark.parametrize("credit", [0, 10**12])
def test_the_space_check_asks_for_the_copy_and_its_rewrite_at_the_least(side, credit, monkeypatch):
    """The rewrite sits beside the copy before the volumes exist, so the bound must reach two copies.
    It does today because the volume set is sized from the copy plus parity; this keeps it so."""
    from src.backup import artifact as art
    from src.backup import stream_backup as sb

    seen: list[int] = []
    monkeypatch.setattr(art, "preflight_free_space", lambda _d, needed, what="": seen.append(needed))
    copy = 50 * 2**30
    sb._preflight_snapshot(Path("."), copy, side, 0.1, credit=credit)
    assert seen and seen[0] >= 2 * copy, seen
