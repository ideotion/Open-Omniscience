"""
One-way encrypt tool for EXISTING plaintext stores (maintainer-ruled flow).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Snapshot first, explicit consent, never silent on upgrade: an existing
plaintext database keeps working untouched until the operator explicitly
encrypts it. The pre-encrypt snapshot is DELIBERATELY plaintext — it is the
operator's last escape hatch if the passphrase is mistyped into muscle memory
wrong; the report says so and the operator deletes it when satisfied.
"One-way" means the tool never decrypts in place; an operator who knows the
passphrase can always produce a plaintext *backup* through the normal flow.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from src.database.connect import (
    connect,
    is_encrypted_file,
    reencrypt_plain_to,
    snapshot_to_plaintext,
)

_LOG = logging.getLogger("database.encrypt_tool")


class EncryptToolError(RuntimeError):
    """Raised when an in-place encryption cannot proceed safely."""


def _table_counts(conn) -> dict[str, int]:
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'article_fts%'"
        )
    ]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}  # noqa: S608  # nosec B608 - identifier from the fixed store list, never input


def encrypt_database(path: Path | str, key: str) -> dict:
    """Encrypt one SQLite file in place: snapshot -> export -> verify -> swap.

    The live file is replaced only AFTER the encrypted copy passes
    quick_check and per-table count equality. Returns an honest report."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {"path": str(p), "skipped": "file does not exist"}
    if is_encrypted_file(p):
        return {"path": str(p), "skipped": "already encrypted"}
    if not key or len(key) < 8:
        raise EncryptToolError("use at least 8 characters")

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = p.with_name(f"pre-encrypt-{ts}-{p.name}")
    snapshot_to_plaintext(p, snapshot)

    enc_tmp = p.with_name(p.name + f".enc-{ts}")
    try:
        reencrypt_plain_to(p, enc_tmp, key)

        src = connect(p, check_same_thread=False)
        try:
            want = _table_counts(src)
        finally:
            src.close()
        chk = connect(enc_tmp, key=key, check_same_thread=False)
        try:
            ok = chk.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            got = _table_counts(chk)
        finally:
            chk.close()
        if not ok or got != want:
            raise EncryptToolError(
                f"verification failed on {p.name} (quick_check={ok}, counts match="
                f"{got == want}); the original file is untouched"
            )

        for suffix in ("-wal", "-shm"):
            stale = p.with_name(p.name + suffix)
            if stale.exists():
                stale.unlink()
        os.replace(enc_tmp, p)  # atomic on the same filesystem
    finally:
        enc_tmp.unlink(missing_ok=True)
    _LOG.info("encrypted %s (snapshot kept: %s)", p.name, snapshot.name)
    return {
        "path": str(p),
        "encrypted": True,
        "tables": len(_table_counts_safe(p, key)),
        "plaintext_snapshot": str(snapshot),
        "snapshot_note": "kept ON PURPOSE as your escape hatch -- delete it once "
        "you have unlocked successfully and are satisfied",
    }


def _table_counts_safe(p: Path, key: str) -> dict:
    conn = connect(p, key=key, check_same_thread=False)
    try:
        return _table_counts(conn)
    finally:
        conn.close()


def encrypt_all(key: str) -> dict:
    """Encrypt EVERY at-rest store under THE one passphrase (design D6).
    The caller disposes the engine before and re-opens after.

    THE LIST IS THE FEATURE, and it is the part that rots. This function enumerated
    the corpus and the custody log for as long as those were the only two databases.
    The versioned-source LANES (``wiki.db`` / ``law.db`` / ``osm.db``) are encrypted
    stores too, and left out they would survive "Encrypt my store" untouched: the
    operator consents, the corpus becomes ciphertext, and the lane stays plaintext on
    disk FOREVER — every later open takes ``connect()``'s plaintext branch, which never
    consults the passphrase at all. The lane holds which sources the operator tracks,
    which is exactly the selection Q1005 = a says is as revealing as the data.

    So the lanes are read from the REGISTRY (``src.versioned.lanes``) rather than listed
    here, and an absent lane is skipped rather than created — ``encrypt_database``
    already reports ``skipped`` for a file that does not exist, which is how the custody
    log has always been handled.

    Held under the single-writer gate (audit finding 2026-07-17): encrypt_database
    reads the live file through a RAW sqlcipher3/sqlite3 connection, not the ORM
    session the gate's flush/commit events watch, so without an EXPLICIT hold a
    concurrently-committing scraper could write new rows into the plaintext file
    AFTER the encrypted copy is built but BEFORE the atomic swap -- those rows
    would be silently discarded when the swap lands. The gate makes every other
    writer QUEUE (never error) for the duration, exactly its documented purpose;
    holding it across this one-time, user-consented, non-hot-path operation is
    the safe tradeoff over risking silent data loss.
    """
    from src.api.unlock import main_db_path
    from src.database.writer import write_lock
    from src.paths import data_dir

    main = main_db_path()
    if main is None:
        raise EncryptToolError("non-SQLite backend: the at-rest layer does not apply")
    from src.versioned.lanes import all_lanes

    with write_lock():
        reports = {
            "corpus": encrypt_database(main, key),
            "custody": encrypt_database(data_dir() / "custody_log.db", key),
        }
        # Close any lane pool first: encrypt_database swaps the file underneath, and a
        # cached engine would go on using a handle to the replaced one.
        try:
            from src.versioned.store import dispose_all as _dispose_lanes

            _dispose_lanes()
        except Exception:  # noqa: BLE001 - never let bookkeeping block the encryption
            _LOG.warning("could not dispose the lane engines before encrypting", exc_info=True)
        # BESIDE THE CORPUS means beside THE CORPUS THIS CALL IS ENCRYPTING — so the
        # lane directory is taken from ``main.parent``, not independently from
        # ``data_dir()``. The two resolvers do not always agree: ``main_db_path()``
        # reads ``DATABASE_URL``, which ``src/database/session.py`` computes at IMPORT
        # time, while ``data_dir()`` re-reads the environment on every call. Where they
        # diverge, encrypting a corpus in one directory and lanes in another would
        # leave the operator's real lanes untouched while reporting success — the exact
        # failure this whole change exists to prevent, one directory over.
        #
        # MEASURED, not hypothesised: a test of this function that pointed OO_DATA_DIR
        # at a temporary directory still reached the session-wide corpus through
        # main_db_path() and encrypted it, taking 86 unrelated tests down with it.
        for spec in all_lanes():
            reports[f"lane:{spec.kind}"] = encrypt_database(main.parent / spec.filename, key)
    return reports
