"""
Encrypted, portable corpus backup (passphrase-protected).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Wraps the existing *online* SQLite backup (a consistent snapshot, valid even while the app
runs) in passphrase encryption (:mod:`src.safety.crypto`), so a journalist can carry or
stash their corpus across a border or a hostile network without exposing it.

Restore is ADDITIVE-ONLY (maintainer-ruled 2026-06-13): the destructive
``restore_encrypted_backup`` that *replaced* the live corpus has been REMOVED.
Restoring now goes exclusively through the merge engine (the oo-backup-2 artifact
+ the ``/api/database/v2/restore`` endpoints), which complements the corpus and
never overwrites it. This module now only *creates* encrypted backups.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.safety.crypto import encrypt_bytes


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
