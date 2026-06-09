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
    """
    from src.backup.sqlite_backup import BackupError, live_db_path, validate_sqlite_file

    plaintext = decrypt_bytes(blob, passphrase)  # raises on wrong passphrase / tamper

    fd, tmp = tempfile.mkstemp(prefix="oo-encrestore-", suffix=".db")
    import os

    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(plaintext)
        rows = validate_sqlite_file(tmp_path)  # raises BackupError if not a real OO DB
        dest = live_db_path()
        if dest is None:
            raise BackupError("restore is only supported for a local SQLite database")
        # Snapshot the current DB next to it before overwriting (never destroy silently).
        if dest.exists():
            from datetime import UTC, datetime

            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dest.with_suffix(dest.suffix + f".pre-restore-{stamp}.bak").write_bytes(dest.read_bytes())
        dest.write_bytes(plaintext)
        return {"restored": True, "validated_rows": rows, "path": str(dest)}
    finally:
        tmp_path.unlink(missing_ok=True)
