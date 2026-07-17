"""Audit finding 2026-07-17: encrypt_all() reads/swaps the live plaintext file
through a RAW sqlcipher3/sqlite3 connection, never the ORM session the
single-writer gate's flush/commit events watch -- so without an explicit hold, a
concurrently-committing scraper could write new rows into the plaintext file
AFTER the encrypted copy is built but BEFORE the atomic os.replace() swap, and
those rows would be silently discarded when the swap lands. Fixed by holding
write_lock() across the whole encrypt_all() operation, so any other writer
QUEUES (never races) for its duration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.database.writer import write_gate


@pytest.fixture(autouse=True)
def _clean_gate():
    # Belt-and-braces: never let a prior test's leaked gate hang this one, and
    # never leave this test's gate held for the next one.
    write_gate._reset_for_tests()
    yield
    write_gate._reset_for_tests()


def test_encrypt_all_holds_the_single_writer_gate_across_both_files(monkeypatch):
    import src.api.unlock as unlock_mod
    import src.database.encrypt_tool as tool

    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: Path("/fake/corpus.db"))
    monkeypatch.setattr("src.paths.data_dir", lambda: Path("/fake"))

    seen_held: list[bool] = []

    def _fake_encrypt_database(path, key):
        # The whole point of the fix: while each file is being processed, the
        # gate must be HELD, so any other writer (a scraper's ORM flush/commit)
        # queues behind it instead of racing the read-export-swap.
        seen_held.append(write_gate.stats()["held"])
        return {"path": str(path), "encrypted": True}

    monkeypatch.setattr(tool, "encrypt_database", _fake_encrypt_database)

    assert write_gate.stats()["held"] is False  # sanity: nothing held before
    reports = tool.encrypt_all("a-real-passphrase-123")
    assert reports["corpus"]["encrypted"] is True
    assert reports["custody"]["encrypted"] is True
    assert seen_held == [True, True]  # held for BOTH the corpus and the custody log
    assert write_gate.stats()["held"] is False  # released again afterwards


def test_encrypt_all_releases_the_gate_even_if_a_file_fails(monkeypatch):
    """The gate must not leak (deadlocking every future writer) if encrypt_database
    raises partway through."""
    import src.api.unlock as unlock_mod
    import src.database.encrypt_tool as tool

    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: Path("/fake/corpus.db"))
    monkeypatch.setattr("src.paths.data_dir", lambda: Path("/fake"))

    def _boom(path, key):
        raise tool.EncryptToolError("simulated failure")

    monkeypatch.setattr(tool, "encrypt_database", _boom)

    with pytest.raises(tool.EncryptToolError):
        tool.encrypt_all("a-real-passphrase-123")
    assert write_gate.stats()["held"] is False


def test_a_concurrent_writer_actually_queues_behind_encrypt_all(monkeypatch):
    """End-to-end proof (not just a stats read): a second thread trying to take
    the gate while encrypt_all is mid-flight genuinely BLOCKS until it releases,
    then proceeds -- it never runs concurrently with the encrypt window (the
    exact race the fix closes: a concurrent writer must never land a commit
    between the encrypted copy being built and the atomic file swap)."""
    import threading
    import time

    import src.api.unlock as unlock_mod
    import src.database.encrypt_tool as tool
    from src.database.writer import write_lock

    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: Path("/fake/corpus.db"))
    monkeypatch.setattr("src.paths.data_dir", lambda: Path("/fake"))

    release_encrypt = threading.Event()
    other_writer_ran_at: list[float] = []

    def _slow_encrypt_database(path, key):
        # Block until the test tells us to finish -- long enough for the other
        # thread below to attempt (and be forced to queue behind) the gate.
        release_encrypt.wait(timeout=5)
        return {"path": str(path), "encrypted": True}

    monkeypatch.setattr(tool, "encrypt_database", _slow_encrypt_database)

    def _other_writer():
        with write_lock():
            other_writer_ran_at.append(time.monotonic())

    encrypt_thread = threading.Thread(target=lambda: tool.encrypt_all("pw-123456"))
    encrypt_thread.start()
    # Give encrypt_all time to acquire the gate and enter the (blocked) first call.
    for _ in range(50):
        if write_gate.stats()["held"]:
            break
        time.sleep(0.02)
    assert write_gate.stats()["held"] is True, "encrypt_all must hold the gate while it runs"

    t = threading.Thread(target=_other_writer)
    t.start()
    time.sleep(0.1)  # let the other thread reach write_lock() and start queuing
    assert not other_writer_ran_at, "the concurrent writer must not run while encrypt_all holds the gate"

    release_encrypt.set()  # let encrypt_all's (blocked) calls finish
    encrypt_thread.join(timeout=5)
    t.join(timeout=5)
    assert other_writer_ran_at, "the concurrent writer must eventually run, after encrypt_all releases"
    assert write_gate.stats()["held"] is False
