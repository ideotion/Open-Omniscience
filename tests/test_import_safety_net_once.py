"""R827 R5/R6(a) (row 408): the safety net is taken once, before the merge, verified whole, and the working
copy is cloned from it.

An import copied the whole live corpus twice: once for the working copy, and again at the commit for the
pre-restore safety net. Now the safety net is copied once from the live corpus, and that copy is kept only
when its size and sha256 equal the source's, both taken under the same write-gate hold. The working copy is
cloned from the safety net, which is never written to, and the commit reuses the net. What these tests pin:
- the copy is byte-identical, verified, and opens under the same key;
- a copy that does not match is removed and refused, and the source is untouched;
- a plaintext store or a disabled gate returns None, so the caller copies the way it did before;
- free space for both copies is checked before anything is written;
- run_restore is wired that way: the clone is taken from the net, and the commit reuses it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.database.connect import connect, get_passphrase, have_driver, set_passphrase
from tests.js_source_helper import python_function_source

sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
_ROOT = Path(__file__).resolve().parents[1]
_PW = "correct horse battery staple"


@pytest.fixture()
def passphrase():
    before = get_passphrase()
    set_passphrase(_PW)
    try:
        yield _PW
    finally:
        set_passphrase(before)


def _encrypted_corpus(path: Path, n: int = 300) -> None:
    con = connect(path, key=_PW, check_same_thread=False)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, content TEXT)")
        con.executemany("INSERT INTO articles VALUES(?,?)", [(i, f"body {i} " * 200) for i in range(n)])
        con.commit()
    finally:
        con.close()


@sqlcipher_only
def test_the_safety_net_is_byte_identical_verified_and_opens(tmp_path, passphrase):
    from src.database.connect import clone_file, verified_store_copy

    live = tmp_path / "live.db"
    _encrypted_corpus(live)
    before = live.read_bytes()
    net = tmp_path / "net.db"
    facts = verified_store_copy(live, net)
    assert facts == {"bytes": len(before), "sha256": hashlib.sha256(before).hexdigest()}
    assert net.read_bytes() == before and live.read_bytes() == before
    working = tmp_path / "w" / "working.db"
    working.parent.mkdir()
    clone_file(net, working)
    assert working.read_bytes() == before
    con = connect(working, check_same_thread=False)
    try:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 300
    finally:
        con.close()


@sqlcipher_only
def test_a_copy_that_does_not_match_is_removed_and_refused(tmp_path, monkeypatch, passphrase):
    import src.database.connect as C

    live = tmp_path / "live.db"
    _encrypted_corpus(live)
    before = live.read_bytes()
    real = C._sha256_of_file

    def _flipped(path, **kw):
        n, h = real(path, **kw)
        return n, ("0" if h[0] != "0" else "1") + h[1:]  # the copy reads back different from what was copied

    monkeypatch.setattr(C, "_sha256_of_file", _flipped)
    net = tmp_path / "net.db"
    with pytest.raises(C.StoreCopyRefused, match="does not match"):
        C.verified_store_copy(live, net)
    assert not net.exists(), "a copy that did not verify is never left to be trusted"
    assert live.read_bytes() == before, "the source is untouched"


def test_a_plaintext_store_is_left_to_the_old_path(tmp_path):
    from src.database.connect import verified_store_copy

    live = tmp_path / "live.db"
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    assert verified_store_copy(live, tmp_path / "net.db") is None
    assert not (tmp_path / "net.db").exists()


@sqlcipher_only
def test_with_the_write_gate_off_nothing_is_copied(tmp_path, monkeypatch, passphrase):
    from src.database.connect import verified_store_copy

    monkeypatch.setenv("OO_WRITE_GATE", "0")
    live = tmp_path / "live.db"
    _encrypted_corpus(live)
    assert verified_store_copy(live, tmp_path / "net.db") is None
    assert not (tmp_path / "net.db").exists()


def test_free_space_for_both_copies_is_checked_before_anything_is_written(tmp_path, monkeypatch):
    import src.backup.merge as m
    import src.backup.sqlite_backup as sb
    from src.backup.artifact import BackupSpaceError

    live = tmp_path / "live.db"
    live.write_bytes(b"x" * 1000)
    monkeypatch.setattr(sb, "live_db_path", lambda: live)
    monkeypatch.setattr(m, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.database.connect.is_encrypted_file", lambda p: True)
    monkeypatch.setattr("src.database.writer.gate_enabled", lambda: True)
    asked: list[int] = []

    def _no_room(target, needed, *, what):
        asked.append(needed)
        raise BackupSpaceError("Not enough free space for the restore")

    monkeypatch.setattr("src.backup.artifact.preflight_free_space", _no_room)
    copied: list[int] = []
    monkeypatch.setattr("src.database.connect.verified_store_copy", lambda *a, **k: copied.append(1))
    with pytest.raises(BackupSpaceError):
        m._take_safety_net_with_the_copy(tmp_path / "staging" / "working.db")
    assert asked == [2000], "the same device holds both copies: twice the corpus"
    assert copied == [] and not list(tmp_path.glob("pre-restore-*")), "nothing written before the check"


def test_a_plaintext_live_store_takes_no_early_net_and_checks_nothing(tmp_path, monkeypatch):
    import src.backup.merge as m
    import src.backup.sqlite_backup as sb

    live = tmp_path / "live.db"
    live.write_bytes(b"SQLite format 3\x00" + b"x" * 100)
    monkeypatch.setattr(sb, "live_db_path", lambda: live)
    monkeypatch.setattr(
        "src.backup.artifact.preflight_free_space",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("checked space for a copy it will not make")),
    )
    assert m._take_safety_net_with_the_copy(tmp_path / "w" / "working.db") is None


def test_run_restore_clones_the_working_copy_from_the_net_and_the_commit_reuses_it():
    src = (_ROOT / "src/backup/merge.py").read_text(encoding="utf-8")
    restore = python_function_source(src, "run_restore")
    take = restore.index("_net_here = _take_safety_net_with_the_copy(working, timings)")
    clone = restore.index("clone_file(_net_here[0], working)")
    merge = restore.index('with timings.stage("merge")')
    assert take < clone < merge, "the net is taken and the working copy cloned from it before the merge"
    assert "_reuse = _net_here[0] if _net_here is not None else _run_scoped_snapshot()" in restore
    assert "if commit and exclusive and _run_scoped_snapshot() is None" in restore, (
        "only a committing restore on a machine it owns takes it early, and only once per run"
    )
