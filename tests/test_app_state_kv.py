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


#: The stand-in for "the previous session's last connection was never closed": a process that commits a store in WAL mode and dies
#: without closing (``os._exit``), leaving ``-wal`` and ``-shm`` behind. The table and the row are ONE transaction on purpose: stdlib
#: sqlite3 commits a ``CREATE TABLE`` by itself, and a reader in this process that met the file between that commit and the insert
#: read "no row" and cached it (``kv_get_json_checked`` fills the cache with an absent value), which then answered the test's own read.
_LEFTOVER_WAL_STAND_IN = (
    "import sqlite3,os,sys\n"
    "c=sqlite3.connect(sys.argv[1],isolation_level=None)\n"
    "c.execute('PRAGMA journal_mode=WAL')\n"
    "c.execute('BEGIN')\n"
    "c.execute('CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)')\n"
    "c.execute(\"INSERT INTO app_state VALUES ('settings.app','{\\\"theme\\\": \\\"dark\\\"}','x')\")\n"
    "c.execute('COMMIT')\n"
    "os._exit(0)\n"
)


def _leave_a_wal(db) -> None:
    """Write the stand-in store, then drop what a reader in this process cached while the file was being written: the cache is
    single-process by contract, and this writer is a second process. Both halves stay: the transaction removes the table-without-row snapshot,
    and the invalidate removes a stale absent that any other reader cached, each sufficient alone (mutation-checked), neither redundant."""
    import subprocess
    import sys

    subprocess.run([sys.executable, "-c", _LEFTOVER_WAL_STAND_IN, str(db)], check=True)
    kv_store.kv_invalidate()


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
    cset.save_settings(
        {"anchoring_mode": "opentimestamps", "pqc_enabled": True, "ots_consent": True}
    )
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


# --------------------------------------------------------------------------- #
# A settings read consumes no evidence and creates no file
# --------------------------------------------------------------------------- #
def test_a_read_leaves_a_leftover_wal_byte_for_byte_and_still_reads_the_value(tmp_path):
    """MUTATION TARGET: ``read_only=True`` in ``kv_get_json``. The last connection that closes on a file checkpoints a leftover ``-wal``
    into it and deletes it: the one trace that the previous session's last connection was never closed."""
    import hashlib

    db = _db(tmp_path)
    _leave_a_wal(db)
    wal = tmp_path / "open_omniscience.db-wal"
    before = hashlib.sha256(wal.read_bytes()).hexdigest()
    # kv_get_json folds every failed read into None; the checked read says which kind it was, and the files say what the open met.
    try:
        got, why = kv_store.kv_get_json_checked("settings.app"), "the read found no value"
    except kv_store.KvReadError as exc:
        got, why = None, f"the read failed ({exc})"
    files = {f.name: f.stat().st_size for f in sorted(tmp_path.iterdir())}
    if got != {"theme": "dark"}:
        # A None has several silent causes (a store path that is not this one, a non-SQLite DATABASE_URL, a first-run fold of "no such table"): say which one met
        # THIS process, and what a direct read-only read of the file this test wrote answers (the files above are the ones the stand-in left, so a read that finds
        # nothing here with a different path, or an error here with None above, names the layer that dropped the value).
        import os

        try:
            direct = repr(kv_store._read_value(str(db), "settings.app", read_only=True))
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            direct = f"{type(exc).__name__}: {exc}"
        why += (f"; kv path {kv_store._db_path()!r} (this test wrote {str(db)!r}); DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}; "
                f"a direct read-only read of the file: {direct}")
    assert got == {"theme": "dark"}, f"{why}; files in the data dir (bytes): {files}; stdlib sqlite {sqlite3.sqlite_version}"
    assert wal.exists() and hashlib.sha256(wal.read_bytes()).hexdigest() == before


#: Rounds the next test runs. Against the two-commit stand-in (``CREATE TABLE`` committed by itself, no invalidation) a polling reader
#: left "no row" in the cache in 119 of 300 and 146 of 400 rounds measured (stdlib sqlite 3.45.1, ``rc-diagnostics/r236/``), 40 and 37
#: percent. Taking 30 percent as a floor BELOW both (a chosen margin, not a measurement) and the rounds as independent, a round misses
#: it with probability 0.7, and 20 rounds all missing it is 0.7**20 = 0.08 percent: the number keeps a green run against the old
#: stand-in a one-in-a-thousand event, not a habit.
_POLLED_ROUNDS = 20


def test_a_reader_polling_the_store_while_the_stand_in_is_written_cannot_leave_no_value_in_the_cache(tmp_path, monkeypatch):
    """MUTATION TARGET: ``_LEFTOVER_WAL_STAND_IN`` (the table and the row in separate commits) and the ``kv_invalidate()`` in ``_leave_a_wal``.
    A leftover thread from an earlier test follows the lazy ``data_dir()`` into the next test's directory (CI 2026-10-27 found a
    ``briefing_cache.json`` there) and reads settings while the second process writes the file: that read is allowed to see no value, and
    the test's own read afterwards must still find the one the stand-in committed. Needs no leftover thread to run: it brings its own."""
    import contextlib
    import threading

    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            for key in ("settings.app", "settings.other"):
                with contextlib.suppress(kv_store.KvReadError):
                    kv_store.kv_get_json_checked(key)

    failures = []
    for i in range(_POLLED_ROUNDS):
        round_dir = tmp_path / f"round{i}"
        round_dir.mkdir()
        monkeypatch.setenv("OO_DATA_DIR", str(round_dir))
        kv_store.kv_invalidate()
        stop.clear()
        poller = threading.Thread(target=poll, name=f"kv-poller-{i}")
        poller.start()
        try:
            _leave_a_wal(_db(round_dir))
            got = kv_store.kv_get_json_checked("settings.app")
        finally:
            stop.set()
            poller.join(timeout=30)
        assert not poller.is_alive(), "the poller thread must be joined before the test ends"
        if got != {"theme": "dark"}:
            failures.append((i, got))
    assert not failures, f"{len(failures)} of {_POLLED_ROUNDS} rounds read no value: {failures[:3]}"


def test_a_read_of_a_store_that_does_not_exist_creates_nothing(tmp_path):
    assert kv_store.kv_get_json("settings.app") is None
    assert list(tmp_path.iterdir()) == []


def test_a_hot_rollback_journal_is_recovered_by_the_fallback_and_never_reads_as_no_value(tmp_path, monkeypatch):
    """MUTATION TARGET: the read-write retry in ``kv_get_json``. A read-only open of a store with a hot rollback journal fails
    ("attempt to write a readonly database") where a read-write open recovers it, and a failed settings read means the defaults,
    which mean protected mode off."""
    import subprocess
    import sys

    work, snap = tmp_path / "work", tmp_path / "snap"
    work.mkdir()
    code = (
        "import sqlite3, shutil, os, sys\n"
        "src, dst = sys.argv[1], sys.argv[2]\n"
        "os.makedirs(dst, exist_ok=True)\n"
        "c = sqlite3.connect(src + '/open_omniscience.db', isolation_level=None)\n"
        "c.execute('PRAGMA journal_mode=DELETE')\n"
        "c.execute('CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)')\n"
        "c.execute('CREATE TABLE junk (a TEXT)')\n"
        "c.execute(\"INSERT INTO app_state VALUES ('settings.app','{\\\"theme\\\": \\\"dark\\\"}','x')\")\n"
        "c.execute('BEGIN')\n"
        "c.executemany('INSERT INTO junk VALUES (?)', [('x' * 500,) for _ in range(2000)])\n"
        "c.execute('PRAGMA cache_size=1')\n"
        "c.execute(\"UPDATE app_state SET value='{\\\"theme\\\": \\\"BROKEN\\\"}'\")\n"
        "c.executemany('INSERT INTO junk VALUES (?)', [('y' * 500,) for _ in range(2000)])\n"
        "for f in os.listdir(src):\n"
        "    shutil.copy(os.path.join(src, f), os.path.join(dst, f))\n"
        "os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", code, str(work), str(snap)], check=True)
    assert (snap / "open_omniscience.db-journal").exists(), "the snapshot must carry a hot journal"
    monkeypatch.setenv("OO_DATA_DIR", str(snap))
    kv_store.kv_invalidate()
    assert kv_store.kv_get_json("settings.app") == {"theme": "dark"}
