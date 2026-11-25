"""R823 (row 402): a copy of a store beside it is head-only, and called destroyed, only with evidence: a header that is not SQLite's
AND the record entry its writer bound to that very file (device, inode and a MAC of its own first 16 bytes). Everything else is
rewritten in full and said "overwritten", by count and kind. R826: the same rule for the split corpus's segments in
<data>/corpus, where anything that is not a segment is left and counted."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database.connect import connect, have_driver
from src.safety import crypto_erase

_PW = "row-402-r823-test-passphrase"
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="the segment sweep keeps descriptors through a folder handle (POSIX)")
_SNAP = "pre-restore-20261124T101010Z.db"


def _encrypted(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("secret-row" * 40,)] * 100)
    con.commit()
    con.close()


def _plaintext(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("plaintext-row" * 40,)] * 100)
    con.commit()
    con.close()


def _keyed(monkeypatch) -> None:
    import src.database.connect as connect_module

    monkeypatch.setattr(connect_module, "opened_with_key", lambda ident: True)


class _Kept:
    def __init__(self, path: Path) -> None:
        self.fd = os.open(path, os.O_RDONLY)
        self.before = path.read_bytes()

    def read(self) -> bytes:
        return os.pread(self.fd, len(self.before), 0)

    def close(self) -> None:
        os.close(self.fd)


def _erase(data: Path) -> dict:
    return crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)


# ---------------------------------------------------------------- the writer's entry


@sqlcipher_only
def test_the_writer_names_a_copy_only_of_a_keyed_source_with_its_very_salt(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    assert at_rest_state.record_copy(snap, main, "corpus") is False, "no keyed source in this process, no record: no entry"
    _keyed(monkeypatch)
    other = tmp_path / "pre-restore-20261124T111111Z.db"
    other.write_bytes(os.urandom(16) + main.read_bytes()[16:])
    assert at_rest_state.record_copy(other, main, "corpus") is False, "another first 16 bytes: not a copy of this source"
    assert at_rest_state.record_copy(snap, main, "corpus") is True
    raw = (tmp_path / at_rest_state.RECORD_NAME).read_text(encoding="utf-8")
    entry = json.loads(raw)["stores"][at_rest_state.copy_key(snap)]
    assert set(entry) == {"encrypted_at", "read_back_with_key", "copy_of", "dev", "ino", "mac"}
    assert main.read_bytes()[:16].hex() not in raw, "never the salt (R828 (1))"


def test_a_plaintext_copy_is_never_named(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _plaintext(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    assert at_rest_state.record_copy(snap, main, "corpus") is False
    assert not (tmp_path / at_rest_state.RECORD_NAME).exists()


# ---------------------------------------------------------------- the erase


@sqlcipher_only
def test_a_named_encrypted_copy_is_head_only_and_destroyed(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    assert at_rest_state.record_copy(snap, main, "corpus")
    kept = _Kept(snap)
    try:
        report = _erase(tmp_path)
        after = kept.read()
    finally:
        kept.close()
    assert report["copies_destroyed"] == {"pre-restore": 1} and not report["copies_overwritten"]
    assert after[:4096] != kept.before[:4096] and after[4096:] == kept.before[4096:], "page 1 only: the body is noise already"


def test_a_damaged_plaintext_copy_with_a_randomised_page_one_is_rewritten_whole(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / "open_omniscience.damaged-20261124T101010Z.db"
    _plaintext(main)
    _plaintext(snap)
    body = snap.read_bytes()
    snap.write_bytes(os.urandom(4096) + body[4096:])  # page 1 randomised (a failed erase): looks encrypted, is not
    _keyed(monkeypatch)  # the main store "being encrypted" is never evidence for a copy either
    kept = _Kept(snap)
    try:
        report = _erase(tmp_path)
        after = kept.read()
    finally:
        kept.close()
    assert report["copies_overwritten"] == {"damaged": 1} and not report["copies_destroyed"]
    assert b"plaintext-row" not in after


@sqlcipher_only
def test_a_replaced_copy_under_a_stale_record_is_rewritten_whole(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    assert at_rest_state.record_copy(snap, main, "corpus")
    snap.unlink()
    _plaintext(snap)  # another file at the copy's name: the record's entry names the old one
    body = snap.read_bytes()
    snap.write_bytes(os.urandom(16) + body[16:])
    kept = _Kept(snap)
    try:
        report = _erase(tmp_path)
        after = kept.read()
    finally:
        kept.close()
    assert report["copies_overwritten"] == {"pre-restore": 1} and not report["copies_destroyed"]
    assert b"plaintext-row" not in after


@sqlcipher_only
def test_inode_reuse_under_a_stale_entry_is_no_evidence(tmp_path, monkeypatch):
    """A file that takes the copy's very (device, inode) later still has other first bytes: the MAC does not match."""
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    assert at_rest_state.record_copy(snap, main, "corpus")
    st = os.stat(snap)
    with open(snap, "r+b") as f:  # the same inode, new contents: what a reused inode looks like to the record
        f.write(os.urandom(16))
    assert os.stat(snap).st_ino == st.st_ino
    report = _erase(tmp_path)
    assert report["copies_overwritten"] == {"pre-restore": 1} and not report["copies_destroyed"]


# ---------------------------------------------------------------- R826: the split corpus


def _segment_entry(data: Path, seg: Path) -> None:
    """Stage 2's write on a segment's first keyed open: the record beside the corpus names it."""
    rec = data / at_rest_state.RECORD_NAME
    doc = json.loads(rec.read_text(encoding="utf-8")) if rec.exists() else {"version": 1, "stores": {}}
    mark = at_rest_state._mark(seg)
    assert mark is not None
    doc.setdefault("binding_key", os.urandom(32).hex())
    entry = at_rest_state._bound_entry(doc, mark)
    entry.update(read_back_with_key=True)
    doc["stores"][at_rest_state.SEGMENT_PREFIX + seg.name.removesuffix(".db")] = entry
    rec.write_text(json.dumps(doc), encoding="utf-8")


@posix_only
@sqlcipher_only
def test_segments_with_evidence_are_destroyed_and_without_are_rewritten_whole(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    s1, s2 = corpus / "seg-1.db", corpus / "seg-2.db"
    _encrypted(s1)
    _encrypted(s2)
    (corpus / "seg-2.db-wal").write_bytes(os.urandom(32 * 1024))
    _segment_entry(data, s1)  # only seg-1 is named
    k1, k2 = _Kept(s1), _Kept(s2)
    try:
        report = _erase(data)
        a1, a2 = k1.read(), k2.read()
    finally:
        k1.close()
        k2.close()
    seg = report["corpus_segments"]
    assert seg["destroyed"] == 2 and seg["overwritten"] == 1, seg  # seg-1 and seg-2's log; seg-2 whole
    assert seg["corpus"] == "overwritten" and seg["foreign"] == 0
    assert a1[4096:] == k1.before[4096:] and a1[:4096] != k1.before[:4096], "with evidence: page 1 only"
    assert a2[4096:] != k2.before[4096:], "without: every byte"
    assert "Parts of the split corpus that could not be shown to be encrypted were overwritten in full" in report["limit"]
    assert not data.exists()


@posix_only
def test_a_plaintext_segment_with_a_randomised_page_one_is_rewritten_whole(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    seg = corpus / "seg-3.db"
    _plaintext(seg)
    seg.write_bytes(os.urandom(4096) + seg.read_bytes()[4096:])
    kept = _Kept(seg)
    try:
        report = _erase(data)
        after = kept.read()
    finally:
        kept.close()
    assert report["corpus_segments"]["overwritten"] == 1 and report["corpus_segments"]["corpus"] == "overwritten"
    assert b"plaintext-row" not in after


@posix_only
@sqlcipher_only
def test_items_in_corpus_that_are_not_segments_are_left_counted_and_never_named(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    s1 = corpus / "seg-1.db"
    _encrypted(s1)
    _segment_entry(data, s1)
    mine = corpus / "my-notes.txt"
    mine.write_bytes(b"the operator's own")
    (corpus / "seg-0.db").write_bytes(b"not a segment name (n from 1)")
    (corpus / "sub").mkdir()
    report = _erase(data)
    assert mine.read_bytes() == b"the operator's own" and (corpus / "seg-0.db").exists() and (corpus / "sub").is_dir()
    assert not s1.exists()
    seg = report["corpus_segments"]
    assert seg["foreign"] == 3 and seg["destroyed"] == 1 and seg["corpus"] == "destroyed"
    assert report["folder_kept_foreign"] is True and report["kept_items"] >= 3
    flat = json.dumps(report, default=str)
    assert "my-notes" not in flat
    assert sorted(p.name for p in data.iterdir()) == ["corpus"], "every other entry of the data folder goes"


@posix_only
def test_a_link_at_a_segment_s_name_is_never_followed(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    target = tmp_path / "elsewhere.db"
    target.write_bytes(b"x" * 8192)
    (corpus / "seg-1.db").symlink_to(target)
    report = _erase(data)
    assert target.read_bytes() == b"x" * 8192
    assert report["corpus_segments"]["left"] == 1 and report["corpus_segments"]["corpus"] == "not_overwritten"
    assert "Parts of the split corpus could not be overwritten, or only partially" in report["limit"]


@posix_only
def test_the_registry_and_the_folder_name_are_never_evidence(tmp_path, monkeypatch):
    """No record entry: an encrypted-looking segment is rewritten whole, whatever else says it is the app's."""
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    seg = corpus / "seg-7.db"
    seg.write_bytes(os.urandom(16384))
    _keyed(monkeypatch)
    report = _erase(data)
    assert report["corpus_segments"]["overwritten"] == 1 and report["corpus_segments"]["destroyed"] == 0


def test_the_copy_and_segment_sentences_are_in_every_locale():
    root = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    for key in (crypto_erase._COPIES_OVERWRITTEN_SENTENCE, crypto_erase._COPIES_SHORT_SENTENCE,
                crypto_erase._SEGMENTS_OVERWRITTEN_SENTENCE, crypto_erase._SEGMENTS_SHORT_SENTENCE):
        for f in root.glob("*.json"):
            doc = json.loads(f.read_text(encoding="utf-8"))
            assert key in doc and "{n}" in doc[key], (f.name, key)
