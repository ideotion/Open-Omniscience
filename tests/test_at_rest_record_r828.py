"""R828: the at-rest record keeps a MAC, never page 1's bytes (1); the erase overwrites and unlinks it in its key-material pass,
before any bulk work, and says "key material may remain" when it cannot (2); it is excluded from every backup, export,
field-data file and diagnostic bundle (3); an entry goes when its file is erased, replaced or decrypted (4)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database import connect as connect_module
from src.database.connect import connect, have_driver
from src.safety import crypto_erase

_PW = "row-400-r828-test-passphrase"

posix_only = pytest.mark.skipif(not crypto_erase.plaintext_body_rewrite_supported(), reason="the R817 path is POSIX only")
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
_ROOT = Path(__file__).resolve().parent.parent


def _encrypted_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("row" * 50,)] * 200)
    con.commit()
    con.close()


def _ident(p: Path) -> tuple[int, int]:
    st = os.stat(p)
    return (st.st_dev, st.st_ino)


def _record(main: Path) -> Path:
    key = os.urandom(32)
    entry = {"encrypted_at": "2026-11-24T00:00:00Z", "read_back_with_key": True, "dev": _ident(main)[0], "ino": _ident(main)[1],
             "mac": at_rest_state._mac(key, main.read_bytes()[:16])}
    p = main.parent / at_rest_state.RECORD_NAME
    p.write_text(json.dumps({"version": 1, "binding_key": key.hex(), "stores": {"corpus": entry}}), encoding="utf-8")
    return p


def _forget_evidence() -> None:
    with connect_module._lock:
        connect_module._opened_with_key.clear()
        connect_module._opened_plain.clear()


# ---------------------------------------------------------------- (1) a MAC, never the bytes


def test_the_mac_needs_the_bytes_and_never_holds_them():
    key, head = os.urandom(32), os.urandom(16)
    mac = at_rest_state._mac(key, head)
    assert len(bytes.fromhex(mac)) == 32 and head.hex() not in mac
    assert mac == at_rest_state._mac(key, head) and mac != at_rest_state._mac(os.urandom(32), head)
    assert mac != at_rest_state._mac(key, os.urandom(16))


@sqlcipher_only
def test_a_keyed_open_writes_no_byte_of_page_one(tmp_path):
    db = tmp_path / "open_omniscience.db"
    _encrypted_db(db)
    connect(db, key=_PW).close()
    at_rest_state.note_main_open(db)
    raw = (tmp_path / at_rest_state.RECORD_NAME).read_text(encoding="utf-8")
    doc = json.loads(raw)
    page1 = db.read_bytes()[:4096]
    for start in range(0, 16):  # not the salt, nor any 4-byte run of it, in any case
        assert page1[start:start + 4].hex() not in raw.lower()
    entry = doc["stores"]["corpus"]
    assert set(entry) == {"encrypted_at", "read_back_with_key", "dev", "ino", "mac"} and "head" not in entry
    assert at_rest_state.record_names_identity(raw.encode(), _ident(db), page1[:16])


# ---------------------------------------------------------------- (2) the erase's key-material pass


def test_the_record_is_overwritten_before_it_is_unlinked(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    before = b'{"version": 1, "binding_key": "' + os.urandom(32).hex().encode() + b'", "stores": {}}'
    rec.write_bytes(before)
    kept = tmp_path / "kept"
    os.link(rec, kept)  # a second name sees what was written over the first
    raw, outcome = crypto_erase._take_record(folder)
    assert raw == before and outcome == "destroyed"
    assert not rec.exists() and kept.read_bytes() != before and len(kept.read_bytes()) == len(before)


def test_a_record_that_cannot_be_overwritten_is_left_never_destroyed(tmp_path, monkeypatch):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    rec.write_bytes(b"{}")
    real_open = os.open

    def refuse(path, flags, *a, **k):
        if str(path).endswith(at_rest_state.RECORD_NAME) and flags & os.O_RDWR:
            raise PermissionError("read-only")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", refuse)
    assert crypto_erase._take_record(folder)[1] == "left"
    assert rec.exists()


def test_a_record_that_cannot_be_unlinked_is_left_never_destroyed(tmp_path, monkeypatch):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    rec.write_bytes(b'{"stores": {}}')
    real_unlink = os.unlink

    def refuse(path, *a, **k):
        if str(path).endswith(at_rest_state.RECORD_NAME):
            raise PermissionError("busy")
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", refuse)
    raw, outcome = crypto_erase._take_record(folder)
    assert outcome == "left" and raw == b'{"stores": {}}'
    assert rec.read_bytes() != b'{"stores": {}}', "overwritten all the same"


def test_a_link_at_the_record_s_name_is_never_written(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_bytes(b"{}")
    (folder / at_rest_state.RECORD_NAME).symlink_to(target)
    assert crypto_erase._take_record(folder) == (None, "absent")
    assert target.read_bytes() == b"{}"


def test_no_record_is_absent_and_nothing_is_created(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    assert crypto_erase._take_record(folder) == (None, "absent")
    assert list(folder.iterdir()) == []


@sqlcipher_only
def test_the_erase_destroys_the_record_before_the_keys_and_the_bulk_steps(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    _encrypted_db(main)
    _forget_evidence()
    rec = _record(main)
    before = rec.read_bytes()
    kept = tmp_path / "kept"
    os.link(rec, kept)
    seen: list[bool] = []
    real_keys = crypto_erase._destroy_keys_folder

    def keys_step(*a, **k):
        seen.append(rec.exists())
        return real_keys(*a, **k)

    monkeypatch.setattr(crypto_erase, "_destroy_keys_folder", keys_step)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert seen == [False], "gone before the key files, so before every bulk step after them"
    assert report["at_rest_record"] == "destroyed" and report["corpus_encryption"] == "encrypted"
    assert kept.read_bytes() != before


@posix_only
def test_the_plaintext_path_destroys_the_record_with_the_first_page(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(8192))
    rec = main.parent / at_rest_state.RECORD_NAME
    rec.write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    before = rec.read_bytes()
    kept = tmp_path / "kept"
    os.link(rec, kept)
    seen: list[bool] = []
    real_rewrite = crypto_erase._rewrite_plain

    def rewrite(*a, **k):
        seen.append(rec.exists() or kept.read_bytes() == before)
        return real_rewrite(*a, **k)

    monkeypatch.setattr(crypto_erase, "_rewrite_plain", rewrite)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["at_rest_record"] == "destroyed"
    assert kept.read_bytes() != before
    assert seen and True not in seen, "never still there when the body rewrite (the bulk work) runs"


def test_a_record_left_says_key_material_may_remain_and_is_never_clean(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(8192))
    monkeypatch.setattr(crypto_erase, "_take_record", lambda folder, dfd=None: (None, "left"))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["at_rest_record"] == "left"
    assert "key material may remain" in report["limit"]
    assert "permanently unrecoverable" not in report["limit"]
    js = (_ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert 'const recordLeft = r.at_rest_record === "left";' in js and "&& !recordLeft;" in js
    assert "so key material may remain on the disk: the erase may be incomplete." in js


def test_the_record_left_sentence_is_in_every_locale():
    key = ("The app’s at-rest record could not be overwritten and removed, so key material may remain on the disk: the erase may be "
           "incomplete.")
    for f in (_ROOT / "src" / "static" / "locales").glob("*.json"):
        assert json.loads(f.read_text(encoding="utf-8")).get(key), f.name
