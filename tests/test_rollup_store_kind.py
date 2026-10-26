"""0.5.1 rollup in-memory fallback misreported as persisted (R268/R269): the opener REPORTS which store it opened.

Before: ``columnar.connect`` returned ``None`` only when the engine is off, and a persisted open that failed (the encryption gate, or the open
itself) fell back to an in-memory connection indistinguishable from a persisted one; ``_refresh_persisted_build`` recorded it as the persisted
store and the dispatcher reported it built. And ``_build_inmemory_and_swap`` returned ``None`` ("built") when the engine was off
(``OO_COLUMNAR=0``), which ``serve_enabled()`` did not honour.
After: ``columnar.open_store`` returns ``OpenedStore(con, kind, fallback_reason)``; a non-persisted store is closed and declined, and an engine
that is off is a decline with no hold, with ``serve_enabled()`` False.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb")

from src.analytics import columnar, rollup_hold, rollup_serve  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_COLUMNAR", raising=False)
    monkeypatch.delenv("OO_COLUMNAR_SERVE", raising=False)
    keys = ("con", "stopped", "failures", "failure_class", "last_outcome", "last_decline", "last_skip", "persisted", "built_at", "bind")
    keep = {k: rollup_serve._STATE.get(k) for k in keys}
    rollup_serve._STATE.update(con=None, stopped=None, failures=0, failure_class=None, last_outcome=None, last_decline=None,
                               last_skip=None, persisted=False, built_at=0.0, bind=None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", False)
    rollup_serve._PERSISTED_DECLINE["why"] = None
    yield
    rollup_serve._STATE.update(keep)
    rollup_serve._PERSISTED_DECLINE["why"] = None


class _Con:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_the_opener_reports_off_when_the_engine_is_off(monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR", "0")
    opened = columnar.open_store("pw")
    assert (opened.con, opened.kind, opened.fallback_reason) == (None, "off", None)
    assert columnar.connect("pw") is None, "connect() keeps answering None for an engine that is off"


def test_a_deliberate_in_memory_request_is_memory_with_no_fallback_reason():
    opened = columnar.open_store(None)
    try:
        assert opened.kind == "memory" and opened.fallback_reason is None and opened.con is not None
    finally:
        opened.con.close()


def test_a_persisted_request_without_a_secure_backend_says_so(monkeypatch):
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: False)
    opened = columnar.open_store("pw")
    try:
        assert opened.kind == "memory" and opened.fallback_reason == "no-secure-backend"
    finally:
        opened.con.close()


def test_a_failed_encryption_gate_is_a_reported_fallback_not_a_persisted_store(monkeypatch):
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "encryption_gate", lambda _p: False)
    opened = columnar.open_store("pw")
    try:
        assert opened.kind == "memory" and opened.fallback_reason == "encryption-gate-failed"
    finally:
        opened.con.close()


def test_a_persisted_open_that_raises_is_a_reported_fallback_and_never_carries_the_exceptions_words(monkeypatch):
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "encryption_gate", lambda _p: True)

    def boom(_path, _key):
        raise RuntimeError("engine words that must not be kept")

    monkeypatch.setattr(columnar, "_attach_persisted", boom)
    opened = columnar.open_store("pw")
    try:
        assert opened.kind == "memory" and opened.fallback_reason == "persisted-open-failed"
        assert "engine words" not in repr(opened)
    finally:
        opened.con.close()


def test_a_persisted_open_that_succeeds_is_persisted_with_no_fallback_reason(monkeypatch):
    import duckdb

    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "encryption_gate", lambda _p: True)
    con = duckdb.connect(":memory:")
    monkeypatch.setattr(columnar, "_attach_persisted", lambda _path, _key: con)
    opened = columnar.open_store("pw")
    try:
        assert opened.kind == "persisted" and opened.fallback_reason is None and opened.con is con
    finally:
        con.close()


@pytest.mark.parametrize("fallback", ["encryption-gate-failed", "persisted-open-failed"])
def test_the_persisted_refresh_closes_an_in_memory_store_it_was_handed_and_records_nothing(monkeypatch, fallback):
    con = _Con()
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: columnar.OpenedStore(con, "memory", fallback))
    assert rollup_serve._refresh_persisted_build() is False
    assert con.closed, "the unwanted in-memory store was left open"
    assert rollup_serve._STATE["persisted"] is False and rollup_serve._STATE["con"] is None
    assert rollup_serve._PERSISTED_DECLINE["why"] == fallback


def test_the_dispatcher_puts_the_fallback_code_in_last_skip(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: columnar.OpenedStore(_Con(), "memory", "encryption-gate-failed"))
    for name in ("_boot_order_verdict", "_affordability_verdict", "_memory_verdict", "_last_build_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    skip = rollup_serve._STATE["last_skip"]
    assert skip["reason"] == "persisted-unavailable" and skip["why"] == "encryption-gate-failed"
    assert rollup_serve._PERSISTED_DECLINE["why"] is None, "the code is read once and cleared"


def test_serve_enabled_is_false_when_the_engine_is_off_even_if_forced_on(monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR", "0")
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    assert rollup_serve.serve_enabled() is False


def test_an_engine_that_is_off_is_a_decline_with_no_hold_never_built(monkeypatch):
    """The in-memory build used to return ``None`` (= built and swapped in) when ``connect`` gave no connection."""
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    for name in ("_boot_order_verdict", "_affordability_verdict", "_memory_verdict", "_last_build_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)  # a caller that kicked before the setting was read
    monkeypatch.setenv("OO_COLUMNAR", "0")
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "failed")
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    assert rollup_serve._LAST_OUTCOME["value"] != "built"
    assert rollup_serve._STATE["stopped"] is None and rollup_hold.read() is None, "a setting is not a stop: no hold"
    skip = rollup_serve._STATE["last_skip"]
    assert skip["reason"] == rollup_serve.ENGINE_OFF and skip["source"] == "engine"
    assert rollup_serve._STATE["con"] is None


def test_the_map_serve_is_not_enabled_when_the_engine_is_off_either(monkeypatch):
    """Same gate gap as the keyword rollup: ``OO_COLUMNAR=0`` switched the engine off but the map serve stayed enabled and kicked a build per call."""
    from src.analytics import map_serve

    monkeypatch.delenv("OO_COLUMNAR_MAP_SERVE", raising=False)
    assert map_serve.serve_enabled() is True, "negative space: the engine on, the serve is on"
    monkeypatch.setenv("OO_COLUMNAR", "0")
    assert map_serve.serve_enabled() is False
    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")
    assert map_serve.serve_enabled() is False, "forced on cannot turn an engine that is off back on"
