"""
Database overview API: honest, read-only statistics about the unified store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Powers the "Database" management tab. Every number here is a real ``COUNT(*)``
or an on-disk byte size -- never an estimate dressed up as a fact
(PRODUCT_SYNTHESIS §3.5 "No fabricated numbers"). Counts are reported only for
tables that actually exist, so a core-only install (no analysis extra, no
commodity table yet) gets an honest, smaller picture rather than a crash.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from src.database.session import engine, get_db

router = APIRouter(prefix="/api/database", tags=["database"])

# Refuse to ingest an unreasonably large "backup" upload (defensive; the real
# corpus for a single user is far smaller, and this caps memory use on restore).
_MAX_RESTORE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


# Human-facing label -> table name. Counted only if the table is present.
_COUNTED_TABLES: dict[str, str] = {
    "articles": "articles",
    "sources": "sources",
    "source_groups": "source_groups",
    "keywords": "keywords",
    "commodity_prices": "commodity_prices",
    "external_sources": "external_sources",
    "article_links": "article_links",
    "article_analyses": "article_analyses",
}


def _sqlite_file_bytes() -> dict | None:
    """Total on-disk size of the SQLite database (main + WAL + SHM), or None.

    Returns None for non-SQLite backends (or an in-memory DB), where a single
    file size is not a meaningful figure.
    """
    db_path = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or not db_path or db_path == ":memory:":
        return None
    main = Path(db_path)
    parts = {
        "main": main,
        "wal": main.with_name(main.name + "-wal"),
        "shm": main.with_name(main.name + "-shm"),
    }
    sizes = {k: (p.stat().st_size if p.exists() else 0) for k, p in parts.items()}
    return {
        "path": str(main),
        "bytes": sum(sizes.values()),
        "components": sizes,
    }


@router.get("/stats")
def database_stats(db: Session = Depends(get_db)) -> dict:
    """Real row counts per table plus backend/on-disk facts.

    Used by the Database management tab. Tables absent from this build are simply
    omitted from ``counts`` rather than reported as zero, so the UI never implies
    a feature exists when it does not.
    """
    from sqlalchemy import func, select, table

    present = set(inspect(engine).get_table_names())

    counts: dict[str, int] = {}
    for label, tbl in _COUNTED_TABLES.items():
        if tbl in present:
            # COUNT(*) over a table named from our own fixed map (never user input).
            counts[label] = int(db.execute(select(func.count()).select_from(table(tbl))).scalar() or 0)

    backend = engine.url.get_backend_name()
    from src.backup.sqlite_backup import is_sqlite

    return {
        "backend": backend,
        "url_summary": f"{backend}:///…/{Path(engine.url.database).name}"
        if engine.url.database and engine.url.database != ":memory:"
        else f"{backend} (in-memory)",
        "counts": counts,
        "file": _sqlite_file_bytes(),
        "table_count": len(present),
        # Whether the backup/restore controls in the Settings tab apply here.
        "backup_supported": is_sqlite(),
    }


@router.get("/backup")
def download_backup() -> FileResponse:
    """Stream a consistent SQLite snapshot of the corpus as a download.

    Uses the online backup API, so the snapshot is valid even while the app is
    running. Refuses (HTTP 400) on non-SQLite backends rather than pretending.
    """
    from src.backup.sqlite_backup import BackupError, backup_to

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # Snapshot into a temp file, then hand it to FileResponse and delete after send.
    fd, tmp = tempfile.mkstemp(prefix="oo-backup-", suffix=".db")
    Path(tmp).unlink(missing_ok=True)  # mkstemp created it; backup_to recreates cleanly
    import os as _os

    _os.close(fd)
    try:
        backup_to(Path(tmp))
    except BackupError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        tmp,
        media_type="application/x-sqlite3",
        filename=f"open-omniscience-backup-{ts}.db",
        background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)),
    )


@router.post("/restore")
async def restore_backup(file: UploadFile) -> dict:
    """Replace the live corpus with an uploaded SQLite backup (destructive).

    The upload is validated (real SQLite, integrity check, core tables present)
    before anything is overwritten, and the current corpus is snapshotted to a
    ``pre-restore-*.db`` first so the operation is reversible.
    """
    from src.backup.sqlite_backup import BackupError, restore_from_bytes

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(data) > _MAX_RESTORE_BYTES:
        raise HTTPException(status_code=413, detail="backup file is too large to restore")
    try:
        report = restore_from_bytes(data)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "restored": True,
        "bytes": report.restored_from_bytes,
        "tables_seen": report.tables_seen,
        "pre_restore_snapshot": report.pre_restore_snapshot,
        "detail": "Corpus restored. A pre-restore snapshot was saved alongside the database.",
    }
