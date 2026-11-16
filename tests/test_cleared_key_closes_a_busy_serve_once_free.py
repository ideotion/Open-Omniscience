"""Clearing the key closes a serve that was in use at that moment as soon as it is free (open-on-main row 85).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``close_serves_for_cleared_key`` never waits, so a serve whose lock was held (a query, a persisted refresh merging) was left
open and only named in ``busy``: a PERSISTED one kept the cleared key inside DuckDB until its next rebuild. It is now closed by a
thread that waits for the lock; a persisted connection swapped in meanwhile is closed too while no passphrase is held (it was
opened with the cleared key), and one opened after a new unlock is left serving. A persisted refresh that opened its store
outside the lock while the key was cleared checks again under the lock and declines instead of recording it.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.analytics import rollup_serve
from src.database import connect as connect_mod
from src.scheduler import release


class _Con:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def served(monkeypatch):
    con = _Con()
    monkeypatch.setitem(rollup_serve._STATE, "con", con)
    monkeypatch.setitem(rollup_serve._STATE, "persisted", True)
    monkeypatch.setitem(rollup_serve._STATE, "spill", None)
    monkeypatch.setitem(rollup_serve._STATE, "built_at", 1.0)
    monkeypatch.delitem(release.sys.modules, "src.analytics.map_serve", raising=False)  # this test closes the rollup serve only
    return con


def _settled() -> bool:
    deadline = time.time() + 5
    while time.time() < deadline:
        if not any(t.name.startswith("close-rollup_serve") for t in threading.enumerate()):
            return True
        time.sleep(0.02)
    return False


def test_a_busy_persisted_serve_is_closed_once_free(served, monkeypatch):
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: None)
    rollup_serve._LOCK.acquire()  # a query is running
    try:
        out = release.close_serves_for_cleared_key()
        assert out.get("busy") == ["rollup_serve"] and out.get("deferred") == ["rollup_serve"]
        time.sleep(0.1)
        assert not served.closed, "closed under a running query"
    finally:
        rollup_serve._LOCK.release()
    assert _settled() and served.closed, "the busy persisted serve kept the cleared key"
    assert rollup_serve._STATE["con"] is None


def test_a_persisted_store_swapped_in_while_no_key_is_held_is_closed(served, monkeypatch):
    """The lock holder was a refresh that read the passphrase before the clearing and recorded its new store."""
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: None)
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        rollup_serve._STATE["con"] = newer
    finally:
        rollup_serve._LOCK.release()
    assert _settled() and newer.closed, "a store opened with the cleared key went on serving"


def test_a_store_opened_after_a_new_unlock_is_left_serving(served, monkeypatch):
    held = {"p": None}
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: held["p"])
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        held["p"] = "the new unlock's key"
        rollup_serve._STATE["con"] = newer
    finally:
        rollup_serve._LOCK.release()
    assert _settled()
    assert not newer.closed and rollup_serve._STATE["con"] is newer, "the store of the new unlock was closed"


def test_an_in_memory_serve_swapped_in_is_left_serving(served, monkeypatch):
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: None)
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        rollup_serve._STATE["con"] = newer
        rollup_serve._STATE["persisted"] = False
    finally:
        rollup_serve._LOCK.release()
    assert _settled() and not newer.closed


def test_the_persisted_refresh_declines_a_store_opened_while_the_key_was_cleared(monkeypatch):
    """The open runs outside the lock: a clearing then finds nothing of it to close, so the refresh checks again under the lock."""
    from types import SimpleNamespace

    from src.analytics import columnar

    keys = iter(["the key", None])  # read once before the open, then cleared before the swap
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: next(keys, None))
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(rollup_serve, "_persisted_spill_setting", lambda: "")
    opened = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: SimpleNamespace(con=opened, kind="persisted", fallback_reason=None))
    refreshed = []
    monkeypatch.setattr(columnar, "refresh_keyword_daily", lambda *a, **k: refreshed.append(1))
    monkeypatch.setitem(rollup_serve._STATE, "con", None)
    monkeypatch.setitem(rollup_serve._STATE, "persisted", False)

    from contextlib import contextmanager

    from src.analytics import corpus_epoch, serve_gate
    from src.database import session as session_mod

    @contextmanager
    def scope():
        yield SimpleNamespace(get_bind=lambda: None)

    monkeypatch.setattr(session_mod, "session_scope", scope)
    monkeypatch.setattr(serve_gate, "change_token", lambda s: "t")
    monkeypatch.setattr(corpus_epoch, "get_corpus_epoch", lambda s: 1)

    assert rollup_serve._refresh_persisted_build() is False
    assert opened.closed and not refreshed and rollup_serve._STATE["con"] is None
    assert rollup_serve._PERSISTED_DECLINE["why"] == "no-passphrase"
