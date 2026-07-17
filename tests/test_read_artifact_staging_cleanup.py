"""Audit finding 2026-07-17: read_artifact left its staging directory (the
extracted, potentially-plaintext corpus copy) on disk indefinitely when a failure
happened AFTER extraction -- unlike its sibling restore paths (read_volume_backup,
read_stream_backup), which already wrap the risky work in try/except + rmtree.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from src.backup.artifact import ArtifactError, read_artifact


def _zip_bytes(manifest: dict, *, extra_files: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"manifest": manifest}))
        zf.writestr("corpus.db", b"not a real sqlite file, just needs to exist")
        for name, data in (extra_files or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_a_failure_after_extraction_cleans_up_the_staging_dir(tmp_path):
    """A wrong backup_schema is caught by _finalize_staged AFTER _safe_extract has
    already written corpus.db to the staging dir -- exactly the case that used to
    leak an extracted corpus copy."""
    blob = _zip_bytes({"backup_schema": "not-a-real-schema", "members": []})

    with pytest.raises(ArtifactError, match="unsupported backup schema"):
        read_artifact(blob, staging_root=tmp_path)

    leftovers = list(tmp_path.glob(".restore-*"))
    assert leftovers == [], f"staging directory was not cleaned up: {leftovers}"


def test_a_malformed_zip_missing_required_members_cleans_up_the_staging_dir(tmp_path):
    """The early "missing manifest/corpus" check also raises after staging.mkdir()
    (before extraction) -- must not litter an (empty) staging dir either."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("irrelevant.txt", b"not a backup")
    blob = buf.getvalue()

    with pytest.raises(ArtifactError, match="missing manifest/corpus"):
        read_artifact(blob, staging_root=tmp_path)

    leftovers = list(tmp_path.glob(".restore-*"))
    assert leftovers == [], f"staging directory was not cleaned up: {leftovers}"


def test_a_successful_read_still_returns_the_staging_dir_uncleaned(tmp_path):
    """The fix must only clean up on FAILURE -- a genuinely valid artifact still
    returns its staging dir intact for the caller to read/merge from."""
    blob = _zip_bytes({"backup_schema": "oo-backup-2", "members": []})

    staged = read_artifact(blob, staging_root=tmp_path)
    assert staged.staging_dir.exists()
    assert staged.corpus_path.exists()
