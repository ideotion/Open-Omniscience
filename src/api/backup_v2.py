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
from src.backup.merge import MergeError, RestoreRefused, run_restore
from src.jobs.background import BackgroundJob, register_job
from src.scheduler.runner import exclusive_window_open

_LOG = logging.getLogger("api.backup_v2")


def _restore_error(action: str, exc: Exception) -> HTTPException:
    """Wrap ``classify_restore_error``'s honest detail (P0-2) in a 500.

    Always JSON {detail} (the SPA reads res.json(); never a plain-text 500)."""
    from src.backup.merge import classify_restore_error

    return HTTPException(status_code=500, detail=classify_restore_error(action, exc))


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
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"could not read {p}: {exc}") from exc
    staged = _stage_upload(data, passphrase or None)
    _apply_restore_selection(staged, include_newsletters=include_newsletters)
    from src.backup import runlog
    from src.backup.volume_job import defer_reindex, hand_off_reindex

    try:
        with runlog.run("import", label=p.name, dest=str(p), legacy_single_file=True):
            report = run_restore(
                staged,
                commit=True,
                allow_unverified=allow_unverified,
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
        _LOG.exception("legacy restore failed")
        raise _restore_error("restore", exc) from exc
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
    from src.backup.merge import reindex_backlog, reindex_imported_articles
    from src.database.corpus_lease import corpus_lease

    bk = reindex_backlog()
    if not bk.get("available"):
        # Never "0 pending" for a read we could not make -- the whole point of the guard.
        raise RuntimeError(f"could not read the re-index backlog: {bk.get('reason')}")

    batches = bk.get("batches") or []
    ctx.set_progress(done=0, total=int(bk.get("articles_pending") or 0), detail="starting")
    out: dict = {"batches": [], "articles_reindexed": 0, "articles_failed": 0, "stopped": False}
    walked = 0

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

    for b in batches:
        # Read `stopping` ONCE: re-reading it for the reason would let a cancel that
        # landed in between relabel a yield as a cancel, or the reverse.
        stopping = ctx.stopping
        if stopping or _yield_to_import():
            out["stopped"] = True
            out["paused_for_import"] = not stopping
            break
        bid = int(b["batch_id"])
        ctx.set_progress(detail=f"import {bid} ({b['articles']} article(s))")

        def _progress(done: int, _total: int, _base: int = walked) -> None:
            ctx.set_progress(done=_base + done)

        with corpus_lease("reindex-resume"):
            res = reindex_imported_articles(
                bid, progress_cb=_progress, should_stop=lambda: ctx.stopping or _yield_to_import()
            )
        walked += int(b["articles"])
        out["batches"].append({"batch_id": bid, **res})
        out["articles_reindexed"] += int(res.get("reindexed") or 0)
        out["articles_failed"] += int(res.get("failed") or 0)
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
