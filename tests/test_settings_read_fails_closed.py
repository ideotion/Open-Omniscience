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
    from src.database import connect as connect_mod
    from tests.test_connect_read_only import _KEY, _crashed, _fingerprint

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


# --- fold 13 ------------------------------------------------------------------------------------------------------------ #
def _damage_the_stored_value(tmp_path, text):
    import sqlite3

    con = sqlite3.connect(tmp_path / "open_omniscience.db")
    con.execute("UPDATE app_state SET value = ? WHERE key = ?", (text, S._KV_KEY))
    con.commit()
    con.close()
    kv_store.kv_invalidate()


@pytest.mark.parametrize("text", ['{"fetch_mode": "prot', "[1, 2]", "not json"], ids=["truncated", "not-an-object", "garbage"])
def test_a_stored_value_that_is_there_and_damaged_fails_closed_not_as_the_defaults(env, tmp_path, text):
    """MUTATION TARGET: ``kv_get_json_checked`` returning ``_loads(raw)`` (damaged reads as absent, then as the direct connection)."""
    _store(env, "transparent")
    _damage_the_stored_value(tmp_path, text)
    with pytest.raises(kv_store.KvReadError):
        kv_store.kv_get_json_checked(S._KV_KEY)
    assert kv_store.kv_get_json(S._KV_KEY) is None, "the lenient reader keeps its old answer for other callers"
    s = S.load_settings()
    assert s.read_failed and s.is_protected and not s.http_proxy


def test_a_corrupt_legacy_settings_file_fails_closed(env, tmp_path):
    (tmp_path / "safety_settings.json").write_text('{"fetch_mode": "prot', encoding="utf-8")
    s = S.load_settings()
    assert s.read_failed and s.is_protected
    (tmp_path / "safety_settings.json").write_text("[1]", encoding="utf-8")
    assert S.load_settings().read_failed
    with pytest.raises(S.SafetySettingsError) as err:
        S.save_settings({"discovery_external_enabled": True})
    assert "JSONDecodeError" in str(err.value) or "NotAnObject" in str(err.value) or "KvReadError" in str(err.value)


def test_a_store_that_was_read_and_is_gone_fails_closed_and_one_never_there_is_a_first_run(env, tmp_path):
    first = S.load_settings()
    assert not first.read_failed and not first.is_protected, "a first run keeps the defaults"
    _store(env)
    S.load_settings()
    (tmp_path / "open_omniscience.db").unlink()
    with kv_store._lock:
        kv_store._cache.clear()
    assert S.load_settings().read_failed


def test_the_first_run_defaults_send_nothing_because_the_app_boots_offline(env):
    """R117: a first run has no store, so the defaults (direct) apply; what keeps them from sending is the airplane switch the BOOT
    engages (driven through the boot path, not by engaging it here), which the session refuses under."""
    from unittest.mock import patch

    from src import ingest as I

    try:
        from src.api import main as M
    except BaseException:  # noqa: BLE001 - the same guard as test_boot_airplane_never_revokes_online
        pytest.skip("src.api.main is unimportable here (CI runs it)")
    env.delenv("OO_NO_SCHEDULER", raising=False)
    # the upkeep would start a REAL boot-sequence thread that nobody joins, and it would write into the next test that patches the
    # boot steps (see tests/test_boot_airplane_never_revokes_online.py::_no_boot_sequence_thread)
    env.setattr("src.api.boot_sequence.run", lambda *a, **k: None)
    I._reset_crossed_online_for_tests()
    I.clear_kill_switch()
    try:
        assert not S.load_settings().read_failed and not S.load_settings().is_protected
        with patch("src.ingest.airplane.install_airplane_socket_guard"):
            M._run_startup_upkeep()
        assert I.kill_switch_active(), "the boot did not go offline"
        with pytest.raises(Exception, match=r"(?i)airplane|offline|kill|blocked"):
            guarded_session().get("https://example.org/", timeout=2)
    finally:
        I._reset_crossed_online_for_tests()
        I.clear_kill_switch()


def test_the_refusal_of_an_unreadable_store_says_so_and_does_not_tell_the_user_to_set_a_proxy(env):
    from src.safety.fetcher import NO_PROXY_REFUSAL, READ_FAILED_REFUSAL, transport_summary

    _store(env)
    _fail_reads(env)
    kv_store.kv_invalidate()
    s = S.load_settings()
    assert guarded_session().transport_refusal == READ_FAILED_REFUSAL != NO_PROXY_REFUSAL
    assert "no proxy" not in READ_FAILED_REFUSAL and "could not be read" in READ_FAILED_REFUSAL
    assert transport_summary(s) == {"kind": "unknown", "reason": "unreadable"}
    from src.api import safety as api

    assert api._settings_payload(s)["read_failed"] is True


def test_a_good_unlock_clears_the_held_failure_so_fetches_do_not_refuse_for_two_more_seconds(env):
    from src.database import connect as connect_mod

    _store(env)
    _fail_reads(env)
    kv_store.kv_invalidate()
    assert S.load_settings().read_failed
    env.setattr(kv_store, "_read_value", _REAL["read"])  # the store reads now, but the failure is held
    assert S.load_settings().read_failed
    connect_mod.set_passphrase(None)
    assert not S.load_settings().read_failed


def test_a_held_session_is_returned_on_a_failed_read_only_for_the_user_agent_it_was_built_with(env):
    _store(env)
    good = following_session("wiki", "ua-one")
    _fail_reads(env)
    kv_store.kv_invalidate()
    other = following_session("wiki", "ua-two")
    assert other is not good and other.transport_refusal and other.headers["User-Agent"] == "ua-two"


def test_no_module_that_logs_around_the_store_or_the_ledger_writes_a_traceback():
    """MUTATION TARGET: ``exc_info=`` back on a log line of one of these (a keyed open chains the driver's own error; the session
    ledger's records are in the bundle). ``log_failure`` writes the same traceback with every passphrase out of it."""
    import src.config.app_settings as a
    import src.custody.settings as c
    import src.monitoring.session_hwm as hwm
    import src.scheduler.settings as sch

    for mod in (kv_store, S, a, c, sch, hwm):
        text = Path(mod.__file__).read_text(encoding="utf-8")
        assert "exc_info" not in text, mod.__name__
    assert "str(exc)" not in Path(hwm.__file__).read_text(encoding="utf-8")



# --- fold 14 ------------------------------------------------------------------------------------------------------------ #
def test_choosing_the_connection_again_replaces_a_damaged_value_and_the_next_read_is_good(env, tmp_path):
    """The way out of a damaged value is the user's own action: a save that supplies the whole choice. MUTATION TARGET:
    ``_DamagedSettings`` re-raised for a full save, or caught for a partial one."""
    _store(env, "transparent")
    _damage_the_stored_value(tmp_path, '{"fetch_mode": "prot')
    assert S.load_settings().read_failed
    with pytest.raises(S.SafetySettingsError) as err:
        S.save_settings({"discovery_external_enabled": True})
    assert "choose the connection again" in str(err.value) and "JSONDecodeError" in str(err.value)
    with pytest.raises(S.SafetySettingsError):
        S.save_settings({"fetch_mode": "protected"})  # half a choice
    saved = S.save_settings({"fetch_mode": "protected", "http_proxy": SOCKS})
    assert saved.is_protected and saved.http_proxy == SOCKS
    assert saved.reset_fields == ["http_proxies", "discovery_external_enabled"], "what the save did not supply is reported as reset"
    kv_store.kv_invalidate()
    again = S.load_settings()
    assert not again.read_failed and again.http_proxy == SOCKS


def test_a_locked_store_is_never_replaced_by_a_full_save(env):
    """Only a value that is there and damaged is replaced; a store that could not be opened may hold a good choice."""
    _store(env)

    def boom(key):
        raise RuntimeError("database is locked")

    env.setattr(kv_store, "kv_get_json_strict", boom)
    with pytest.raises(S.SafetySettingsError) as err:
        S.save_settings({"fetch_mode": "transparent", "http_proxy": ""})
    assert "choose the connection again" not in str(err.value)


def test_a_corrupt_legacy_file_is_replaced_by_a_full_save_and_not_read_again(env, tmp_path):
    legacy = tmp_path / "safety_settings.json"
    legacy.write_text("{bad", encoding="utf-8")
    assert S.load_settings().read_failed
    S.save_settings({"fetch_mode": "transparent", "http_proxy": ""})
    kv_store.kv_invalidate()
    assert not S.load_settings().read_failed


def test_the_environment_decides_before_a_failed_read_does(env):
    _store(env, "transparent")
    _fail_reads(env)
    kv_store.kv_invalidate()
    env.setenv("OO_FETCH_MODE", "protected")
    env.setenv("OO_HTTP_PROXY", SOCKS)
    s = S.load_settings()
    assert not s.read_failed and s.http_proxy == SOCKS
    assert guarded_session().transport_proxy == SOCKS
    env.delenv("OO_FETCH_MODE")
    kv_store.kv_invalidate()
    s = S.load_settings()  # no mode named: protected, through the proxy the environment names
    assert s.is_protected and s.http_proxy == SOCKS and not s.read_failed


def test_a_store_that_is_created_or_erased_is_not_a_vanished_one_and_a_failed_unlock_does_not_forget_it(env, tmp_path):
    """The stores seen are forgotten where a key is actually set (unlock, create) and where the crypto-erase ran, never on a failed
    unlock's clearing of the key (``set_passphrase(None)``), which would blind the vanished-store check."""
    from src.database import connect as connect_mod

    _store(env)
    S.load_settings()
    (tmp_path / "open_omniscience.db").unlink()
    with kv_store._lock:
        kv_store._cache.clear()
    connect_mod.set_passphrase(None)  # a failed unlock clears the key
    assert S.load_settings().read_failed, "the vanished store went unnoticed after a failed unlock"
    kv_store.forget_stores()  # what the crypto-erase and a set key do
    with kv_store._lock:
        kv_store._failed.clear()
    assert not S.load_settings().read_failed
    _store(env)
    S.load_settings()
    (tmp_path / "open_omniscience.db").unlink()
    with kv_store._lock:
        kv_store._cache.clear()
    connect_mod.set_passphrase("a passphrase long enough for the test")
    try:
        assert not S.load_settings().read_failed
    finally:
        connect_mod.set_passphrase(None)


def test_the_crypto_erase_forgets_the_stores_seen_and_the_panic_wipe_goes_offline_for_good(env, tmp_path):
    """After a wipe the next settings read is a first run (the defaults, which are direct): the panic route engages the kill switch
    so a process still running online cannot rebuild a followed session from that read and leave Tor. MUTATION TARGET: the
    ``activate_kill_switch`` in ``panic_wipe``'s ``finally``, or the ``kv_invalidate`` beside it."""
    from src import ingest as I
    from src.api import insights, served_cache
    from src.safety import panic_wipe

    _store(env)
    session = following_session("wiki", "ua")
    assert session.transport_proxy == SOCKS
    insights._STATUS_MEMO.update(bind=object(), epoch=0, total_articles=5, indexed=5, mentions=9, duration_s=1.0, finished_at=0.0)
    served_cache._CACHE["insights:status"] = {"payload": {"total_articles": 5}, "bind": object(), "built_at": 0, "checked_at": 0, "probe": 1}
    I.clear_kill_switch()
    try:
        panic_wipe(tmp_path, confirm=True)
        assert I.kill_switch_active(), "the wipe left the app online"
        assert not kv_store._seen and not kv_store._cache, "the wiped store is still remembered"
        assert not served_cache._CACHE, "the served counts of the wiped corpus are still served"
        assert not insights._STATUS_MEMO, "the status scans carried beside them are still carried"
        with pytest.raises(Exception, match=r"(?i)airplane|offline|kill|blocked"):
            following_session("wiki", "ua").get("https://example.org/", timeout=2)
    finally:
        I.clear_kill_switch()


# --- fold 15: the other three preference modules ------------------------------------------------------------------------ #
_MODULES = [
    ("src.config.app_settings", "AppSettingsError", {"theme": "dark"}, "theme"),
    ("src.scheduler.settings", "SchedulerSettingsError", {"auto_run_market_rules": True}, "auto_run_market_rules"),
    ("src.custody.settings", "CustodySettingsError", {"auto_log_on_ingest": False}, "auto_log_on_ingest"),
]


@pytest.mark.parametrize(("module", "error", "update", "field"), _MODULES)
def test_a_damaged_value_is_replaced_by_the_users_own_save_and_refused_to_anything_else(env, tmp_path, module, error, update, field):
    """MUTATION TARGET: ``replace_damaged`` ignored (a damaged value refuses every save for good) or assumed (an automated save
    writes the defaults over it)."""
    import importlib
    import sqlite3

    mod = importlib.import_module(module)
    mod.save_settings(update)
    kv_store.kv_invalidate()
    con = sqlite3.connect(tmp_path / "open_omniscience.db")
    con.execute("UPDATE app_state SET value = ? WHERE key = ?", ('{"truncat', mod._KV_KEY))
    con.commit()
    con.close()
    kv_store.kv_invalidate()
    with pytest.raises(getattr(mod, error)) as err:
        mod.save_settings(update)  # an automated caller: refused
    assert "choose the settings again" in str(err.value) and "JSONDecodeError" in str(err.value)
    saved = mod.save_settings(update, replace_damaged=True)  # the user's save
    assert getattr(saved, field) == update[field]
    assert field not in saved.reset_fields and saved.reset_fields, "what the save did not supply is reported as reset"
    kv_store.kv_invalidate()
    assert getattr(mod.load_settings(), field) == update[field]
    mod.save_settings(update)  # and the next automated save is fine


@pytest.mark.parametrize(("module", "error", "update", "field"), _MODULES)
def test_a_locked_store_is_never_replaced_even_by_the_users_save(env, module, error, update, field):
    import importlib

    mod = importlib.import_module(module)
    mod.save_settings(update)
    kv_store.kv_invalidate()

    def boom(key):
        raise RuntimeError("database is locked")

    env.setattr(kv_store, "kv_get_json_strict", boom)
    with pytest.raises(getattr(mod, error)) as err:
        mod.save_settings(update, replace_damaged=True)
    assert "choose the settings again" not in str(err.value)


def test_the_users_routes_ask_for_the_replacement_and_serve_what_was_reset():
    """The routes are the user's own save; the internal callers (the LLM installer, the OSM picker) are not."""
    import inspect

    from src.api import custody as r_custody
    from src.api import scheduler as r_sched
    from src.api import settings as r_app

    for fn in (r_app.update_settings, r_custody.put_settings, r_sched.scheduler_update_config):
        src = inspect.getsource(fn)
        assert "replace_damaged=True" in src and '"reset"' in src, fn.__name__


# --- fold 16 ------------------------------------------------------------------------------------------------------------ #
def _damage_row(tmp_path, key):
    import sqlite3

    con = sqlite3.connect(tmp_path / "open_omniscience.db")
    con.execute("UPDATE app_state SET value = ? WHERE key = ?", ('{"truncat', key))
    con.commit()
    con.close()
    kv_store.kv_invalidate()


_ROUTES = [
    ("put", "/api/safety/settings", {"fetch_mode": "protected", "http_proxy": SOCKS}, "src.safety.settings"),
    ("put", "/api/settings", {"theme": "dark"}, "src.config.app_settings"),
    ("put", "/api/custody/settings", {"auto_log_on_ingest": False}, "src.custody.settings"),
    ("put", "/api/scheduler/config", {"auto_run_market_rules": True}, "src.scheduler.settings"),
]


@pytest.mark.parametrize(("verb", "url", "body", "module"), _ROUTES, ids=[r[1] for r in _ROUTES])
def test_the_users_route_over_a_damaged_value_replaces_it_and_serves_what_was_reset(env, tmp_path, verb, url, body, module):
    """The routes themselves, over a real damaged row (MUTATION TARGET: a route that drops ``replace_damaged=True`` answers 400
    for good; one that drops ``"reset"`` replaces silently)."""
    import importlib

    from fastapi.testclient import TestClient

    from src.api.main import app

    mod = importlib.import_module(module)
    env.setenv("OO_NO_SCHEDULER", "1")
    # a good value first, so the row exists; the safety module has its own seed
    if module == "src.safety.settings":
        _store(env)
    else:
        mod.save_settings(next(iter([{k: (not v) if isinstance(v, bool) else "light" for k, v in body.items()}])))
    kv_store.kv_invalidate()
    _damage_row(tmp_path, mod._KV_KEY)
    with TestClient(app) as c:
        r = getattr(c, verb)(url, json=body)
    assert r.status_code == 200, r.text
    reset = r.json()["reset"]
    assert isinstance(reset, list)
    if module == "src.safety.settings":
        assert reset == ["http_proxies", "discovery_external_enabled"]
    else:
        assert reset and not set(body) & set(reset)
    kv_store.kv_invalidate()
    again = mod.load_settings()
    assert not getattr(again, "read_failed", False)
    for k, v in body.items():
        assert getattr(again, k) == v


def test_only_the_three_users_routes_ask_for_the_replacement():
    """MUTATION TARGET: ``replace_damaged=True`` appearing in an automated caller (the LLM installer, the OSM picker, a scheduler
    loop), which would write the defaults over a damaged value without the user having chosen anything."""
    root = Path(__file__).resolve().parent.parent / "src"
    allowed = {"api/settings.py", "api/custody.py", "api/scheduler.py"}
    found = {
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*.py")
        if "replace_damaged=True" in p.read_text(encoding="utf-8")
    }
    assert found == allowed, found


def test_the_scheduler_replacement_writes_the_online_fields_it_was_not_given_off(env, tmp_path):
    """A repair must not start network work nobody asked for: the defaults are ``on``."""
    from src.scheduler import settings as SCH

    SCH.save_settings({"auto_run_market_rules": True})
    kv_store.kv_invalidate()
    _damage_row(tmp_path, SCH._KV_KEY)
    saved = SCH.save_settings({"auto_run_market_rules": True, "auto_track_law": True}, replace_damaged=True)
    kv_store.kv_invalidate()
    again = SCH.load_settings()
    assert saved.auto_track_law and again.auto_track_law, "what the user supplied stays as supplied"
    for off in ("continuous", "auto_track_signals", "auto_import_calendars", "crawl_supplement", "auto_refresh_stat_subscriptions"):
        assert getattr(again, off) is False, off
    assert again.wiki_lane_state == "halted"


def test_a_value_repaired_in_the_meantime_is_not_overwritten(env, tmp_path):
    """The replacement reads once more, uncached, first. MUTATION TARGET: the ``kv_invalidate`` before that read."""
    from src.config import app_settings as A

    A.save_settings({"theme": "dark"})
    kv_store.kv_invalidate()
    _damage_row(tmp_path, A._KV_KEY)
    with pytest.raises(A._DamagedAppSettingsError):
        A.load_settings(strict=True)  # the cache now holds the failure
    import sqlite3

    con = sqlite3.connect(tmp_path / "open_omniscience.db")  # another process repaired it, behind this one's cached failure
    con.execute("UPDATE app_state SET value = ? WHERE key = ?", ('{"theme": "light"}', A._KV_KEY))
    con.commit()
    con.close()
    saved = A.save_settings({"language": "fr"}, replace_damaged=True)
    assert saved.theme == "light" and not saved.reset_fields


def test_the_custody_replacement_keeps_the_no_record_default(env, tmp_path, monkeypatch):
    from src.custody import settings as C

    monkeypatch.setattr(C, "_legacy_auto_log_default", lambda: False)
    C.save_settings({"pqc_enabled": True})
    kv_store.kv_invalidate()
    _damage_row(tmp_path, C._KV_KEY)
    saved = C.save_settings({"pqc_enabled": True}, replace_damaged=True)
    assert saved.auto_log_on_ingest is False


def test_the_default_dir_crypto_erase_still_overwrites_when_forgetting_the_stores_fails(env, tmp_path, monkeypatch):
    """MUTATION TARGET: ``forget_stores()`` outside its guard in ``quick_crypto_erase`` (a raise there would skip the overwrite of
    everything under the data dir)."""
    from src.safety.crypto_erase import quick_crypto_erase

    _store(env)
    side = tmp_path / "side.txt"
    side.write_text("x" * 64, encoding="utf-8")

    def boom():
        raise RuntimeError("bookkeeping broke")

    monkeypatch.setattr(kv_store, "forget_stores", boom)
    report = quick_crypto_erase(confirm=True)  # data_dir=None: the default store (OO_DATA_DIR)
    assert not side.exists(), "the overwrite was skipped"
    assert report is not None
