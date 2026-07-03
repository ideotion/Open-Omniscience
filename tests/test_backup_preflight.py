"""Backup reliability H3/H4: the AES-GCM 2 GiB cap fails HONESTLY, and a disk-space
PREFLIGHT refuses loudly before a backup/restore rather than failing mid-write.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The crypto tests are pure (cryptography is a core dep). The preflight-wiring tests
monkeypatch the free-space probe / the live-DB path, so they never need a real corpus.
"""

from __future__ import annotations

import pytest

from src import safety
from src.backup import artifact as art
from src.backup.artifact import BackupSpaceError, preflight_free_space
from src.safety import crypto
from src.safety.crypto import EncryptionError, decrypt_bytes, encrypt_bytes


# --------------------------------------------------------------------------- #
# H4 — the AES-GCM ~2 GiB cap fails with an honest error, not a cryptic OverflowError


def test_encrypt_over_the_gcm_cap_raises_a_clear_error(monkeypatch):
    # Lower the cap so we can exercise the guard without allocating 2 GiB.
    monkeypatch.setattr(crypto, "_GCM_MAX_BYTES", 16)
    with pytest.raises(EncryptionError) as exc:
        encrypt_bytes(b"x" * 20, "pw")
    msg = str(exc.value).lower()
    assert "aes-gcm" in msg or "2 gib" in msg
    assert "streaming" in msg or "volume" in msg  # points at the real answer
    # It is an EncryptionError, NOT an OverflowError.
    assert not isinstance(exc.value, OverflowError)


def test_decrypt_over_the_gcm_cap_raises_a_clear_error(monkeypatch):
    # A valid container built under the real cap, then the cap lowered so the ciphertext
    # length exceeds it -> an honest error instead of AES-GCM's OverflowError.
    blob = encrypt_bytes(b"y" * 64, "pw")
    monkeypatch.setattr(crypto, "_GCM_MAX_BYTES", 8)
    with pytest.raises(EncryptionError) as exc:
        decrypt_bytes(blob, "pw")
    assert "aes-gcm" in str(exc.value).lower() or "2 gib" in str(exc.value).lower()


def test_normal_round_trip_still_works():
    blob = encrypt_bytes(b"hello world" * 100, "correct horse")
    assert decrypt_bytes(blob, "correct horse") == b"hello world" * 100
    with pytest.raises(EncryptionError):
        decrypt_bytes(blob, "wrong")


# --------------------------------------------------------------------------- #
# H3 — the disk-space preflight helper


def test_preflight_refuses_when_free_is_below_needed(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    monkeypatch.setattr(fb, "free_bytes", lambda p: 10)  # only 10 bytes free
    with pytest.raises(BackupSpaceError) as exc:
        preflight_free_space(tmp_path, needed=1_000_000, what="backup")
    m = str(exc.value).lower()
    assert "not enough free space" in m and "needs" in m and "free" in m
    # A BackupSpaceError is an ArtifactError, so existing callers that catch ArtifactError
    # (mapped to HTTP 400) surface it cleanly.
    assert isinstance(exc.value, art.ArtifactError)


def test_preflight_passes_when_there_is_room(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    monkeypatch.setattr(fb, "free_bytes", lambda p: 10_000_000)
    preflight_free_space(tmp_path, needed=1000, what="backup")  # no raise


# --------------------------------------------------------------------------- #
# H3 — the preflight is wired into the create + restore paths


def test_write_backup_refuses_on_a_full_disk(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb
    import src.backup.sqlite_backup as sb

    fake_db = tmp_path / "live.db"
    fake_db.write_bytes(b"Z" * 4096)  # a non-trivial "corpus" so needed > 0
    monkeypatch.setattr(sb, "live_db_path", lambda: fake_db)
    monkeypatch.setattr(fb, "free_bytes", lambda p: 0)  # nothing free anywhere
    with pytest.raises(BackupSpaceError):
        art.write_backup_v2(tmp_path / "out.oo-backup-2", passphrase="pw")


def test_restore_refuses_on_a_full_disk_before_staging(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    # A plaintext blob (not an OOENC1 header) reaches the preflight before any format check.
    blob = b"not-a-real-artifact" * 100
    monkeypatch.setattr(fb, "free_bytes", lambda p: len(blob) - 1)  # one byte short
    with pytest.raises(BackupSpaceError):
        art.read_artifact(blob, staging_root=tmp_path)
    # No staging dir should have been created (it refused before mkdir).
    assert not any(p.name.startswith(".restore-") for p in tmp_path.iterdir())


def test_restore_preflight_passes_then_fails_on_format(tmp_path, monkeypatch):
    import src.backup.folder_backup as fb

    blob = b"not-a-real-artifact"
    monkeypatch.setattr(fb, "free_bytes", lambda p: 10_000_000)  # plenty of room
    # The preflight passes; read_artifact then rejects the garbage format (ArtifactError,
    # NOT a BackupSpaceError) — proving the preflight let it through.
    with pytest.raises(art.ArtifactError) as exc:
        art.read_artifact(blob, staging_root=tmp_path)
    assert not isinstance(exc.value, BackupSpaceError)


def test_safety_module_import_smoke():
    # crypto lives under src.safety; ensure the package import is intact.
    assert hasattr(safety, "__name__")
