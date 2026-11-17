"""Clearing the key closes a serve that was in use at that moment as soon as it is free (open-on-main row 85).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``close_serves_for_cleared_key`` never waits, so a serve whose lock was held (a query, a persisted refresh merging) was left
open and only named in ``busy``: a PERSISTED one kept the cleared key inside DuckDB until its next rebuild. It is now closed by a
thread that waits for the lock; a persisted connection swapped in meanwhile is closed too when it was opened with a key
generation no later than the clearing's (``connect.key_generation`` moves on every set and clear), and one opened after a new
unlock or create is left serving. A persisted refresh that opened its store outside the lock while the key was cleared or set
anew checks the generation again under the lock and declines instead of recording it. The crypto-erase closes the serves a second
time once its key is cleared, so a store recorded while the key was still held does not outlive the erase.
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
    monkeypatch.setitem(rollup_serve._STATE, "key_gen", -1)
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


def test_a_persisted_store_opened_with_the_cleared_key_and_swapped_in_is_closed(served, monkeypatch):
    """The lock holder was a refresh that read the key before the clearing and recorded its new store."""
    gen = connect_mod.key_generation()
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        rollup_serve._STATE["con"] = newer
        rollup_serve._STATE["key_gen"] = gen
    finally:
        rollup_serve._LOCK.release()
    assert _settled() and newer.closed, "a store opened with the cleared key went on serving"


def test_a_store_opened_after_a_new_key_is_left_serving_even_when_the_same_key_comes_back(served, monkeypatch):
    """A new unlock or create while the lock was held: its store carries a later generation (the passphrase may even be equal)."""
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        rollup_serve._STATE["con"] = newer
        rollup_serve._STATE["key_gen"] = connect_mod.key_generation() + 2
    finally:
        rollup_serve._LOCK.release()
    assert _settled()
    assert not newer.closed and rollup_serve._STATE["con"] is newer, "the store of the new unlock was closed"


def test_an_in_memory_serve_swapped_in_is_left_serving(served, monkeypatch):
    newer = _Con()
    rollup_serve._LOCK.acquire()
    try:
        release.close_serves_for_cleared_key()
        rollup_serve._STATE["con"] = newer
        rollup_serve._STATE["persisted"] = False
    finally:
        rollup_serve._LOCK.release()
    assert _settled() and not newer.closed


def _refresh_with(monkeypatch, generations):
    """Run ``_refresh_persisted_build`` with the opener and the session faked; ``generations`` is what the in-lock read returns."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from src.analytics import columnar, corpus_epoch, serve_gate
    from src.database import session as session_mod

    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "the key")
    monkeypatch.setattr(rollup_serve, "_key_generation", lambda: next(generations))
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(rollup_serve, "_persisted_spill_setting", lambda: "")
    opened = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: SimpleNamespace(con=opened, kind="persisted", fallback_reason=None))
    refreshed = []
    monkeypatch.setattr(columnar, "refresh_keyword_daily", lambda *a, **k: refreshed.append(1))
    monkeypatch.setitem(rollup_serve._STATE, "con", None)
    monkeypatch.setitem(rollup_serve._STATE, "persisted", False)

    @contextmanager
    def scope():
        yield SimpleNamespace(get_bind=lambda: None)

    monkeypatch.setattr(session_mod, "session_scope", scope)
    monkeypatch.setattr(serve_gate, "change_token", lambda s: "t")
    monkeypatch.setattr(corpus_epoch, "get_corpus_epoch", lambda s: 1)
    return opened, refreshed


def test_the_persisted_refresh_declines_a_store_opened_while_the_key_was_cleared(monkeypatch):
    """The open runs outside the lock: a clearing then finds nothing of it to close, so the refresh checks again under the lock."""
    opened, refreshed = _refresh_with(monkeypatch, iter([7, 8]))  # read before the key, then under the lock: it moved on (a clear, or a new key)
    assert rollup_serve._refresh_persisted_build() is False
    assert opened.closed and not refreshed and rollup_serve._STATE["con"] is None
    assert rollup_serve._PERSISTED_DECLINE["why"] == "no-passphrase"


def test_the_persisted_refresh_records_its_generation(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_require_library_unchanged", lambda stamp: None)
    from src.database import library_generation

    monkeypatch.setattr(library_generation, "current", lambda: 0)
    opened, refreshed = _refresh_with(monkeypatch, iter([7, 7]))
    opened.execute = lambda sql: type("R", (), {"fetchone": lambda self: (3,)})()
    monkeypatch.setitem(rollup_serve._STATE, "key_gen", -1)
    assert rollup_serve._refresh_persisted_build() is True
    assert refreshed and rollup_serve._STATE["con"] is opened and rollup_serve._STATE["key_gen"] == 7


def test_the_generation_moves_on_every_set_and_clear(monkeypatch):
    monkeypatch.setattr(connect_mod, "_guard_the_key", lambda: None)
    held = connect_mod.get_passphrase()
    g0 = connect_mod.key_generation()
    try:
        connect_mod.set_passphrase("k")
        connect_mod.set_passphrase(None)
        connect_mod.set_passphrase("k")
        assert connect_mod.get_passphrase() == "k" and connect_mod.key_generation() == g0 + 3
    finally:
        connect_mod.set_passphrase(held)


def test_the_erase_closes_the_serves_again_once_its_key_is_cleared(monkeypatch, tmp_path):
    """The erase's first close runs while the key is still held: a store recorded after it, before the key goes, is closed by the
    second, made after the clearing."""
    from src.safety import crypto_erase

    calls = []

    def close():
        calls.append(connect_mod.get_passphrase())
        return {"closed": []}

    monkeypatch.setattr(release, "close_serves_for_cleared_key", close)
    monkeypatch.setattr(connect_mod, "_guard_the_key", lambda: None)
    held = connect_mod.get_passphrase()
    connect_mod.set_passphrase("the erased key")
    # The default-store path (data_dir=None) on a temp folder, as tests/test_crypto_erase.py reaches it: no real corpus is touched.
    monkeypatch.setattr(
        crypto_erase,
        "_resolve",
        lambda dd: {
            "base": tmp_path,
            "main_db": tmp_path / "open_omniscience.db",
            "keys_dir": tmp_path / "keys",
            "store_dir": tmp_path,
            "custody_db": tmp_path / "custody_log.db",
            "anchors_db": tmp_path / "anchors.db",
        },
    )
    try:
        (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
        assert crypto_erase.quick_crypto_erase(confirm=True)["passphrase_cleared"] is True
    finally:
        connect_mod.set_passphrase(held)
    assert len(calls) == 2 and calls[0] == "the erased key" and calls[1] is None, calls
