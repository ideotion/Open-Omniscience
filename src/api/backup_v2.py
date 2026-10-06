"""
oo-backup-2 endpoints: the import QUEUE, the persisted import reports, and the
legacy single-file restore. The size-capped single-file CREATE was retired
(2026-07-01) — backups are made by the unified volume/folder export.

ONE IMPORT PATH (Q214 = a, 2026-09-16). ``/v2/restore/preview``,
``/v2/restore/commit`` and ``DELETE /v2/restore/preview/{token}`` are GONE. They
were an upload-based preview→commit two-step for a single artifact, with no caller
anywhere in ``src/static/`` or ``src/``; ``import-queue/*`` is the path the app
takes, and on a loopback-only, local-first app any file a browser could have
uploaded is already a server-side path the queue accepts. The two options only
those routes could express -- ``allow_unverified`` and ``include_newsletters`` --
moved onto ``ImportQueueItem`` rather than being dropped. The dry-run plan they
also offered stays available in the library (``run_restore(commit=False)``), which
is what the queue's own preflight and the merge tests use.

The legacy single-file RESTORE stays forever, as ``read_artifact``'s docstring
commits and Q215 ⛔ = a re-affirms.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design: docs/design/DB_RELIABILITY_02_DESIGN.md §2-3. The legacy endpoints
(/api/database/backup|restore, /api/safety/*) stay for compatibility; these are
the mandate's surface: one artifact carrying EVERYTHING, restore that merges
and can refuse, never replaces.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from src.backup.artifact import ArtifactError, StagedArtifact, cleanup_staging, read_artifact
from src.backup.merge import MergeError, RestoreRefused, check_memory_before_staging, run_restore
from src.jobs.background import BackgroundJob, Framed, register_job
from src.scheduler.runner import exclusive_window_open

_LOG = logging.getLogger("api.backup_v2")


def _restore_error(action: str, exc: Exception, *secrets: str | None) -> HTTPException:
    """Wrap ``classify_restore_error``'s honest detail (P0-2) in a 500.

    Always JSON {detail} (the SPA reads res.json(); never a plain-text 500)."""
    from src.backup import runlog
    from src.backup.merge import classify_restore_error

    detail = str(runlog.scrub_secrets(classify_restore_error(action, exc), *secrets))
    return HTTPException(status_code=500, detail=detail[: runlog.FAILURE_MSG_KEEP])


router = APIRouter(prefix="/api/backup", tags=["backup-v2"])

# The read/RAM cap for the legacy single-file restore path (``_stage_upload`` reads
# the whole archive into memory before decrypting it). Aligned EXACTLY to the AES-GCM limit
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


@router.get("/import-reports")
def import_reports_list() -> dict:
    """List the persisted, downloadable import/restore reports (S3.5, field-feedback
    A1) -- read-only, newest first. An empty/missing directory is honestly an empty
    list (never an error)."""
    from src.backup.import_reports import list_import_reports

    return {"reports": list_import_reports()}


@router.get("/import-reports/{filename}")
def import_reports_download(filename: str, format: str = Query("json")) -> Response:
    """Download one persisted import/restore report by its exact filename.

    ``format=json`` (default) returns the raw stored JSON; ``format=md`` renders the
    same report through the pure Markdown formatter. 404 on an unknown or
    traversal-attempting filename (never a 500, never another file's contents)."""
    from src.backup.import_reports import read_import_report, render_import_report_markdown

    try:
        report = read_import_report(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    if format == "md":
        return Response(
            render_import_report_markdown(report),
            media_type="text/markdown; charset=utf-8",
        )
    if format != "json":
        raise HTTPException(status_code=400, detail="format must be 'json' or 'md'")
    import json as _json

    return Response(_json.dumps(report, indent=2, default=str), media_type="application/json")


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
    plaintext corpus copy BEFORE the merge reads it. Reuses the backup-side,
    stdlib-tested filter. Only newsletters are filterable in the main artifact today
    (maps/wiki/models are separate/excluded).

    Reachable ONLY on the legacy single-file path, which is the only one that stages
    a single artifact this filter can edit. The import queue therefore REFUSES
    ``include_newsletters=false`` for a volume corpus backup by name rather than
    accepting it and doing nothing (:meth:`ImportQueueManager._run_corpus`)."""
    if include_newsletters:
        return
    from src.backup.artifact import _drop_newsletter_articles

    try:
        _drop_newsletter_articles(staged.corpus_path)
    except Exception:  # noqa: BLE001 - never block a restore on the optional filter
        _LOG.warning("restore: newsletter filter on the staged corpus failed", exc_info=True)


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
    same staging + additive merge helpers the import queue's own legacy items take
    (``restore_legacy_path`` below is the one implementation; this is its thin
    wrapper), so a legacy archive nested in a subfolder is a first-class importable
    item. The 2 GiB legacy-format cap still applies (these single files were always
    ≤2 GiB — the volume set is the large path)."""
    return restore_legacy_path(
        body.path,
        body.passphrase or None,
        include_newsletters=body.include_newsletters,
        allow_unverified=body.allow_unverified,
    )


def restore_legacy_path(
    path: str,
    passphrase: str | None,
    *,
    include_newsletters: bool = True,
    allow_unverified: bool = False,
    trust_fetch_history: bool | None = None,
    should_stop=None,
) -> dict:
    """The legacy single-file restore, callable WITHOUT a request.

    Extracted from the endpoint above (2026-07-29) so the server-side import queue
    runs the IDENTICAL path -- staging, selection filter, additive merge, staging
    cleanup and the same honest error classification -- rather than a second
    implementation that could drift from it. The endpoint is now a thin wrapper, so
    there is exactly one legacy-restore code path in the app."""
    from pathlib import Path as _Path

    p = _Path(path)
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"{p} is not a file to restore.")
    # Before a byte is read or staged: an encrypted corpus that this machine cannot hold a merge
    # for is told so now, not after the staging (see check_memory_before_staging).
    try:
        check_memory_before_staging()
    except MergeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"could not read {p}: {exc}") from exc
    staged = _stage_upload(data, passphrase or None)
    _apply_restore_selection(staged, include_newsletters=include_newsletters)
    from src.backup import runlog
    from src.backup.volume_job import defer_reindex, hand_off_reindex

    try:
        with runlog.run(
            "import", label=p.name, dest=str(p), secrets=(passphrase,), legacy_single_file=True
        ):
            report = run_restore(
                staged,
                commit=True,
                allow_unverified=allow_unverified,
                # The Q701-note answer for THIS import; None falls back to the stored
                # first-launch choice inside run_restore, so the endpoint wrapper that
                # sends nothing is byte-identical to today.
                trust_fetch_history=trust_fetch_history,
                should_stop=should_stop,
                # The import queue holds ONE exclusive window across the whole run, so
                # a restore driven from it owns the machine: the whole-corpus snapshots
                # may take the byte-copy fast path instead of re-encrypting the corpus
                # row by row. Read live rather than passed in, so the plain endpoint
                # wrapper (a user-facing request that must NOT stall the app) keeps the
                # default.
                exclusive=exclusive_window_open(),
                # Deferred from the same switch as every other committing path -- this
                # one is queue-driven, so a folder of mixed volume and legacy backups
                # would otherwise defer for some items and block for hours on others
                # inside a single run.
                reindex_imported=not defer_reindex(),
            )
            if defer_reindex():
                hand_off_reindex(report)
            return report
    except (MergeError, RestoreRefused) as exc:
        # See restore_commit above: a refusal keeps its own message.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # JSON, never a plain-text 500 (P0-3).
        # Written from the scrubbed fields, never with exc_info: the engine's text can quote the
        # passphrase in scope here, and the log rides the debug bundle.
        fields = runlog.failure_fields(exc, passphrase)
        _LOG.warning("legacy restore failed (%s); the run journal carries the scrubbed text", fields["cls"])
        raise _restore_error("restore", exc, passphrase) from exc
    finally:
        cleanup_staging(staged)


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
# Differences from restores (R61, item 12): the other value a restore brought for a deduced
# item this corpus already had. Local values are never touched by a restore; these routes are
# the operator's explicit choices about them. See src/backup/alternates.py.
# --------------------------------------------------------------------------- #
def _alt_call(fn, *args, **kwargs) -> dict:
    from src.backup.alternates import AlternateError
    from src.database.session import get_session

    s = get_session()
    try:
        return fn(s, *args, **kwargs)
    except AlternateError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    finally:
        s.close()


@router.get("/alternates")
def alternates_list(
    status: str = Query("pending", pattern="^(pending|kept|all)$"),
    limit: int = 50,
    offset: int = 0,
) -> dict:
    from src.backup.alternates import list_alternates

    return _alt_call(list_alternates, status=status, limit=limit, offset=offset)


@router.post("/alternates/batch/{batch_id}/discard")
def alternates_discard_batch(batch_id: int) -> dict:
    from src.backup.alternates import discard_batch

    return _alt_call(discard_batch, batch_id)


@router.post("/alternates/{alt_id}/keep")
def alternates_keep(alt_id: int) -> dict:
    from src.backup.alternates import keep

    return _alt_call(keep, alt_id)


@router.post("/alternates/{alt_id}/discard")
def alternates_discard(alt_id: int, confirm: bool = False) -> dict:
    from src.backup.alternates import discard

    return _alt_call(discard, alt_id, confirm=confirm)


@router.post("/alternates/{alt_id}/swap")
def alternates_swap(alt_id: int) -> dict:
    from src.backup.alternates import swap

    return _alt_call(swap, alt_id)


# --------------------------------------------------------------------------- #
# Large-data "copy to a folder/drive" backup (brief §2.A) — wiki dumps + OSM
# maps + Ollama models streamed SERVER-SIDE into a user-chosen directory. These
# public, re-downloadable blobs are copied as-is (the encrypted corpus stays in
# oo-backup-2); the copy is a pausable, task-manager-visible job.
# --------------------------------------------------------------------------- #
_FOLDER_CATEGORIES = ("wiki_dumps", "osm_regions", "models", "hf_models")


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
        include_hf="hf_models" in cats,
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
    never overwriting a differing local dump/blob).

    CONTENT-VERIFIED WHILE COPYING: each file is hashed as it streams and checked against
    the sha256 the backup recorded when it wrote those bytes; a mismatch is discarded with
    its temp file, so a member that rotted on the drive never reaches the live data
    directory. The result carries ``corrupt_refused`` (with the named ``corrupt`` members)
    and ``restored_unverified`` -- the latter counting files a backup written before the
    checksums existed could not be checked against. Both ride ``/folder/status``."""
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

    Read-only. Every manifest-listed file must be present with the exact recorded size and,
    where the backup recorded one, matching the sha256 it wrote (2026-09-07 — before that
    wiki dumps and OSM extracts were size-verified only, and an older backup still is: those
    files are counted in ``size_only`` rather than silently called sound). The
    content-addressed Ollama model blobs (``blobs/sha256-<hex>``) are checked against the
    hash in their own filename as well. The manifest itself is signed, and its state
    (``signed`` / ``unsigned`` / ``bad-signature``) rides the verdict. Runs as the (single) folder job, so it
    surfaces in /api/jobs + /folder/status and is cancellable; the verdict rides
    ``status()['verify']`` (schema ``oo-folder-verify-1``: ok, files_checked, files_checksummed,
    summary{ok,size_only,missing,size_mismatch,checksum_mismatch,traversal_refused},
    signature_state, problems).
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
    # S6.2: large public categories to carry INSIDE the artifact rather than copied
    # alongside it. Empty = the behaviour that shipped, byte for byte.
    include_blobs: list[str] = []
    # Q218 = a: re-read every volume after writing and check its checksum. Default ON,
    # here as well as in the manager, so a caller that never went through the dialog
    # gets the ruled behaviour rather than the cheaper one.
    verify_after_write: bool = True


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
            include_blobs=body.include_blobs,
            verify_after_write=body.verify_after_write,
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


# --------------------------------------------------------------------------- #
#  Server-side IMPORT QUEUE (field remarks 2026-07-29 remark 2, rulings 10/13/15/16).
#  A multi-backup folder is ONE import: the sequencing, the identity of each item,
#  the single exclusive collection window and the Stop all live here rather than in
#  the browser, so a page reload no longer decapitates a running import.
# --------------------------------------------------------------------------- #
class ExportFolderBody(BaseModel):
    """The PARENT the operator chose; the dated folder is allocated under it.

    The other three fields are what the export was ASKED to hold (J-1), recorded in
    the folder so a reopened dialog can tell a finished export from one whose
    large-data copy never ran. Optional: a caller that sends none of them gets the
    folder and no record, exactly as before -- and an unknown request, never an
    empty one.
    """

    parent: str
    corpus: bool | None = None
    categories: list[str] | None = None
    inside: bool = False


class ExportSummaryBody(BaseModel):
    dir: str


@router.post("/export-folder")
def export_folder_allocate(body: ExportFolderBody) -> dict:
    """Create the dated export folder for ONE export and return its path (R5; Q210–Q213).

    Called once per export, BEFORE either phase starts, so the encrypted volumes and
    the copied large-data files land in the same folder. Computing the name in each
    phase instead would give two folders whenever an export crosses a minute boundary,
    and neither of them would be the one the panel names.

    The allocation is an exclusive ``mkdir``: this can only ever return a directory
    that did not exist a moment ago, so it can never adopt a folder that already holds
    somebody's backup (Q213 = c, no reuse of a previous export, is a property of the
    folder rather than a flag anyone has to remember to pass).
    """
    from src.backup.export_folder import (
        ExportFolderError,
        allocate_export_folder,
        write_export_request,
    )

    try:
        d = allocate_export_folder(body.parent)
    except ExportFolderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    recorded = None
    if body.corpus is not None or body.categories is not None:
        recorded = write_export_request(
            d,
            corpus=bool(body.corpus),
            categories=list(body.categories or []),
            inside=body.inside,
        )
    return {
        "dir": str(d),
        "name": d.name,
        "parent": str(d.parent),
        "request_recorded": recorded is not None,
    }


def _export_summary_facts(dirname: str) -> dict:
    from src.backup.export_summary import export_facts
    from src.backup.volume_job import get_volume_manager

    # THIS folder's completed backup, not the manager's last job: a restore or a verify
    # run since the export would otherwise stand in for it and be refused, and the
    # folder read back as holding no corpus (J1).
    return export_facts(dirname, volume_status=get_volume_manager().backup_status_for(dirname))


def _is_export_destination(dirname: str) -> bool:
    """Whether a backup job actually wrote to this folder in this process.

    The write below is refused for anything else. Not a security boundary (the app is
    loopback-only and every other endpoint here takes a server-side path), but a
    correctness one: a summary file describes the export that made a folder, so
    writing one into a folder no export wrote to would produce a document whose
    every fact is about something else.
    """
    from pathlib import Path

    from src.backup.folder_backup import get_folder_manager
    from src.backup.volume_job import get_volume_manager

    try:
        target = Path(dirname).resolve()
    except OSError:
        return False
    for st in (get_volume_manager().status(), get_folder_manager().status()):
        if st.get("mode") != "backup" or not st.get("dest"):
            continue
        try:
            if Path(str(st["dest"])).resolve() == target:
                return True
        except OSError:
            continue
    return False


@router.get("/export-summary")
def export_summary_read(folder: str = Query(..., alias="dir")) -> dict:
    """The completion panel's facts for an export folder — READ ONLY (R4; Q208 = a).

    The same :func:`~src.backup.export_summary.export_facts` the written file renders
    from, so a reopened dialog and the file on the drive cannot disagree.

    ``summary_path`` says whether ``BACKUP_SUMMARY.md`` is actually beside the backup
    (``None`` when it is not), so a reopened panel can name the file -- or its absence
    -- instead of implying one (J2).
    """
    from pathlib import Path

    from src.backup.export_summary import SUMMARY_NAME

    facts = _export_summary_facts(folder)
    p = Path(folder) / SUMMARY_NAME
    facts["summary_path"] = str(p) if p.is_file() else None
    return facts


@router.post("/export-summary")
def export_summary_write(body: ExportSummaryBody) -> dict:
    """Write ``BACKUP_SUMMARY.md`` beside ``volumes.json`` and return the facts (Q209 = a).

    Called LAST, after both phases and after the verify-after-write pass, which is
    what lets the file carry the verify verdict rather than promising one. Each export
    phase now writes the file itself when it completes (J2), so this is an idempotent
    rewrite from the same facts -- and the way a reopened dialog recovers a file the
    job could not write.
    """
    from src.backup.export_summary import SUMMARY_NAME, write_backup_summary

    if not _is_export_destination(body.dir):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{body.dir} is not the destination of a backup this app ran — "
                "refusing to write a summary describing an export that did not happen."
            ),
        )
    facts = _export_summary_facts(body.dir)
    try:
        path = write_backup_summary(body.dir, facts)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot write {SUMMARY_NAME}: {exc}") from exc
    return {"summary_path": str(path), "facts": facts}


class ImportQueueItem(BaseModel):
    kind: str
    path: str
    label: str | None = None
    categories: list[str] = []
    # MOVED HERE FROM /v2/restore/* (Q214 = a, 2026-09-16). Those two routes were the
    # only surface that could express either option, so deleting them without these
    # would have retired a capability nobody decided to drop. Both are DECLARED here
    # -- a settings key that exists in the store and the writer but not in the request
    # model is accepted with a 200 and silently discarded, which is the defect the
    # 2026-09-16 `auto_track_signals` lesson records.
    allow_unverified: bool = False
    include_newsletters: bool = True
    # "Trust the backup scrapping history" for THIS import (the Q701 note). Declared
    # for the same reason as the two above, and NULLABLE rather than defaulted: None
    # means "this import did not choose", which resolves to the operator's stored
    # first-launch answer. A `bool = True` default here would make every caller that
    # omits the field assert a choice it never made.
    trust_fetch_history: bool | None = None


class ImportQueueBody(BaseModel):
    items: list[ImportQueueItem]
    passphrase: str = ""


@router.post("/import-queue/start")
def import_queue_start(body: ImportQueueBody) -> dict:
    """Queue an import run and begin it. 409 if one is already in flight."""
    from src.backup.import_queue import get_import_queue

    try:
        return get_import_queue().start(
            [i.model_dump() for i in body.items], passphrase=body.passphrase
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/import-queue/status")
def import_queue_status() -> dict:
    """The whole run: per-item identity + outcome, the live sub-job progress, real
    elapsed times. Safe to poll; also how the dialog recovers its own state after a
    reload (ruling item 16)."""
    from src.backup.import_queue import get_import_queue

    return get_import_queue().status()


@router.post("/import-queue/stop")
def import_queue_stop() -> dict:
    """Stop the run IMMEDIATELY (ruling item 15). Before a restore's atomic swap the
    abort is free and complete — the live corpus is byte-identical. After it, the
    swap has already landed (there is no sound undo) and this stops the remaining
    work, whose durable cursor resumes it later. Items still queued are cancelled."""
    from src.backup.import_queue import get_import_queue

    mgr = get_import_queue()
    mgr.stop()
    return mgr.status()


@router.post("/import-queue/clear")
def import_queue_clear() -> dict:
    """Forget a FINISHED run so the dialog starts clean. 409 while one is running."""
    from src.backup.import_queue import get_import_queue

    try:
        return get_import_queue().clear()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reindex-backlog")
def reindex_backlog_status() -> dict:
    """Imports whose articles are merged but not yet confirmed re-indexed.

    The mandatory guard on the 2026-07-29 option-(a) ruling: the merge no longer copies
    the incoming corpus's derived rows, so an un-re-indexed import has NO keywords. That
    is honoured structurally by every analytics path, but it trades a bounded staleness
    for an unbounded invisibility if the backlog is ever lost — so it has to be
    readable. ``available: false`` means the backlog could not be read, never that it is
    empty."""
    from src.backup.merge import reindex_backlog

    return reindex_backlog()


def _accumulate(run: dict, st: dict, *, commit_batch: int | None, idle: bool) -> None:
    """Fold ONE batch's ``reindex_articles`` stats into the run-level accumulator.

    FULL PRECISION IN, ROUNDING ONLY ON THE WAY OUT (:func:`_drain_metrics`) -- the
    lesson ``ReindexJobManager`` already carries: rounding each batch and summing those
    floors every sub-second batch to zero, and over the thousands of batches a
    million-article drain walks, a real cost reports as none at all.

    Tolerates an EMPTY ``st``: a batch whose articles were all already re-indexed
    returns before ``reindex_articles`` runs, so it genuinely has nothing to report,
    and inventing zeros for it would put a fabricated sample in the mean.
    """
    if not st:
        return
    for k in ("wall_s", "load_s", "precompute_s", "apply_s", "apply_index_s", "apply_commit_s"):
        v = st.get(k)
        if v is not None:
            run[k] = float(run.get(k, 0.0)) + float(v)
    for k in ("articles", "mentions_written", "mentions_kept", "mentions_updated",
              "mentions_removed", "mentions_added"):
        run[k] = int(run.get(k, 0)) + int(st.get(k, 0) or 0)
    # The seconds inside index_article by part, summed at full precision like the rest.
    split = st.get("apply_split")
    if isinstance(split, dict):
        acc_split = dict(run.get("apply_split") or {})
        for name, secs in split.items():
            acc_split[str(name)] = float(acc_split.get(str(name), 0.0)) + float(secs or 0.0)
        run["apply_split"] = acc_split
    # WHICH SETTINGS PRODUCED THESE SECONDS. Without this the split is uninterpretable
    # across a run that went online half-way through: the same apply_s means different
    # things at commit batch 1 and at 200, and that comparison is the whole point of
    # letting the drain use the import's settings at all.
    run["exclusive_articles" if idle else "shared_articles"] = int(
        run.get("exclusive_articles" if idle else "shared_articles", 0)
    ) + int(st.get("articles", 0) or 0)
    widths = set(run.get("commit_batch_seen") or ())
    if commit_batch:
        widths.add(int(commit_batch))
    run["commit_batch_seen"] = sorted(widths)
    # WHICH precompute path ran, summed across batches. "pool" versus "serial" is the
    # difference between every core and one, and a pool that quietly fell back is the
    # exact degradation the split exists to expose rather than average away.
    pre = st.get("precompute")
    by_path = (pre or {}).get("by_path") if isinstance(pre, dict) else None
    if isinstance(by_path, dict):
        acc = dict(run.get("precompute_by_path") or {})
        for path, n in by_path.items():
            acc[str(path)] = int(acc.get(str(path), 0)) + int(n or 0)
        run["precompute_by_path"] = acc


def _drain_metrics(run: dict) -> dict | None:
    """The published, rounded view of the drain's accumulated split; None when empty.

    ``None`` rather than a dict of zeros: a drain that has not yet finished a batch has
    measured nothing, and a zeroed split reads as "instant", which is a different
    claim. Same rule for the rate -- it is reported only when both sides of the
    division are real, never fabricated and never infinite.
    """
    if not run.get("articles"):
        return None
    # Annotated because the values are deliberately HETEROGENEOUS -- rounded seconds,
    # counts, a list of widths, a path histogram, and a rate that may be None. Without
    # it the comprehension below fixes the value type at float and every later
    # assignment is a type error.
    out: dict[str, object] = {
        k: round(float(run[k]), 3)
        for k in ("wall_s", "load_s", "precompute_s", "apply_s", "apply_index_s", "apply_commit_s")
        if run.get(k) is not None
    }
    out["articles"] = int(run.get("articles", 0))
    out["mentions_written"] = int(run.get("mentions_written", 0))
    for k in ("mentions_kept", "mentions_updated", "mentions_removed", "mentions_added"):
        out[k] = int(run.get(k, 0))
    if run.get("apply_split"):
        out["apply_split"] = {k: round(float(v), 3) for k, v in run["apply_split"].items()}
    out["exclusive_articles"] = int(run.get("exclusive_articles", 0))
    out["shared_articles"] = int(run.get("shared_articles", 0))
    out["commit_batch_seen"] = list(run.get("commit_batch_seen") or [])
    if run.get("precompute_by_path"):
        out["precompute_by_path"] = dict(run["precompute_by_path"])
    wall = float(run.get("wall_s") or 0.0)
    articles = int(run.get("articles", 0))
    out["articles_per_second"] = round(articles / wall, 2) if articles and wall > 0 else None
    return out


def _reindex_resume_worker(ctx, **_kw) -> dict:
    """Finish the re-index for every batch still stamped ``merged``.

    Nothing new is computed here: :func:`reindex_imported_articles` already owns the
    durable watermark, the batching and the parallel precompute, and is idempotent, so
    this is only the CALLER the backlog never had. Before this, the re-index ran solely
    inside the import; an import interrupted during it (a clean shutdown is enough --
    field bundle 2026-08-02, ``died_in_stage: reindex`` after 6.5 h) left the batch
    stamped ``merged`` forever with no way to pick it up again, and under the option-(a)
    ruling those articles carry NO keywords at all.

    Cooperative: it stops at the next BATCH boundary, and the watermark inside the batch
    means a stop mid-batch is resumed exactly, never redone from the top.
    """
    from src.analytics.corpus_epoch import bump_corpus_epoch
    from src.analytics.counter_deferral import is_deferral_open, open_deferral
    from src.analytics.store import finish_deferral
    from src.backup.merge import (
        default_reindex_commit_batch,
        import_reindex_commit_batch,
        reindex_backlog,
        reindex_imported_articles,
    )
    from src.database.corpus_lease import corpus_lease
    from src.database.session import session_scope

    bk = reindex_backlog()
    if not bk.get("available"):
        # Never "0 pending" for a read we could not make -- the whole point of the guard.
        raise RuntimeError(f"could not read the re-index backlog: {bk.get('reason')}")

    batches = bk.get("batches") or []
    # The same job's first line, keyed too (I-6's class): "starting" matched no key, so it
    # printed in English wherever the task manager looked it up.
    ctx.set_progress(done=0, total=int(bk.get("articles_pending") or 0),
                     detail=Framed("starting…", "starting…"))
    out: dict = {"batches": [], "articles_reindexed": 0, "articles_failed": 0, "stopped": False}
    walked = 0
    # The measured split, accumulated ACROSS batches and republished after each one, so a
    # drain that runs for days says what it is spending the time on WHILE it runs rather
    # than only in the result nobody waits for (F3, 2026-09-21 audit docs/audit/15). The
    # numbers are reindex_articles' own out-parameter -- load / precompute / apply, and
    # apply split into staging versus commit -- which this entry point simply never asked
    # for, so the one job that most needed them was the one job running blind.
    run: dict[str, float] = {}

    # YIELD TO AN IMPORT (field report 2026-08-11). An import run claims the machine --
    # all cores, an enlarged page cache, collection paused -- and this drain is the one
    # heavy writer that was never told. ``ReindexJobManager`` grew ``_yield_to_exclusive``
    # for exactly this and THIS job is a different entry point, added later: the standing
    # lesson is that the entry points added AFTER a "gate every entry point" ruling are
    # the ones that will be missing, and here it was.
    #
    # STOP rather than park, because ``should_stop`` is polled inside the article loop
    # while a park could only happen BETWEEN batches -- and a single import is a single
    # batch, so parking would never fire on the one shape that matters. Stopping is free:
    # the per-article watermark resumes exactly where it left off, and the import queue
    # restarts the drain at the end of every run, so the work is deferred, never lost.
    def _yield_to_import() -> bool:
        return exclusive_window_open()

    # THE DRAIN MAY RUN LIKE THE IMPORT WHEN NOTHING IS COLLECTING (R21, maintainer
    # 2026-09-22, default accepted; F3 in docs/audit/15). Identical work -- the same
    # index_article over the same articles -- ran at ONE COMMIT PER ARTICLE here and at
    # 200 inside an import, for no reason but the entry point. OO_REINDEX_COMMIT_BATCH's
    # default of 1 is the right conservative answer only while a live scrape needs the
    # single-writer gate back between articles; with the collector stopped, nothing is
    # waiting on that gate and every fsync through the SQLCipher codec is pure cost.
    #
    # "IDLE" IS DELIBERATELY THE STRICT READING: the scheduler LOOP is not alive. Not
    # "no pass is active this instant" -- a live loop can start a pass between two
    # articles, and a wide batch holds the gate across its whole commit, so the moment
    # the collector woke it would wait on us. Airplane mode stops the loop
    # (src/api/system.py), which makes this exactly the operator step the audit asks
    # for: collection off, then drain. Unknown is never idle: any failure to read the
    # scheduler answers False and the conservative default applies.
    #
    # Workers are LEFT ALONE on purpose (audit §9.1 step 3). This machine is write-bound,
    # not CPU-bound; adding cores to the precompute would only fill the apply queue
    # faster, and the worker count is the knob whose effect the A/B still has to measure.
    def _collector_idle() -> bool:
        try:
            from src.scheduler.runner import get_scheduler

            if get_scheduler().is_running():
                return False
        except Exception:  # noqa: BLE001 - an unreadable scheduler is never "idle"
            return False
        return not exclusive_window_open()

    # ONE corpus-epoch bump per RUN, at the START and again at the END (F3). Every
    # article this drain touches has its mention rows rewritten (changed rows updated in
    # place, gone ones deleted, new ones inserted; unchanged ones left alone), so a rollup built before
    # the run must be invalidated (the start bump) and so must one snapshotted while
    # it ran (the end bump) -- the second is not a nicety: bumping per batch used to
    # close that window by accident, and a start-only bump would silently stop
    # closing it. Best-effort by bump_corpus_epoch's own contract, and each in its own
    # short session because this worker holds none (reindex_imported_articles opens
    # its own) -- a cache-coordination write may never break, or mask, the drain.
    def _bump(reason: str) -> None:
        try:
            with session_scope() as _s:
                bump_corpus_epoch(_s, reason=reason)
        except Exception:  # noqa: BLE001 - never let the epoch bump break the drain
            _LOG.warning("corpus-epoch bump failed (%s)", reason, exc_info=True)

    # R22 -- the counters stop being maintained per article while the machine is ours,
    # and the disclosure says so until the drain's own reconcile lands.
    #
    # OPENED ONCE FOR THE RUN, NOT PER BATCH, and closed in the finally below. Per batch
    # would make each one reconcile the whole corpus at its own end -- ten batches, ten
    # whole-corpus GROUP BYs over 11 M keywords -- which is slower than never deferring.
    # Opened LAZILY, at the first batch that actually turns out to be exclusive, because
    # `idle` is re-read per batch and a run that never gets the machine should never
    # publish an `estimated` it did not earn.
    deferring = False

    def _open_deferral_once() -> bool:
        nonlocal deferring
        if deferring:
            return True
        try:
            with session_scope() as _s:
                open_deferral(_s, reason="reindex-resume")
            deferring = True
        except Exception:  # noqa: BLE001 - no marker, no deferral; the drain still runs
            _LOG.warning(
                "could not open the counter-deferral marker; counters stay maintained",
                exc_info=True,
            )
        return deferring

    if batches:
        _bump("reindex-resume:start")
    clean_end = False  # every batch walked, nothing raised, nothing stopped the run
    try:
        for b in batches:
            # Read `stopping` ONCE: re-reading it for the reason would let a cancel that
            # landed in between relabel a yield as a cancel, or the reverse.
            stopping = ctx.stopping
            if stopping or _yield_to_import():
                out["stopped"] = True
                out["paused_for_import"] = not stopping
                break
            bid = int(b["batch_id"])
            # A keyed FRAME beside the English (2026-09-27 re-walk, I-6): a plain str left
            # detail_i18n null, so the task manager printed "import 2 (1200 article(s))"
            # in every language with its count ungrouped. The count is its own one/many
            # phrase (the task manager formats the number); the batch id is data.
            n_art = int(b["articles"])
            ctx.set_progress(detail=Framed(
                f"import {bid} ({n_art} article(s))", "import {batch} ({articles})",
                batch=str(bid),
                articles={"i18n": "{n} article" if n_art == 1 else "{n} articles",
                          "vars": {"n": n_art}},
            ))

            def _progress(done: int, _total: int, _base: int = walked) -> None:
                ctx.set_progress(done=_base + done)

            # Re-read per batch, never once at the top: a drain measured in days must follow
            # the machine it is actually on, and the operator may go online mid-run. The
            # value used is PUBLISHED beside the numbers it produced, so a slow batch can be
            # read against the settings it ran under instead of guessed at.
            idle = _collector_idle()
            # RESOLVED, never left as None. Passing None would behave identically
            # (reindex_imported_articles reads the same env var), but the width is
            # PUBLISHED beside the seconds it produced, and the audit's own operator
            # step sets OO_REINDEX_COMMIT_BATCH=200 -- so a reporter that assumed the
            # default's default would print "1" for a run committing in 200s.
            commit_batch = (
                import_reindex_commit_batch() if idle else default_reindex_commit_batch()
            )
            # Deferral rides the SAME exclusivity signal as the commit width: a batch
            # that is not exclusive keeps maintaining its counters inline, and the marker
            # (if an earlier batch opened one) simply stays open until the final
            # reconcile -- a mixed run is still honest, just less deferred.
            defer = _open_deferral_once() if idle else False
            st: dict = {}
            with corpus_lease("reindex-resume"):
                res = reindex_imported_articles(
                    bid,
                    commit_batch=commit_batch,
                    defer_counters=defer,
                    stats=st,
                    # ONE epoch bump per RUN (below), not one per batch: the bump takes the
                    # single-writer gate and commits, and a backlog of many imports is ONE
                    # logical mutation of the derived rows.
                    bump_epoch=False,
                    progress_cb=_progress,
                    should_stop=lambda: ctx.stopping or _yield_to_import(),
                )
            walked += int(b["articles"])
            out["batches"].append(
                {
                    "batch_id": bid,
                    "exclusive_settings": idle,
                    # Published beside the seconds it produced, for the same reason
                    # exclusive_settings is: a batch's numbers cannot be read without
                    # knowing which regime produced them.
                    "counters_deferred": defer,
                    **res,
                }
            )
            out["articles_reindexed"] += int(res.get("reindexed") or 0)
            out["articles_failed"] += int(res.get("failed") or 0)
            _accumulate(run, st, commit_batch=commit_batch, idle=idle)
            ctx.set_metrics(_drain_metrics(run))
        clean_end = not out["stopped"]
    finally:
        # In a finally for the same reason as the bump below, and BEFORE it: whatever
        # ended the run -- a cancel, a crash on the last batch -- the counters it stopped
        # maintaining must be reconciled and the disclosure lifted. A run that ends early
        # still reconciles: the articles it DID re-index are committed, so their counters
        # are drifted whether or not the drain finished. finish_deferral never raises, and
        # leaves the marker open if it could not finish, so an interrupted drain degrades to
        # an honest `estimated` rather than to a silent `exact`.
        #
        # EXCEPT WHILE AN IMPORT OWNS THE MACHINE (2026-09-27). The reconcile is an
        # unbounded whole-corpus sweep committing slice by slice on the LIVE file, and an
        # import that made this drain yield is about to snapshot that file, merge into the
        # copy and swap it in. Run beside it, the sweep straddled the swap: slices it
        # reconciled after the snapshot were discarded with the old file, it carried on
        # against the new one, completed, and closed the marker there -- `exact` over
        # counters it never reconciled. Reproduced with the app's own finish_deferral,
        # snapshot and swap on 300,000 keywords, snapshot at 30% of the sweep and swap at
        # 60%: the new file had no marker, read `exact`, and held 27,143 drifted keywords,
        # exactly the slices reconciled between the two (0 when the sweep ended first).
        # So on a yield the marker is LEFT OPEN, counters read `estimated`, and the drain
        # the import queue restarts after its run closes it. The sweep that does run holds
        # a corpus lease, so a swap waits for it rather than landing under it, and stops at
        # its next slice if an import claims the machine meanwhile.
        #
        # A marker an EARLIER run left open that way is this run's to close when it ends
        # cleanly, even if this run never deferred (a restarted drain that finds the
        # collector running has no marker of its own, and would otherwise leave that one
        # open for good).
        #
        # THE EPOCH BUMP COMES FIRST, then again after a reconcile that finished. The sweep
        # below runs for minutes on a large corpus (86-104 s a pass on 3 million keywords), and
        # a run killed inside it never reaches a bump placed after it: the next run finds no
        # batch left, walks none, and never bumps, so a rollup built from the middle of this
        # run would keep the old numbers of rows changed in place under their old ids. The first
        # bump covers the mention rows (the sweep touches counters, not rows); the second covers
        # the counters the rollup's keyword table copies, so a rollup built between the two is
        # rebuilt once the sweep has ended. An extra bump is only ever an extra, correct rebuild.
        #
        # THE REMAINING BOUND, and the condition it stands on. A lost end bump leaves the next
        # run with no batch to walk and so no bump of its own. It is lost by a hard kill between
        # the last batch's completion stamp and this line, and equally by a bump that FAILS
        # (``_bump`` and ``bump_corpus_epoch`` swallow their errors, by design: a coordination
        # write may not break the drain). A second window mirrors it: ``finish_deferral``
        # (store.py) calls ``close_deferral`` (counter_deferral.py), which closes the marker a
        # moment before the reconciled bump below.
        # What is exposed is a rollup built from the middle of the run, and not only to counts:
        # an attribution change (country, language, source, extractor), a deleted row and a row
        # missing from the snapshot the build read are all invisible to an id-tail refresh.
        # Today that is bounded by the serving layers' backstop rebuilds
        # (``rollup_serve._BACKSTOP_S`` and ``map_serve._BACKSTOP_S``, one hour each), which
        # rebuild regardless of the token. THAT HOLDS ONLY FOR THE IN-MEMORY SERVE: with the
        # persisted store active, ``_refresh_persisted_build`` merges only the tail while the
        # epoch is unchanged, so a lost bump would be UNBOUNDED there. The persisted store is off today
        # only because the httpfs pins in ``configs/external_artifacts.yml`` are blank
        # (``tests/test_reindex_drain_settings.py`` fails the day they are filled, pointing
        # here). A persisted "bump owed" marker is the fix that day, not before: it would add a
        # second place that says whether the corpus changed, which is the thing the epoch is.
        if batches:
            _bump("reindex-resume:end")
        window = _yield_to_import()
        leftover = False
        if not deferring and clean_end and not ctx.stopping and not window:
            try:
                with session_scope() as _s:
                    leftover = is_deferral_open(_s)
            except Exception:  # noqa: BLE001 - unreadable: the next run looks again
                _LOG.warning("could not read the counter-deferral marker", exc_info=True)
        if (deferring or leftover) and window:
            out["counter_reconcile"] = {
                "reconciled": False, "closed": False, "complete": False,
                "deferred": (
                    "an import has claimed the machine, so the whole-corpus counter sweep "
                    "does not run beside it; the counters stay disclosed as estimated until "
                    "the drain the import queue restarts after its run completes the sweep"
                ),
            }
        elif deferring or leftover:
            try:
                with corpus_lease("reindex-resume"), session_scope() as _s:
                    out["counter_reconcile"] = finish_deferral(_s, should_stop=_yield_to_import)
                if leftover:
                    out["counter_reconcile"]["left_by_an_earlier_run"] = True
            except Exception:  # noqa: BLE001 - never let it mask what ended the run
                _LOG.warning("deferred-counter reconcile failed", exc_info=True)
        # Every run that reconciled counters bumps again here, with or without a batch of its
        # own: a resumed run with nothing pending can still close a sweep an earlier run left
        # open (killed inside it, or stopped for an import), and a rollup built since keeps the
        # keyword table it copied before that reconcile until an epoch change.
        if out.get("counter_reconcile", {}).get("reconciled"):
            _bump("reindex-resume:reconciled")
    # A cancel during the LAST batch leaves the loop normally, so the top-of-loop check
    # never sees it -- without this, a partial run would report stopped:false and read as
    # a completed drain. reindex_imported_articles takes should_stop, so it genuinely can
    # return early on the final batch. The same holds for an import window opening
    # mid-batch, and the two are reported apart: a cancel is the operator's decision, a
    # yield is ours, and only the second one restarts itself.
    if ctx.stopping:
        out["stopped"] = True
    elif _yield_to_import():
        out["stopped"] = True
        out["paused_for_import"] = True
    # Re-read rather than infer: a batch only leaves the backlog when it was stamped
    # complete, so this reports what is actually LEFT, not what we believe we did.
    after = reindex_backlog()
    out["remaining"] = after.get("articles_pending") if after.get("available") else None
    out["remaining_unreadable_reason"] = None if after.get("available") else after.get("reason")
    # The same split the job published live, banked in the result so a finished run is
    # still readable after the live channel is cleared by the next start.
    out["stats"] = _drain_metrics(run)
    return out


_REINDEX_RESUME_JOB = register_job(
    BackgroundJob(
        "reindex-resume",
        "finishing the re-index of imported articles",
        _reindex_resume_worker,
        is_writer=True,
        cancellable=True,
    )
)


@router.post("/reindex-backlog/resume")
def reindex_backlog_resume() -> dict:
    """Finish the pending re-index as a visible, cancellable background job.

    The half the guard was missing: the backlog was reported and then nobody could act
    on it from the app. Idempotent and resumable -- safe to start, stop and start again.
    An already-running job returns its status with ``started: false`` rather than 409,
    so a double-click can never look like an error."""
    try:
        st = _REINDEX_RESUME_JOB.start()
        st["started"] = True
    except RuntimeError:
        st = _REINDEX_RESUME_JOB.status()
        st["started"] = False
    return st


@router.get("/reindex-backlog/resume/status")
def reindex_backlog_resume_status() -> dict:
    """Live status of the re-index resume job, plus the BACKLOG it drains.

    ADDITIVE (2026-09-16, Q204 = a): every key the job already published is
    unchanged; ``backlog`` is new. It is here rather than behind a second poll
    because stage 4 of the import lifecycle needs both facts to say anything true --
    the job answers *is a drain running and how far has it got*, the backlog answers
    *how much is left*, and an idle job's ``total`` is a stale number from whenever
    it last ran, which on its own reads as "nothing to do". ``backlog.available:
    false`` still means the backlog could not be READ, never that it is empty.

    One poll chain, one read (Q206): the import dialog's stage-4 row polls this and
    nothing else.

    WHAT THE BACKLOG READ COSTS, measured rather than assumed before it was put on a
    polled route. ``_BACKLOG_SQL`` is an index-only seek per PENDING batch over the
    ``merged_rows`` primary key, so it is LINEAR IN THE PENDING ARTICLE COUNT and
    free once the backlog is empty. On a fresh PLAINTEXT SQLite fixture (3 pending
    batches, five times as many non-article rows beside them, ANALYZE run, five
    repetitions, median): **0.97 ms at 10,000 pending articles, 10.5 ms at 100,000,
    101.9 ms at 1,000,000.** That is a floor -- the encrypted store pays the codec on
    top -- and 102 ms is far too much for a one-second poll, which is why the client
    paces THIS read at 5 s inside its single chain while the queue status keeps the
    1 s cadence. The figure moves on the scale of minutes, so nothing is lost.
    """
    from src.backup.merge import reindex_backlog

    st = _REINDEX_RESUME_JOB.status()
    st["backlog"] = reindex_backlog()
    return st


@router.post("/reindex-backlog/resume/cancel")
def reindex_backlog_resume_cancel() -> dict:
    """Stop at the next batch boundary. The durable watermark resumes exactly."""
    _REINDEX_RESUME_JOB.cancel()
    return _REINDEX_RESUME_JOB.status()
