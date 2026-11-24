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
R830 (amends R827): the net is flushed to disk and its size and key checked on the critical path; the read-back
of the whole copy, compared with the hash taken while copying, runs beside the merge, and a mismatch refuses
before the swap, removes the net and forgets it as the run's safety net.

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
    assert facts == {"bytes": len(before), "sha256": hashlib.sha256(before).hexdigest(), "read_back": True}
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


@sqlcipher_only
def test_without_read_back_the_cheap_checks_still_run_and_the_copy_says_it_is_not_yet_verified(
    tmp_path, monkeypatch, passphrase
):
    import src.database.connect as C

    live = tmp_path / "live.db"
    _encrypted_corpus(live)
    before = live.read_bytes()
    read: list[Path] = []
    real = C._sha256_of_file
    monkeypatch.setattr(C, "_sha256_of_file", lambda p, **kw: (read.append(p), real(p, **kw))[1])
    synced: list[Path] = []
    real_sync = C._fsync_file
    monkeypatch.setattr(C, "_fsync_file", lambda p: (synced.append(p), real_sync(p))[1])
    net = tmp_path / "net.db"
    facts = C.verified_store_copy(live, net, read_back=False)
    assert facts == {"bytes": len(before), "sha256": hashlib.sha256(before).hexdigest(), "read_back": False}
    assert [r for r in read if Path(r) == net] == [], "the read-back is left to the caller"
    assert [y for y in synced if Path(y) == net] == [net], "the copy is flushed to disk before anything relies on it"
    C.store_copy_reads_back(net, facts)  # and the caller's read-back passes on a good copy
    net.write_bytes(net.read_bytes()[:-1] + b"\x00")
    with pytest.raises(C.StoreCopyRefused, match="does not match"):
        C.store_copy_reads_back(net, facts)


def _net_facts(tmp_path: Path, body: bytes = b"n" * 100_000) -> tuple[Path, dict]:
    net = tmp_path / "pre-restore-x.db"
    net.write_bytes(body)
    return net, {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "read_back": False}


class _Rec:
    def __init__(self) -> None:
        self.seen: dict[str, float] = {}

    def record(self, name: str, seconds: float) -> None:
        self.seen[name] = seconds


def test_the_read_back_beside_the_merge_passes_and_marks_the_net_verified(tmp_path):
    from src.backup.merge import _net_read_back_alongside

    net, facts = _net_facts(tmp_path)
    rec = _Rec()
    ran = []
    with _net_read_back_alongside((net, facts), rec):
        ran.append("merge")
    assert ran == ["merge"] and facts["read_back"] is True and net.exists()
    assert set(rec.seen) == {"merge:net_read_back", "merge:net_read_back_wait"}


def test_a_net_that_does_not_read_back_refuses_before_the_swap_and_is_dropped(tmp_path, monkeypatch):
    import src.backup.merge as m
    from src.backup.merge import MergeError, _net_read_back_alongside

    net, facts = _net_facts(tmp_path)
    net.write_bytes(b"x" * facts["bytes"])  # same size, different bytes: the disk does not hold what was copied
    monkeypatch.setattr(m, "_RUN_SNAPSHOT", (7, net))
    after = []
    with pytest.raises(MergeError, match="could not be verified") as exc:
        with _net_read_back_alongside((net, facts), None):
            pass
        after.append("verify")  # never reached: no verify stage, so no swap
    assert after == [] and "not changed" in str(exc.value)
    assert not net.exists(), "a net that did not verify is never left to be trusted"
    assert m._RUN_SNAPSHOT is None, "and is forgotten as the run's safety net"
    assert facts["read_back"] is False


def test_a_failing_merge_keeps_its_own_error_and_an_unfinished_read_back_drops_the_net(tmp_path, monkeypatch):
    import threading

    import src.database.connect as C
    from src.backup.merge import _net_read_back_alongside

    net, facts = _net_facts(tmp_path)
    started = threading.Event()

    def _slow(path, facts, *, should_stop=None):
        started.set()
        while not should_stop():
            threading.Event().wait(0.01)
        raise C.StoreCopyRefused("stopped")

    monkeypatch.setattr(C, "store_copy_reads_back", _slow)
    with pytest.raises(ValueError, match="the merge failed"), _net_read_back_alongside((net, facts), None):
        started.wait(5)
        raise ValueError("the merge failed")
    assert not net.exists() and facts["read_back"] is False


def test_no_net_taken_in_this_call_reads_nothing(tmp_path):
    from src.backup.merge import _net_read_back_alongside

    with _net_read_back_alongside(None, None):
        pass


def test_run_restore_clones_the_working_copy_from_the_net_and_the_commit_reuses_it():
    src = (_ROOT / "src/backup/merge.py").read_text(encoding="utf-8")
    restore = python_function_source(src, "run_restore")
    take = restore.index("_net_here = _take_safety_net_with_the_copy(working, timings)")
    clone = restore.index("clone_file(_net_here[0], working)")
    merge = restore.index('timings.stage("merge"),')
    assert take < clone < merge, "the net is taken and the working copy cloned from it before the merge"
    assert "_reuse = _net_here[0] if _net_here is not None else _run_scoped_snapshot()" in restore
    assert "if commit and exclusive and _run_scoped_snapshot() is None" in restore, (
        "only a committing restore on a machine it owns takes it early, and only once per run"
    )
    merge_block = restore.index("_net_read_back_alongside(_net_here, timings)")
    assert merge < merge_block < restore.index('_abort_point("verify")'), (
        "R830: the net's read-back runs beside the merge and is waited for before verify, so before any swap"
    )
    take_src = python_function_source(src, "_take_safety_net_with_the_copy")
    assert "verified_store_copy(live, net, read_back=False)" in take_src
