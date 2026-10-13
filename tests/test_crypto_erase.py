"""
OO-02 regression: the two-phase secure wipe (crypto-erase + optional full scrub).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The old panic wipe overwrote only the first 4 MiB of every file before deleting it,
so most of a multi-GB corpus survived, forensically recoverable. These tests prove:
  * the salt page of an encrypted DB is destroyed -> the correct passphrase can no
    longer open it (true crypto-erase, the real guarantee);
  * a full overwrite now covers the WHOLE file, not just the first 4 MiB;
  * quick_crypto_erase destroys keys, clears the in-memory passphrase (default store
    only), and removes the data dir;
  * full_secure_erase validates passes and cleans up its fill files;
  * the uninstall watcher's embedded, import-free copy runs the same crypto-erase.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.database.connect import (
    connect,
    get_passphrase,
    have_driver,
    is_encrypted_file,
    set_passphrase,
)
from src.safety import crypto_erase

sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")

_PW = "correct horse battery staple"


# --------------------------------------------------------------------------- #
#  The crypto-erase primitive: destroying page 1 kills the key.
# --------------------------------------------------------------------------- #
@sqlcipher_only
def test_salt_page_overwrite_makes_encrypted_db_unopenable(tmp_path):
    db = tmp_path / "corpus.db"
    con = connect(db, key=_PW)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()
    assert is_encrypted_file(db) is True
    # Sanity: the correct key opens it now.
    ok = connect(db, key=_PW)
    assert ok.execute("SELECT x FROM t").fetchone()[0] == 42
    ok.close()

    head_before = db.read_bytes()[:crypto_erase._SQLCIPHER_PAGE1]
    crypto_erase._overwrite(db, head_bytes=crypto_erase._SQLCIPHER_PAGE1)  # the quick-pass move
    head_after = db.read_bytes()[:crypto_erase._SQLCIPHER_PAGE1]
    assert head_after != head_before, "the salt page must be overwritten"

    # Salt gone -> the PBKDF2 key can never be re-derived: the correct passphrase fails.
    with pytest.raises(Exception):  # noqa: B017 - WrongPassphraseError / sqlcipher DatabaseError
        bad = connect(db, key=_PW)
        bad.execute("SELECT x FROM t").fetchone()


def test_full_overwrite_covers_entire_file_not_just_4mib(tmp_path):
    """The core OO-02 fix: a full overwrite must rewrite the WHOLE file. The old code
    capped at 4 MiB, so bytes past 4 MiB survived."""
    f = tmp_path / "big.bin"
    f.write_bytes(b"\x00" * (6 * 1024 * 1024))  # 6 MiB of zeros
    crypto_erase._overwrite(f)  # head_bytes=None -> full length
    data = f.read_bytes()
    cap = 4 * 1024 * 1024
    # A 4 KiB window starting past the old 4 MiB cap cannot be all-zero after a random
    # overwrite (probability ~2^-32768) -> proves the tail was actually rewritten.
    assert data[cap : cap + 4096] != b"\x00" * 4096


def test_shred_overwrites_then_unlinks(tmp_path):
    f = tmp_path / "anchors.db"
    f.write_bytes(b"SECRET" * 1000)
    seen, overwritten, unlinked = crypto_erase._shred(f)
    assert seen and overwritten and unlinked
    assert not f.exists()
    # A missing file is neither seen, overwritten, nor unlinked.
    assert crypto_erase._shred(tmp_path / "gone.db") == (False, False, False)


def test_shred_does_not_report_overwrite_success_when_write_fails(tmp_path, monkeypatch):
    """Regression: a failed overwrite (e.g. ENOSPC mid-write on a CoW filesystem) must
    never be reported as destroyed just because the subsequent unlink succeeded --
    that would be exactly the false-confidence bug OO-02 exists to eliminate."""
    f = tmp_path / "corpus.db"
    f.write_bytes(b"SECRET" * 1000)

    def _boom(fd):
        raise OSError("ENOSPC (simulated)")

    monkeypatch.setattr(crypto_erase.os, "fsync", _boom)
    seen, overwritten, unlinked = crypto_erase._shred(f)
    # The unlink still succeeds (directory-entry removal needs no new block), but the
    # overwrite must be reported as failed -- not folded into "destroyed".
    assert seen is True
    assert overwritten is False
    assert unlinked is True
    assert not f.exists()


# --------------------------------------------------------------------------- #
#  quick_crypto_erase orchestration.
# --------------------------------------------------------------------------- #
def test_quick_crypto_erase_requires_confirm(tmp_path):
    with pytest.raises(PermissionError):
        crypto_erase.quick_crypto_erase(data_dir=tmp_path)
    with pytest.raises(PermissionError):
        crypto_erase.quick_crypto_erase(confirm=False, data_dir=tmp_path)


@sqlcipher_only
def test_quick_crypto_erase_destroys_dbs_keys_and_removes_dir(tmp_path):
    for name in ("open_omniscience.db", "custody_log.db"):
        con = connect(tmp_path / name, key=_PW)
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
        con.close()
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "custody_ed25519.pem").write_bytes(b"PRIVATE" * 100)
    (keys / "custody_ml_dsa_65.key").write_bytes(b"MLDSA" * 100)
    (tmp_path / "anchors.db").write_bytes(b"plaintext-anchors" * 100)
    (tmp_path / "analytics.duckdb").write_bytes(b"DUCK" * 2000)
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")

    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)

    assert report["encrypted_corpus"] is True
    assert "open_omniscience.db" in report["headers_destroyed"]
    assert "custody_log.db" in report["headers_destroyed"]
    assert set(report["keys_destroyed"]) == {"custody_ed25519.pem", "custody_ml_dsa_65.key"}
    assert report["files_wiped"] >= 6
    assert report["removed"] is True
    assert not tmp_path.exists()
    # An explicit override dir must NOT mutate the live process passphrase.
    assert report["passphrase_cleared"] is False


def test_quick_crypto_erase_overwrites_the_columnar_key_sidecar_where_the_salt_lives(tmp_path, monkeypatch):
    """The cache's key is stretched from the passphrase AND the salt in ``analytics.duckdb.kdf``, so the erase destroys the
    sidecar with the cache's header: with the salt gone the key is not derivable even from the right passphrase. What is
    pinned is the BYTES at the moment the file is about to go: the overwrite ran, over the head, and no longer holds the
    salt. (The erase then unlinks the file and removes the directory, so nothing would be left for a later look.)"""
    from src.analytics import columnar

    salt = bytes(range(16))
    store = tmp_path / "analytics.duckdb"
    store.write_bytes(b"DUCK" * 2000)
    sidecar = columnar._kdf_sidecar_path(store)
    columnar._write_kdf_sidecar(sidecar, salt)
    assert salt.hex() in sidecar.read_text(encoding="utf-8")  # the salt is where the test says it is

    real_overwrite = crypto_erase._overwrite
    seen: dict[str, object] = {}

    def spy(path, *, head_bytes=None):
        done = real_overwrite(path, head_bytes=head_bytes)
        if path.name == sidecar.name:
            seen.update(done=done, head_bytes=head_bytes, after=path.read_bytes())
        return done

    monkeypatch.setattr(crypto_erase, "_overwrite", spy)

    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)

    assert seen, "the sidecar was never handed to the overwrite"
    assert seen["done"] is True and seen["head_bytes"] == crypto_erase._SQLCIPHER_PAGE1
    assert salt.hex().encode() not in seen["after"], "the salt survived the overwrite"
    assert not sidecar.exists() and report["removed"] is True


def test_quick_crypto_erase_takes_every_file_of_a_cache_directory_outside_the_data_dir_and_only_those(tmp_path, monkeypatch):
    """With ``OO_COLUMNAR_DIR`` outside the data directory the erase walks the cache's directory BY NAME (it is not ours to
    remove, so nothing else in it is touched). An unclean end leaves ``analytics.duckdb.wal`` beside the cache: ciphertext
    under the same key, and with the sidecar destroyed the key is not derivable, but it is the store's own file, so the
    list that is walked names it too. The unrelated file in that directory is left alone."""
    data = tmp_path / "data"
    data.mkdir()
    cache = tmp_path / "columnar-cache"
    cache.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    for name in ("analytics.duckdb", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb"):
        (cache / name).write_bytes(b"D" * 8192)
    (cache / "analytics.duckdb.kdf").write_text('{"v": 2}', encoding="utf-8")
    (cache / "unrelated.txt").write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(
        crypto_erase,
        "_resolve",
        lambda dd: {
            "base": data,
            "main_db": data / "open_omniscience.db",
            "keys_dir": data / "keys",
            "store_dir": cache,
            "custody_db": data / "custody_log.db",
            "anchors_db": data / "anchors.db",
        },
    )
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["removed"] is True and not data.exists()
    assert sorted(p.name for p in cache.iterdir()) == ["unrelated.txt"], "every file the cache keeps went, and nothing else"


def test_quick_crypto_erase_clears_passphrase_on_default_store(tmp_path, monkeypatch):
    """The default (data_dir=None) path clears the in-memory passphrase; an override dir
    does not (proven above). Resolvers are monkeypatched onto the temp dir so no real
    corpus is touched."""
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
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    set_passphrase("live-secret")
    try:
        assert get_passphrase() == "live-secret"
        report = crypto_erase.quick_crypto_erase(confirm=True)  # data_dir=None
        assert report["passphrase_cleared"] is True
        assert get_passphrase() is None
    finally:
        set_passphrase(None)


# --------------------------------------------------------------------------- #
#  full_secure_erase (optional defence-in-depth free-space scrub).
# --------------------------------------------------------------------------- #
def test_full_secure_erase_rejects_invalid_passes(tmp_path):
    for bad in (0, 2, 4, 5, 6, 7, 9, -1):
        with pytest.raises(ValueError):
            crypto_erase.full_secure_erase(bad, base_dir=tmp_path)


def test_full_secure_erase_scrubs_and_cleans_up(tmp_path):
    cap = 256 * 1024
    report = crypto_erase.full_secure_erase(3, base_dir=tmp_path, _cap_bytes=cap)
    assert report["passes"] == 3
    assert report["bytes_written"] == 3 * cap  # ~passes x free space (capped for the test)
    # Fill files + scrub dir are cleaned up.
    assert not (tmp_path / ".oo_scrub").exists()
    assert not list(tmp_path.glob("**/*.bin"))


# --------------------------------------------------------------------------- #
#  The uninstall watcher's embedded, import-free copy runs the same crypto-erase.
# --------------------------------------------------------------------------- #
def test_uninstall_watcher_embedded_crypto_erase(tmp_path):
    from src.safety.uninstall import _WATCHER_SRC

    # A pid that is already dead so the watcher's wait loop returns immediately.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()

    data = tmp_path / "data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)  # 'encrypted' corpus
    (data / "settings.json").write_text("{}", encoding="utf-8")
    audit = tmp_path / "audit.log"
    plan = {
        "files": [],
        "venv": None,
        "app_folder": None,
        "wipe_data_dir": str(data),
        "audit_log": str(audit),
    }

    subprocess.run(
        [sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)],
        check=True,
        timeout=60,
    )

    assert not data.exists(), "the watcher must wipe the data dir"
    log_text = audit.read_text(encoding="utf-8")
    assert "crypto-erase" in log_text  # the new (non-4-MiB-cap) code path ran
