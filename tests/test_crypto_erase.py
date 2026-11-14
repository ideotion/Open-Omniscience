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

import contextlib
import json
import os
import subprocess
import sys

import pytest

from src.database.connect import (
    WrongPassphraseError,
    connect,
    get_passphrase,
    have_driver,
    is_encrypted_file,
    set_passphrase,
)
from src.safety import crypto_erase
from tests.os_scope import scope_os

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
    with pytest.raises(WrongPassphraseError, match="does not open"):
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

    scope_os(monkeypatch, crypto_erase, fsync=_boom)
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


def _salt_hits(data: bytes, salt: bytes) -> list[int]:
    hits, i = [], data.find(salt)
    while i != -1:
        hits.append(i)
        i = data.find(salt, i + 1)
    return hits


@sqlcipher_only
@pytest.mark.skipif(sys.platform == "win32", reason="reads an open, unlinked WAL through a hard link (POSIX semantics)")
def test_quick_crypto_erase_destroys_every_copy_of_the_salt_in_the_write_ahead_log(tmp_path):
    """R708. SQLCipher keeps the salt in plaintext at the start of page 1, and every commit that touches page 1 leaves a
    copy of that page in a WAL frame, far past the WAL's first 4 KiB. The old erase overwrote only those 4 KiB, so the
    salt stayed readable in the frames behind them. The connection stays OPEN (as the running app's does: closing it
    would checkpoint and delete the WAL), and a hard link outside the data dir keeps the WAL's inode readable after the
    erase unlinks it, so what is read back is exactly the bytes a seized disk would hold."""
    data = tmp_path / "data"
    data.mkdir()
    db = data / "open_omniscience.db"
    con = connect(db, key=_PW)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE t(x)")
        con.commit()
        for _ in range(20):
            con.execute("CREATE TABLE IF NOT EXISTS u(x)")  # schema churn rewrites page 1 on every commit
            con.execute("INSERT INTO t VALUES (randomblob(3000))")
            con.commit()
        salt = db.read_bytes()[:16]
        wal = db.with_name(db.name + "-wal")
        kept = tmp_path / "kept-wal"
        os.link(wal, kept)
        before = _salt_hits(kept.read_bytes(), salt)
        assert [h for h in before if h >= crypto_erase._SQLCIPHER_PAGE1], "the setup must put the salt past the head"

        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    finally:
        con.close()

    assert report["overwrite_failures"] == []
    assert _salt_hits(kept.read_bytes(), salt) == [], "a copy of the salt survived in the write-ahead log"


@sqlcipher_only
@pytest.mark.skipif(os.name != "posix", reason="the kept descriptors are POSIX only")
@pytest.mark.parametrize("mode", ["DELETE", "WAL"])
def test_a_transaction_that_commits_after_the_erase_is_rewritten_through_the_kept_descriptors(tmp_path, mode):
    """A transaction already under way when the erase runs commits into the unlinked file and puts page 1, salt
    included, back on the disk (measured by the security read: 0 copies before the COMMIT, 1 after). The panic wipe
    keeps a descriptor on every unlinked main file, -wal and -journal, and rewrites them again once the pool is closed."""
    data = tmp_path / "data"
    data.mkdir()
    db = data / "custody_log.db"
    con = connect(db, key=_PW)
    kept: list = []
    try:
        con.execute(f"PRAGMA journal_mode={mode}")
        con.execute("CREATE TABLE t(x)")
        con.commit()
        salt = db.read_bytes()[:16]
        os.link(db, tmp_path / "kept-db")
        con.execute("BEGIN")
        con.execute("CREATE TABLE u(x)")  # a schema change rewrites page 1
        con.execute("INSERT INTO t VALUES (randomblob(3000))")
        for suffix in ("-wal", "-journal"):
            side = db.with_name(db.name + suffix)
            if side.exists():
                os.link(side, tmp_path / ("kept" + suffix))
        crypto_erase.quick_crypto_erase(confirm=True, data_dir=data, hold_for_rescrub=True)
        with contextlib.suppress(Exception):
            con.commit()
    finally:
        with contextlib.suppress(Exception):
            con.close()
    kept = sorted(tmp_path.glob("kept*"))
    late = [k.name for k in kept if _salt_hits(k.read_bytes(), salt)]
    assert late, "the setup must reproduce the late commit putting the salt back"
    assert crypto_erase.rescrub_held(close=True) >= 1
    assert [k.name for k in kept if _salt_hits(k.read_bytes(), salt)] == [], (
        f"a late commit's salt survived the rescrub (before it: {late})"
    )


def test_the_log_index_head_is_zeroed_never_randomised(tmp_path):
    """A connection that rolls back after the erase reads its frame count from the -shm header and grows the mapped file
    toward it: random bytes there grew it toward 32 GiB in the security read (the disk filled). The header holds no page
    data, so the erase writes zeros over it, which read as "rebuild the index from the log"."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    shm = data / "open_omniscience.db-shm"
    shm.write_bytes(b"\xff" * 32768)
    kept = tmp_path / "kept-shm"
    os.link(shm, kept)

    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)

    assert kept.read_bytes()[: crypto_erase._SQLCIPHER_PAGE1] == bytes(crypto_erase._SQLCIPHER_PAGE1)
    assert str(shm) not in report["overwrite_failures"]


def test_quick_crypto_erase_overwrites_the_whole_rollback_journal(tmp_path):
    """R708, the rollback-mode twin: a hot -journal holds the original page 1, salt included, at an offset past the
    head. The erase rewrites it whole."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"\x00" * 8192)
    salt = b"SALT-SALT-SALT-!"
    journal = data / "open_omniscience.db-journal"
    journal.write_bytes(b"\x00" * 8192 + salt + b"\x00" * 8192)
    kept = tmp_path / "kept-journal"
    os.link(journal, kept)

    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)

    assert salt not in kept.read_bytes()


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

    def spy(path, *, head_bytes=None, zeros=False):
        done = real_overwrite(path, head_bytes=head_bytes, zeros=zeros)
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


def test_uninstall_watcher_overwrites_the_whole_write_ahead_log(tmp_path):
    """R708 in the watcher's embedded copy: a server that died without a clean close leaves a -wal whose frames hold
    copies of page 1, salt included, past the first 4 KiB. The watcher rewrites it whole (and the -shm stays head-only)."""
    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    data = tmp_path / "data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    salt = b"SALT-SALT-SALT-!"
    wal = data / "open_omniscience.db-wal"
    wal.write_bytes(b"\x00" * 8192 + salt + b"\x00" * 8192)
    kept = tmp_path / "kept-wal"
    os.link(wal, kept)
    plan = {"files": [], "venv": None, "app_folder": None, "wipe_data_dir": str(data), "audit_log": str(tmp_path / "a.log")}

    subprocess.run([sys.executable, "-c", _WATCHER_SRC, str(dead.pid), json.dumps(plan)], check=True, timeout=60)

    assert salt not in kept.read_bytes()


@pytest.mark.skipif(os.name != "posix", reason="the kept descriptors are POSIX only")
def test_a_closing_pass_closes_each_descriptor_once_and_keeps_later_ones(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"A" * 100)
    b.write_bytes(b"B" * 100)
    crypto_erase._hold(a, whole=True)
    assert crypto_erase.rescrub_held(close=False) >= 1
    first = crypto_erase.held_count()
    crypto_erase._hold(b, whole=True)
    assert crypto_erase.rescrub_held(close=True) == first + 1
    assert crypto_erase.held_count() == 0
    assert a.read_bytes() != b"A" * 100 and b.read_bytes() != b"B" * 100


@sqlcipher_only
def test_an_erase_stopped_before_step_six_leaves_no_readable_salt_anywhere_under_the_data_dir(tmp_path, monkeypatch):
    """Encrypted copies of the corpus live under the data dir under names no list keeps up with (pre-restore snapshots,
    salvage copies, anything copied byte for byte), each with the salt in its first page. Step 4b destroys every file's
    head before the slow step 6, so an erase stopped right before step 6 leaves no salt to read anywhere."""
    import shutil

    data = tmp_path / "data"
    data.mkdir()
    db = data / "open_omniscience.db"
    con = connect(db, key=_PW)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (randomblob(9000))")
    con.commit()
    con.close()
    salt = db.read_bytes()[:16]
    copies = [
        data / "pre-restore-20261114T090000Z.db",
        data / ".restore-ab12" / "open_omniscience.db",
        data / ".bak-build-cd34" / "corpus.db",
        data / "open_omniscience.salvage-20261114T090000Z.db",
        data / "snapshots" / "deep" / "anything.bin",
    ]
    for c in copies:
        c.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(db, c)
    (data / "pre-restore-20261114T090000Z.db-wal").write_bytes(b"\x00" * 9000 + salt + b"\x00" * 100)

    def stopped(*_a, **_k):
        raise KeyboardInterrupt("the machine was switched off here")

    import src.safety.data_volume as data_volume

    monkeypatch.setattr(data_volume, "configured_folder", stopped)  # the first thing step 6 does
    with pytest.raises(KeyboardInterrupt):
        crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)

    left = [p for p in data.rglob("*") if p.is_file() and salt in p.read_bytes()]
    assert left == [], f"a salt is still readable before step 6: {left}"


@pytest.mark.skipif(os.name != "posix", reason="symlinks and FIFOs need POSIX here")
@pytest.mark.parametrize("stop_after_step_one", [True, False])
def test_the_erase_never_writes_outside_the_data_dir_through_a_link(tmp_path, monkeypatch, stop_after_step_one):
    """Steps 1 and 6 touch every file under the data dir; neither may leave it. A symlinked folder is not entered, a
    symlinked file is removed and never written through, a FIFO never blocks the walk, and the targets outside are intact."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    outside = tmp_path / "outside"
    outside.mkdir()
    precious = outside / "precious.txt"
    precious.write_bytes(b"KEEP" * 2048)
    (outside / "inner.db-wal").write_bytes(b"KEEP" * 2048)
    (data / "linked-folder").symlink_to(outside, target_is_directory=True)
    (data / "linked-file.db").symlink_to(precious)
    (data / "loop").symlink_to(data, target_is_directory=True)
    os.mkfifo(data / "a-fifo")
    # The app's own names too: a sidecar, a key file and anchors.db that are links outside are never written through.
    for name, target in (("open_omniscience.db-wal", "w"), ("anchors.db", "a"), ("keys/custody_ed25519.pem", "k")):
        (outside / target).write_bytes(b"KEEP" * 2048)
        (data / name).parent.mkdir(exist_ok=True)
        (data / name).symlink_to(outside / target)
    if stop_after_step_one:

        def stopped(*_a, **_k):
            raise KeyboardInterrupt("stopped after step 1")

        import src.safety.data_volume as data_volume

        monkeypatch.setattr(data_volume, "configured_folder", stopped)
        with pytest.raises(KeyboardInterrupt):
            crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    else:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
        assert report["removed"] is True
    assert precious.read_bytes() == b"KEEP" * 2048
    assert (outside / "inner.db-wal").read_bytes() == b"KEEP" * 2048
    for target in ("w", "a", "k"):
        assert (outside / target).read_bytes() == b"KEEP" * 2048, target


@pytest.mark.skipif(os.name != "posix", reason="symlinks need POSIX here")
def test_a_corpus_linked_into_place_is_still_erased_where_it_really_is(tmp_path):
    """The app's own databases are the one place a link is followed: a corpus kept on another drive and linked into the
    data dir loses its salt page at its real location."""
    data = tmp_path / "data"
    data.mkdir()
    real = tmp_path / "other-drive" / "corpus.db"
    real.parent.mkdir()
    real.write_bytes(b"SALT-SALT-SALT-!" + b"S" * 8176)
    (data / "open_omniscience.db").symlink_to(real)

    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)

    assert b"SALT-SALT-SALT-!" not in (real.read_bytes() if real.exists() else b"")
    assert report["overwrite_failures"] == []


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a folder this user cannot list")
def test_a_folder_the_erase_cannot_list_is_named_as_a_failure(tmp_path):
    data = tmp_path / "data"
    locked = data / "locked"
    locked.mkdir(parents=True)
    (locked / "pre-restore-1.db").write_bytes(b"S" * 8192)
    locked.chmod(0)
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    finally:
        locked.chmod(0o700)
    assert str(locked) in report["overwrite_failures"]
    assert report["overwrite_failures"].count(str(locked)) == 1
