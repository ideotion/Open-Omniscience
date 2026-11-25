"""R826 / R828 (row 402, for the split corpus's stage 2): the public helpers that name a corpus segment in the at-rest record
(``record_segment``) and drop it again (``forget_segment``). An entry is written only for a ``seg-<n>.db`` in the data folder's own
``corpus`` folder that this process holds open under a key; every other name, a link, and a path outside that folder are refused,
and a refusal changes nothing."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database.connect import connect, have_driver
from src.safety import crypto_erase

_PW = "row-402-r826-segment-test-passphrase"
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="links and the segment sweep (POSIX)")


@pytest.fixture()
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "OOS data"
    (d / "corpus").mkdir(parents=True)
    _empty_record(d)
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    return d


def _empty_record(d: Path) -> None:
    """The record the corpus's encryption wrote (``record_encrypted``): the helpers never create one."""
    (d / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")


def _main(data: Path) -> Path:
    return data / "open_omniscience.db"


def _record(data: Path) -> dict:
    rec = data / at_rest_state.RECORD_NAME
    return json.loads(rec.read_text(encoding="utf-8")) if rec.exists() else {}


def _stores(data: Path) -> dict:
    return _record(data).get("stores") or {}


def _encrypted(path: Path):
    """A segment created and read back under the key; the connection is returned OPEN (the helper needs it held)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("segment-row" * 40,)] * 100)
    con.commit()
    con.close()
    con = connect(path, key=_PW)  # the keyed read back: a fresh file is noted only by its first keyed reopen
    con.execute("SELECT count(*) FROM t").fetchone()
    return con


def _keyed(monkeypatch) -> None:
    import src.database.connect as connect_module

    monkeypatch.setattr(connect_module, "opened_with_key", lambda ident: True)


@posix_only
@sqlcipher_only
def test_a_keyed_segment_is_named_and_an_erase_then_destroys_only_its_page_one(data):
    seg = data / "corpus" / "seg-1.db"
    con = _encrypted(seg)
    try:
        assert at_rest_state.record_segment(seg, main=_main(data)) is True
    finally:
        con.close()
    doc = _record(data)
    entry = doc["stores"]["corpus:seg-1"]
    assert set(entry) >= {"dev", "ino", "mac", "read_back_with_key"}
    salt = seg.read_bytes()[:16]
    raw = (data / at_rest_state.RECORD_NAME).read_bytes()
    assert salt not in raw and salt.hex().encode() not in raw, "R828 (1): never a byte of the segment's page 1"
    fd = os.open(seg, os.O_RDONLY)
    before = seg.read_bytes()
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
        after = os.pread(fd, len(before), 0)
    finally:
        os.close(fd)
    assert report["corpus_segments"]["destroyed"] == 1 and report["corpus_segments"]["overwritten"] == 0
    assert after[:4096] != before[:4096] and after[4096:] == before[4096:]


@sqlcipher_only
def test_a_segment_no_longer_held_under_a_key_is_never_named(data):
    seg = data / "corpus" / "seg-2.db"
    _encrypted(seg).close()
    assert at_rest_state.record_segment(seg, main=_main(data)) is False
    assert not _stores(data)


def test_a_plaintext_segment_is_never_named(data, monkeypatch):
    import sqlite3

    seg = data / "corpus" / "seg-3.db"
    con = sqlite3.connect(seg)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    _keyed(monkeypatch)
    assert at_rest_state.record_segment(seg, main=_main(data)) is False
    assert not _stores(data)


@pytest.mark.parametrize("name", ["seg-0.db", "seg-01.db", "seg-12345.db", "seg-1.db-wal", "seg-1.db-journal", "seg-1",
                                  "open_omniscience.db", "seg-1.DB", "x-seg-1.db"])
def test_any_other_name_is_refused(data, monkeypatch, name):
    p = data / "corpus" / name
    p.write_bytes(os.urandom(8192))
    _keyed(monkeypatch)
    assert at_rest_state.record_segment(p, main=_main(data)) is False
    assert at_rest_state.forget_segment(p, main=_main(data)) is False
    assert not _stores(data)


@posix_only
def test_a_link_at_the_segment_s_name_is_refused(data, monkeypatch):
    target = data / "elsewhere.db"
    target.write_bytes(os.urandom(8192))
    link = data / "corpus" / "seg-4.db"
    link.symlink_to(target)
    _keyed(monkeypatch)
    assert at_rest_state.record_segment(link, main=_main(data)) is False
    assert at_rest_state.forget_segment(link, main=_main(data)) is False
    assert not _stores(data)


@posix_only
def test_a_segment_with_a_second_name_is_refused(data, monkeypatch):
    seg = data / "corpus" / "seg-5.db"
    seg.write_bytes(os.urandom(8192))
    os.link(seg, data / "other-name.db")
    _keyed(monkeypatch)
    assert at_rest_state.record_segment(seg, main=_main(data)) is False
    assert not _stores(data)


@posix_only
def test_a_link_at_the_corpus_folder_s_name_is_refused(tmp_path, monkeypatch):
    d = tmp_path / "OOS data"
    real = tmp_path / "real corpus"
    real.mkdir()
    d.mkdir()
    (d / "corpus").symlink_to(real, target_is_directory=True)
    _empty_record(d)
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    seg = real / "seg-6.db"
    seg.write_bytes(os.urandom(8192))
    _keyed(monkeypatch)
    for p in (d / "corpus" / "seg-6.db", seg):
        assert at_rest_state.record_segment(p, main=_main(d)) is False
        assert at_rest_state.forget_segment(p, main=_main(d)) is False
    assert not _stores(d)


@pytest.mark.parametrize("where", ["data", "other/corpus", "corpus/sub"])
def test_a_path_outside_the_data_folder_s_corpus_folder_is_refused(data, tmp_path, monkeypatch, where):
    folder = (data if where != "other/corpus" else tmp_path) / where if where != "data" else data
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "seg-7.db"
    p.write_bytes(os.urandom(8192))
    _keyed(monkeypatch)
    assert at_rest_state.record_segment(p, main=_main(data)) is False
    assert at_rest_state.forget_segment(p, main=_main(data)) is False
    assert not _stores(data)


@sqlcipher_only
def test_forget_drops_the_entry_whether_the_file_is_still_there_or_not(data):
    s8, s9 = data / "corpus" / "seg-8.db", data / "corpus" / "seg-9.db"
    c8, c9 = _encrypted(s8), _encrypted(s9)
    try:
        assert at_rest_state.record_segment(s8, main=_main(data))
        assert at_rest_state.record_segment(s9, main=_main(data))
    finally:
        c8.close()
        c9.close()
    assert at_rest_state.forget_segment(s8, main=_main(data)) is True  # replaced or decrypted: the file is still there
    s9.unlink()
    assert at_rest_state.forget_segment(s9, main=_main(data)) is True  # deleted first
    assert set(_record(data)["stores"]) == set()


@sqlcipher_only
def test_neither_helper_ever_creates_the_record(data):
    (data / at_rest_state.RECORD_NAME).unlink()
    seg = data / "corpus" / "seg-1.db"
    con = _encrypted(seg)
    try:
        assert at_rest_state.record_segment(seg, main=_main(data)) is False
    finally:
        con.close()
    assert at_rest_state.forget_segment(data / "corpus" / "seg-1.db", main=_main(data)) is True
    assert not (data / at_rest_state.RECORD_NAME).exists()


def test_the_helpers_and_the_erase_agree_on_the_segment_name():
    for name in ("seg-1.db", "seg-9999.db", "seg-0.db", "seg-10000.db", "seg-1.db-wal"):
        assert bool(at_rest_state._SEGMENT_NAME.match(name)) == bool(
            crypto_erase._SEGMENT_RE.match(name) and crypto_erase._SEGMENT_RE.match(name).group(2) is None), name
    assert at_rest_state.SEGMENT_DIR == crypto_erase.CORPUS_DIR
