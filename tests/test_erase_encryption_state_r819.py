"""
Row 396 (R819/R820): the erase calls the main database "encrypted" only on positive evidence, never on a header that is not
SQLite's. In-process evidence (this process read the very file under a key) keeps the encrypted path; otherwise the store takes
the plaintext path, and the verdict is settled after its first page and log are destroyed: SQLite's own header is "not encrypted";
another header with the app's record naming this very (device, inode) is "encrypted" (no body rewrite); every other case is "could
not be determined", with the full rewrite and the fail-closed note. Three states, said on the CLI and in the HTTP answer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database import connect as connect_module
from src.database.connect import connect, have_driver
from src.safety import crypto_erase, data_scope

_PW = "row-396-test-passphrase"
WITNESS = b"R819-WITNESS-ROW-" * 64
GUARANTEE = "permanently unrecoverable"
posix_only = pytest.mark.skipif(not crypto_erase.plaintext_body_rewrite_supported(), reason="the R817 path is POSIX only")
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")


@pytest.fixture(autouse=True)
def _no_evidence_from_other_tests():
    """The in-process evidence is process-wide: each test starts with none, and leaves none."""
    with connect_module._lock:
        saved = set(connect_module._opened_with_key)
        connect_module._opened_with_key.clear()
    with at_rest_state._NOTE_LOCK:
        keyed, plain = set(at_rest_state._NOTED_KEYED), set(at_rest_state._NOTED_PLAIN)
        at_rest_state._NOTED_KEYED.clear()
        at_rest_state._NOTED_PLAIN.clear()
    yield
    with connect_module._lock:
        connect_module._opened_with_key.clear()
        connect_module._opened_with_key.update(saved)
    with at_rest_state._NOTE_LOCK:
        at_rest_state._NOTED_KEYED.clear()
        at_rest_state._NOTED_KEYED.update(keyed)
        at_rest_state._NOTED_PLAIN.clear()
        at_rest_state._NOTED_PLAIN.update(plain)


def _ident(p: Path) -> tuple[int, int]:
    st = os.stat(p)
    return (st.st_dev, st.st_ino)


def _record(folder: Path, ident: tuple[int, int] | None, **extra) -> Path:
    entry: dict = {"encrypted_at": "2026-11-24T00:00:00Z", "read_back_with_key": True, **extra}
    if ident is not None:
        entry.update(dev=ident[0], ino=ident[1])
    p = folder / at_rest_state.RECORD_NAME
    p.write_text(json.dumps({"version": 1, "stores": {"corpus": entry}}), encoding="utf-8")
    return p


def _plain_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table t(x blob)")
    for _ in range(40):
        con.execute("insert into t values (?)", (WITNESS,))
    con.commit()
    con.close()


def _encrypted_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("row" * 50,)] * 200)
    con.commit()
    con.close()


def _forget_evidence() -> None:
    with connect_module._lock:
        connect_module._opened_with_key.clear()


def _data(tmp_path: Path) -> Path:
    data = tmp_path / "OOS data"
    data.mkdir()
    return data


# ---------------------------------------------------------------- the in-process evidence (connect.py)


@sqlcipher_only
def test_a_keyed_read_is_evidence_and_a_plaintext_open_forgets_it(tmp_path):
    db = tmp_path / "store.db"
    _encrypted_db(db)
    ident = _ident(db)
    assert not connect_module.opened_with_key(ident), "creating a store is not a keyed read of it"
    connect(db, key=_PW).close()
    assert connect_module.opened_with_key(ident)
    connect_module._note_open(db, keyed=False)  # what a plaintext open of the same identity does
    assert not connect_module.opened_with_key(ident)


def test_a_plaintext_open_never_records_evidence(tmp_path):
    db = tmp_path / "plain.db"
    _plain_db(db)
    ident = _ident(db)
    with connect_module._lock:
        connect_module._opened_with_key.add(ident)  # an identity an older, encrypted file left behind
    connect(db).close()
    assert not connect_module.opened_with_key(ident)


# ---------------------------------------------------------------- the record (at_rest_state.py)


@sqlcipher_only
def test_the_record_gets_the_identity_after_a_keyed_read_and_loses_it_on_a_plaintext_open(tmp_path):
    db = tmp_path / "open_omniscience.db"
    _encrypted_db(db)
    at_rest_state.note_main_open(db)
    assert not (tmp_path / at_rest_state.RECORD_NAME).exists(), "no keyed read yet: nothing is written"
    connect(db, key=_PW).close()
    at_rest_state.note_main_open(db)
    raw = (tmp_path / at_rest_state.RECORD_NAME).read_bytes()
    assert at_rest_state.record_names_identity(raw, _ident(db))
    # the same identity, now opened as plaintext (a reused inode, a decrypted file): its identity leaves the record
    connect_module._note_open(db, keyed=False)
    at_rest_state.note_main_open(db)
    raw = (tmp_path / at_rest_state.RECORD_NAME).read_bytes()
    assert not at_rest_state.record_names_identity(raw, _ident(db))


def test_a_record_that_cannot_be_written_never_fails_the_open(tmp_path, monkeypatch):
    db = tmp_path / "open_omniscience.db"
    _plain_db(db)
    monkeypatch.setattr(connect_module, "opened_with_key", lambda ident: True)

    def boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(at_rest_state, "_write_identity", boom)
    at_rest_state.note_main_open(db)  # never raises


@pytest.mark.parametrize("case", ["none", "garbage", "old", "other", "bool", "not_read_back", "too_long", "match"])
def test_the_record_names_the_store_only_with_its_own_identity(tmp_path, case):
    ident = (12, 345)
    entry: dict = {"read_back_with_key": True, "dev": 12, "ino": 345}
    if case == "old":
        entry = {"read_back_with_key": True}  # a record from before R820: never evidence
    elif case == "other":
        entry["ino"] = 346
    elif case == "bool":
        entry["dev"] = True
    elif case == "not_read_back":
        entry["read_back_with_key"] = False
    raw = None if case == "none" else b"{not json" if case == "garbage" else json.dumps({"stores": {"corpus": entry}}).encode()
    if case == "too_long":
        raw = json.dumps({"stores": {"corpus": entry}, "pad": "x" * at_rest_state.RECORD_MAX_BYTES}).encode()
    assert at_rest_state.record_names_identity(raw, ident) is (case == "match")


def test_the_record_is_one_of_the_app_s_own_files():
    assert at_rest_state.RECORD_NAME in data_scope.APP_FILES


# ---------------------------------------------------------------- the verdict on the plaintext path (crypto_erase.py)


@posix_only
def test_a_plaintext_store_with_a_randomised_first_page_is_unknown_and_rewritten_whole(tmp_path):
    """R819 (6): a plaintext store left by a failed earlier erase (page 1 random, no record) is never called encrypted."""
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    _plain_db(main)
    with open(main, "r+b") as fh:
        fh.write(os.urandom(4096))
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["encrypted_corpus"] is None
    assert report["corpus_encryption"] == "unknown"
    assert GUARANTEE not in report["limit"]
    assert WITNESS[:34] not in kept.read_bytes(), "the body is rewritten in full"


@posix_only
@sqlcipher_only
def test_an_encrypted_store_named_by_the_record_is_encrypted_and_never_rewritten_whole(tmp_path):
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    _encrypted_db(main)
    _forget_evidence()  # another process (the CLI) holds no evidence of its own
    _record(data, _ident(main))
    body = main.read_bytes()[4096:]
    head = main.read_bytes()[:4096]
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["encrypted_corpus"] is True
    assert report["corpus_encryption"] == "encrypted"
    assert crypto_erase._MAIN_DB in report["headers_destroyed"]
    assert report.get("plaintext_store") is None
    assert kept.read_bytes()[:4096] != head, "its first page (the salt) is destroyed"
    assert kept.read_bytes()[4096:] == body, "never rewritten whole: the salt is the guarantee"
    assert not (data / at_rest_state.RECORD_NAME).exists()


@posix_only
@sqlcipher_only
def test_an_encrypted_store_without_a_record_is_unknown_and_rewritten_whole(tmp_path):
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    _encrypted_db(main)
    _forget_evidence()
    body = main.read_bytes()[4096:]
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "unknown" and report["encrypted_corpus"] is None
    assert kept.read_bytes()[4096:] != body, "could not be determined: the full rewrite runs"


@posix_only
def test_a_sqlite_header_is_not_encrypted_whatever_the_record_says(tmp_path):
    """R820 (5): a reused inode carrying a plaintext file under a matching record."""
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    _plain_db(main)
    _record(data, _ident(main))
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["encrypted_corpus"] is False and report["corpus_encryption"] == "not_encrypted"
    assert WITNESS[:34] not in kept.read_bytes()


@posix_only
def test_a_replaced_store_is_unknown_and_rewritten_whole(tmp_path):
    """R820 (5): restore, repair, encrypt or decrypt put another file at the name: the record's identity no longer matches."""
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(8192))
    _record(data, _ident(main))
    replacement = data / "incoming.db"
    replacement.write_bytes(os.urandom(4096) + WITNESS)
    os.replace(replacement, main)
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "unknown"
    assert WITNESS[:34] not in kept.read_bytes()


@posix_only
def test_a_record_that_is_a_link_is_never_followed(tmp_path):
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(4096) + WITNESS)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = _record(elsewhere, _ident(main))
    (data / at_rest_state.RECORD_NAME).symlink_to(target)
    kept = tmp_path / "kept"
    os.link(main, kept)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "unknown"
    assert WITNESS[:34] not in kept.read_bytes()
    assert target.exists(), "the link's target is never touched"


@posix_only
def test_an_oversized_record_is_not_the_app_s(tmp_path):
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(4096) + WITNESS)
    _record(data, _ident(main), pad="x" * at_rest_state.RECORD_MAX_BYTES)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "unknown"


@posix_only
def test_a_log_left_unwritten_keeps_the_verdict_unknown(tmp_path):
    """The security reads' check: "encrypted" on the plaintext path skips the body rewrite, so a log the fast destruction did not
    write whole (one with another name, never written there) leaves the verdict "could not be determined"."""
    data = _data(tmp_path)
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(4096) + WITNESS)
    wal = data / (crypto_erase._MAIN_DB + "-wal")
    wal.write_bytes(os.urandom(8192))
    os.link(wal, tmp_path / "kept-wal")
    _record(data, _ident(main))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "unknown"


def test_a_short_header_read_is_not_other():
    assert crypto_erase._header_kind(b"SQLite") is None
    assert crypto_erase._header_kind(b"SQLite format 3\x00") == "sqlite"
    assert crypto_erase._header_kind(os.urandom(16)) == "other"


@sqlcipher_only
def test_in_process_evidence_keeps_the_encrypted_path_and_destroys_the_record(tmp_path, monkeypatch):
    data = _data(tmp_path)
    main = tmp_path / "internal" / crypto_erase._MAIN_DB  # outside the data folder: the erase removes the record itself
    _encrypted_db(main)
    connect(main, key=_PW).close()
    _record(main.parent, _ident(main))
    real_resolve = crypto_erase._resolve
    monkeypatch.setattr(crypto_erase, "_resolve", lambda d: {**real_resolve(d), "main_db": main})
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] == "encrypted" and report["encrypted_corpus"] is True
    assert not (main.parent / at_rest_state.RECORD_NAME).exists()


def test_no_main_database_says_no_state(tmp_path):
    data = _data(tmp_path)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["corpus_encryption"] is None


# ---------------------------------------------------------------- the words, CLI and page


def test_the_three_states_have_words_and_the_unknown_store_is_never_called_unencrypted():
    assert set(crypto_erase.CORPUS_ENCRYPTION) == {"encrypted", "encrypted_key_left", "not_encrypted", "unknown"}
    for state in crypto_erase.PLAIN_STORE_STATE:
        words = crypto_erase.plaintext_store_sentences({"plaintext_store": {"state": state, "form": "unknown"}})
        assert words and "unencrypted" not in words[0]
    assert "unencrypted" not in crypto_erase.PLAIN_STORE_NOTICE_UNKNOWN


@pytest.mark.parametrize("state", ["encrypted", "encrypted_key_left", "not_encrypted", "unknown"])
def test_the_cli_says_the_state(state, monkeypatch, capsys, tmp_path):
    from src.api import main as api_main

    report = {"files_wiped": 0, "files_seen": 0, "data_dir": str(tmp_path), "limit": "", "corpus_encryption": state,
              "encrypted_corpus": state.startswith("encrypted") or (None if state == "unknown" else False), "other_holder": "none"}
    monkeypatch.setattr("src.safety.panic_wipe", lambda **k: report)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with contextlib.suppress(SystemExit):
        api_main._panic_cli(force=True)
    assert crypto_erase.CORPUS_ENCRYPTION[state] in capsys.readouterr().out


def test_the_page_says_the_state_and_never_calls_an_unknown_store_unencrypted():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    for words in crypto_erase.CORPUS_ENCRYPTION.values():
        assert json.dumps(words) in js
    for words in crypto_erase.PLAIN_STORE_STATE_UNKNOWN.values():
        assert json.dumps(words) in js
    assert "r.corpus_encryption" in js and 'ps.form === "unknown"' in js
