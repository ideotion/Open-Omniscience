"""
A settings read that FAILS never reads as the defaults (which are the direct connection), a retry runs only for the failure it
was built for, a failed read is logged by class, and the writers that rewrite what they read refuse on a failed read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.config import kv_store
from src.safety import fetcher as fetcher_mod
from src.safety import settings as S
from src.safety.fetcher import (
    TransportUnavailable,
    following_session,
    guarded_session,
    make_fetcher,
)

SOCKS = "socks5h://127.0.0.1:9050"
_REAL: dict = {}


class _Wrong(RuntimeError):
    """Stands in for ``WrongPassphraseError`` (the keyed driver is not needed to pin the retry policy)."""


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    for name in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(fetcher_mod, "_FOLLOWING", {})
    kv_store.kv_invalidate()
    yield monkeypatch
    kv_store.kv_invalidate()


def _store(env, mode="protected"):
    S.save_settings({"fetch_mode": mode, "http_proxy": SOCKS})
    kv_store.kv_invalidate()


def _heal(env):
    env.setattr(kv_store, "_read_value", _REAL["read"])
    kv_store.kv_invalidate()


def _fail_reads(env, exc=None):
    """Every read of the store fails with ``exc``; returns the list of ``read_only`` flags the opens were made with."""
    calls: list[bool] = []
    _REAL.setdefault("read", kv_store._read_value)

    def boom(path, key, *, read_only):
        calls.append(read_only)
        raise exc if exc is not None else _Wrong("secret engine words")

    env.setattr(kv_store, "_read_value", boom)
    return calls


# --- the retry --------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("exc", [_Wrong("wrong key"), TimeoutError("busy"), RuntimeError("database is locked")])
def test_a_failure_the_read_write_retry_was_not_built_for_is_not_retried(env, exc):
    """MUTATION TARGET: ``_ro_only_failure`` widened. A wrong-key read-write open folds and deletes a leftover ``-wal``, and a lock
    would stall twice."""
    _store(env)
    calls = _fail_reads(env, exc)
    with pytest.raises(kv_store.KvReadError):
        kv_store.kv_get_json_checked(S._KV_KEY)
    assert calls == [True], calls


def test_the_failure_a_read_only_open_has_and_a_read_write_one_does_not_is_retried(env):
    _store(env)

    class OperationalError(Exception):  # the keyed driver's own class has this name
        pass

    seen: list[bool] = []

    def fake(path, key, *, read_only):
        seen.append(read_only)
        if read_only:
            raise OperationalError("attempt to write a readonly database")
        return '{"fetch_mode": "protected"}'

    env.setattr(kv_store, "_read_value", fake)
    assert kv_store.kv_get_json_checked(S._KV_KEY) == {"fetch_mode": "protected"}
    assert seen == [True, False]


# --- the log ----------------------------------------------------------------------------------------------------------- #
def test_a_failed_read_is_logged_by_class_and_the_source_has_no_traceback_sink():
    """MUTATION TARGET: ``exc_info=`` back on a log line of ``kv_store`` (a keyed open's error chains the driver's own)."""
    src = Path(kv_store.__file__).read_text(encoding="utf-8")
    assert "exc_info" not in src and ".exception(" not in src


def test_the_records_of_a_failed_read_carry_the_class_and_no_traceback(env, caplog):
    _store(env)
    _fail_reads(env)
    with caplog.at_level(logging.DEBUG, logger=kv_store.__name__), pytest.raises(kv_store.KvReadError) as err:
        kv_store.kv_get_json_checked(S._KV_KEY)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert all(r.exc_info is None and "secret engine words" not in r.getMessage() for r in caplog.records)
    assert any("_Wrong" in r.getMessage() for r in caplog.records)


# --- fail closed ------------------------------------------------------------------------------------------------------- #
def test_an_absent_store_is_the_defaults_and_an_unreadable_one_is_not(env):
    assert not S.load_settings().is_protected and not S.load_settings().read_failed
    _store(env, "transparent")
    _fail_reads(env)
    kv_store.kv_invalidate()
    s = S.load_settings()
    assert s.is_protected and s.http_proxy == "" and s.read_failed
    assert "read_failed" not in s.to_dict()


def test_no_session_or_fetcher_is_direct_while_the_store_cannot_be_read(env):
    """MUTATION TARGET: ``load_settings`` answering the defaults for a failed read, or ``KvReadError`` swallowed in ``_read_raw``."""
    _store(env, "transparent")
    _fail_reads(env)
    kv_store.kv_invalidate()
    s = guarded_session()
    assert s.transport_refusal and not s.proxies
    with pytest.raises(TransportUnavailable):
        make_fetcher()


def test_a_session_already_built_keeps_its_transport_when_the_read_fails_and_the_next_good_read_rebuilds(env):
    _store(env)
    good = following_session("wiki", "ua")
    assert good.transport_proxy == SOCKS
    calls = _fail_reads(env)
    kv_store.kv_invalidate()
    for _ in range(3):
        assert following_session("wiki", "ua") is good, "a failed read moved a live client's transport"
    assert len(calls) == 1, "the failed store was opened again for every request"
    _heal(env)
    assert following_session("wiki", "ua").transport_proxy == SOCKS


def test_a_client_first_used_while_the_store_cannot_be_read_gets_a_refusing_session_that_the_next_good_read_replaces(env):
    _store(env, "transparent")
    calls = _fail_reads(env)
    kv_store.kv_invalidate()
    first = following_session("ores", "ua")
    assert first.transport_refusal
    _heal(env)
    second = following_session("ores", "ua")
    assert second is not first and not second.transport_refusal
    assert calls


def test_a_stream_is_not_moved_by_a_failed_read(env):
    """The stream ends a connection when ``client.session`` is no longer the session it opened with."""
    _store(env)
    opened = following_session("wiki", "ua")
    _fail_reads(env)
    kv_store.kv_invalidate()
    assert following_session("wiki", "ua") is opened


# --- the writers ------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("module", "error", "update"),
    [
        ("src.config.app_settings", "AppSettingsError", {"theme": "dark"}),
        ("src.scheduler.settings", "SchedulerSettingsError", {"auto_run_market_rules": False}),
        ("src.custody.settings", "CustodySettingsError", {"auto_log_on_ingest": True}),
    ],
)
def test_a_save_after_a_failed_read_refuses_and_writes_nothing(env, module, error, update):
    """MUTATION TARGET: ``save_settings`` reading through the lenient ``load_settings``: a failed read is the defaults, and the save
    writes them over the user's settings."""
    import importlib

    mod = importlib.import_module(module)
    mod.save_settings(update)
    kv_store.kv_invalidate()
    writes: list[str] = []
    env.setattr(kv_store, "kv_set_json", lambda *a, **k: writes.append("write"))

    def broken(key):
        raise RuntimeError("engine words that must stay out")

    env.setattr(kv_store, "kv_get_json_strict", broken)
    env.setattr(kv_store, "kv_get_json", lambda key: None)  # what a locked store reads as, leniently
    with pytest.raises(getattr(mod, error)) as err:
        mod.save_settings(update)
    assert "RuntimeError" in str(err.value) and "engine words" not in str(err.value)
    assert writes == []


def test_a_wrong_key_read_of_an_encrypted_store_with_a_leftover_log_fails_closed_and_leaves_the_log_untouched(env, tmp_path):
    """MUTATION TARGET: the read-write retry taken for a wrong key. A read-write close folds a leftover ``-wal`` into the file and
    deletes it, with a wrong key too (measured in ``test_connect_read_only``), and that log is the evidence of how the last session
    ended. On a REAL keyed store."""
    pytest.importorskip("sqlcipher3")
    from tests.test_connect_read_only import _KEY, _crashed, _fingerprint

    from src.database import connect as connect_mod

    folder = tmp_path / "enc"
    db = _crashed(folder, _KEY)
    db.rename(folder / "open_omniscience.db")
    for suffix in ("-wal", "-shm"):
        side = Path(str(db) + suffix)
        if side.exists():
            side.rename(folder / ("open_omniscience.db" + suffix))
    db = folder / "open_omniscience.db"
    env.setenv("OO_DATA_DIR", str(folder))
    kv_store.kv_invalidate()
    before = _fingerprint(db)
    connect_mod.set_passphrase("not the key")
    try:
        with pytest.raises(kv_store.KvReadError):
            kv_store.kv_get_json_checked(S._KV_KEY)
        assert S.load_settings().read_failed
    finally:
        connect_mod.set_passphrase(None)
    assert _fingerprint(db) == before, "a failed read moved the file or consumed its log"
