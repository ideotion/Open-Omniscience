"""The columnar cache's key is stretched like the corpus's, from the passphrase and a salt of its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The persisted DuckDB cache is opened with a key derived from the ONE corpus passphrase. It used to be one SHA-256 of the
passphrase behind a fixed prefix (CodeQL ``py/weak-sensitive-data-hashing``): the same passphrase opens the corpus behind
PBKDF2-HMAC-SHA512 at 256,000 rounds, so a fast hash on the cache beside it was the cheapest offline attack on the one
passphrase that opens everything. No shipped build creates the file yet (``secure_crypto_available()`` is False until the
per-OS crypto extension is bundled), so this is fixed before the day it matters, not after.

What is pinned here: the derivation against answers computed by an independent implementation (OpenSSL's), the round count
against the one SQLCipher reports for the corpus, the salt's sidecar (written atomically, private, v2 only, never shared by
two threads), what ``connect`` does with a store that has none (the cache is disposable: it is removed and rebuilt, never
migrated), that the encryption gate proves the ENGINE with a throwaway key and takes no passphrase, that a failed open
writes neither the passphrase nor the key to the log, and that the crypto-erase and the uninstall watcher destroy the sidecar.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import stat
import threading
import time
from pathlib import Path

import pytest

from src.analytics import columnar
from src.monitoring.secret_scrub import REDACTED

PASS = "kQ7!vLm-the-columnar-passphrase"

#: ``openssl kdf -keylen 32 -kdfopt digest:SHA512 -kdfopt pass:<passphrase> -kdfopt hexsalt:<salt> -kdfopt iter:256000 PBKDF2``.
#: An independent implementation, so a change of hash, round count, key length or text encoding cannot pass by agreeing
#: with itself.
_VECTORS = [
    ("correct horse battery staple", "000102030405060708090a0b0c0d0e0f",
     "2c6ee106931bbdc6ea7e33497f04526ccbe4fb541379d36a506a65eabed0d8e2"),
    ("pässwörd ✓", "ffeeddccbbaa99887766554433221100",
     "9a5ac646b9ca9f9c8d203b20c510bdb0dbc7862e9f3016ef2259a3243e2cb16b"),
]


# --------------------------------------------------------------------------- #
# Where these tests run
# --------------------------------------------------------------------------- #
def test_the_lane_that_has_duckdb_runs_this_file():
    """Every test below that drives the engine imports DuckDB with ``importorskip``, and the lanes without it (the main one
    and the portability ones) skip all of them: 20 of this file's tests are skips there. The ``columnar`` lane installs the
    extra, so it is the one place they run, and its command lists its files by name: a lane that no longer names this file
    turns the real-engine tests into a pass that tested nothing."""
    import yaml

    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    commands = "\n".join(step.get("run", "") for step in workflow["jobs"]["columnar"]["steps"])
    assert "tests/test_columnar_key_derivation.py" in commands, "the columnar lane does not run the key-derivation tests"


# --------------------------------------------------------------------------- #
# The derivation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("passphrase", "salt_hex", "expected"), _VECTORS)
def test_the_key_matches_an_independent_implementations_known_answers(passphrase, salt_hex, expected):
    assert columnar._derive_key(passphrase, bytes.fromhex(salt_hex)) == expected


def test_the_key_depends_on_the_passphrase_and_on_the_salt_and_is_a_literal_safe_hex_string():
    salt = bytes(range(16))
    key = columnar._derive_key(PASS, salt)
    assert len(key) == 2 * columnar._KDF_KEY_BYTES and key == key.lower() and bytes.fromhex(key)
    assert columnar._derive_key(PASS + "x", salt) != key, "another passphrase, another key"
    assert columnar._derive_key(PASS, bytes(reversed(salt))) != key, "another salt, another key"
    assert columnar._derive_key(PASS, salt) == key, "and the same inputs give the same key"


def test_the_cache_key_costs_what_the_corpus_key_costs():
    """The count is the point: it must not be below the one SQLCipher stretches the corpus's key with, or the cache file
    is the cheaper thing to attack. Read back from a live SQLCipher connection, not copied from its documentation."""
    sqlcipher = pytest.importorskip("sqlcipher3.dbapi2")
    con = sqlcipher.connect(":memory:")
    try:
        con.execute("PRAGMA key = 'x'")
        corpus_rounds = int(con.execute("PRAGMA kdf_iter").fetchone()[0])
        corpus_kdf = str(con.execute("PRAGMA cipher_kdf_algorithm").fetchone()[0])
    finally:
        con.close()
    assert corpus_rounds <= columnar._KDF_ITERATIONS, "the cache must never be cheaper to attack than the corpus"
    assert corpus_kdf.lower().replace("_", "-") == columnar._KDF_NAME, "and it is the same function"


# --------------------------------------------------------------------------- #
# The sidecar
# --------------------------------------------------------------------------- #
def test_the_sidecar_is_a_v2_record_written_atomically_and_private(tmp_path):
    sidecar = tmp_path / "analytics.duckdb.kdf"
    salt = os.urandom(columnar._KDF_SALT_BYTES)
    columnar._write_kdf_sidecar(sidecar, salt)
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {
        "v": 2, "kdf": "pbkdf2-hmac-sha512", "iterations": 256_000, "salt": salt.hex(),
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == ["analytics.duckdb.kdf"], "no temp file is left beside it"
    assert columnar._read_kdf_salt(sidecar) == salt
    if os.name != "nt":  # Windows has no owner-only mode to set
        assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_a_write_that_fails_leaves_the_old_sidecar_whole_and_no_temp_file(tmp_path, monkeypatch):
    sidecar = tmp_path / "analytics.duckdb.kdf"
    old = os.urandom(columnar._KDF_SALT_BYTES)
    columnar._write_kdf_sidecar(sidecar, old)
    before = sidecar.read_bytes()

    def broken(src, dst):
        raise OSError("the replace failed")

    monkeypatch.setattr(columnar.os, "replace", broken)
    with pytest.raises(OSError, match="the replace failed"):
        columnar._write_kdf_sidecar(sidecar, os.urandom(columnar._KDF_SALT_BYTES))
    monkeypatch.undo()
    assert sidecar.read_bytes() == before, "the sidecar a store already depends on is never half-replaced"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["analytics.duckdb.kdf"]


def test_a_leftover_temp_file_of_a_crashed_write_does_not_stop_the_next_one(tmp_path):
    sidecar = tmp_path / "analytics.duckdb.kdf"
    (tmp_path / "analytics.duckdb.kdf.tmp").write_text("half a record", encoding="utf-8")
    salt = os.urandom(columnar._KDF_SALT_BYTES)
    columnar._write_kdf_sidecar(sidecar, salt)
    assert columnar._read_kdf_salt(sidecar) == salt


def _record(**changes):
    record = {"v": 2, "kdf": "pbkdf2-hmac-sha512", "iterations": 256_000, "salt": "00" * 16}
    record.update(changes)
    return record


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '"a string"',
        "7",
        json.dumps({}),
        json.dumps({k: v for k, v in _record().items() if k != "salt"}),
        json.dumps(_record(v=1)),
        json.dumps(_record(v="2")),
        json.dumps(_record(v=3)),
        json.dumps(_record(kdf="sha256")),
        json.dumps(_record(iterations=1)),
        json.dumps(_record(iterations="256000")),
        json.dumps(_record(salt="zz" * 16)),
        json.dumps(_record(salt=7)),
        json.dumps(_record(salt="00" * 8)),
        json.dumps(_record(salt="00" * 32)),
        json.dumps(_record(salt="")),
    ],
)
def test_a_sidecar_that_is_not_a_v2_record_of_this_derivation_reads_as_no_salt(tmp_path, text):
    sidecar = tmp_path / "analytics.duckdb.kdf"
    sidecar.write_text(text, encoding="utf-8")
    assert columnar._read_kdf_salt(sidecar) is None


def test_a_sidecar_that_is_not_text_or_is_absent_reads_as_no_salt(tmp_path):
    assert columnar._read_kdf_salt(tmp_path / "analytics.duckdb.kdf") is None
    binary = tmp_path / "analytics.duckdb.kdf"
    binary.write_bytes(b"\xff\xfe\x00\x80")
    assert columnar._read_kdf_salt(binary) is None


# --------------------------------------------------------------------------- #
# A store and its salt
# --------------------------------------------------------------------------- #
def test_a_new_store_gets_a_salt_once_and_keeps_it(tmp_path):
    store = tmp_path / "analytics.duckdb"
    salt = columnar._store_salt(store)
    assert len(salt) == columnar._KDF_SALT_BYTES
    assert columnar._read_kdf_salt(tmp_path / "analytics.duckdb.kdf") == salt
    assert columnar._store_salt(store) == salt, "the second open reads the salt, it does not make another"


def test_a_store_with_a_valid_sidecar_is_left_alone(tmp_path):
    store = tmp_path / "analytics.duckdb"
    salt = columnar._store_salt(store)
    store.write_bytes(b"the cache")
    (tmp_path / "analytics.duckdb.wal").write_bytes(b"its log")
    assert columnar._store_salt(store) == salt
    assert store.read_bytes() == b"the cache" and (tmp_path / "analytics.duckdb.wal").exists()


@pytest.mark.parametrize("sidecar_text", [None, "garbage", json.dumps(_record(v=1))])
def test_a_store_without_a_valid_sidecar_is_removed_with_its_log_and_given_a_new_salt(tmp_path, sidecar_text):
    """An older build keyed it with one unsalted SHA-256 and no sidecar, and a lost sidecar loses the salt: either way the
    key cannot be derived, and the cache is disposable, so it is rebuilt, never migrated."""
    store = tmp_path / "analytics.duckdb"
    store.write_bytes(b"a cache under a key nobody can derive")
    (tmp_path / "analytics.duckdb.wal").write_bytes(b"its log")
    sidecar = tmp_path / "analytics.duckdb.kdf"
    if sidecar_text is not None:
        sidecar.write_text(sidecar_text, encoding="utf-8")
    salt = columnar._store_salt(store)
    assert not store.exists() and not (tmp_path / "analytics.duckdb.wal").exists()
    assert columnar._read_kdf_salt(sidecar) == salt != bytes.fromhex("00" * 16)


def test_two_threads_opening_a_new_store_agree_on_one_salt(tmp_path, monkeypatch):
    """Without the lock each thread reads "no sidecar", makes a salt and writes it, and the store ends up under one key with
    a sidecar naming another. The write is slowed so that every thread is past its read before any write lands."""
    store = tmp_path / "analytics.duckdb"
    real_write = columnar._write_kdf_sidecar

    def slow_write(sidecar, salt):
        time.sleep(0.05)
        real_write(sidecar, salt)

    monkeypatch.setattr(columnar, "_write_kdf_sidecar", slow_write)
    seen: list[bytes] = []
    barrier = threading.Barrier(8)

    def open_store():
        barrier.wait()
        seen.append(columnar._store_salt(store))

    threads = [threading.Thread(target=open_store) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == 8 and len(set(seen)) == 1
    assert columnar._read_kdf_salt(tmp_path / "analytics.duckdb.kdf") == seen[0]


# --------------------------------------------------------------------------- #
# connect(): the persisted branch, with the secure backend stubbed (none ships offline yet)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def persisted(tmp_path, monkeypatch):
    """The persisted branch of ``connect`` with a secure backend that is not there: the gate passes and the attach is a
    recorder that makes the store file as DuckDB would and hands back a usable in-memory connection."""
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(tmp_path))
    monkeypatch.delenv("OO_COLUMNAR", raising=False)
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    rec = type("Rec", (), {})()
    rec.gate_calls = []
    rec.attached = []
    rec.fail_with = None

    def gate(*args, **kwargs):
        rec.gate_calls.append((args, kwargs))
        return True

    def attach(path, encryption_key):
        rec.attached.append((Path(path), encryption_key))
        if rec.fail_with is not None:
            raise rec.fail_with(encryption_key)
        if not Path(path).exists():
            Path(path).write_bytes(b"a new store")
        return duckdb.connect()

    monkeypatch.setattr(columnar, "encryption_gate", gate)
    monkeypatch.setattr(columnar, "_attach_persisted", attach)
    rec.dir = tmp_path
    return rec


def test_connect_keys_the_store_from_the_passphrase_and_the_salt_of_its_sidecar(persisted):
    con = columnar.connect(passphrase=PASS)
    assert con is not None
    con.close()
    salt = columnar._read_kdf_salt(persisted.dir / "analytics.duckdb.kdf")
    assert salt is not None
    assert persisted.attached == [(persisted.dir / "analytics.duckdb", columnar._derive_key(PASS, salt))]
    assert persisted.gate_calls == [((persisted.dir / ".oo_columnar_probe.duckdb",), {})], "the gate is given the probe path alone"


def test_the_next_open_reuses_the_salt_and_the_store_and_a_new_passphrase_changes_only_the_key(persisted):
    columnar.connect(passphrase=PASS).close()
    store = persisted.dir / "analytics.duckdb"
    before = store.read_bytes()
    columnar.connect(passphrase=PASS).close()
    columnar.connect(passphrase=PASS + "!").close()
    (_, first), (_, second), (_, third) = persisted.attached
    assert first == second != third
    assert store.read_bytes() == before, "a valid sidecar means the store is kept"


def test_a_store_that_has_no_valid_sidecar_is_rebuilt_not_opened(persisted):
    store = persisted.dir / "analytics.duckdb"
    store.write_bytes(b"a cache an older build keyed with one SHA-256")
    (persisted.dir / "analytics.duckdb.wal").write_bytes(b"its log")
    columnar.connect(passphrase=PASS).close()
    assert store.read_bytes() == b"a new store", "the old file was removed before the attach made a new one"
    assert not (persisted.dir / "analytics.duckdb.wal").exists()
    assert columnar._read_kdf_salt(persisted.dir / "analytics.duckdb.kdf") is not None


def test_a_failed_open_falls_back_to_memory_and_logs_neither_the_passphrase_nor_the_key(persisted, caplog):
    """An ATTACH that fails can quote its own statement, which carries the key; the passphrase and the key it was derived
    into are taken out of the record's failure line and out of its traceback, which is text and not ``exc_info``."""
    persisted.fail_with = lambda key: RuntimeError(f"Parser Error near ENCRYPTION_KEY '{key}' (the passphrase was {PASS})")
    store = persisted.dir / "analytics.duckdb"
    # The sidecar is made first: a store with no valid one is removed before the attach is tried, so without it the file
    # would be gone whether or not the failure's handler drops it, and the assertion below would hold for the wrong reason.
    salt = columnar._store_salt(store)
    store.write_bytes(b"a cache that will not open")
    caplog.set_level(logging.DEBUG, logger="src.analytics.columnar")
    con = columnar.connect(passphrase=PASS)
    assert con is not None, "the engine falls back to an in-memory store"
    con.close()
    assert columnar._read_kdf_salt(persisted.dir / "analytics.duckdb.kdf") == salt, "the sidecar was valid, so the open was tried"
    assert persisted.attached, "the attach ran: only the failure's handler can have dropped the file"
    assert not store.exists(), "the disposable file is dropped"
    (_, key), = persisted.attached
    text = "\n".join(f"{r.getMessage()}\n{r.exc_text or ''}\n{r.exc_info!r}" for r in caplog.records)
    assert PASS not in text and key not in text
    failures = [r for r in caplog.records if "persisted open failed" in r.getMessage()]
    assert len(failures) == 1 and failures[0].levelno == logging.WARNING and failures[0].exc_info is None
    assert (
        f"columnar engine: persisted open failed; in-memory: RuntimeError: Parser Error near ENCRYPTION_KEY '{REDACTED}' "
        f"(the passphrase was {REDACTED})" in failures[0].getMessage()
    )


def test_a_read_model_refresh_that_fails_logs_without_the_passphrase(persisted, monkeypatch, caplog):
    duckdb = pytest.importorskip("duckdb")
    monkeypatch.setattr(columnar, "connect", lambda passphrase=None, **k: duckdb.connect())

    def boom(con, session):
        raise RuntimeError(f"the build read {PASS}")

    monkeypatch.setattr(columnar, "build_keyword_read_model", boom)
    caplog.set_level(logging.DEBUG, logger="src.analytics.columnar")
    assert columnar.refresh_persisted_read_model(None, passphrase=PASS) == {"skipped": "error"}
    (record,) = [r for r in caplog.records if "refresh failed" in r.getMessage()]
    assert PASS not in record.getMessage() and record.exc_info is None
    assert f"RuntimeError: the build read {REDACTED}" in record.getMessage()


def test_a_marker_that_is_not_compatible_rebuilds_the_store_under_the_same_key(persisted, monkeypatch):
    """The rebuild (a DuckDB upgrade, a new read-model schema) removes the store and attaches again: the sidecar is
    untouched, so the second attach is under the key the first was."""
    columnar.connect(passphrase=PASS).close()
    salt = columnar._read_kdf_salt(persisted.dir / "analytics.duckdb.kdf")
    persisted.attached.clear()
    monkeypatch.setattr(columnar, "read_store_meta", lambda con: "an older marker")
    monkeypatch.setattr(columnar, "marker_compatible", lambda marker: False)
    columnar.connect(passphrase=PASS).close()
    assert [key for _path, key in persisted.attached] == [columnar._derive_key(PASS, salt)] * 2
    assert columnar._read_kdf_salt(persisted.dir / "analytics.duckdb.kdf") == salt


def test_a_salt_that_cannot_be_made_falls_back_to_memory_and_the_log_holds_no_secret(persisted, monkeypatch, caplog):
    """The failure can come BEFORE the key exists (the sidecar cannot be written): the handler must still run, with the
    key not yet made, and the fallback must still be the in-memory store, never an exception out of ``connect``."""

    def cannot(path):
        raise OSError(f"cannot write the sidecar for {PASS}")

    monkeypatch.setattr(columnar, "_store_salt", cannot)
    caplog.set_level(logging.DEBUG, logger="src.analytics.columnar")
    con = columnar.connect(passphrase=PASS)
    assert con is not None
    con.close()
    assert persisted.attached == [], "nothing was attached"
    (failure,) = [r for r in caplog.records if "persisted open failed" in r.getMessage()]
    assert PASS not in failure.getMessage() and failure.exc_info is None
    assert f"OSError: cannot write the sidecar for {REDACTED}" in failure.getMessage()


def test_the_store_goes_before_the_new_sidecar_is_written(tmp_path, monkeypatch):
    """The order is the crash safety: if the new sidecar cannot be written the old store is already gone, so a store
    is never left under a salt that was not recorded (the next open has no store and no sidecar, which is a fresh start)."""
    store = tmp_path / "analytics.duckdb"
    store.write_bytes(b"a store under a salt that is lost")
    wal = tmp_path / "analytics.duckdb.wal"
    wal.write_bytes(b"its log")

    def cannot(sidecar, salt):
        raise OSError("disk full")

    monkeypatch.setattr(columnar, "_write_kdf_sidecar", cannot)
    with pytest.raises(OSError, match="disk full"):
        columnar._store_salt(store)
    assert not store.exists() and not wal.exists() and not (tmp_path / "analytics.duckdb.kdf").exists()


# --------------------------------------------------------------------------- #
# The statement: the key is bound and the path is escaped
# --------------------------------------------------------------------------- #
def test_the_attach_binds_the_key_and_escapes_the_path(monkeypatch, tmp_path):
    seen = []

    class Con:
        def execute(self, sql, params=None):
            seen.append((sql, params))
            return self

    monkeypatch.setattr(columnar, "_persisted_connection", lambda: Con())
    key = "ab" * 32
    columnar._attach_persisted(tmp_path / "o'brien" / "analytics.duckdb", key)
    (attach_sql, params), (use_sql, _) = seen
    assert key not in attach_sql and params == [key] and "ENCRYPTION_KEY ?" in attach_sql
    assert "o''brien" in attach_sql and use_sql == "USE oo"


@pytest.mark.parametrize("text", ["", "plain", "o'brien", "''", "a'; DROP TABLE t; --", "back\\slash", "ünï ✓", "new\nline"])
def test_a_path_goes_into_a_statement_as_exactly_itself(text):
    duckdb = pytest.importorskip("duckdb")
    assert duckdb.connect().execute(f"SELECT {columnar._sql_text(text)}").fetchone() == (text,)


# --------------------------------------------------------------------------- #
# The real engine, with a software crypto backend that exists here (the shipped backend is the per-OS httpfs one)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def real_engine(tmp_path, monkeypatch):
    """``connect`` against REAL DuckDB: the secure-backend and gate checks are stubbed true (they ask for the httpfs
    binary this repository does not bundle yet) and ``_persisted_connection`` hands back a connection with DuckDB's own
    software backend switched on, which is enough to run the statement and the key for real. Skipped where the installed
    DuckDB has no such switch. The data directory holds an apostrophe, which is the case that used to break the statement."""
    duckdb = pytest.importorskip("duckdb")
    probe = duckdb.connect()
    try:
        probe.execute("SET force_mbedtls_unsafe = 'true'")
    except duckdb.Error:
        pytest.skip("this DuckDB has no software crypto backend to run the statement against")
    finally:
        probe.close()

    def connection():
        con = duckdb.connect()
        con.execute("SET force_mbedtls_unsafe = 'true'")
        return con

    data = tmp_path / "o'brien"
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(data))
    monkeypatch.delenv("OO_COLUMNAR", raising=False)
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "encryption_gate", lambda path: True)
    monkeypatch.setattr(columnar, "_persisted_connection", connection)
    return data


def test_a_real_engine_keeps_the_data_under_the_derived_key_and_in_a_directory_with_an_apostrophe(real_engine, caplog):
    caplog.set_level(logging.DEBUG, logger="src.analytics.columnar")
    con = columnar.connect(passphrase=PASS)
    assert con.execute("SELECT current_database()").fetchone() == ("oo",), "the persisted store, not the in-memory fallback"
    con.execute("CREATE TABLE t (s VARCHAR)")
    con.execute("INSERT INTO t VALUES ('canary-7f3a9c1d')")
    con.execute("CHECKPOINT oo")
    con.close()
    store = real_engine / "analytics.duckdb"
    assert store.exists() and b"canary-7f3a9c1d" not in store.read_bytes(), "ciphertext on disk"

    again = columnar.connect(passphrase=PASS)  # the same salt, so the same key: the data is there
    assert again.execute("SELECT s FROM t").fetchall() == [("canary-7f3a9c1d",)]
    again.close()
    salt = columnar._read_kdf_salt(real_engine / "analytics.duckdb.kdf")
    key = columnar._derive_key(PASS, salt)
    text = "\n".join(f"{r.getMessage()}\n{r.exc_text or ''}" for r in caplog.records)
    assert PASS not in text and key not in text


def test_a_real_engine_refuses_another_passphrase_and_falls_back_to_memory_without_naming_either(real_engine, caplog):
    columnar.connect(passphrase=PASS).close()
    salt = columnar._read_kdf_salt(real_engine / "analytics.duckdb.kdf")
    caplog.set_level(logging.DEBUG, logger="src.analytics.columnar")
    other = "an-other-passphrase-1b7"
    con = columnar.connect(passphrase=other)
    assert con.execute("SELECT current_database()").fetchone() == ("memory",), "a wrong key opens nothing"
    con.close()
    assert not (real_engine / "analytics.duckdb").exists(), "the disposable store is dropped"
    (failure,) = [r for r in caplog.records if "persisted open failed" in r.getMessage()]
    assert "Wrong encryption key" in failure.getMessage()
    text = "\n".join(f"{r.getMessage()}\n{r.exc_text or ''}" for r in caplog.records)
    for secret in (PASS, other, columnar._derive_key(PASS, salt), columnar._derive_key(other, salt)):
        assert secret not in text


# --------------------------------------------------------------------------- #
# The encryption gate: the engine is what it proves
# --------------------------------------------------------------------------- #
_ATTACH = re.compile(r"ATTACH '((?:[^']|'')*)' AS")


class _FakeSecureEngine:
    """The engine as the gate meets it WITH a secure backend: an ATTACH under a key makes a file of noise that a keyless
    ATTACH cannot read, and the probe table reads back under the key. ``encrypts=False`` is an engine that ignores the key
    and writes the sentinel in the clear: the case the gate exists to refuse."""

    def __init__(self, store, *, encrypts=True):
        self.store, self.encrypts = store, encrypts
        self.statements: list[str] = []
        self.bound: list[str] = []
        self.key_of_file: dict[str, str] = {}

    def connection(self):
        engine = self

        class Con:
            def execute(self, sql, params=None):
                engine.statements.append(sql)
                attach = _ATTACH.match(sql)
                path = attach.group(1).replace("''", "'") if attach else None
                if path and "ENCRYPTION_KEY" in sql:
                    assert "ENCRYPTION_KEY ?" in sql, "the key is bound, never written into the statement"
                    (key,) = params
                    engine.bound.append(key)
                    if Path(path).exists():
                        if engine.key_of_file.get(path) != key:
                            raise RuntimeError("wrong key")
                    else:
                        engine.key_of_file[path] = key
                        Path(path).write_bytes(os.urandom(512))
                elif path and engine.encrypts:
                    raise RuntimeError("the file is encrypted: a key is needed")
                if sql.startswith("INSERT") and not engine.encrypts:
                    Path(engine.store).write_bytes(columnar._SENTINEL.encode("utf-8"))
                return self

            def fetchone(self):
                return (columnar._SENTINEL,)

            def fetchall(self):
                return [(columnar._SENTINEL,)]

            def close(self):
                pass

        return Con()


def test_the_gate_takes_no_passphrase_and_proves_the_engine_with_a_throwaway_random_key(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    assert list(inspect.signature(columnar.encryption_gate).parameters) == ["path"]
    keys = []
    for _ in range(2):
        probe = tmp_path / "probe.duckdb"
        engine = _FakeSecureEngine(probe)
        monkeypatch.setattr(columnar, "_persisted_connection", engine.connection)
        assert columnar.encryption_gate(probe) is True
        assert not probe.exists(), "the probe file is cleaned up"
        assert len(engine.bound) == 2 and len(set(engine.bound)) == 1, "the keyed attach and the keyed read-back use the one key"
        (key,) = set(engine.bound)
        assert all(key not in sql for sql in engine.statements), "the key is bound, never part of a statement"
        assert len(key) == 2 * columnar._KDF_KEY_BYTES and bytes.fromhex(key)
        keys.append(key)
    assert keys[0] != keys[1], "a fresh key for every call: nothing in the probe depends on the passphrase"


def test_the_gate_escapes_the_probe_path_in_every_statement(tmp_path, monkeypatch):
    """The gate's own statements are the ones a data directory with an apostrophe would break: all three escape it."""
    pytest.importorskip("duckdb")
    directory = tmp_path / "o'brien"
    directory.mkdir()
    probe = directory / "probe.duckdb"
    engine = _FakeSecureEngine(probe)
    monkeypatch.setattr(columnar, "_persisted_connection", engine.connection)
    assert columnar.encryption_gate(probe) is True
    attaches = [sql for sql in engine.statements if sql.startswith("ATTACH")]
    assert len(attaches) == 3 and all("o''brien" in sql and "o'brien" not in sql for sql in attaches), attaches


def test_the_gate_refuses_an_engine_that_writes_the_sentinel_in_the_clear(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    probe = tmp_path / "probe.duckdb"
    engine = _FakeSecureEngine(probe, encrypts=False)
    monkeypatch.setattr(columnar, "_persisted_connection", engine.connection)
    assert columnar.encryption_gate(probe) is False
    assert not probe.exists()


# --------------------------------------------------------------------------- #
# The sidecar is destroyed with the cache
# --------------------------------------------------------------------------- #
def test_the_erase_and_the_uninstall_watcher_name_every_file_the_store_keeps_at_rest():
    """The store, the sidecar beside it, the log the engine leaves beside the store after an unclean end and the gate's probe
    are the files the engine leaves on disk. The erase and the watcher (a source text with its own copy of the names,
    because it imports nothing) each carry a list of them: a file the engine learns to keep that neither names is one the
    erase leaves behind (under ``OO_COLUMNAR_DIR`` outside the data directory it is only the names that are walked), and a
    name that no longer matches a file is a list that has gone stale. The byte-level check that the erase overwrites the
    sidecar and the log is in ``tests/test_crypto_erase.py``; the watcher's in ``tests/test_uninstall.py``."""
    from src.safety import crypto_erase, uninstall

    sidecar = columnar._STORE_FILENAME + columnar._KDF_SIDECAR_SUFFIX
    assert sidecar == "analytics.duckdb.kdf"
    log = columnar._STORE_FILENAME + ".wal"
    assert log == "analytics.duckdb.wal"
    kept = {columnar._STORE_FILENAME, sidecar, log, ".oo_columnar_probe.duckdb"}
    assert set(crypto_erase._DUCK_FILES) == kept
    # The watcher names each in its header-only list and in the external store dir's list, the probe included.
    for name in kept:
        assert uninstall._WATCHER_SRC.count(f'"{name}"') == 2, name
