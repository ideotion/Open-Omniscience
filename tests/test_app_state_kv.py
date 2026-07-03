"""
The ``app_state`` kv store + the settings→DB migration (DB-reliability D1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the durability win: settings now live in a row of the (encrypted) corpus DB,
transactionally, instead of a loose JSON side-file — while the read/write API each
caller uses is unchanged, and a pre-existing JSON file is migrated once, idempotently.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.config import kv_store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # Each test gets its own data dir (lazy data_dir() resolution) + a clean cache.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    kv_store.kv_invalidate()
    yield
    kv_store.kv_invalidate()


def _db(tmp_path):
    return tmp_path / "open_omniscience.db"


# --------------------------------------------------------------------------- #
# The generic kv primitive
# --------------------------------------------------------------------------- #
def test_kv_get_is_none_when_empty():
    assert kv_store.kv_get_json("settings.app") is None


def test_kv_set_then_get_round_trips(tmp_path):
    kv_store.kv_set_json("settings.app", {"theme": "dark", "n": 3})
    assert kv_store.kv_get_json("settings.app") == {"theme": "dark", "n": 3}
    # It really landed in a row of the corpus DB (durable + encryptable + backed up).
    con = sqlite3.connect(_db(tmp_path))
    try:
        (val,) = con.execute("SELECT value FROM app_state WHERE key='settings.app'").fetchone()
    finally:
        con.close()
    assert json.loads(val)["theme"] == "dark"


def test_kv_set_upserts_not_duplicates(tmp_path):
    kv_store.kv_set_json("k", {"v": 1})
    kv_store.kv_set_json("k", {"v": 2})
    assert kv_store.kv_get_json("k") == {"v": 2}
    con = sqlite3.connect(_db(tmp_path))
    try:
        (n,) = con.execute("SELECT COUNT(*) FROM app_state WHERE key='k'").fetchone()
    finally:
        con.close()
    assert n == 1


def test_kv_cache_survives_row_delete_until_invalidated(tmp_path):
    kv_store.kv_set_json("k", {"v": 1})
    con = sqlite3.connect(_db(tmp_path))
    try:
        con.execute("DELETE FROM app_state WHERE key='k'")
        con.commit()
    finally:
        con.close()
    # Still cached (single-process coherence): the reader trusts its own last write.
    assert kv_store.kv_get_json("k") == {"v": 1}
    kv_store.kv_invalidate("k")
    assert kv_store.kv_get_json("k") is None


def test_kv_delete_removes_the_row(tmp_path):
    kv_store.kv_set_json("k", {"v": 1})
    kv_store.kv_delete("k")
    assert kv_store.kv_get_json("k") is None


# --------------------------------------------------------------------------- #
# App settings: DB-backed, API unchanged, JSON migrated once
# --------------------------------------------------------------------------- #
def test_app_settings_save_writes_db_not_json(tmp_path):
    from src.config import app_settings as aset

    aset.save_settings({"theme": "dark", "default_result_limit": 42})
    # No JSON side-file is created any more — the durable home is the DB.
    assert not (tmp_path / "app_settings.json").exists()
    reloaded = aset.load_settings()
    assert reloaded.theme == "dark"
    assert reloaded.default_result_limit == 42
    # And it is in the app_state row.
    assert kv_store.kv_get_json("settings.app")["theme"] == "dark"


def test_app_settings_migrates_legacy_json_once(tmp_path):
    from src.config import app_settings as aset

    # A pre-existing legacy file (from before this feature).
    (tmp_path / "app_settings.json").write_text(
        json.dumps({"version": "oo-app-settings-1", "theme": "light",
                    "default_result_limit": 7}), "utf-8")
    kv_store.kv_invalidate()

    s = aset.load_settings()
    assert s.theme == "light" and s.default_result_limit == 7
    # Migrated into the DB on first load.
    assert kv_store.kv_get_json("settings.app")["theme"] == "light"

    # Idempotent: deleting the legacy file changes nothing (DB is now the source).
    (tmp_path / "app_settings.json").unlink()
    kv_store.kv_invalidate()
    assert aset.load_settings().theme == "light"


def test_app_settings_defaults_when_nothing_stored():
    from src.config import app_settings as aset

    s = aset.load_settings()
    assert s.theme == "system"
    assert s.default_result_limit == 50


# --------------------------------------------------------------------------- #
# The other three settings modules round-trip + default correctly through the DB
# --------------------------------------------------------------------------- #
def test_custody_settings_round_trip_through_db(tmp_path):
    from src.custody import settings as cset

    assert cset.load_settings().anchoring_mode == "local"  # honest default
    cset.save_settings({"anchoring_mode": "opentimestamps", "pqc_enabled": True})
    assert not (tmp_path / "custody_settings.json").exists()
    s = cset.load_settings()
    assert s.anchoring_mode == "opentimestamps" and s.pqc_enabled is True


def test_scheduler_settings_round_trip_through_db(tmp_path):
    from src.scheduler import settings as sset

    sset.save_settings({"interval_minutes": 45, "continuous": False})
    assert not (tmp_path / "scheduler_settings.json").exists()
    s = sset.load_settings()
    assert s.interval_minutes == 45 and s.continuous is False


def test_safety_settings_round_trip_and_env_override(tmp_path, monkeypatch):
    from src.safety import settings as sset

    sset.save_settings({"fetch_mode": "protected", "http_proxy": "socks5://127.0.0.1:9050"})
    assert not (tmp_path / "safety_settings.json").exists()
    assert sset.load_settings().fetch_mode == "protected"
    # Env still overrides the persisted value (headless use) — behaviour preserved.
    monkeypatch.setenv("OO_FETCH_MODE", "transparent")
    assert sset.load_settings().fetch_mode == "transparent"


def test_safety_settings_migrates_legacy_json(tmp_path):
    from src.safety import settings as sset

    (tmp_path / "safety_settings.json").write_text(
        json.dumps({"version": "oo-safety-settings-1", "fetch_mode": "protected",
                    "http_proxy": "socks5://127.0.0.1:9050"}), "utf-8")
    kv_store.kv_invalidate()
    assert sset.load_settings().fetch_mode == "protected"
    assert kv_store.kv_get_json("settings.safety")["fetch_mode"] == "protected"
