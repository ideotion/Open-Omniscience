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
from tests.os_scope import scope_os

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


def _empty_record(d: Path) -> None:
    """The record the store's encryption wrote (``record_encrypted``): the copy writer never creates one."""
    (d / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")


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
    assert at_rest_state.record_copy(snap, main, "corpus") is False, "never creates the record (security reads, row 402)"
    assert not (tmp_path / at_rest_state.RECORD_NAME).exists()
    _empty_record(tmp_path)
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
    _empty_record(tmp_path)
    assert at_rest_state.record_copy(snap, main, "corpus") is False
    assert json.loads((tmp_path / at_rest_state.RECORD_NAME).read_text(encoding="utf-8"))["stores"] == {}


# ---------------------------------------------------------------- the erase


@sqlcipher_only
def test_a_named_encrypted_copy_is_head_only_and_destroyed(tmp_path, monkeypatch):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    _empty_record(tmp_path)
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
    _empty_record(tmp_path)
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
    _empty_record(tmp_path)
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
    assert seg["destroyed"] == 1 and seg["overwritten"] == 2, seg  # seg-1; seg-2 whole and its log (no evidence: never "destroyed")
    assert seg["corpus"] == "overwritten" and seg["foreign"] == 0
    assert a1[4096:] == k1.before[4096:] and a1[:4096] != k1.before[:4096], "with evidence: page 1 only"
    assert a2[4096:] != k2.before[4096:], "without: every byte"
    assert "Corpus files that could not be shown to be encrypted were overwritten in full" in report["limit"]
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
    assert "Some corpus files could not be overwritten, or only partially" in report["limit"]


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


# ---------------------------------------------------------------- the two security reads of row 402


def test_a_copy_with_a_second_name_is_never_written_and_said_not_overwritten(tmp_path):
    """Writing through a copy that has another name would reach that file, which may not be the app's."""
    main, snap = tmp_path / "open_omniscience.db", tmp_path / "open_omniscience.salvage-20261124T101010Z.db"
    _plaintext(main)
    _plaintext(snap)
    other = tmp_path.parent / f"{tmp_path.name}-operator-file.db"
    os.link(snap, other)
    before = other.read_bytes()
    report = _erase(tmp_path)
    assert other.read_bytes() == before, "never written through its other name"
    assert report["copies_not_overwritten"] == {"salvage": 1} and not report["copies_destroyed"]
    assert snap.name not in json.dumps(report, default=str), "count and kind only, never a copy's name"
    other.unlink()


@sqlcipher_only
def test_a_copy_swapped_after_the_evidence_read_is_never_head_only(tmp_path, monkeypatch):
    """The evidence, the identity and the page-1 write go through one descriptor: a file renamed onto the name later is not it."""
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    _keyed(monkeypatch)
    _empty_record(tmp_path)
    assert at_rest_state.record_copy(snap, main, "corpus")
    real = crypto_erase._copy_take
    swapped = tmp_path.parent / f"{tmp_path.name}-swapped.db"

    def take(p, raws, generation, *, side=False):
        if p.name == _SNAP:
            _plaintext(swapped)
            os.replace(swapped, p)  # a plaintext file takes the name before the erase opens it
        return real(p, raws, generation, side=side)

    monkeypatch.setattr(crypto_erase, "_copy_take", take)
    report = _erase(tmp_path)
    assert report["copies_overwritten"] == {"pre-restore": 1} and not report["copies_destroyed"]


def test_a_plaintext_copy_s_log_is_rewritten_whole_and_said_overwritten(tmp_path):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / _SNAP
    _plaintext(main)
    _plaintext(snap)
    wal = tmp_path / (_SNAP + "-wal")
    wal.write_bytes(b"plaintext-row" * 4000)
    kept = _Kept(wal)
    try:
        report = _erase(tmp_path)
        after = kept.read()
    finally:
        kept.close()
    assert report["copies_overwritten"] == {"pre-restore": 2} and not report["copies_destroyed"]
    assert b"plaintext-row" not in after


@posix_only
def test_in_a_shared_folder_only_a_segment_the_record_names_is_reached(tmp_path, monkeypatch):
    """R711: in a broad folder (a home folder), ``corpus/seg-1.db`` may be another tool's: without a record entry naming that very
    file it is never opened for writing, never written, and counted as not the app's."""
    shared = tmp_path / "home"
    corpus = shared / "corpus"
    corpus.mkdir(parents=True)
    monkeypatch.setenv("OO_DATA_DIR", str(shared))
    (shared / "thesis.docx").write_bytes(b"years of work")
    theirs = corpus / "seg-1.db"
    theirs.write_bytes(b"another tool's segment" * 500)
    before = theirs.read_bytes()
    report = _erase(shared)
    assert report["scope"] == "app-only"
    assert theirs.read_bytes() == before
    assert report["corpus_segments"]["foreign"] == 1 and report["corpus_segments"]["overwritten"] == 0


@posix_only
@sqlcipher_only
def test_in_a_shared_folder_a_named_segment_is_still_destroyed(tmp_path, monkeypatch):
    shared = tmp_path / "home"
    corpus = shared / "corpus"
    monkeypatch.setenv("OO_DATA_DIR", str(shared))
    s1 = corpus / "seg-1.db"
    _encrypted(s1)
    (shared / "thesis.docx").write_bytes(b"years of work")
    _segment_entry(shared, s1)
    report = _erase(shared)
    assert report["scope"] == "app-only"
    assert report["corpus_segments"]["destroyed"] == 1 and not s1.exists()


@posix_only
def test_a_segment_with_a_second_name_keeps_the_folder_out_of_the_walks(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    outside = tmp_path / "operator.db"
    outside.write_bytes(b"the operator's file" * 500)
    os.link(outside, corpus / "seg-1.db")
    before = outside.read_bytes()
    report = _erase(data)
    assert outside.read_bytes() == before, "never written by path in 5b or step 6 either"
    assert report["corpus_segments"]["left"] == 1 and report["corpus_segments"]["corpus"] == "not_overwritten"


@posix_only
def test_a_log_with_no_segment_beside_it_is_overwritten_never_destroyed(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "seg-4.db-wal").write_bytes(os.urandom(16384))
    (corpus / "seg-4.db-shm").write_bytes(os.urandom(32768))
    report = _erase(data)
    seg = report["corpus_segments"]
    assert seg["destroyed"] == 0 and seg["overwritten"] == 2 and seg["corpus"] == "overwritten"


@posix_only
def test_a_segment_without_evidence_is_rewritten_whole_by_the_late_pass_too(tmp_path):
    """A holder can write plaintext pages back after the inline rewrite: its kept descriptor is rewritten whole, never page 1 only."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "seg-2.db").write_bytes(os.urandom(16384))
    generation = 987654
    sweep = crypto_erase._corpus_open(tmp_path, generation)
    try:
        crypto_erase._corpus_settle(sweep, [])
        kinds = [kind for fd, kind, _cap in crypto_erase._HELD.get(generation, []) if fd == sweep["files"][0]["fd"]]
        assert kinds == ["whole"]
    finally:
        for fd, _kind, _cap in crypto_erase._HELD.pop(generation, []):
            os.close(fd)
        os.close(sweep["dfd"])


def test_on_windows_a_corpus_folder_with_foreign_items_is_kept_and_its_segments_said_left(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "seg-1.db").write_bytes(b"x" * 100)
    (corpus / "notes.txt").write_bytes(b"mine")
    scope_os(monkeypatch, crypto_erase, supports_dir_fd=set())
    sweep = crypto_erase._corpus_open(tmp_path, 1)
    assert sweep["state"] == "by_path" and sweep["foreign"] == 1 and sweep["left"] == 1
    assert crypto_erase._corpus_report(sweep)["corpus"] == "not_overwritten"


def test_the_copy_and_segment_sentences_are_in_every_locale():
    root = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    for key in (crypto_erase._COPIES_OVERWRITTEN_SENTENCE, crypto_erase._COPIES_SHORT_SENTENCE,
                crypto_erase._SEGMENTS_OVERWRITTEN_SENTENCE, crypto_erase._SEGMENTS_SHORT_SENTENCE):
        for f in root.glob("*.json"):
            doc = json.loads(f.read_text(encoding="utf-8"))
            assert key in doc and "{n}" in doc[key], (f.name, key)


def test_the_kept_handle_reads_and_writes_without_pread_or_pwrite(tmp_path, monkeypatch):
    """Windows has neither ``os.pread`` nor ``os.pwrite``: the copy and segment steps read and write through seek then read/write,
    so no AttributeError can end the erase there."""
    p = tmp_path / "f.bin"
    p.write_bytes(b"A" * 64)
    scope_os(monkeypatch, crypto_erase)._hidden.update({"pread", "pwrite"})
    assert not hasattr(crypto_erase.os, "pread") and not hasattr(crypto_erase.os, "pwrite")
    fd = os.open(p, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        assert crypto_erase._read_at(fd, 16, 0) == b"A" * 16
        assert crypto_erase._write_at(fd, b"B" * 16, 0) == 16
    finally:
        os.close(fd)
    assert p.read_bytes() == b"B" * 16 + b"A" * 48
