"""
PR-E: SQLCipher at-rest encryption — factory, boot states, tool, round trips.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The honesty gate (CLAUDE.md): the passphrase prompt ships TOGETHER with the
working crypto. These tests prove the crypto half end-to-end; the boot/unlock
scenarios run in subprocesses (the engine binds at import time and the lock
flag is process-global). The crown scenario: backup + merge-restore on an
ENCRYPTED live corpus must leave it encrypted — a restore that silently
decrypts the store would be the worst possible regression.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "sqlcipher_helper.py"
_TORTURE = _REPO / "tests" / "torture_helper.py"


def _run(helper: Path, data_dir: Path, *args: str, env_extra: dict | None = None) -> dict:
    env = dict(
        os.environ,
        OO_DATA_DIR=str(data_dir),
        OO_NO_SCHEDULER="1",
        OO_DB_PLAINTEXT="",  # the suite default is plaintext; these tests opt back IN
        OO_DB_PASSPHRASE="",
    )
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(helper), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=240,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------- #
#  The factory (in-process: explicit keys, no global state)
# --------------------------------------------------------------------------- #
def test_factory_encrypted_roundtrip_and_wrong_key(tmp_path):
    from src.database.connect import WrongPassphraseError, connect, is_encrypted_file

    p = tmp_path / "enc.db"
    con = connect(p, key="factory-pw")
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (7)")
    con.commit()
    con.close()
    assert is_encrypted_file(p) is True
    con2 = connect(p, key="factory-pw")
    assert con2.execute("SELECT x FROM t").fetchone() == (7,)
    con2.close()
    with pytest.raises(WrongPassphraseError):
        connect(p, key="WRONG")
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(p)).execute("SELECT * FROM t")


def test_factory_plaintext_and_fresh_policy(tmp_path, monkeypatch):
    from src.database.connect import DatabaseLockedError, connect, is_encrypted_file

    plain = tmp_path / "plain.db"
    sqlite3.connect(str(plain)).execute("CREATE TABLE t(x)")
    con = connect(plain)  # existing plaintext opens via stdlib, no key needed
    assert type(con).__module__.startswith("sqlite3")
    con.close()

    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    fresh = tmp_path / "fresh.db"
    with pytest.raises(DatabaseLockedError):
        connect(fresh, key=None)  # encrypted-by-default needs an explicit choice
    con3 = connect(fresh, create_encrypted=False)  # the explicit opt-out
    con3.close()
    assert is_encrypted_file(fresh) in (False, None)


def test_snapshot_helpers_cross_boundary(tmp_path):
    from src.database.connect import (
        connect,
        is_encrypted_file,
        reencrypt_plain_to,
        set_passphrase,
        snapshot_preserving,
        snapshot_to_plaintext,
    )

    enc = tmp_path / "enc.db"
    con = connect(enc, key="snap-pw")
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()

    set_passphrase("snap-pw")
    try:
        plain = snapshot_to_plaintext(enc, tmp_path / "plain.db")
        assert is_encrypted_file(plain) is False
        assert sqlite3.connect(str(plain)).execute("SELECT x FROM t").fetchone() == (1,)

        keep = snapshot_preserving(enc, tmp_path / "keep.db")
        assert is_encrypted_file(keep) is True  # the safety net stays ciphertext
        c = connect(keep, key="snap-pw")
        assert c.execute("SELECT x FROM t").fetchone() == (1,)
        c.close()
    finally:
        set_passphrase(None)

    back = reencrypt_plain_to(plain, tmp_path / "back.db", "snap-pw2")
    assert is_encrypted_file(back) is True
    c2 = connect(back, key="snap-pw2")
    assert c2.execute("SELECT x FROM t").fetchone() == (1,)
    c2.close()


def test_snapshot_and_reencrypt_preserve_source_page_size_and_auto_vacuum(tmp_path):
    """Found empirically while building DB-10 §1b: snapshot_preserving and
    reencrypt_plain_to ATTACH a fresh encrypted target and export into it —
    an empty ATTACHed database otherwise defaults to SQLCipher's compiled-in
    page size regardless of the source, so a merge/restore cycle (which uses
    snapshot_preserving for its pre-restore safety net) silently DOWNGRADED
    a fresh 16384-page/auto_vacuum=INCREMENTAL corpus back to the legacy
    default the moment it took a snapshot — reproduced live via
    tests/torture_helper.py's build+build+merge sequence, which regressed
    from a hard failure (the marker-based design) to a silent, undetected
    page-size loss (this design) before this fix. Both directions matter: a
    NEW-ruled-default source must not get silently downgraded, and a LEGACY
    source must not get silently upgraded — snapshot/re-encrypt preserves
    whatever the source actually is, exactly like it already preserves the
    source's encryption state."""
    from src.database.connect import (
        connect,
        reencrypt_plain_to,
        set_passphrase,
        snapshot_preserving,
    )

    # A fresh (ruled-default) source: 16384 / INCREMENTAL.
    enc = tmp_path / "enc.db"
    con = connect(enc, key="pp-pw")
    con.execute("CREATE TABLE t(x)")
    con.commit()
    assert int(con.execute("PRAGMA page_size").fetchone()[0]) == 16384
    assert int(con.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    con.close()

    set_passphrase("pp-pw")
    try:
        keep = snapshot_preserving(enc, tmp_path / "keep.db")
    finally:
        set_passphrase(None)
    k = connect(keep, key="pp-pw")
    assert int(k.execute("PRAGMA page_size").fetchone()[0]) == 16384  # NOT silently downgraded
    assert int(k.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    k.close()

    # A LEGACY-shaped source (explicit non-ruled size): must NOT be upgraded.
    legacy_enc = tmp_path / "legacy_enc.db"
    con2 = connect(legacy_enc, key="pp-pw2", cipher_page_size=4096)
    con2.execute("CREATE TABLE t(x)")
    con2.commit()
    assert int(con2.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2  # still ruled (§1a, no reopen hazard)
    con2.close()
    set_passphrase("pp-pw2")
    try:
        keep2 = snapshot_preserving(legacy_enc, tmp_path / "keep2.db")
    finally:
        set_passphrase(None)
    k2 = connect(keep2, key="pp-pw2")
    assert int(k2.execute("PRAGMA page_size").fetchone()[0]) == 4096  # NOT silently upgraded
    k2.close()

    # reencrypt_plain_to (the encrypt-in-place tool's own path): a NORMAL
    # plaintext source (SQLite's own default page size — this is the
    # realistic case, an EXISTING plaintext corpus being encrypted, not a
    # brand-new one) must land the re-encrypted target at that SAME size —
    # encrypting an existing corpus is a format conversion, not a "new
    # corpus," so it must NOT silently jump to the §1b ruled default either.
    plain = tmp_path / "plain.db"
    p = sqlite3.connect(str(plain))
    default_page_size = int(p.execute("PRAGMA page_size").fetchone()[0])
    p.execute("CREATE TABLE t(x)")
    p.commit()
    p.close()
    reenc = reencrypt_plain_to(plain, tmp_path / "reenc.db", "pp-pw3")
    r = connect(reenc, key="pp-pw3")  # the probe's 2nd candidate (legacy default) finds it
    assert int(r.execute("PRAGMA page_size").fetchone()[0]) == default_page_size
    r.close()


def test_fresh_stores_get_incremental_auto_vacuum_legacy_stores_untouched(tmp_path):
    """DB-10 §1a (ruled 2026-07-17): every NEW corpus — encrypted or plaintext —
    is created with ``auto_vacuum=INCREMENTAL`` (2), and a PRE-EXISTING store
    (created before this change, or by any path other than a fresh connect())
    keeps whatever mode it already had. auto_vacuum has no reopen hazard (it is
    read back from the file header on every open, no extra plumbing needed —
    unlike page_size), so a plain reopen is the whole round-trip proof."""
    from src.database.connect import connect

    # Fresh ENCRYPTED store.
    enc = tmp_path / "fresh_enc.db"
    c1 = connect(enc, key="av-pw")
    c1.execute("CREATE TABLE t(x)")
    c1.commit()
    # int(): some sqlcipher3 builds return PRAGMA values as TEXT ("2" not 2).
    assert int(c1.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    c1.close()
    # Reopen via the NORMAL encrypted path (state is now True, not "fresh") —
    # the mode is read from the file header, not re-declared.
    c1b = connect(enc, key="av-pw")
    assert int(c1b.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    c1b.close()

    # Fresh PLAINTEXT store (the explicit opt-out path).
    plain = tmp_path / "fresh_plain.db"
    c2 = connect(plain, create_encrypted=False)
    c2.execute("CREATE TABLE t(x)")
    c2.commit()
    assert int(c2.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    c2.close()

    # A LEGACY store — created by a path connect() never touches (bypassing its
    # fresh-file branch entirely, standing in for any corpus that existed before
    # this ruling) — must be left exactly as it was: auto_vacuum stays NONE (0).
    legacy = tmp_path / "legacy_plain.db"
    raw = sqlite3.connect(str(legacy))
    raw.execute("CREATE TABLE t(x)")
    raw.commit()
    raw.close()
    c3 = connect(legacy)  # now an existing plaintext file -> the "state is False" path
    assert int(c3.execute("PRAGMA auto_vacuum").fetchone()[0]) == 0
    c3.close()


def test_page_size_1b_round_trip_across_a_real_restart(tmp_path):
    """DB-10 §4.1.6 mandatory acceptance test — the proof that closes the
    §1b reopen-safety gap: create -> close the process entirely -> reopen via
    the NORMAL boot path (session.py's engine creator, which passes NO
    cipher_page_size at all) in a BRAND NEW process -> the SAME passphrase
    still opens it AND page_size reads back 16384. Without connect()'s
    verify-then-fallback probe, this reproduces the exact 2026-07-19 field
    incident: a correct passphrase misread as wrong after a restart."""
    d = tmp_path / "pagesize"
    d.mkdir()
    created = _run(_HELPER, d, "pagesize-create")
    assert created["created"] is True
    assert created["api_ok"] == 200
    assert created["page_size"] == 16384  # DB-10 §1b's ruled default, applied on create

    reopened = _run(
        _HELPER, d, "pagesize-reopen", env_extra={"OO_DB_PASSPHRASE": "pw-pagesize-test"}
    )
    assert reopened["state"] == "unlocked-encrypted"
    assert reopened["api_ok"] == 200  # the passphrase STILL opens it after a real restart
    assert reopened["doctor_corpus"] == "encrypted" and reopened["cipher"]
    assert reopened["page_size"] == 16384  # the probe found it with zero call-site change


def test_page_size_probe_resolves_automatically_in_process(tmp_path):
    """The lighter, in-process companion to the full-process round trip above:
    connect() with NO explicit cipher_page_size still opens a fresh store at
    its real 16384 (the exact call shape session.py's engine creator uses),
    by PROBING -- never a persisted marker (see the design-choice comment
    above connect.py's _FRESH_PAGE_SIZE: a marker went stale in this exact
    codebase when snapshot_preserving/reencrypt_plain_to silently rewrote a
    live path at a different size). An explicit caller value still wins, at
    both create and reopen time. A LEGACY store (built by a path other than
    a fresh connect(), standing in for any corpus older than this ruling)
    keeps opening at whatever size is ACTUALLY on disk -- never a fabricated
    16384, and the probe pays exactly one extra page-1 HMAC check for it."""
    from src.database.connect import connect

    enc = tmp_path / "enc.db"
    c1 = connect(enc, key="rt-pw")
    c1.execute("CREATE TABLE t(x)")
    c1.commit()
    assert int(c1.execute("PRAGMA page_size").fetchone()[0]) == 16384
    c1.close()

    # Reopen with NO cipher_page_size argument at all -- the probe's FIRST
    # candidate (16384) matches immediately, zero extra cost.
    c1b = connect(enc, key="rt-pw")
    assert int(c1b.execute("PRAGMA page_size").fetchone()[0]) == 16384
    c1b.execute("SELECT 1 FROM sqlite_master").fetchone()  # actually readable, not just labelled
    c1b.close()

    # An explicit override still wins, at BOTH create and reopen time.
    enc2 = tmp_path / "enc2.db"
    c2 = connect(enc2, key="rt-pw2", cipher_page_size=4096)
    c2.execute("CREATE TABLE t(x)")
    c2.commit()
    assert int(c2.execute("PRAGMA page_size").fetchone()[0]) == 4096
    c2.close()
    # Reopen with NO explicit size -- the probe's SECOND candidate (legacy
    # default) finds it, since 16384 (tried first) genuinely mismatches.
    c2b = connect(enc2, key="rt-pw2")
    assert int(c2b.execute("PRAGMA page_size").fetchone()[0]) == 4096
    c2b.close()

    # A LEGACY store (built by a path connect() never touches, standing in for
    # any corpus that existed before this ruling) -- the probe finds its
    # ACTUAL on-disk size, never a fabricated 16384.
    from sqlcipher3 import dbapi2 as sqc

    legacy = tmp_path / "legacy.db"
    raw = sqc.connect(str(legacy))
    raw.execute("PRAGMA key = 'legacy-pw'")
    raw.execute("CREATE TABLE t(x)")
    raw.commit()
    legacy_size = int(raw.execute("PRAGMA page_size").fetchone()[0])
    raw.close()
    c3 = connect(legacy, key="legacy-pw")  # now an existing encrypted file
    assert int(c3.execute("PRAGMA page_size").fetchone()[0]) == legacy_size
    c3.execute("SELECT 1 FROM sqlite_master").fetchone()
    c3.close()


def test_page_size_probe_still_raises_wrongpassphraseerror_on_a_genuinely_wrong_key(tmp_path):
    """The probe must not mask an actually-wrong passphrase: EVERY candidate
    it tries fails against the wrong key, and the final, honest
    WrongPassphraseError still surfaces -- exactly as it did before the probe
    existed, with its ORIGINAL cause chained (``__cause__``) for
    debuggability rather than silently discarded."""
    from src.database.connect import WrongPassphraseError, connect

    enc = tmp_path / "enc.db"
    c1 = connect(enc, key="right-pw")
    c1.execute("CREATE TABLE t(x)")
    c1.commit()
    c1.close()
    with pytest.raises(WrongPassphraseError) as excinfo:
        connect(enc, key="WRONG")
    assert excinfo.value.__cause__ is not None


def test_page_size_probe_finds_an_atypical_size_with_no_explicit_hint(tmp_path):
    """Adversarial-skeptic finding (2026-07-23, HIGH): probing only
    [16384, None] left any store at some OTHER legitimate page size
    unopenable with no explicit cipher_page_size -- reproducing this fix's
    own target bug (encrypt_tool.py's immediate post-encrypt self-verify
    passes no explicit size). The widened candidate list must find an
    ATYPICAL size (8192 -- neither the ruled default nor the common legacy
    default) automatically."""
    from src.database.connect import connect

    enc = tmp_path / "enc.db"
    c1 = connect(enc, key="atypical-pw", cipher_page_size=8192)
    c1.execute("CREATE TABLE t(x)")
    c1.commit()
    assert int(c1.execute("PRAGMA page_size").fetchone()[0]) == 8192
    c1.close()

    # Reopen with NO explicit cipher_page_size at all -- the probe must find
    # 8192 on its own.
    c2 = connect(enc, key="atypical-pw")
    assert int(c2.execute("PRAGMA page_size").fetchone()[0]) == 8192
    c2.execute("SELECT 1 FROM sqlite_master").fetchone()
    c2.close()


def test_page_size_probe_caches_the_winning_candidate_per_path(tmp_path):
    """Adversarial-skeptic finding (2026-07-23, performance): a widened probe
    without a cache would pay the (deliberately expensive) key derivation
    once per candidate tried on EVERY new connection to a non-default store.
    The in-process cache (never persisted -- see the design-choice comment)
    must record the winning candidate after the first open and serve it
    first on a repeated open of the SAME path, verified by watching
    connect.py's OWN cache dict directly (a real behavioural effect, not a
    mocked call count)."""
    from src.database import connect as connect_mod

    enc = tmp_path / "enc.db"
    resolved = str(enc.resolve())
    assert resolved not in connect_mod._last_good_page_size

    c1 = connect_mod.connect(enc, key="cache-pw", cipher_page_size=8192)
    c1.execute("CREATE TABLE t(x)")
    c1.commit()
    c1.close()

    # An explicit cipher_page_size at CREATE time never touches the cache.
    assert resolved not in connect_mod._last_good_page_size

    c2 = connect_mod.connect(enc, key="cache-pw")  # no explicit size -> probes + caches
    c2.close()
    assert connect_mod._last_good_page_size.get(resolved) == 8192

    # A SUBSEQUENT open of the same path must still succeed (and keep
    # reporting the same cached winner) -- the cache is never trusted
    # blindly, but here it is also genuinely correct.
    c3 = connect_mod.connect(enc, key="cache-pw")
    assert int(c3.execute("PRAGMA page_size").fetchone()[0]) == 8192
    c3.close()
    assert connect_mod._last_good_page_size.get(resolved) == 8192


def test_encrypt_tool_inplace(tmp_path):
    from src.database.connect import connect, is_encrypted_file
    from src.database.encrypt_tool import encrypt_database

    db = tmp_path / "corpus.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, t TEXT)")
    raw.executemany("INSERT INTO articles(t) VALUES (?)", [("a",), ("b",)])
    raw.commit()
    raw.close()

    rep = encrypt_database(db, "tool-pw-123")
    assert rep["encrypted"] is True
    assert is_encrypted_file(db) is True
    assert Path(rep["plaintext_snapshot"]).exists()  # the deliberate escape hatch
    c = connect(db, key="tool-pw-123")
    assert c.execute("SELECT COUNT(*) FROM articles").fetchone() == (2,)
    c.close()
    assert encrypt_database(db, "tool-pw-123")["skipped"] == "already encrypted"


def test_legacy_plaintext_keys_survive_passphrase(tmp_path, monkeypatch):
    """Signing keys created BEFORE encryption keep loading after THE passphrase
    exists (D6 fallback): they are re-wrapped only by an explicit re-key, never
    silently broken — and key_protection reports the file's REAL state."""
    from src.custody.signing import HybridSigner
    from src.database.connect import set_passphrase

    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    ed, ml = tmp_path / "k.pem", tmp_path / "k.mldsa"
    s1 = HybridSigner(ed25519_path=ed, mldsa_path=ml)  # created plaintext
    ident = s1.public_identity().to_dict()
    set_passphrase("now-encrypted-pw")
    try:
        s2 = HybridSigner(ed25519_path=ed, mldsa_path=ml)  # must still load
        assert s2.public_identity().to_dict() == ident
        assert s2.key_protection == "plaintext-0600"  # honest about the file
    finally:
        set_passphrase(None)


# --------------------------------------------------------------------------- #
#  Boot states (subprocesses: import-time engine + process-global lock flag)
# --------------------------------------------------------------------------- #
def test_boot_fresh_create_then_locked_then_env(tmp_path):
    d = tmp_path / "boot"
    d.mkdir()
    fresh = _run(_HELPER, d, "boot-fresh")
    assert fresh["state"] == "fresh"
    assert fresh["root_redirect"] and fresh["gated_503"] and fresh["unlock_page_ok"]
    assert fresh["mismatch_400"] and fresh["created"]
    assert fresh["state_after"] == "unlocked-encrypted" and fresh["api_after"] == 200
    assert fresh["file_encrypted"] is True and fresh["doctor_corpus"] == "encrypted"

    locked = _run(_HELPER, d, "boot-locked")
    assert locked["state"] == "locked" and locked["gated_503"]
    assert locked["wrong_403"] and locked["right_200"]
    assert locked["state_after"] == "unlocked-encrypted" and locked["api_after"] == 200

    headless = _run(_HELPER, d, "boot-env", env_extra={"OO_DB_PASSPHRASE": "pw-boot-test"})
    assert headless["state"] == "unlocked-encrypted" and headless["api"] == 200
    assert headless["doctor_corpus"] == "encrypted" and headless["cipher"]


def test_encrypt_inplace_endpoint(tmp_path):
    d = tmp_path / "tool"
    d.mkdir()
    out = _run(_HELPER, d, "encrypt-inplace", env_extra={"OO_DB_PLAINTEXT": "1"})
    assert out["before"] == "plaintext"
    assert out["no_consent_400"] and out["done"]
    assert out["after"] == "encrypted" and out["file_encrypted"] is True
    assert out["snapshot_kept"] and out["api_after"] == 200
    assert out["cipher"]  # doctor read the real cipher version through the key


# --------------------------------------------------------------------------- #
#  The crown: backup + merge-restore on an ENCRYPTED live corpus
# --------------------------------------------------------------------------- #
def test_backup_and_merge_keep_encryption(tmp_path):
    """An encrypted corpus backs up (plaintext member inside the encrypted
    artifact), merges a foreign artifact, and is STILL ciphertext afterwards —
    the restore pipeline must never silently decrypt the store."""
    enc_env = {"OO_DB_PASSPHRASE": "pw-crown"}
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "b.oobak.ooenc"

    built = _run(_TORTURE, b, "build", "B", "--artifact", str(art),
                 "--passphrase", "artifact-pw", env_extra=enc_env)
    assert built.get("artifact")
    assert (b / "open_omniscience.db").exists()
    from src.database.connect import is_encrypted_file

    assert is_encrypted_file(b / "open_omniscience.db") is True  # B lived encrypted

    _run(_TORTURE, a, "build", "A", env_extra=enc_env)
    assert is_encrypted_file(a / "open_omniscience.db") is True

    rep = _run(_TORTURE, a, "merge", str(art), "--passphrase", "artifact-pw",
               "--commit", env_extra=enc_env)["report"]
    assert rep["committed"] is True and rep["verification"]["ok"] is True

    live = a / "open_omniscience.db"
    assert is_encrypted_file(live) is True, "merge-restore silently DECRYPTED the corpus"
    snaps = list(a.glob("pre-restore-*.db"))
    assert snaps and all(is_encrypted_file(s) for s in snaps), (
        "the pre-restore safety net leaked plaintext to disk"
    )
    dump = _run(_TORTURE, a, "dump", env_extra=enc_env)["dump"]
    assert dump["articles_n"] == 4  # shared + uniqA + uniqB + fillerB
