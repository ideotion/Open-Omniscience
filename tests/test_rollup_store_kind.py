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
    rollup_serve._PERSISTED_FELL_BACK["why"] = None
    yield
    rollup_serve._STATE.update(keep)
    rollup_serve._PERSISTED_DECLINE["why"] = None
    rollup_serve._PERSISTED_FELL_BACK["why"] = None


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


def _kick_ready(monkeypatch, *, fallback):
    """A dispatcher whose verdicts all pass and whose persisted opener answers ``fallback``; returns the list of in-memory builds started."""
    builds: list = []
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: columnar.OpenedStore(_Con(), "memory", fallback))
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: builds.append(1))
    for name in ("_boot_order_verdict", "_affordability_verdict", "_memory_verdict", "_last_build_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)
    return builds


def _kick():
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    return rollup_serve._build_and_swap()


@pytest.mark.parametrize("fallback", ["encryption-gate-failed", "persisted-open-failed"])
def test_a_persisted_open_that_fell_back_builds_in_memory_in_the_same_kick_and_says_why(monkeypatch, fallback):
    builds = _kick_ready(monkeypatch, fallback=fallback)
    assert _kick() == "built"
    assert builds == [1], "the in-memory build did not run: every kick would decline and the rollup would never be served"
    skip = rollup_serve._STATE["last_skip"]
    assert skip["reason"] == "persisted-unavailable" and skip["why"] == fallback and skip["source"] == "persisted"
    assert rollup_serve._PERSISTED_DECLINE["why"] is None, "the code is read once and cleared"
    assert rollup_serve._PERSISTED_FELL_BACK["why"] == fallback


def test_after_a_fallback_the_process_serves_in_memory_and_does_not_retry_the_persisted_open(monkeypatch):
    builds = _kick_ready(monkeypatch, fallback="persisted-open-failed")
    opens: list = []
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: (opens.append(1), columnar.OpenedStore(_Con(), "memory", "persisted-open-failed"))[1])
    assert _kick() == "built"
    assert rollup_serve._persisted_serve_active() is False, "the verdicts must read the in-memory holds the fallback build keeps"
    assert _kick() == "built"
    assert len(opens) == 1 and builds == [1, 1], "the second kick went through the persisted open again"


def test_an_in_memory_build_that_fails_after_a_fallback_keeps_the_in_memory_hold(monkeypatch):
    _kick_ready(monkeypatch, fallback="encryption-gate-failed")

    def boom():
        raise RuntimeError("engine words that must not be kept")

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", boom)
    assert _kick() == "failed"
    held = rollup_serve._STATE["stopped"]
    assert held["reason"] == "build-failed" and "store" not in held, "the hold is the in-memory one, not a persisted one"
    assert rollup_serve._stopped_build_verdict() is not None, "the next verdict must see it: persisted is no longer the active store"


@pytest.mark.parametrize("why", ["no-secure-backend", "engine-off"])
def test_a_persisted_decline_that_is_not_a_fallback_builds_nothing(monkeypatch, why):
    builds = _kick_ready(monkeypatch, fallback=None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)  # the verdict said persisted; the refresh finds it gone
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: why != "no-secure-backend")
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: columnar.OpenedStore(None, "off"))
    assert _kick() == "declined"
    assert builds == [] and rollup_serve._STATE["last_skip"]["why"] == why
    assert rollup_serve._PERSISTED_FELL_BACK["why"] is None


def test_the_persisted_refresh_records_a_store_the_opener_says_is_persisted(monkeypatch):
    """Negative space for the declines: the success path still records the persisted store (a refresh that always declined would pass every test above)."""
    import duckdb

    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE keyword_daily(keyword VARCHAR, day DATE, n INTEGER)")
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "open_store", lambda *a, **k: columnar.OpenedStore(con, "persisted"))
    monkeypatch.setattr(columnar, "refresh_keyword_daily", lambda *a, **k: None)
    monkeypatch.setattr("src.analytics.serve_gate.change_token", lambda _s: "t")
    monkeypatch.setattr("src.analytics.corpus_epoch.get_corpus_epoch", lambda _s: 1)
    try:
        assert rollup_serve._refresh_persisted_build() is not False
        assert rollup_serve._STATE["persisted"] is True and rollup_serve._STATE["con"] is con
        assert rollup_serve._PERSISTED_DECLINE["why"] is None
    finally:
        con.close()


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
