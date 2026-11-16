"""The persisted refresh retires the in-memory rollup it replaces (open-on-main row 25).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: when the process was serving an IN-MEMORY rollup and the persisted store became available (the passphrase was set, the
secure backend arrived), ``_refresh_persisted_build`` wrote its persisted connection over ``_STATE["con"]`` without closing the
in-memory one, which kept holding up to DuckDB's whole memory limit until the process ended, and left that store's offload folder
(``_STATE["spill"]``, under the data directory) on disk.

Row 48: the persisted connection now gets its OWN offload folder under the data directory (it had none, so DuckDB used ``.tmp``
beside the working directory), recorded in ``_STATE["spill"]`` with it and removed whenever it is not the one serving.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

import pytest

from src.analytics import columnar, rollup_serve


class _Con:
    def __init__(self):
        self.closed = False

    def execute(self, *_a, **_k):
        return self

    def fetchone(self):
        return (3,)

    def close(self):
        self.closed = True


def _folders() -> list[str]:
    from src.paths import data_dir

    root = data_dir() / "duckdb_tmp"
    return sorted(str(p) for p in root.iterdir()) if root.is_dir() else []


def _assert_own_folder(spill) -> None:
    """The serving persisted store's folder: one per connection, under the data directory, owner-only."""
    import os
    import stat
    from pathlib import Path

    from src.paths import data_dir

    assert spill and Path(spill).parent == data_dir() / "duckdb_tmp" and _folders() == [spill]
    if os.name == "posix":
        assert stat.S_IMODE(Path(spill).stat().st_mode) == 0o700


@pytest.fixture
def served_in_memory(monkeypatch, tmp_path):
    from src.analytics import corpus_epoch, serve_gate
    from src.database import library_generation
    from src.database import session as app_session

    class _S:
        def get_bind(self):
            return "bind"

    @contextmanager
    def scope():
        yield _S()

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    old = _Con()
    spill = tmp_path / "old-spill"  # outside duckdb_tmp: the new folder's sweep must not be what removes it
    spill.mkdir(parents=True)
    state = dict(rollup_serve._STATE, con=old, persisted=False, spill=str(spill), token=None, rows=None, built_at=None, bind=None,
                 pending=True)
    monkeypatch.setattr(rollup_serve, "_STATE", state)
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "refresh_keyword_daily", lambda *_a, **_k: {"mode": "full"})
    monkeypatch.setattr(serve_gate, "change_token", lambda _s: (7, 1000))
    monkeypatch.setattr(corpus_epoch, "get_corpus_epoch", lambda _s: 1)
    monkeypatch.setattr(library_generation, "current", lambda: 0)
    monkeypatch.setattr(rollup_serve, "_require_library_unchanged", lambda _stamp: None)
    monkeypatch.setattr(app_session, "session_scope", scope)
    return state, old, spill


def test_the_persisted_store_replaces_the_in_memory_one_and_closes_it(monkeypatch, served_in_memory):
    state, old, spill = served_in_memory
    new = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: columnar.OpenedStore(new, "persisted"))
    assert rollup_serve._refresh_persisted_build() is True
    assert state["con"] is new and state["persisted"] is True
    assert old.closed, "the in-memory rollup it replaced was left open, holding its memory until the process ends"
    assert not spill.exists(), "the replaced in-memory store's offload folder was left on disk"
    assert not new.closed
    _assert_own_folder(state["spill"])


def test_a_refresh_that_fails_leaves_the_in_memory_store_serving(monkeypatch, served_in_memory):
    """Nothing is retired before the persisted store is recorded: a failed refresh keeps what was serving."""
    state, old, spill = served_in_memory
    new = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: columnar.OpenedStore(new, "persisted"))

    def boom(*_a, **_k):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(columnar, "refresh_keyword_daily", boom)
    with pytest.raises(RuntimeError):
        rollup_serve._refresh_persisted_build()
    assert state["con"] is old and not old.closed and spill.exists() and state["spill"] == str(spill)
    assert new.closed, "the persisted connection this attempt opened is released"
    assert _folders() == [], "the failed attempt's offload folder was left on disk"


def test_a_cached_persisted_store_is_refreshed_in_place_and_never_closed(monkeypatch, served_in_memory):
    state, _old, _spill = served_in_memory
    cached = _Con()
    own = rollup_serve._persisted_spill_setting()
    state.update(con=cached, persisted=True, spill=own)
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: pytest.fail("a cached persisted store is not reopened"))
    assert rollup_serve._refresh_persisted_build() is True
    assert state["con"] is cached and not cached.closed
    assert state["spill"] == own and _folders() == [own], "the serving persisted store's own offload folder was removed"


def test_a_raise_after_the_store_is_recorded_does_not_close_the_serving_connection(monkeypatch, served_in_memory):
    """The session's closing commit runs after the swap: if it raises, the recorded persisted store must stay open."""
    from src.database import session as app_session

    state, old, _spill = served_in_memory
    new = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: columnar.OpenedStore(new, "persisted"))

    class _S:
        def get_bind(self):
            return "bind"

    @contextmanager
    def scope():
        yield _S()
        raise RuntimeError("commit failed")

    monkeypatch.setattr(app_session, "session_scope", scope)
    with pytest.raises(RuntimeError):
        rollup_serve._refresh_persisted_build()
    assert state["con"] is new and not new.closed, "the store recorded as serving was closed under every later serve"
    assert old.closed
    _assert_own_folder(state["spill"])


def test_the_persisted_connection_is_handed_its_own_folder_even_for_an_encrypted_corpus(monkeypatch, served_in_memory):
    """The persisted store's offload is encrypted (temp_file_encryption), so it gets a folder where the in-memory path gets none."""
    state, _old, _spill = served_in_memory
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    got: dict = {}

    def open_store(*_a, **k):
        got.update(k)
        return columnar.OpenedStore(_Con(), "persisted")

    monkeypatch.setattr(columnar, "open_store", open_store)
    assert rollup_serve._spill_setting() == "", "the in-memory path must still decline a folder for an encrypted corpus"
    assert rollup_serve._refresh_persisted_build() is True
    assert got.get("persisted_spill") == state["spill"] and "spill" not in got
    _assert_own_folder(state["spill"])


def test_a_declined_open_removes_the_folder_it_made(monkeypatch, served_in_memory):
    """The opener handed back an in-memory store: it is closed, not recorded, and the folder made for the persisted one goes too."""
    state, old, spill = served_in_memory
    fallback = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: columnar.OpenedStore(fallback, "memory", "persisted-open-failed"))
    assert rollup_serve._refresh_persisted_build() is False
    assert fallback.closed and state["con"] is old and state["spill"] == str(spill)
    assert _folders() == []


def test_closing_the_serves_removes_the_persisted_folder(monkeypatch, served_in_memory):
    """The memory ladder, the lock and a cleared key close the serves through ``release._close_serves``: the folder goes too."""
    from src.scheduler import release

    state, _old, _spill = served_in_memory
    new = _Con()
    monkeypatch.setattr(columnar, "open_store", lambda *_a, **_k: columnar.OpenedStore(new, "persisted"))
    assert rollup_serve._refresh_persisted_build() is True
    _assert_own_folder(state["spill"])
    monkeypatch.delitem(sys.modules, "src.analytics.map_serve", raising=False)  # this test closes the keyword rollup's serve only
    release._close_serves(wait=False)
    assert new.closed and state["con"] is None and state["spill"] is None
    assert _folders() == []


def test_an_opener_that_raises_leaves_no_folder(monkeypatch, served_in_memory):
    state, old, spill = served_in_memory

    def boom(*_a, **_k):
        raise MemoryError("the in-memory fallback could not be made either")

    monkeypatch.setattr(columnar, "open_store", boom)
    with pytest.raises(MemoryError):
        rollup_serve._refresh_persisted_build()
    assert state["con"] is old and state["spill"] == str(spill) and _folders() == []


def test_with_no_folder_the_persisted_store_opens_with_no_offload(monkeypatch, served_in_memory, caplog):
    """The folder cannot be made: the store still opens, bounded and with no offload (never DuckDB's default), and says so."""
    state, _old, _spill = served_in_memory
    monkeypatch.setattr(rollup_serve, "_persisted_spill_setting", lambda: "")
    got: dict = {}

    def open_store(*_a, **k):
        got.update(k)
        return columnar.OpenedStore(_Con(), "persisted")

    monkeypatch.setattr(columnar, "open_store", open_store)
    with caplog.at_level("WARNING", logger=rollup_serve._LOG.name):
        assert rollup_serve._refresh_persisted_build() is True
    assert got["persisted_spill"] is None and state["spill"] is None
    assert "no offload folder" in caplog.text
