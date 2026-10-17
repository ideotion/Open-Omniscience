"""Encrypting the corpus in place swaps the file inside the library's window, so a save that was queued on the gate fails loudly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP (independent read of the follow-on, M3). ``encrypt_all`` replaces the corpus file under the write gate. A request that already held a
pooled connection to the OLD file and was queued on the gate flushes and commits into the replaced inode once the gate is given back: the save
reports success and the row is in no library. The restore and the repair close this with ``library_generation.swap_window`` (every connection
made before the window is refused from its first line, "do it again"); the encryption never opened it.

THE GUARD. ``encrypt_database(..., library=True)`` (what ``encrypt_all`` passes for the corpus) does the swap inside the window and announces
``disk_changing`` before it removes the log names. Four tests, each red without the part it names: the queued save is refused and lost nothing,
the window is the corpus's only (the custody log and the lanes have no such engine), a window that cannot be had is a named refusal with the
original untouched, and a replace that fails after the log names were removed does not give the earlier connections their validity back.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import QueuePool

from src.database import encrypt_tool, library_generation, writer
from src.database.connect import connect, is_encrypted_file
from tests.test_gate_connection_order import _factory

_KEY = "a-long-enough-passphrase-for-the-test-9Q"


def _engine(path):
    eng = create_engine(f"sqlite:///{path}", poolclass=QueuePool, pool_size=2, max_overflow=0)

    @event.listens_for(eng, "connect")
    def _wal(dbapi, _rec):
        dbapi.execute("PRAGMA journal_mode=WAL")

    library_generation.attach(eng)  # the stale-connection guard, attached as on the real engine
    with eng.begin() as c:
        c.execute(text("CREATE TABLE notes(x TEXT)"))
        c.execute(text("INSERT INTO notes VALUES ('before')"))
    return eng


def _rows(path):
    enc = connect(path, key=_KEY, check_same_thread=False)
    try:
        return [r[0] for r in enc.execute("SELECT x FROM notes ORDER BY rowid")]
    finally:
        enc.close()


def test_a_save_queued_on_the_gate_during_the_encryption_is_refused_and_loses_nothing(tmp_path, monkeypatch):
    """The probe of the read, with the corpus encrypted the way ``encrypt_all`` does. RED WITHOUT ``library=True``: the save reports
    ``committed`` and the encrypted library does not hold it."""
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    p = tmp_path / "corpus.db"
    eng = _engine(p)
    factory = _factory(eng)
    out: dict = {}
    started, go = threading.Event(), threading.Event()

    def request_save():  # reads (a connection is checked out), then saves while the encryption holds the gate
        s = factory()
        try:
            s.execute(text("SELECT count(*) FROM notes")).scalar()
            started.set()
            go.wait(5)
            s.execute(text("INSERT INTO notes VALUES ('saved-during-encrypt')"))
            s.commit()
            out["save"] = "committed"
        except Exception as exc:  # noqa: BLE001
            out["save"] = type(exc).__name__
        finally:
            s.close()

    t = threading.Thread(target=request_save)
    t.start()
    assert started.wait(5)
    with writer.write_lock():  # what encrypt_all does around encrypt_database
        go.set()
        time.sleep(0.3)  # the save is now queued on the gate with its connection out
        report = encrypt_tool.encrypt_database(p, _KEY, library=True)
    t.join(10)
    eng.dispose()
    assert report.get("encrypted") is True and is_encrypted_file(p)
    assert out.get("save") == "StaleLibraryError", f"the queued save {out.get('save')!r}: it must be refused, never reported as saved"
    assert _rows(p) == ["before"]


def test_encrypt_all_asks_for_the_window_for_the_corpus_and_only_for_it(tmp_path, monkeypatch):
    """The corpus is encrypted with ``library=True`` and the custody log and every lane without: they have no engine of that kind. RED
    WITHOUT the argument in ``encrypt_all``: the corpus swaps outside the window."""
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr("src.api.unlock.main_db_path", lambda: tmp_path / "corpus.db")
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(encrypt_tool, "encrypt_database", lambda path, key, *, library=False: calls.append((path.name, library)) or {})
    monkeypatch.setattr("src.versioned.store.dispose_all", lambda: None)
    encrypt_tool.encrypt_all(_KEY)
    assert calls[0] == ("corpus.db", True) and calls[1] == ("custody_log.db", False)
    assert all(library is False for _name, library in calls[1:])


def test_the_swap_is_inside_the_window_and_announces_the_log_names_it_is_about_to_remove(tmp_path, monkeypatch):
    """The order of the three steps: window open, ``disk_changing``, then the removal and the replace. RED WITHOUT any of them."""
    p = tmp_path / "corpus.db"
    eng = _engine(p)
    eng.dispose()
    order: list[str] = []
    real_replace = encrypt_tool.os.replace

    @contextmanager
    def window(source):
        order.append("open")
        try:
            yield
        finally:
            order.append("close")

    monkeypatch.setattr(library_generation, "swap_window", window)
    monkeypatch.setattr(library_generation, "disk_changing", lambda: order.append("disk_changing"))
    monkeypatch.setattr(encrypt_tool.os, "replace", lambda a, b: order.append("replace") or real_replace(a, b))
    encrypt_tool.encrypt_database(p, _KEY, library=True)
    assert order == ["open", "disk_changing", "replace", "close"], order
    order.clear()
    p2 = tmp_path / "custody.db"
    eng2 = _engine(p2)
    eng2.dispose()
    encrypt_tool.encrypt_database(p2, _KEY)
    assert order == ["replace"], f"a store without the library's engine swaps outside any window: {order}"


def test_a_window_that_cannot_be_had_is_a_named_refusal_and_the_original_file_is_untouched(tmp_path, monkeypatch):
    """A connection still being opened after the wait: nothing was replaced, the file is still plaintext, the encrypted copy is gone, and the
    words say so. RED WITHOUT the conversion: the route would answer a bare ``LibraryBusy`` as a 500."""
    p = tmp_path / "corpus.db"
    _engine(p).dispose()

    @contextmanager
    def busy(source):
        raise library_generation.LibraryBusy("a connection to the library was still being opened after 60 s, so the file was not switched")
        yield

    monkeypatch.setattr(library_generation, "swap_window", busy)
    with pytest.raises(encrypt_tool.EncryptToolError, match="original file is untouched"):
        encrypt_tool.encrypt_database(p, _KEY, library=True)
    assert not is_encrypted_file(p)
    assert not list(tmp_path.glob("*.enc-*")), "the encrypted copy is not left behind"


def test_a_replace_that_fails_after_the_log_names_went_does_not_revive_the_earlier_connections(tmp_path, monkeypatch):
    """``disk_changing`` is what keeps a failed swap from giving the old connections their validity back once the live ``-wal`` was
    removed (a pooled connection would hold that log by an inode no name points at). RED WITHOUT the call: the connection is revived and
    a later save lands where no later connection reads."""
    p = tmp_path / "corpus.db"
    eng = _engine(p)
    conn = eng.connect()
    conn.execute(text("SELECT count(*) FROM notes")).scalar()
    monkeypatch.setattr(encrypt_tool.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError(13, "denied")))
    with pytest.raises(OSError):
        encrypt_tool.encrypt_database(p, _KEY, library=True)
    with pytest.raises(Exception) as caught:  # noqa: B017 - SQLAlchemy may wrap the refusal; the class name is checked below
        conn.execute(text("INSERT INTO notes VALUES ('after-the-failed-swap')"))
    assert "StaleLibraryError" in {c.__name__ for c in type(caught.value).__mro__} | {type(caught.value.__cause__).__name__}
    conn.close()
    eng.dispose()
