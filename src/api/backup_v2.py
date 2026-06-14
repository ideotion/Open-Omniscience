"""
oo-backup-2 endpoints: full-state backup + merge-only restore (preview/commit).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design: docs/design/DB_RELIABILITY_02_DESIGN.md §2-3. The legacy endpoints
(/api/database/backup|restore, /api/safety/*) stay for compatibility; these are
the mandate's surface: one artifact carrying EVERYTHING, restore that merges
and can refuse, never replaces.
"""

from __future__ import annotations

import logging
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.backup.artifact import ArtifactError, StagedArtifact, cleanup_staging, read_artifact
from src.backup.merge import MergeError, run_restore

_LOG = logging.getLogger("api.backup_v2")

router = APIRouter(prefix="/api/backup", tags=["backup-v2"])

_MAX_RESTORE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB, same honest cap as legacy restore

# Staged previews awaiting a commit decision: token -> StagedArtifact. Process-
# local by design (preview + commit happen within one operator session); orphans
# on disk are reclaimed by cleanup_stale_staging at boot.
_PENDING: dict[str, StagedArtifact] = {}


class BackupBody(BaseModel):
    passphrase: str | None = None
    plaintext: bool = False


@router.post("/v2")
def backup_v2(body: BackupBody) -> FileResponse:
    """Build and download a full oo-backup-2 artifact.

    Encrypted (passphrase) is the intended default; ``plaintext=true`` must be
    passed EXPLICITLY and the artifact then excludes the signing keys (D2)."""
    from starlette.background import BackgroundTask

    from src.backup.artifact import write_backup_v2
    from src.backup.sqlite_backup import BackupError, is_sqlite

    if not is_sqlite():
        raise HTTPException(status_code=400, detail="backup v2 supports the SQLite backend only")
    if not body.plaintext and not body.passphrase:
        raise HTTPException(
            status_code=400,
            detail="a passphrase is required (or set plaintext=true explicitly -- "
            "a plaintext backup excludes your signing keys and protects nothing at rest)",
        )
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = ".oobak" if body.plaintext else ".oobak.ooenc"
    fd, tmp = tempfile.mkstemp(prefix="oo-bak-", suffix=suffix)
    import os

    # Close the open descriptor BEFORE unlinking/reopening: Windows cannot
    # delete a file that still has an open handle (WinError 32).
    os.close(fd)
    Path(tmp).unlink(missing_ok=True)
    dest = Path(tmp)
    try:
        write_backup_v2(dest, passphrase=None if body.plaintext else body.passphrase)
    except (BackupError, ArtifactError) as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        dest,
        media_type="application/octet-stream",
        filename=f"open-omniscience-{ts}{suffix}",
        background=BackgroundTask(lambda: dest.unlink(missing_ok=True)),
    )


def _stage_upload(data: bytes, passphrase: str | None) -> StagedArtifact:
    from src.safety.crypto import EncryptionError

    if len(data) > _MAX_RESTORE_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds the 2 GiB restore cap")
    try:
        return read_artifact(data, passphrase=passphrase)
    except EncryptionError as exc:
        raise HTTPException(status_code=400, detail=f"decryption failed: {exc}") from exc
    except ArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v2/restore/preview")
async def restore_preview(
    file: UploadFile = File(...),
    passphrase: str = Form(""),
    allow_unverified: bool = Form(False),
) -> dict:
    """Stage an artifact and return the dry-run merge plan + verification verdicts.

    Nothing in the live corpus changes. The returned token authorises ONE commit
    of exactly this staged artifact."""
    staged = _stage_upload(await file.read(), passphrase or None)
    try:
        report = run_restore(staged, commit=False, allow_unverified=allow_unverified)
    except MergeError as exc:
        cleanup_staging(staged)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        cleanup_staging(staged)
        raise
    token = secrets.token_urlsafe(24)
    _PENDING[token] = staged
    report["commit_token"] = token
    return report


@router.post("/v2/restore/commit")
async def restore_commit(
    token: str = Form(""),
    file: UploadFile | None = File(None),
    passphrase: str = Form(""),
    allow_unverified: bool = Form(False),
) -> dict:
    """Merge a previously previewed artifact (token) -- or stage+merge directly
    when called with a file. The merge re-plans against the CURRENT corpus at
    commit time; the preview is advisory, the commit's own verification decides."""
    if token:
        staged = _PENDING.pop(token, None)
        if staged is None or not staged.staging_dir.exists():
            raise HTTPException(
                status_code=409,
                detail="unknown or expired preview token -- preview again",
            )
    elif file is not None:
        staged = _stage_upload(await file.read(), passphrase or None)
    else:
        raise HTTPException(status_code=400, detail="provide a preview token or a file")
    try:
        report = run_restore(staged, commit=True, allow_unverified=allow_unverified)
        return report
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        cleanup_staging(staged)


@router.delete("/v2/restore/preview/{token}")
def restore_discard(token: str) -> dict:
    """Discard a staged preview without merging."""
    staged = _PENDING.pop(token, None)
    if staged is not None:
        cleanup_staging(staged)
    return {"discarded": staged is not None}


@router.get("/v2/batches")
def merge_batches(limit: int = 20) -> dict:
    """Import history: every merge batch with its counts + verification report."""
    import json as _json

    from src.database.session import get_session

    s = get_session()
    try:
        from src.database.models import MergeBatch

        rows = (
            s.query(MergeBatch).order_by(MergeBatch.id.desc()).limit(max(1, min(limit, 100))).all()
        )
        return {
            "batches": [
                {
                    "id": b.id,
                    "imported_at": b.imported_at.isoformat() if b.imported_at else None,
                    "artifact_kind": b.artifact_kind,
                    "origin_fingerprint": b.origin_fingerprint,
                    "app_version": b.app_version,
                    "alembic_rev": b.alembic_rev,
                    "status": b.status,
                    "counts": _json.loads(b.counts_json) if b.counts_json else None,
                }
                for b in rows
            ]
        }
    finally:
        s.close()
