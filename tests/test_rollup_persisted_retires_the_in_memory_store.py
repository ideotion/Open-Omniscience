"""The persisted refresh retires the in-memory rollup it replaces (open-on-main row 25).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: when the process was serving an IN-MEMORY rollup and the persisted store became available (the passphrase was set, the
secure backend arrived), ``_refresh_persisted_build`` wrote its persisted connection over ``_STATE["con"]`` without closing the
in-memory one, which kept holding up to DuckDB's whole memory limit until the process ended, and left that store's offload folder
(``_STATE["spill"]``, under the data directory) on disk.
"""

from __future__ import annotations

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

    old = _Con()
    spill = tmp_path / "duckdb_tmp" / "123-abcd"
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
    assert state.get("spill") is None
    assert not new.closed


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
    assert state["con"] is old and not old.closed and spill.exists()
    assert new.closed, "the persisted connection this attempt opened is released"
