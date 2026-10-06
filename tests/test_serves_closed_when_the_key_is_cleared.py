"""The columnar serve connections are closed where the process stops holding the passphrase they were keyed by (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A PERSISTED serve (the encrypted columnar cache) keeps the key it was opened with inside DuckDB for the life of the process and
goes on answering with the rows it had. ``set_passphrase(None)`` is called by three places (a failed unlock, a failed create and
the crypto-erase), and the pooled SQLCipher connections were already dropped with it; the serves were not. The three now call
``release.close_serves_for_cleared_key`` right after the clearing (the erase, before a byte is touched, as the lane engines are
disposed there), which never waits and never raises: a serve whose lock is held (a query, a persisted refresh merging) is left
open and NAMED, because closing a DuckDB connection under a running statement is what the lock exists to prevent.

The persisted branch is dormant today (no build carries the httpfs binary it needs), so these tests use the serves' own state with a
handle that records what was done to it.
"""

from __future__ import annotations

import sys
import threading

import pytest
from fastapi import HTTPException

from src.analytics import map_serve, rollup_serve
from src.api import unlock as unlock_mod
from src.database import connect as connect_mod
from src.safety import crypto_erase
from src.scheduler import release as R

TYPED = "Qv9#k'L-72mZpx"


class _Con:
    """A serve connection that records what is done to it, and in what order relative to the rest."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.closed = 0

    def close(self) -> None:
        self.closed += 1
        self.events.append("serve closed")


@pytest.fixture
def serves(monkeypatch):
    """Both serves holding a recording connection, with their own state put back after the test."""
    events: list[str] = []
    cons = {"rollup_serve": _Con(events), "map_serve": _Con(events)}
    for mod in (rollup_serve, map_serve):
        monkeypatch.setitem(mod._STATE, "con", cons[mod.__name__.rsplit(".", 1)[1]])
        monkeypatch.setitem(mod._STATE, "built_at", 123.0)
    return cons, events


def _state(mod) -> tuple[object, float]:
    with mod._LOCK:
        return mod._STATE["con"], mod._STATE["built_at"]


def _without_waiting(fn, *, seconds: float = 20.0):
    """``fn()`` run in a thread, to be called while the test holds a serve's lock: a call that waits for it would hang the suite
    (the lock is not re-entrant), so a regression is a failed assertion and not a stuck run. The caller releases the lock when
    this returns, which lets a thread that did wait finish."""
    out: list = []
    worker = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), "it waited for a lock that was held"
    return out[0]


# --------------------------------------------------------------------------- #
#  The close itself
# --------------------------------------------------------------------------- #
def test_the_close_for_a_cleared_key_closes_every_serve_and_marks_it_not_built(serves):
    cons, _ = serves
    rec = R.close_serves_for_cleared_key()
    assert rec["ok"] is True and sorted(rec["closed"]) == ["map_serve", "rollup_serve"] and "busy" not in rec
    assert [c.closed for c in cons.values()] == [1, 1], "each connection closed once"
    for mod in (rollup_serve, map_serve):
        assert _state(mod) == (None, 0.0), "marked not-built: the serve falls back to live queries and never answers from it"


def test_a_serve_in_use_is_left_open_and_named_and_the_others_are_still_closed(serves):
    """MUTATION TARGET: the lock taken blocking again. A refresh that holds ``_LOCK`` through a merge (a full rebuild is the long
    one) would hold the erase up behind it; and a connection closed under a running statement is what the lock prevents."""
    cons, _ = serves
    with rollup_serve._LOCK:  # a serve mid-query, or a persisted refresh mid-merge
        rec = _without_waiting(R.close_serves_for_cleared_key)
    assert rec["busy"] == ["rollup_serve"] and rec["closed"] == ["map_serve"] and rec["ok"] is True
    assert cons["rollup_serve"].closed == 0, "a connection in use is not closed under the statement"
    assert cons["map_serve"].closed == 1
    assert _state(rollup_serve)[0] is cons["rollup_serve"], "and it is not marked not-built: it is still the one being used"
    rec = R.close_serves_for_cleared_key()  # once nothing holds the lock, the next call closes it
    assert rec["closed"] == ["rollup_serve"] and cons["rollup_serve"].closed == 1


def test_the_release_ladders_close_still_waits_for_a_serve_in_use(serves):
    """The ladder's own step keeps the default it always had: it waits its turn (``wait=True``), and runs when the lock is free.
    Only the callers that must not wait ask for that."""
    cons, _ = serves
    started, done = threading.Event(), threading.Event()
    records: list[dict] = []

    def run() -> None:
        started.set()
        records.append(R._close_serves())
        done.set()

    rollup_serve._LOCK.acquire()
    try:
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert started.wait(10)
        assert not done.wait(0.3), "the ladder's step returned while the serve's lock was held"
        assert cons["rollup_serve"].closed == 0
    finally:
        rollup_serve._LOCK.release()
    assert done.wait(10), "it must run once the lock is free"
    worker.join(10)
    assert "rollup_serve" in records[0]["closed"] and cons["rollup_serve"].closed == 1


def test_a_serve_module_that_was_never_imported_holds_no_connection_and_is_not_imported_to_find_out(monkeypatch):
    """MUTATION TARGET: ``__import__`` back in ``_close_serves``. The ladder runs when memory is short, which is no time to load
    a module, and a cleared passphrase is no reason to load one either."""
    monkeypatch.delitem(sys.modules, "src.analytics.map_serve", raising=False)
    monkeypatch.setattr(rollup_serve, "_STATE", dict(rollup_serve._STATE, con=None))
    rec = R.close_serves_for_cleared_key()
    assert rec["ok"] is True and rec["closed"] == []
    assert "src.analytics.map_serve" not in sys.modules, "the close imported a serve it had no use for"


# --------------------------------------------------------------------------- #
#  The three places that clear the passphrase
# --------------------------------------------------------------------------- #
@pytest.fixture
def unlock_ready(monkeypatch, tmp_path):
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "wal_state_before_open", lambda: None)
    monkeypatch.setattr(unlock_mod, "_begin_recovery_notice", lambda wal_state: None)
    monkeypatch.setattr(unlock_mod, "_end_recovery_notice", lambda token: None)
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: None)
    return tmp_path / "oo.db"


def test_a_failed_unlock_finish_closes_the_serves_after_it_has_cleared_the_passphrase(unlock_ready, serves, monkeypatch):
    """MUTATION TARGET: the call taken out of the failed-finish branch, or put BEFORE ``set_passphrase(None)`` (a refresh that
    starts between the two would find the passphrase still held and open the store again)."""
    cons, events = serves
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: object())
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: events.append("passphrase set" if p else "passphrase cleared"))
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: events.append("pool disposed"))

    def finish(**kwargs):
        raise RuntimeError("the drive is full")

    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    with pytest.raises(RuntimeError):
        unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), unlock_ready)
    assert [c.closed for c in cons.values()] == [1, 1]
    assert events[:2] == ["passphrase set", "passphrase cleared"] and events.count("serve closed") == 2
    assert events.index("passphrase cleared") < events.index("serve closed"), events


def test_a_wrong_passphrase_closes_nothing(unlock_ready, serves, monkeypatch):
    """A wrong key never reached the store, so it cleared nothing and the serves of the session that is open are not touched."""
    cons, _ = serves

    def refuse(*args, **kwargs):
        raise connect_mod.WrongPassphraseError("no")

    monkeypatch.setattr(connect_mod, "connect", refuse)
    with pytest.raises(HTTPException):
        unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), unlock_ready)
    assert [c.closed for c in cons.values()] == [0, 0]


def test_a_failed_create_closes_the_serves_after_it_has_cleared_the_passphrase(serves, monkeypatch, tmp_path):
    cons, events = serves
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: tmp_path / "oo.db")
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "fresh")
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: events.append("passphrase set" if p else "passphrase cleared"))
    monkeypatch.setattr(connect_mod, "invalidate_header_cache", lambda: None)

    def finish():
        raise RuntimeError("the drive is full")

    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    with pytest.raises(RuntimeError):
        unlock_mod.create_db(unlock_mod.CreateBody(passphrase=TYPED, confirm=TYPED))
    assert [c.closed for c in cons.values()] == [1, 1]
    assert events.index("passphrase cleared") < events.index("serve closed"), events


def test_the_crypto_erase_closes_the_serves_before_a_byte_is_touched(serves, monkeypatch, tmp_path):
    """MUTATION TARGET: the call moved after the shredding, or taken out. The same measured failure the lane engines are
    disposed first for: a connection already open went on serving pre-erase rows from a file that had been overwritten."""
    cons, events = serves
    (tmp_path / "open_omniscience.db").write_bytes(b"S" * 8192)
    real_shred = crypto_erase._shred

    def shred(path, *, head_bytes=None):
        events.append("shred")
        return real_shred(path, head_bytes=head_bytes)

    monkeypatch.setattr(crypto_erase, "_shred", shred)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert report["removed"] is True
    assert [c.closed for c in cons.values()] == [1, 1]
    assert "shred" in events and events.index("serve closed") < events.index("shred"), events


def test_a_serve_in_use_during_the_erase_does_not_hold_it_up_and_is_logged(serves, monkeypatch, tmp_path, caplog):
    cons, _ = serves
    (tmp_path / "open_omniscience.db").write_bytes(b"S" * 8192)
    with rollup_serve._LOCK, caplog.at_level("WARNING", logger="safety.crypto_erase"):
        report = _without_waiting(lambda: crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path))
    assert report["removed"] is True, "the erase finished while a serve held its lock"
    assert cons["rollup_serve"].closed == 0 and cons["map_serve"].closed == 1
    assert any("left open" in r.getMessage() and "rollup_serve" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_a_close_that_fails_never_stops_the_erase(serves, monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("no")

    monkeypatch.setattr(R, "close_serves_for_cleared_key", boom)
    (tmp_path / "open_omniscience.db").write_bytes(b"S" * 8192)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert report["removed"] is True and not tmp_path.exists()
