"""
Encrypted, portable corpus backup (passphrase-protected).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Wraps the existing *online* SQLite backup (a consistent snapshot, valid even while the app
runs) in passphrase encryption (:mod:`src.safety.crypto`), so a journalist can carry or
stash their corpus across a border or a hostile network without exposing it. Restore
decrypts, then *validates* the snapshot is a genuine Open Omniscience database before it is
written — a wrong passphrase or a tampered file is rejected loudly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.safety.crypto import decrypt_bytes, encrypt_bytes


def make_encrypted_backup(passphrase: str) -> bytes:
    """Return a passphrase-encrypted snapshot of the live corpus DB."""
    from src.backup.sqlite_backup import backup_to

    fd, tmp = tempfile.mkstemp(prefix="oo-encbak-", suffix=".db")
    Path(tmp).unlink(missing_ok=True)  # backup_to recreates cleanly
    import os

    os.close(fd)
    try:
        backup_to(Path(tmp))
        plaintext = Path(tmp).read_bytes()
        return encrypt_bytes(plaintext, passphrase)
    finally:
        Path(tmp).unlink(missing_ok=True)


def restore_encrypted_backup(blob: bytes, passphrase: str) -> dict:
    """Decrypt + validate an encrypted backup and restore it over the live DB.

    Returns a small report. Raises ``EncryptionError`` on a bad passphrase/tamper and
    ``BackupError`` if the decrypted payload is not a genuine Open Omniscience database
    (so a hostile file can never overwrite the corpus).

    The swap itself is delegated to :func:`src.backup.sqlite_backup.restore_from_bytes`
    -- ONE restore path, encryption is only an envelope -- so this flow carries the
    same guarantees as the plain one: validation on a staged copy, a pre-restore
    snapshot via the online backup API, engine-pool disposal, stale ``-wal``/``-shm``
    removal, an atomic ``os.replace`` and the schema/FTS reconcile. (Re-implementing
    the swap by hand here had drifted into a non-atomic write with none of those
    steps -- gap analysis `docs/design/DB_RELIABILITY_01_GAP_ANALYSIS.md` §4.)
    """
    from src.backup.sqlite_backup import live_db_path, restore_from_bytes

    plaintext = decrypt_bytes(blob, passphrase)  # raises on wrong passphrase / tamper
    report = restore_from_bytes(plaintext)  # raises BackupError before touching anything
    return {
        "restored": True,
        "validated_rows": report.tables_seen,
        "path": str(live_db_path()),
        "pre_restore_snapshot": report.pre_restore_snapshot,
    }
