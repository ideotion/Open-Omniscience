"""
oo-backup-2 endpoints: merge-only restore (preview/commit). The size-capped
single-file CREATE was retired (2026-07-01) — backups are made by the unified
volume/folder export. Restore stays for legacy single-file backups (to be removed
in a future release once the single-file format is fully retired).

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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.backup.artifact import ArtifactError, StagedArtifact, cleanup_staging, read_artifact
from src.backup.merge import MergeError, run_restore

_LOG = logging.getLogger("api.backup_v2")


def _restore_error(action: str, exc: Exception) -> HTTPException:
    """Wrap ``classify_restore_error``'s honest detail (P0-2) in a 500.

    Always JSON {detail} (the SPA reads res.json(); never a plain-text 500)."""
    from src.backup.merge import classify_restore_error

    return HTTPException(status_code=500, detail=classify_restore_error(action, exc))


router = APIRouter(prefix="/api/backup", tags=["backup-v2"])

# The upload/RAM cap for the single-shot restore path. Aligned EXACTLY to the AES-GCM limit
# (2**31-1 = src.safety.crypto._GCM_MAX_BYTES, a fixed cryptographic constant) so an
# encrypted blob that passes this guard can't then overflow AES-GCM on decrypt — the old
# 2*1024**3 (=2**31) was one byte too generous. Above this, use the streaming volume restore.
_MAX_RESTORE_BYTES = 2**31 - 1


@router.get("/inventory")
def backup_inventory_endpoint() -> dict:
    """What is available to back up + sizes — drives the unified Export checklist.

    The Corpus is one atomic encrypted item (articles, sources, dates, agenda, law,
    markets, annotations, settings…) with a breakdown; models/maps/wiki dumps are the
    separately-selectable file blobs. Read-only; the actual backup reuses the
    always-works streaming engines (volumes+parity for the corpus, folder stream for
    the blobs)."""
    from src.backup.inventory import backup_inventory
    from src.database.session import session_scope

    with session_scope() as session:
        return backup_inventory(session)


@router.get("/import-scan")
def import_scan_endpoint(path: str) -> dict:
    """Classify a folder's importable contents — drives the unified Import checklist.

    Read-only discovery: reports the kinds present (our encrypted corpus volume set,
    large-data blobs, loose .eml newsletters, a source CSV, a legacy single-file
    backup). 400 if the path is not a folder."""
    from src.backup.import_scan import scan_import_folder

    try:
        return scan_import_folder(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# Staged previews awaiting a commit decision: token -> StagedArtifact. Process-
# local by design (preview + commit happen within one operator session); orphans
# on disk are reclaimed by cleanup_stale_staging at boot.
_PENDING: dict[str, StagedArtifact] = {}


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


def _apply_restore_selection(staged: StagedArtifact, *, include_newsletters: bool) -> None:
    """Selective restore (maintainer 2026-06-21): drop a category from the STAGED
    plaintext corpus copy BEFORE the merge reads it, so the preview reflects exactly
    what the commit will do (they share the filtered staged copy). Reuses the
    backup-side, stdlib-tested filter. Only newsletters are filterable in the main
    artifact today (maps/wiki/models are separate/excluded)."""
    if include_newsletters:
        return
    from src.backup.artifact import _drop_newsletter_articles

    try:
        _drop_newsletter_articles(staged.corpus_path)
    except Exception:  # noqa: BLE001 - never block a restore on the optional filter
        _LOG.warning("restore: newsletter filter on the staged corpus failed", exc_info=True)


def _preview_sync(
    data: bytes, passphrase: str | None, *, allow_unverified: bool, include_newsletters: bool
) -> dict:
    """The blocking body of restore_preview (decrypt + stage + dry-run merge).

    Runs OFF the event loop (run_in_threadpool). Preview copies the live corpus to
    a disposable working DB and runs the FULL merge against it so the plan can never
    lie — on a large corpus that is nearly as costly as a commit, so it MUST NOT run
    on the single async worker's event loop (it would freeze every other request —
    the task manager, polls, the UI — for the whole restore; field report 2026-07-02
    'stuck on Previewing… for an hour')."""
    staged = _stage_upload(data, passphrase)
    _apply_restore_selection(staged, include_newsletters=include_newsletters)
    try:
        report = run_restore(staged, commit=False, allow_unverified=allow_unverified)
    except MergeError as exc:
        cleanup_staging(staged)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        cleanup_staging(staged)
        raise
    except Exception as exc:
        # Any other failure (e.g. an OLD backup whose corpus carries a schema this
        # build cannot stage-migrate) must STILL return a JSON {detail}, never a bare
        # plain-text 500 — the SPA reads res.json() and would otherwise show only
        # "JSON.parse: unexpected character" (field test 2026-06-19 P0-3).
        cleanup_staging(staged)
        _LOG.exception("restore preview failed")
        raise _restore_error("read", exc) from exc
    token = secrets.token_urlsafe(24)
    _PENDING[token] = staged
    report["commit_token"] = token
    return report


@router.post("/v2/restore/preview")
async def restore_preview(
    file: UploadFile = File(...),
    passphrase: str = Form(""),
    allow_unverified: bool = Form(False),
    include_newsletters: bool = Form(True),
) -> dict:
    """Stage an artifact and return the dry-run merge plan + verification verdicts.

    Nothing in the live corpus changes. The returned token authorises ONE commit
    of exactly this staged artifact. ``include_newsletters=false`` drops imported
    newsletters from the staged corpus so the preview AND the eventual commit
    (which reuses this filtered staged copy) restore everything else.

    The heavy stage+merge runs in the threadpool so a long preview never freezes the
    single-worker server (see _preview_sync)."""
    data = await file.read()
    return await run_in_threadpool(
        _preview_sync,
        data,
        passphrase or None,
        allow_unverified=allow_unverified,
        include_newsletters=include_newsletters,
    )


def _commit_sync(staged: StagedArtifact, *, allow_unverified: bool) -> dict:
    """The blocking body of restore_commit (full merge + atomic swap). Runs OFF the
    event loop for the same reason preview does (see _preview_sync)."""
    try:
        return run_restore(staged, commit=True, allow_unverified=allow_unverified)
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # JSON, never a plain-text 500 (P0-3) — see preview above.
        _LOG.exception("restore commit failed")
        raise _restore_error("restore", exc) from exc
    finally:
        cleanup_staging(staged)


@router.post("/v2/restore/commit")
async def restore_commit(
    token: str = Form(""),
    file: UploadFile | None = File(None),
    passphrase: str = Form(""),
    allow_unverified: bool = Form(False),
    include_newsletters: bool = Form(True),
) -> dict:
    """Merge a previously previewed artifact (token) -- or stage+merge directly
    when called with a file. The merge re-plans against the CURRENT corpus at
    commit time; the preview is advisory, the commit's own verification decides.
    A token's staged copy already reflects the preview's selection; a direct-file
    commit applies ``include_newsletters`` here.

    The heavy stage+merge runs in the threadpool so the swap never freezes the
    single-worker server."""
    if token:
        staged = _PENDING.pop(token, None)
        if staged is None or not staged.staging_dir.exists():
            raise HTTPException(
                status_code=409,
                detail="unknown or expired preview token -- preview again",
            )
        # token path: the staged corpus was already filtered at preview time.
    elif file is not None:
        data = await file.read()
        staged = await run_in_threadpool(_stage_upload, data, passphrase or None)
        await run_in_threadpool(
            _apply_restore_selection, staged, include_newsletters=include_newsletters
        )
    else:
        raise HTTPException(status_code=400, detail="provide a preview token or a file")
    return await run_in_threadpool(_commit_sync, staged, allow_unverified=allow_unverified)


class LegacyRestoreBody(BaseModel):
    path: str  # server-side path to a legacy single-file backup (oo-backup-2 / .db)
    passphrase: str = ""
    allow_unverified: bool = False
    include_newsletters: bool = True


@router.post("/legacy/restore")
def legacy_restore(body: LegacyRestoreBody) -> dict:
    """Restore ONE legacy single-file backup found on disk (a SERVER-SIDE path),
    additively — the unified Import dialog's path for legacy archives it discovered in
    a scanned folder (a folder may hold several; the caller merges each in turn). Reuses
    the exact staging + additive merge as the upload path (``restore_commit``), so a
    legacy archive nested in a subfolder is now a first-class importable item, not just a
    note pointing at the old panel. The 2 GiB legacy-format cap still applies (these
    single files were always ≤2 GiB — the volume set is the large path)."""
    from pathlib import Path

    p = Path(body.path)
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"{p} is not a file to restore.")
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"could not read {p}: {exc}") from exc
    staged = _stage_upload(data, body.passphrase or None)
    _apply_restore_selection(staged, include_newsletters=body.include_newsletters)
    try:
        report = run_restore(staged, commit=True, allow_unverified=body.allow_unverified)
        return report
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # JSON, never a plain-text 500 (P0-3).
        _LOG.exception("legacy restore failed")
        raise _restore_error("restore", exc) from exc
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


# --------------------------------------------------------------------------- #
# Large-data "copy to a folder/drive" backup (brief §2.A) — wiki dumps + OSM
# maps + Ollama models streamed SERVER-SIDE into a user-chosen directory. These
# public, re-downloadable blobs are copied as-is (the encrypted corpus stays in
# oo-backup-2); the copy is a pausable, task-manager-visible job.
# --------------------------------------------------------------------------- #
_FOLDER_CATEGORIES = ("wiki_dumps", "osm_regions", "models")


class FolderBackupBody(BaseModel):
    dest: str
    categories: list[str] | None = None  # None = all three


class FolderRestoreBody(BaseModel):
    src: str
    categories: list[str] | None = None


def _folder_categories(cats: list[str] | None) -> list[str]:
    return [c for c in (cats or _FOLDER_CATEGORIES) if c in _FOLDER_CATEGORIES]


@router.get("/folder/status")
def folder_backup_status() -> dict:
    """Live state of the (single) folder backup/restore job — for the UI + /api/jobs."""
    from src.backup.folder_backup import get_folder_manager

    return get_folder_manager().status()


@router.post("/folder/plan")
def folder_backup_plan(body: FolderBackupBody) -> dict:
    """Preflight WITHOUT starting: validate the destination, enumerate the completed
    dumps/maps/models, and report the size to copy vs free space at the destination —
    so the UI shows an honest 'needs X, Y free' before the user commits."""
    from src.backup.folder_backup import (
        collect_items,
        free_bytes,
        human_bytes,
        needed_bytes,
        validate_dest,
    )

    cats = _folder_categories(body.categories)
    try:
        destp = validate_dest(body.dest)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = collect_items(
        include_wiki="wiki_dumps" in cats,
        include_osm="osm_regions" in cats,
        include_models="models" in cats,
    )
    per_cat: dict[str, dict] = {}
    for c in cats:
        ci = [it for it in items if it.category == c]
        per_cat[c] = {"files": len(ci), "bytes": sum(it.size for it in ci)}
    need = needed_bytes(destp, items)
    free = free_bytes(destp)
    return {
        "dest": str(destp),
        "categories": cats,
        "files": len(items),
        "total_bytes": sum(it.size for it in items),
        "needed_bytes": need,
        "needed_human": human_bytes(need),
        "free_bytes": free,
        "free_human": human_bytes(free),
        "enough_space": need <= free,
        "by_category": per_cat,
    }


@router.post("/folder/start")
def folder_backup_start(body: FolderBackupBody) -> dict:
    """Start (or restart/resume) the folder backup. 400 on a bad destination or
    insufficient free space; 409 if one is already running."""
    from src.backup.folder_backup import get_folder_manager

    try:
        return get_folder_manager().start(body.dest, _folder_categories(body.categories))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/folder/restore")
def folder_backup_restore(body: FolderRestoreBody) -> dict:
    """Restore a folder backup ADDITIVELY back into the live locations (skip-if-present,
    never overwriting a differing local dump/blob)."""
    from src.backup.folder_backup import get_folder_manager

    try:
        return get_folder_manager().start(
            body.src, _folder_categories(body.categories), mode="restore"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/folder/verify")
def folder_backup_verify(body: FolderRestoreBody) -> dict:
    """Verify a folder backup at ``src`` against its manifest — the standalone integrity check
    the volumes backup already has (``/v2/volumes/verify``) but the folder backup lacked.

    Read-only. Every manifest-listed file must be present with the exact recorded size; the
    content-addressed Ollama model blobs (``blobs/sha256-<hex>``) are additionally content-
    hashed. Wiki dumps + OSM extracts carry NO stored checksum (immutable public downloads) so
    they are size-verified only — stated per file. Runs as the (single) folder job, so it
    surfaces in /api/jobs + /folder/status and is cancellable; the verdict rides
    ``status()['verify']`` (schema ``oo-folder-verify-1``: ok, files_checked, files_checksummed,
    summary{ok,size_only,missing,size_mismatch,checksum_mismatch,traversal_refused}, problems).
    400 on a bad path; 409 if a folder job is already running."""
    from src.backup.folder_backup import get_folder_manager

    try:
        return get_folder_manager().start(
            body.src, _folder_categories(body.categories), mode="verify"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/folder/{action}")
def folder_backup_action(action: str) -> dict:
    """Pause / resume / cancel the running folder job (routed to the owner)."""
    from src.backup.folder_backup import get_folder_manager

    mgr = get_folder_manager()
    if action == "pause":
        mgr.pause()
    elif action == "resume":
        try:
            return mgr.resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif action == "cancel":
        mgr.cancel()
    else:
        raise HTTPException(status_code=404, detail=f"unknown action {action}")
    return mgr.status()


# --------------------------------------------------------------------------- #
#  Large ENCRYPTED backup as a volume set + parity (field test 2026-06-24).
#  No 2 GiB cap, never the whole archive in RAM; a corrupt/lost volume is rebuilt
#  from Reed-Solomon parity. Written to a server-side directory, run as a job.
# --------------------------------------------------------------------------- #
class VolumeBackupBody(BaseModel):
    dest: str
    passphrase: str
    include_newsletters: bool = True
    parity_fraction: float = 0.1


class VolumeRestoreBody(BaseModel):
    src: str
    passphrase: str
    allow_unverified: bool = False
    # An oo-volumes-2 backup carries the corpus as its at-rest SQLCipher bytes
    # (never decrypted at backup time); restoring it needs the corpus's OWN
    # passphrase. Empty = try the live unlocked key, then the backup passphrase
    # (they are usually the same operator secret) — a wrong key fails loudly.
    corpus_passphrase: str = ""


class VolumeVerifyBody(BaseModel):
    src: str
    passphrase: str = ""  # empty = checksums/signature only (nothing decrypted)


@router.get("/v2/volumes/status")
def volume_backup_status() -> dict:
    """Live state of the (single) volume backup/restore job — for the UI + /api/jobs."""
    from src.backup.volume_job import get_volume_manager

    return get_volume_manager().status()


@router.post("/v2/volumes/start")
def volume_backup_start(body: VolumeBackupBody) -> dict:
    """Start the LARGE encrypted backup (volumes + parity) into a server-side directory,
    as a cancellable background job. 400 on a bad destination / missing passphrase;
    409 if a volume backup/restore is already running."""
    from src.backup.volume_job import get_volume_manager

    try:
        return get_volume_manager().start_backup(
            body.dest,
            body.passphrase,
            include_newsletters=body.include_newsletters,
            parity_fraction=body.parity_fraction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v2/volumes/restore")
def volume_backup_restore(body: VolumeRestoreBody) -> dict:
    """Restore a volume-set backup from a server-side directory: verify + parity-recover
    + reassemble, then merge ADDITIVELY into the live corpus (the standard merge)."""
    from src.backup.volume_job import get_volume_manager

    try:
        return get_volume_manager().start_restore(
            body.src,
            body.passphrase,
            allow_unverified=body.allow_unverified,
            corpus_passphrase=body.corpus_passphrase or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v2/volumes/verify")
def volume_backup_verify(body: VolumeVerifyBody) -> dict:
    """VERIFY a volume-set backup end to end as a background job (P0.1): manifest
    signature + every data/parity volume checksum + structure; with the passphrase
    every volume is additionally stream-decrypted into a hash sink (nothing
    written, the live corpus untouched). The report (naming exactly which volumes
    are bad and whether parity can recover them) lands in the job summary."""
    from src.backup.volume_job import get_volume_manager

    try:
        return get_volume_manager().start_verify(body.src, body.passphrase or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v2/volumes/cancel")
def volume_backup_cancel() -> dict:
    """Cancel a running volume BUILD — stops between volumes; a cancelled FIRST
    build's partial set is removed (never mistakable for a good backup) while a
    cancelled incremental REFRESH keeps the previous complete set restorable.
    A restore mid-merge is atomic and not interruptible."""
    from src.backup.volume_job import get_volume_manager

    mgr = get_volume_manager()
    mgr.cancel()
    return mgr.status()


@router.post("/v2/volumes/pause")
def volume_backup_pause() -> dict:
    """PAUSE a running volume BUILD keeping the finished volumes + the resume
    log — starting the same backup again continues where it left off (P0.1
    resumable). No effect on a restore/verify."""
    from src.backup.volume_job import get_volume_manager

    mgr = get_volume_manager()
    mgr.pause()
    return mgr.status()
