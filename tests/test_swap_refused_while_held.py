"""A swap that Windows refuses because the library file is still open (R741, row 145), simulated on every OS.

Windows refuses to remove or replace a file another handle holds (ERROR_SHARING_VIOLATION, ``winerror`` 32); POSIX never does, so the
refusal is injected here with the attribute the product keys on (``merge._file_is_locked``). What is pinned:

* the swap's 300 s wait ends EARLY only on a positive "this process holds the file" answer, given within a bounded time; a slow, failed
  or empty answer, or a refused file with no name, keeps the ordinary wait to its deadline (both branches);
* a repair whose switch is refused that way is "writer-busy" (refused, not failed) and keeps its finished copy for the next start;
* an encryption refused at each of its three steps (the ``-wal`` removal, the ``-shm`` removal, the replace) leaves the original file's
  bytes as they were and the file unencrypted, and says "untouched" only where that is true.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.backup import merge
from src.database import encrypt_tool, library_generation
from src.database.connect import is_encrypted_file
from tests.os_scope import scope_os

_KEY = "a-long-enough-passphrase-for-the-test-9Q"


class _HeldOpen(PermissionError):
    """What Windows raises for a file another handle holds: the code the product reads, on any OS."""

    winerror = 32


def _held(path: Path | str) -> _HeldOpen:
    return _HeldOpen(13, "The process cannot access the file because it is being used by another process", str(path))


# --- the wait and its early end --------------------------------------------------------------------------------------


def test_the_grace_question_is_asked_once_and_a_raise_ends_the_wait_at_once():
    asked: list[OSError] = []

    def refuse(_exc):
        asked.append(_exc)
        raise library_generation.LibraryBusy("ours")

    def op():
        raise _held("x.db-wal")

    started = time.monotonic()
    with pytest.raises(library_generation.LibraryBusy):
        merge._retry_while_locked(op, deadline=time.monotonic() + 30, after_grace=refuse, grace_s=0.3)
    took = time.monotonic() - started
    assert len(asked) == 1 and 0.25 <= took < 5, f"the wait ended after {took:.2f} s"


def test_an_answer_that_is_not_ours_keeps_the_wait_to_its_deadline_and_raises_the_os_refusal():
    asked: list[OSError] = []

    def op():
        raise _held("x.db-wal")

    started = time.monotonic()
    with pytest.raises(_HeldOpen):
        merge._retry_while_locked(op, deadline=time.monotonic() + 1.0, after_grace=asked.append, grace_s=0.1)
    assert len(asked) == 1 and time.monotonic() - started >= 0.95


def test_only_a_positive_answer_about_this_process_refuses(monkeypatch, tmp_path):
    target = tmp_path / "live.db"
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: True)
    with pytest.raises(library_generation.LibraryBusy) as busy:
        merge._refuse_if_this_process_holds(_held(target))
    assert str(busy.value) == merge.OWN_HOLDER_BUSY
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: False)
    assert merge._refuse_if_this_process_holds(_held(target)) is None
    # a refused REPLACE names the source in ``filename`` and the destination in ``filename2``: the one asked about is the destination
    asked: list[Path] = []
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: asked.append(path) or False)
    working = tmp_path / "working.db"
    replace_refused = _HeldOpen(13, "refused", str(working), None, str(target))
    assert merge._refuse_if_this_process_holds(replace_refused) is None
    assert asked == [target], "a refused replace must ask about the live file it would replace, not the copy it would move"
    no_name = _HeldOpen(13, "refused")  # a refusal that names no file cannot be asked about
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: pytest.fail("asked about no file"))
    assert merge._refuse_if_this_process_holds(no_name) is None


class _FakeProcess:
    def __init__(self, files=None, delay=0.0, fail=False):
        self._files, self._delay, self._fail = files or [], delay, fail

    def open_files(self):
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError("access denied")
        return self._files


class _Opened:
    def __init__(self, path):
        self.path = str(path)


@pytest.mark.parametrize(
    "process, expected",
    [
        pytest.param(lambda f: _FakeProcess([_Opened(f)]), True, id="listed"),
        pytest.param(lambda f: _FakeProcess([]), False, id="empty"),
        pytest.param(lambda f: _FakeProcess([_Opened(f.with_name("other.db"))]), False, id="another-file"),
        pytest.param(lambda f: _FakeProcess(fail=True), False, id="error"),
        pytest.param(lambda f: _FakeProcess([_Opened(f)], delay=1.0), False, id="slower-than-the-bound"),
    ],
)
def test_the_probe_is_true_only_for_a_listed_file_inside_its_bound(monkeypatch, tmp_path, process, expected):
    import psutil

    target = tmp_path / "live.db"
    target.write_bytes(b"")
    fake = process(target)
    monkeypatch.setattr(psutil, "Process", lambda *a, **kw: fake)
    started = time.monotonic()
    assert merge._this_process_holds(target, timeout_s=0.3) is expected
    assert time.monotonic() - started < 0.9, "the probe outlived its bound"


# --- the swap itself -------------------------------------------------------------------------------------------------


def _store(path: Path) -> None:
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()


@pytest.fixture()
def swap_parts(tmp_path, monkeypatch):
    live, working = tmp_path / "live.db", tmp_path / "working.db"
    _store(live)
    _store(working)
    Path(str(live) + "-wal").write_bytes(b"")
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: {"checked_out": 0})
    monkeypatch.setattr(merge, "_OWN_HOLDER_GRACE_S", 0.2)
    real = merge._retry_while_locked

    calls: list[int] = []

    def refused_wal(op, **kw):
        calls.append(1)
        if len(calls) > 1:  # the swap's first file step is the -wal removal: that is the one refused
            return real(op, **kw)

        def held():
            raise _held(str(live) + "-wal")

        return real(held, **kw)

    monkeypatch.setattr(merge, "_retry_while_locked", refused_wal)
    return live, working


def test_a_swap_held_by_this_process_is_busy_in_seconds_and_switches_nothing(swap_parts, monkeypatch):
    live, working = swap_parts
    before = live.read_bytes()
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: True)
    monkeypatch.setattr(merge, "_SWAP_HANDLE_WAIT_S", 3.0)  # without the early refusal this would end in the OS refusal after 3 s
    started = time.monotonic()
    with pytest.raises(library_generation.LibraryBusy) as busy:
        merge.swap_in_corpus(working, live)
    assert str(busy.value) == merge.OWN_HOLDER_BUSY
    assert time.monotonic() - started < 10, "the swap waited out its budget for a holder that was its own"
    assert live.read_bytes() == before and working.exists()


def test_a_swap_held_by_another_program_waits_its_budget_as_before(swap_parts, monkeypatch):
    live, working = swap_parts
    monkeypatch.setattr(merge, "_SWAP_HANDLE_WAIT_S", 1.0)
    monkeypatch.setattr(merge, "_this_process_holds", lambda path, **kw: False)
    started = time.monotonic()
    with pytest.raises(_HeldOpen):
        merge.swap_in_corpus(working, live)
    assert time.monotonic() - started >= 0.95, "a foreign holder must keep the ordinary wait"
    assert working.exists()


# --- encryption: the original at each refused step -------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def wal_store(tmp_path):
    """A plaintext store with one saved row."""
    p = tmp_path / "corpus.db"
    c = sqlite3.connect(str(p))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE notes(x TEXT)")
    c.execute("INSERT INTO notes VALUES ('saved')")
    c.commit()
    c.close()
    return p


def _rows_of_the_file_alone(p: Path, tmp_path: Path) -> list:
    alone = tmp_path / "alone.db"
    alone.write_bytes(p.read_bytes())
    c = sqlite3.connect(str(alone))
    try:
        return c.execute("SELECT x FROM notes").fetchall()
    finally:
        c.close()


@pytest.mark.parametrize(
    "refused_at, words",
    [("-wal", encrypt_tool.HELD_UNTOUCHED), ("-shm", encrypt_tool.HELD_LOG_REMOVED), ("replace", encrypt_tool.HELD_LOG_REMOVED)],
)
def test_an_encryption_refused_at_each_step_leaves_the_original_unencrypted_and_says_only_what_is_true(
    wal_store, tmp_path, monkeypatch, refused_at, words
):
    """The steps run inside the window; the state the window opens on is the one each refusal is measured against. The ``-wal`` and
    ``-shm`` are put there as a holder keeps them on Windows (here a SECOND SQLite library in the process folds and removes the log
    before the window, which is a POSIX-only effect of per-process locks, so they are written by hand)."""
    p = wal_store
    at_swap: dict = {}

    @contextmanager
    def window(_enc_tmp):
        for side in ("-wal", "-shm"):
            Path(str(p) + side).write_bytes(b"held by a request")
        at_swap["sha"] = _sha(p)
        yield

    monkeypatch.setattr(encrypt_tool, "_library_window", window)
    real_unlink = encrypt_tool.os.unlink

    def unlink(path, *a, **kw):
        if str(path).endswith(refused_at):
            raise _held(path)
        return real_unlink(path, *a, **kw)

    def replace(src, dst):
        raise _held(dst)

    if refused_at == "replace":
        scope_os(monkeypatch, encrypt_tool, replace=replace)
    else:
        scope_os(monkeypatch, encrypt_tool, unlink=unlink)
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_database(p, _KEY, library=True)
    assert str(refused.value) == words
    assert refused.value.__suppress_context__, "the OS's text must not ride along"
    # the library file itself: the bytes the window opened on, still plaintext, holding what was saved; no encrypted copy left beside it
    assert _sha(p) == at_swap["sha"] and not is_encrypted_file(p)
    assert _rows_of_the_file_alone(p, tmp_path) == [("saved",)]
    assert not list(p.parent.glob("corpus.db.enc-*"))
    sides = {side: Path(str(p) + side).exists() for side in ("-wal", "-shm")}
    if refused_at == "-wal":
        assert sides == {"-wal": True, "-shm": True}, "untouched means the log files are still there too"
    else:
        assert not sides["-wal"], "the words say a log file went, so one must have"
    # the snapshot made just before holds everything and is plaintext
    (snapshot,) = p.parent.glob("pre-encrypt-*-corpus.db")
    assert not is_encrypted_file(snapshot)
    c = sqlite3.connect(str(snapshot))
    try:
        assert c.execute("SELECT x FROM notes").fetchall() == [("saved",)]
    finally:
        c.close()


def test_an_error_that_is_not_a_held_file_is_not_called_one(wal_store, monkeypatch):
    def replace(src, dst):
        raise PermissionError(13, "read-only volume", str(dst))  # no winerror: not a held file

    scope_os(monkeypatch, encrypt_tool, replace=replace)
    with pytest.raises(PermissionError):
        encrypt_tool.encrypt_database(wal_store, _KEY)


def test_only_a_removed_write_ahead_log_changes_the_words():
    """The ``-shm`` is an index SQLite rebuilds; the file is whole without it. Only a removed ``-wal`` (which carries saves) makes
    the snapshot the complete copy."""
    assert encrypt_tool._held_words([]) == encrypt_tool.HELD_UNTOUCHED
    assert encrypt_tool._held_words(["-shm"]) == encrypt_tool.HELD_UNTOUCHED
    assert encrypt_tool._held_words(["-wal"]) == encrypt_tool.HELD_LOG_REMOVED
    assert encrypt_tool._held_words(["-wal", "-shm"]) == encrypt_tool.HELD_LOG_REMOVED


def test_a_probe_thread_that_cannot_start_is_cannot_tell(monkeypatch, tmp_path):
    class _NoStart:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(merge.threading, "Thread", _NoStart)
    assert merge._this_process_holds(tmp_path / "live.db") is False


def test_a_held_store_other_than_the_library_keeps_its_own_error(wal_store, monkeypatch):
    """``encrypt_all`` encrypts the corpus FIRST, so a later store refused as held follows a library that is already ciphertext: the
    library's "not encrypted, untouched" words would be false there, so they are kept for ``library=True`` alone."""

    def replace(src, dst):
        raise _held(dst)

    scope_os(monkeypatch, encrypt_tool, replace=replace)
    with pytest.raises(_HeldOpen):
        encrypt_tool.encrypt_database(wal_store, _KEY)
    assert not is_encrypted_file(wal_store)


def test_the_two_refusals_are_keyed_in_every_locale_and_the_page_translates_them():
    import json

    root = Path(__file__).resolve().parents[1]
    for f in sorted((root / "src/static/locales").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert encrypt_tool.HELD_UNTOUCHED in d and encrypt_tool.HELD_LOG_REMOVED in d, f.name
    js = (root / "src/static/app-backup.js").read_text(encoding="utf-8")
    assert "msg.textContent = t(e.message);" in js


def test_the_probe_runs_on_its_own_thread_so_a_hang_cannot_hold_the_swap(monkeypatch, tmp_path):
    import psutil

    gate = threading.Event()

    class Hangs:
        def open_files(self):
            gate.wait(5)
            return []

    monkeypatch.setattr(psutil, "Process", lambda *a, **kw: Hangs())
    started = time.monotonic()
    assert merge._this_process_holds(tmp_path / "x.db", timeout_s=0.2) is False
    assert time.monotonic() - started < 1
    gate.set()
