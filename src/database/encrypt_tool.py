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
    """Encrypt the main corpus AND the custody log under THE one passphrase
    (design D6). The caller disposes the engine before and re-opens after.

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
    with write_lock():
        reports = {
            "corpus": encrypt_database(main, key),
            "custody": encrypt_database(data_dir() / "custody_log.db", key),
        }
    return reports
