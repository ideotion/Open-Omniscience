"""Root-cause guard: a volumes+parity backup nested in a SUBFOLDER must scan to the
exact directory holding its manifest, and restore from THAT path (not the scanned
parent) — the field report where a unified import of a volume set failed with
"Import failed — see console".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

read_volume_set/read_volume_backup call load_manifest(src_dir), which requires
src_dir/volumes.json. If the unified dialog handed the scanned ROOT while the set
lived one level down, load_manifest raised VolumeError. The recursive scan now returns
the subfolder path; the dialog restores each corpus with c.path. This test pins that
contract end to end (scan → the returned path restores; the parent does NOT).
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from src.backup.artifact import BACKUP_SCHEMA, read_volume_backup
from src.backup.import_scan import scan_import_folder
from src.backup.volumes import VolumeError, write_volume_set
from src.reporting.evidence import canonical_bytes


def _signed_backup_zip(tmp: Path, corpus: bytes) -> Path:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    manifest = {
        "backup_schema": BACKUP_SCHEMA,
        "app_version": "test",
        "alembic_rev": "rev",
        "created_at": "2026-07-02T00:00:00+00:00",
        "encrypted": True,
        "keys_included": True,
        "members": [
            {"name": "corpus.db", "role": "corpus",
             "sha256": hashlib.sha256(corpus).hexdigest(), "bytes": len(corpus)}
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


def test_nested_volume_set_scans_and_restores_from_its_own_dir(tmp_path):
    corpus = b"SQLite format 3\x00" + b"corpus-payload" * 400
    root = tmp_path / "mixed-backups"
    setdir = root / "corpus-backup"
    setdir.mkdir(parents=True)
    z = _signed_backup_zip(tmp_path, corpus)
    write_volume_set(z, setdir, "pw", volume_size=2048, chunk_size=1024)

    # The scan (recursive) reports the SUBFOLDER as the corpus path.
    found = scan_import_folder(root)["found"]
    assert len(found["corpus"]) == 1
    corpus_path = found["corpus"][0]["path"]
    assert corpus_path == str(setdir)
    assert found["corpus"][0]["volumes"] >= 1

    # Restoring from the reported path works …
    staged = read_volume_backup(Path(corpus_path), "pw", staging_root=tmp_path / "stage")
    assert staged.corpus_path.read_bytes() == corpus

    # … while restoring from the scanned PARENT fails loudly (the old bug: no manifest
    # in the parent). This is exactly why the dialog must use the scanned subfolder path.
    with pytest.raises(VolumeError):
        read_volume_backup(root, "pw", staging_root=tmp_path / "stage2")
