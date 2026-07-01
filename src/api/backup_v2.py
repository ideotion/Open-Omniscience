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
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.backup.artifact import ArtifactError, StagedArtifact, cleanup_staging, read_artifact
from src.backup.merge import MergeError, run_restore
from src.paths import data_dir

_LOG = logging.getLogger("api.backup_v2")


def _restore_error(action: str, exc: Exception) -> HTTPException:
    """Classify an unexpected restore failure into an HONEST 500 detail (P0-2).

    The old wording blamed an "incompatible version" for EVERY non-MergeError, so a
    plain database constraint clash (the merge UNIQUE collision the maintainer hit on
    their own backup) read as a version mismatch. Distinguish the real causes:
      * a constraint/integrity clash = a MERGE data conflict (a duplicate row), not a
        version problem;
      * a missing table/column = an actual schema/version gap (keep that wording);
      * anything else = an honest, non-speculative "could not <action>".
    Always JSON {detail} (the SPA reads res.json(); never a plain-text 500)."""
    msg = str(exc)
    low = msg.lower()
    # A real version/schema gap: a staged migration failed, or the corpus uses a
    # table/column this build doesn't know. "incompatible version" is accurate here.
    is_version = (
        "migration" in low
        or "incompatible" in low
        or "no such table" in low
        or "no such column" in low
        or "schema" in low
    )
    if isinstance(exc, sqlite3.IntegrityError):
        detail = (
            f"the backup's data conflicts with your corpus on a database constraint "
            f"(e.g. a duplicate row) while merging — this is a data-merge issue, not a "
            f"version mismatch: {msg}"
        )
    elif is_version:
        detail = f"could not {action} this backup (it may be from an incompatible version): {msg}"
    else:
        detail = f"could not {action} this backup: {msg}"
    return HTTPException(status_code=500, detail=detail)


def _staging_dir() -> str:
    """Where to stage a backup/export build + its temp file.

    NEVER the system temp dir: on Linux (notably Fedora/Qubes) ``/tmp`` is tmpfs
    (RAM-backed), so building a DB-sized snapshot + zip there exhausts RAM and fails
    with ``[Errno 28] No space left on device`` even when the real disk has dozens
    of GB free (field report 2026-06-18). The data dir lives on real disk beside the
    corpus, with the room a backup needs; ``write_backup_v2`` builds in ``dest.parent``,
    so pointing the temp file here puts the WHOLE build on disk."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


router = APIRouter(prefix="/api/backup", tags=["backup-v2"])

_MAX_RESTORE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB, same honest cap as legacy restore


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

# Staged previews awaiting a commit decision: token -> StagedArtifact. Process-
# local by design (preview + commit happen within one operator session); orphans
# on disk are reclaimed by cleanup_stale_staging at boot.
_PENDING: dict[str, StagedArtifact] = {}


class BackupBody(BaseModel):
    passphrase: str | None = None
    plaintext: bool = False
    # What to back up (maintainer 2026-06-21). The corpus is always included; this
    # toggles whether imported-newsletter (.eml/mailbox) articles ride along — so a
    # user fixing faulty imports can back up WITHOUT them, then re-import clean ones.
    include_newsletters: bool = True


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
    fd, tmp = tempfile.mkstemp(prefix="oo-bak-", suffix=suffix, dir=_staging_dir())
    import os

    # Close the open descriptor BEFORE unlinking/reopening: Windows cannot
    # delete a file that still has an open handle (WinError 32).
    os.close(fd)
    Path(tmp).unlink(missing_ok=True)
    dest = Path(tmp)
    try:
        write_backup_v2(
            dest,
            passphrase=None if body.plaintext else body.passphrase,
            include_newsletters=body.include_newsletters,
        )
    except (BackupError, ArtifactError) as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        # Any OTHER failure (e.g. a full temp volume raising sqlite3.OperationalError
        # while the ~DB-sized snapshot is written) must STILL return a JSON {detail},
        # never a bare plain-text 500: the browser calls res.json() on the error body
        # and would otherwise report only "JSON.parse: unexpected character", masking
        # the real cause. Log the traceback so it is recoverable from the server log.
        dest.unlink(missing_ok=True)
        _LOG.exception("backup v2 build failed")
        raise HTTPException(status_code=500, detail=f"backup failed: {exc}") from exc
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
    (which reuses this filtered staged copy) restore everything else."""
    staged = _stage_upload(await file.read(), passphrase or None)
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
    commit applies ``include_newsletters`` here."""
    if token:
        staged = _PENDING.pop(token, None)
        if staged is None or not staged.staging_dir.exists():
            raise HTTPException(
                status_code=409,
                detail="unknown or expired preview token -- preview again",
            )
        # token path: the staged corpus was already filtered at preview time.
    elif file is not None:
        staged = _stage_upload(await file.read(), passphrase or None)
        _apply_restore_selection(staged, include_newsletters=include_newsletters)
    else:
        raise HTTPException(status_code=400, detail="provide a preview token or a file")
    try:
        report = run_restore(staged, commit=True, allow_unverified=allow_unverified)
        return report
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # JSON, never a plain-text 500 (P0-3) — see preview above.
        _LOG.exception("restore commit failed")
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
#  LLM models companion backup (maintainer-asked 2026-06-17): models live in
#  Ollama's OWN store, OUTSIDE the corpus — so they are an OPT-IN, SEPARATE
#  companion artifact, never in oo-backup-2. Lets a restoring user avoid
#  re-downloading multi-GB models; restore is additive + bit-identical
#  (content-addressed blobs, deduped). See src/backup/ollama_models.py.
# --------------------------------------------------------------------------- #
@router.get("/models")
def models_status() -> dict:
    """Is the local Ollama model store present, and what's in it (sizes)?

    Detects the real store across locations (incl. the protected Linux systemd
    service dir) and, when models can't be reached, returns an actionable ``hint``
    so the backup degrades LOUDLY instead of silently reporting nothing."""
    from src.backup.ollama_models import store_status

    return store_status()


class ModelsExportBody(BaseModel):
    refs: list[str] | None = None   # specific model refs, or None = all


@router.post("/models/export")
def models_export(body: ModelsExportBody) -> FileResponse:
    """Build + download an OPT-IN companion archive of the local Ollama models."""
    import os

    from starlette.background import BackgroundTask

    from src.backup.ollama_models import (
        build_models_archive,
        default_store,
        list_models,
        store_status,
    )

    store = default_store()
    # Refuse HONESTLY with an actionable reason when there is nothing to export, instead
    # of a misleading 404 or a near-empty archive (maintainer 2026-06-21: the button
    # "doesn't work"). The commonest case is a systemd-service Ollama whose models live
    # in a protected dir the app can't read — store_status() carries the exact hint
    # (set OLLAMA_MODELS to a path you own); an empty store says "pull a model first".
    models = list_models(store) if store.exists() else []
    if not models:
        status = store_status()
        detail = status.get("hint") or (
            "No Ollama models found to back up — pull a model first, or set OLLAMA_MODELS "
            "if your models live elsewhere."
        )
        raise HTTPException(status_code=409, detail=detail)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    fd, tmp = tempfile.mkstemp(prefix="oo-models-", suffix=".oomodels", dir=_staging_dir())
    os.close(fd)
    Path(tmp).unlink(missing_ok=True)
    dest = Path(tmp)
    try:
        build_models_archive(dest, store, refs=body.refs)
    except FileNotFoundError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        dest.unlink(missing_ok=True)
        _LOG.exception("models export failed")
        raise HTTPException(status_code=500, detail=f"models export failed: {exc}") from exc
    return FileResponse(
        dest, media_type="application/octet-stream",
        filename=f"open-omniscience-models-{ts}.oomodels",
        background=BackgroundTask(lambda: dest.unlink(missing_ok=True)),
    )


@router.post("/models/import")
async def models_import(file: UploadFile = File(...)) -> dict:
    """Restore a models companion archive into the local Ollama store (additive,
    bit-identical — existing blobs are skipped, never overwritten)."""
    import os

    from src.backup.ollama_models import default_store, restore_models_archive

    data = await file.read()
    if len(data) > _MAX_RESTORE_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds the 2 GiB cap")
    fd, tmp = tempfile.mkstemp(prefix="oo-models-imp-", suffix=".oomodels", dir=_staging_dir())
    os.close(fd)
    dest = Path(tmp)
    try:
        dest.write_bytes(data)
        store = default_store()
        store.mkdir(parents=True, exist_ok=True)
        return restore_models_archive(dest, store)
    except Exception as exc:
        _LOG.exception("models import failed")
        raise HTTPException(status_code=400, detail=f"models import failed: {exc}") from exc
    finally:
        dest.unlink(missing_ok=True)


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
            body.src, body.passphrase, allow_unverified=body.allow_unverified
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/v2/volumes/cancel")
def volume_backup_cancel() -> dict:
    """Cancel a running volume BUILD — stops between volumes + removes the partial set.
    A restore mid-merge is atomic and not interruptible."""
    from src.backup.volume_job import get_volume_manager

    mgr = get_volume_manager()
    mgr.cancel()
    return mgr.status()
