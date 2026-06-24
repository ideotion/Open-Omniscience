"""Volume-set backup restore wiring (src/backup/artifact.py:read_volume_backup), slice 1b.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Verifies the new large-backup RESTORE path end to end at the artifact level (no live
data dir needed): a signed oo-backup-2 zip -> volume set (+ optional parity) -> verify
-> reassemble -> extract -> manifest signature + member-hash check -> StagedArtifact.
Pins that a wrong passphrase fails, and that Reed-Solomon parity transparently recovers a
corrupt volume so the restore still verifies (the maintainer's corruption-survival goal).
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup.artifact import BACKUP_SCHEMA, read_volume_backup
from src.backup.volumes import write_volume_set
from src.reporting.evidence import canonical_bytes


def _signed_backup_zip(tmp: Path, corpus: bytes) -> Path:
    """Build a minimal, validly-signed oo-backup-2 zip (manifest + corpus.db)."""
    key = Ed25519PrivateKey.generate()
    manifest = {
        "backup_schema": BACKUP_SCHEMA,
        "app_version": "test",
        "alembic_rev": "rev",
        "created_at": "2026-06-24T00:00:00+00:00",
        "encrypted": True,
        "keys_included": True,
        "members": [
            {"name": "corpus.db", "role": "corpus", "sha256": hashlib.sha256(corpus).hexdigest(),
             "bytes": len(corpus)}
        ],
        "excluded": {},
        "corpus": {},
    }
    envelope = {
        "manifest": manifest,
        "signature": key.sign(canonical_bytes(manifest)).hex(),
        "public_key": key.public_key().public_bytes_raw().hex(),
        "algorithm": "ed25519",
    }
    z = tmp / "artifact.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", json.dumps(envelope, ensure_ascii=False, indent=1))
        zf.writestr("corpus.db", corpus)
    return z


def _corpus() -> bytes:
    return b"SQLite format 3\x00" + b"corpus-payload" * 400  # > volume_size -> many volumes


def test_volume_backup_restore_round_trip(tmp_path):
    corpus = _corpus()
    z = _signed_backup_zip(tmp_path, corpus)
    dest = tmp_path / "vols"
    write_volume_set(z, dest, "pw", volume_size=2048, chunk_size=1024)

    staged = read_volume_backup(dest, "pw", staging_root=tmp_path / "stage")
    assert staged.signature_state == "verified"
    assert staged.hash_failures == []
    assert staged.corpus_path.read_bytes() == corpus
    assert staged.encrypted is True


def test_volume_backup_wrong_passphrase_fails(tmp_path):
    z = _signed_backup_zip(tmp_path, _corpus())
    dest = tmp_path / "vols"
    write_volume_set(z, dest, "pw", volume_size=2048, chunk_size=1024)
    with pytest.raises(Exception):  # noqa: B017 - EncryptionError/VolumeError, both loud
        read_volume_backup(dest, "WRONG", staging_root=tmp_path / "stage")


def test_volume_backup_parity_recovers_corruption(tmp_path):
    pytest.importorskip("numpy")
    from src.backup.parity import write_parity

    corpus = _corpus()
    z = _signed_backup_zip(tmp_path, corpus)
    dest = tmp_path / "vols"
    write_volume_set(z, dest, "pw", volume_size=2048, chunk_size=1024)
    write_parity(dest, parity_count=2)

    victim = dest / "vol-00002.ooenc"
    victim.write_bytes(victim.read_bytes()[:-4])  # corrupt a data volume

    staged = read_volume_backup(dest, "pw", staging_root=tmp_path / "stage")
    assert staged.signature_state == "verified"  # parity rebuilt it -> still verifies
    assert staged.corpus_path.read_bytes() == corpus
