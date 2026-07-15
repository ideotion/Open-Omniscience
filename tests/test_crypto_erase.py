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
    seen, wiped = crypto_erase._shred(f)
    assert seen and wiped
    assert not f.exists()
    # A missing file is neither seen nor wiped.
    assert crypto_erase._shred(tmp_path / "gone.db") == (False, False)


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
