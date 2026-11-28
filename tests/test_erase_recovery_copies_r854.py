"""R854 (row 409 stage 4d): the erase sweep covers the torn-segment recovery copies' folder, ``<data>/corpus/recovery``, before any
code can create it. A copy's page 1 is key material (the key-material pass, never capped, R797), its data regions are overwritten
after it, a leftover is counted and never named (R806), and neither its name nor its folder is evidence of encryption: a copy is
always rewritten whole (R823/R820). Anything in the folder that is not the app's is left and counted. The folder is never a segment,
and no backup, export or bundle reaches it."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database.connect import have_driver
from src.safety import crypto_erase
from tests.test_erase_copies_r823 import _encrypted, _erase, _Kept, _plaintext, _segment_entry

ROOT = Path(__file__).resolve().parents[1]
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="the segment sweep keeps descriptors through a folder handle (POSIX)")


def _copy_of(seg: Path) -> Path:
    """A leftover recovery copy of ``seg`` and its journal, as stage 4d would leave them after a crash."""
    rec = seg.parent / "recovery"
    rec.mkdir(mode=0o700, exist_ok=True)
    copy = rec / seg.name.replace(".db", ".check.db")
    shutil.copyfile(seg, copy)
    (rec / (copy.name + "-journal")).write_bytes(seg.read_bytes()[:8192])
    return copy


@posix_only
@sqlcipher_only
def test_a_leftover_copy_beside_a_named_segment_is_rewritten_whole_and_never_named(tmp_path):
    data = tmp_path / "OOS data"
    s1 = data / "corpus" / "seg-1.db"
    _encrypted(s1)
    _segment_entry(data, s1)
    copy = _copy_of(s1)
    journal = copy.with_name(copy.name + "-journal")
    kc, kj = _Kept(copy), _Kept(journal)
    try:
        report = _erase(data)
        after, after_j = kc.read(), kj.read()
    finally:
        kc.close()
        kj.close()
    seg = report["corpus_segments"]
    # the segment has evidence (its record entry); the copy, a byte-for-byte twin with the same header, has none and never will
    assert seg["destroyed"] == 1 and seg["overwritten"] == 2 and seg["recovery_copies"] == 2, seg
    assert seg["foreign"] == 0 and seg["left"] == 0
    assert after[:4096] != kc.before[:4096], "page 1 first, in the key-material pass"
    assert all(after[i:i + 4096] != kc.before[i:i + 4096] for i in range(0, len(after), 4096)), "then every data page"
    assert after_j != kj.before
    assert not data.exists(), "nothing of the app's is left, the folder included"
    assert "check.db" not in json.dumps(report, default=str), "counted, never named (R806)"


@posix_only
def test_a_plaintext_copy_is_rewritten_in_full(tmp_path):
    data = tmp_path / "OOS data"
    rec = data / "corpus" / "recovery"
    rec.mkdir(parents=True)
    copy = rec / "seg-4.check.db"
    _plaintext(copy)
    kept = _Kept(copy)
    try:
        report = _erase(data)
        after = kept.read()
    finally:
        kept.close()
    assert report["corpus_segments"]["overwritten"] == 1 and report["corpus_segments"]["corpus"] == "overwritten"
    assert b"plaintext-row" not in after and b"SQLite format 3" not in after


@posix_only
def test_an_encrypted_looking_copy_is_never_evidence(tmp_path, monkeypatch):
    """No header test, no record and no folder makes a copy "destroyed": it is rewritten whole whatever it looks like."""
    import src.database.connect as connect_module

    monkeypatch.setattr(connect_module, "opened_with_key", lambda ident: True)
    data = tmp_path / "OOS data"
    rec = data / "corpus" / "recovery"
    rec.mkdir(parents=True)
    copy = rec / "seg-2.check.db"
    copy.write_bytes(os.urandom(16384))
    kept = _Kept(copy)
    try:
        report = _erase(data)
        after = kept.read()
    finally:
        kept.close()
    assert report["corpus_segments"]["destroyed"] == 0 and report["corpus_segments"]["overwritten"] == 1
    assert after[4096:] != kept.before[4096:]


@posix_only
def test_what_is_not_the_app_s_in_the_folder_is_left_counted_and_never_named(tmp_path):
    data = tmp_path / "OOS data"
    rec = data / "corpus" / "recovery"
    rec.mkdir(parents=True)
    copy = rec / "seg-1.check.db"
    _plaintext(copy)
    mine = rec / "my-notes.txt"
    mine.write_bytes(b"the operator's own")
    (rec / "seg-0.check.db").write_bytes(b"not a copy's name (n from 1)")
    (rec / "seg-1.db").write_bytes(b"a segment's name, but not where segments live")
    report = _erase(data)
    seg = report["corpus_segments"]
    assert mine.read_bytes() == b"the operator's own" and (rec / "seg-0.check.db").exists() and (rec / "seg-1.db").exists()
    assert not copy.exists() and seg["overwritten"] == 1 and seg["foreign"] == 3, seg
    assert report["folder_kept_foreign"] is True
    assert "my-notes" not in json.dumps(report, default=str)


@posix_only
def test_a_link_at_the_folder_s_name_is_never_followed(tmp_path):
    data = tmp_path / "OOS data"
    corpus = data / "corpus"
    corpus.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "seg-1.check.db"
    target.write_bytes(b"x" * 8192)
    (corpus / "recovery").symlink_to(elsewhere, target_is_directory=True)
    report = _erase(data)
    assert target.read_bytes() == b"x" * 8192
    assert report["corpus_segments"]["foreign"] == 1 and report["corpus_segments"]["overwritten"] == 0


@posix_only
def test_a_copy_with_a_second_name_is_never_written(tmp_path):
    data = tmp_path / "OOS data"
    rec = data / "corpus" / "recovery"
    rec.mkdir(parents=True)
    outside = tmp_path / "operator.db"
    outside.write_bytes(b"the operator's file" * 500)
    os.link(outside, rec / "seg-1.check.db")
    before = outside.read_bytes()
    report = _erase(data)
    assert outside.read_bytes() == before, "never written, by the sweep or by path in 5b or step 6"
    assert report["corpus_segments"]["left"] == 1 and report["corpus_segments"]["corpus"] == "not_overwritten"


@posix_only
def test_in_a_shared_folder_a_copy_beside_no_named_segment_is_never_reached(tmp_path, monkeypatch):
    """R711: in a broad folder, a copy is the app's only beside a segment the record names."""
    shared = tmp_path / "home"
    rec = shared / "corpus" / "recovery"
    rec.mkdir(parents=True)
    monkeypatch.setenv("OO_DATA_DIR", str(shared))
    (shared / "thesis.docx").write_bytes(b"years of work")
    theirs = rec / "seg-1.check.db"
    theirs.write_bytes(b"another tool's file" * 500)
    before = theirs.read_bytes()
    report = _erase(shared)
    assert report["scope"] == "app-only"
    assert theirs.read_bytes() == before
    assert report["corpus_segments"]["overwritten"] == 0 and report["corpus_segments"]["foreign"] >= 1


# ---------------------------------------------------------------- never a segment, never in a backup, export or bundle


def test_a_copy_is_never_a_segment():
    from src.database import segment_open

    for name in ("seg-1.check.db", "seg-1.check.db-journal", "recovery"):
        assert segment_open.SEGMENT_NAME_RE.match(name) is None, name
        assert crypto_erase._SEGMENT_RE.match(name) is None, name
    assert crypto_erase._RECOVERY_RE.match("seg-1.check.db") and crypto_erase._RECOVERY_RE.match("seg-9999.check.db-journal")
    for bad in ("seg-0.check.db", "seg-10000.check.db", "seg-1.check.db\n", "seg-1.check.db-wal", "x/seg-1.check.db"):
        assert crypto_erase._RECOVERY_RE.match(bad) is None, bad


def test_the_record_helper_refuses_a_copy(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    rec = data / "corpus" / "recovery"
    rec.mkdir(parents=True)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    copy = rec / "seg-1.db"  # even a segment's own name, inside the folder, is not a segment
    copy.write_bytes(b"x" * 4096)
    assert at_rest_state._segment_entry(copy, must_exist=True) is None


#: The modules that write a backup, an export or a diagnostic bundle. None of them may reach the corpus folder at all today;
#: when one is taught to carry segments, it must skip ``recovery`` and this list must say how.
_CARRIERS = [
    *sorted((ROOT / "src" / "backup").glob("*.py")),
    ROOT / "src" / "api" / "backup_v2.py",
    ROOT / "src" / "api" / "diagnostics" / "bundle.py",
]
_REACHES_CORPUS = re.compile(r"SEGMENT_DIR|CORPUS_DIR|corpus_folder\(|[\"']corpus/|/ *[\"']corpus[\"']")


@pytest.mark.parametrize("path", _CARRIERS, ids=lambda p: p.name)
def test_no_backup_export_or_bundle_reaches_the_corpus_folder(path):
    assert not _REACHES_CORPUS.search(path.read_text(encoding="utf-8")), path.name
