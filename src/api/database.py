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

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.database.session import engine, get_db

router = APIRouter(prefix="/api/database", tags=["database"])


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
    return {
        "backend": backend,
        "url_summary": f"{backend}:///…/{Path(engine.url.database).name}"
        if engine.url.database and engine.url.database != ":memory:"
        else f"{backend} (in-memory)",
        "counts": counts,
        "file": _sqlite_file_bytes(),
        "table_count": len(present),
    }
