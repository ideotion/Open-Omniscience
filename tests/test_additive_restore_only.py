"""Guard: restore is ADDITIVE-ONLY — no replace path may ever come back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-13: restoring a backup must NEVER replace the corpus.
The destructive "replace the live database" paths were removed; the merge engine
(the oo-backup-2 artifact + /api/backup/v2/restore) is the ONLY restore. This
test fails the build if a replace-restore endpoint or function reappears — so the
guarantee cannot silently regress between sessions.
"""

from __future__ import annotations


def test_no_replace_restore_function_survives():
    import src.backup.sqlite_backup as sqlite_backup
    import src.safety
    import src.safety.backup as safety_backup

    # The destructive "atomically replace the live database" function is gone.
    assert not hasattr(sqlite_backup, "restore_from_bytes"), (
        "restore_from_bytes (replace-restore) must stay removed — restore is additive-only"
    )
    # Its encrypted envelope is gone too (it delegated to the same replace).
    assert not hasattr(safety_backup, "restore_encrypted_backup")
    assert not hasattr(src.safety, "restore_encrypted_backup")
    assert "restore_encrypted_backup" not in getattr(src.safety, "__all__", [])
    # Backup CREATION is untouched (still exported / present).
    assert hasattr(src.safety, "make_encrypted_backup")
    assert hasattr(sqlite_backup, "backup_to")


def test_replace_restore_endpoints_are_gone_and_merge_remains():
    from src.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    # The two destructive replace-restore endpoints no longer exist.
    assert "/api/database/restore" not in paths
    assert "/api/safety/restore/encrypted" not in paths
    # The ONE restore — the additive merge — is present.
    assert any("/v2/restore" in p for p in paths), "the merge restore endpoint must remain"
    # Backup CREATION endpoints remain (creating a backup is not a replace).
    assert "/api/safety/backup/encrypted" in paths
