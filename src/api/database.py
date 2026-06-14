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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from src.database.session import engine, get_db
from src.utils.cache import SimpleCache

router = APIRouter(prefix="/api/database", tags=["database"])

# Count aggregations are full table scans in SQLite (and the Library tab polls
# them). VERIFIED caching: an entry is served only while two cheap probes —
# PRAGMA data_version (commits by other connections) and total_changes()
# (writes on this connection) — prove the database unchanged since it was
# computed, with the TTL as an upper bound. A write from ANY path (scraper,
# import, direct session) flips a probe and forces a recompute, so a number
# can be stale only while nothing was written. computed_at + cache_ttl_s are
# stamped into every payload so freshness stays visible regardless.
_CACHE_TTL_S = 30
_cache = SimpleCache(max_size=8, default_ttl=_CACHE_TTL_S)


def _db_change_probe(db: Session) -> tuple:
    from sqlalchemy import text

    if engine.url.get_backend_name() != "sqlite":
        return (None, None)
    return (
        db.execute(text("PRAGMA data_version")).scalar(),
        db.execute(text("SELECT total_changes()")).scalar(),
    )


def _cached(key: str, compute, db: Session) -> dict:
    probe = _db_change_probe(db)
    hit = _cache.get(key)
    if hit is not None and hit.get("probe") == probe:
        return hit["payload"]
    out = compute()
    out["computed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    out["cache_ttl_s"] = _CACHE_TTL_S
    _cache.set(key, {"probe": probe, "payload": out})
    return out


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
    "mentioned_dates": "article_mentioned_dates",
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
    a feature exists when it does not. Cached briefly (computed_at/cache_ttl_s
    state the freshness window in the response).
    """

    def _compute() -> dict:
        from sqlalchemy import func, select, table, text

        present = set(inspect(engine).get_table_names())

        counts: dict[str, int] = {}
        for label, tbl in _COUNTED_TABLES.items():
            if tbl in present:
                # COUNT(*) over a table named from our own fixed map (never user input).
                counts[label] = int(
                    db.execute(select(func.count()).select_from(table(tbl))).scalar() or 0
                )

        backend = engine.url.get_backend_name()
        from src.backup.sqlite_backup import is_sqlite

        reclaimable = None
        if backend == "sqlite":
            # Free pages only VACUUM returns to the filesystem — real PRAGMA
            # readings, shown next to the Settings compact tool.
            free_pages = int(db.execute(text("PRAGMA freelist_count")).scalar() or 0)
            page_size = int(db.execute(text("PRAGMA page_size")).scalar() or 0)
            reclaimable = free_pages * page_size

        return {
            "backend": backend,
            "url_summary": f"{backend}:///…/{Path(engine.url.database).name}"
            if engine.url.database and engine.url.database != ":memory:"
            else f"{backend} (in-memory)",
            "counts": counts,
            "file": _sqlite_file_bytes(),
            "reclaimable_bytes": reclaimable,
            "table_count": len(present),
            # Whether the backup/restore controls in the Settings tab apply here.
            "backup_supported": is_sqlite(),
        }

    return _cached("stats", _compute, db)


@router.get("/coverage")
def country_coverage(db: Session = Depends(get_db)) -> dict:
    """Summary of how many countries the catalog reaches, plus the gaps.

    Counts are computed from each source's country code (real data) against the
    ISO 3166-1 set, so coverage is measured, never asserted. ``missing`` lists
    country codes with no source; ``thin`` lists covered countries with very few.
    """
    from sqlalchemy import func

    from src.catalog.countries import country_display_name
    from src.catalog.coverage import (
        country_counts_from_session,
        coverage_report,
        regional_report,
    )
    from src.database.models import Source

    def _compute() -> dict:
        counts = country_counts_from_session(db)
        report = coverage_report(counts)
        report["missing"] = report["missing"][:80]  # trim for the UI; details in /countries
        total_sources = int(db.query(func.count(Source.id)).scalar() or 0)
        report["regional"] = regional_report(counts, total_sources=total_sources)
        # Full display names for every code this response mentions (one conversion
        # layer, applied server-side; the UI never carries its own country table).
        mentioned = (
            set(report["missing"])
            | set(report["thin"])
            | set(report["extra_codes"])
            | set(report["special_codes"])
        )
        top = report["regional"]["top_country"]["code"]
        if top:
            mentioned.add(top)
        report["names"] = {c: country_display_name(c) for c in sorted(mentioned)}
        return report

    return _cached("coverage", _compute, db)


@router.get("/countries")
def sources_by_country(db: Session = Depends(get_db)) -> dict:
    """Per-country breakdown: source count, enabled count, and topic keywords.

    Topic keywords are the aggregated tags of the sources in each country — they
    show, at a glance, which subjects a country's sources cover (and by absence,
    which topics may be missing). Countries with no source are returned in
    ``missing`` so covered vs not-covered is explicit.
    """
    from collections import Counter

    from src.catalog.countries import (
        ISO_3166_1_ALPHA2,
        continent_of,
        country_display_name,
    )
    from src.database.models import Source

    def _compute() -> dict:
        rows = db.query(Source.country, Source.enabled, Source.tags).all()
        per: dict[str, dict] = {}
        for country, enabled, tags in rows:
            cc = (country or "").strip().lower() or "(none)"
            slot = per.setdefault(cc, {"sources": 0, "enabled": 0, "tags": Counter()})
            slot["sources"] += 1
            if enabled:
                slot["enabled"] += 1
            for t in (tags or "").split(","):
                t = t.strip()
                if t:
                    slot["tags"][t] += 1

        countries = [
            {
                "code": cc,
                "name": None if cc == "(none)" else country_display_name(cc),
                "region": None if cc == "(none)" else continent_of(cc),
                "sources": d["sources"],
                "enabled": d["enabled"],
                "top_tags": d["tags"].most_common(8),
            }
            for cc, d in per.items()
        ]
        countries.sort(key=lambda c: (-c["sources"], c["code"]))

        present = {cc for cc in per if cc != "(none)"}
        missing = sorted(c for c in ISO_3166_1_ALPHA2 if c not in present)
        return {
            "countries": countries,
            "covered": len(present),
            "total_countries": len(ISO_3166_1_ALPHA2),
            "missing": missing,
            "missing_names": {c: country_display_name(c) for c in missing},
            "missing_count": len(missing),
        }

    return _cached("countries", _compute, db)


@router.post("/vacuum")
def vacuum() -> dict:
    """Rebuild the database file (VACUUM) + refresh planner statistics.

    The Settings maintenance tool (performance batch 2026-06-12): reclaims the
    free pages that deletes leave behind and defragments the b-trees. Honest
    costs are part of the contract: the rebuild takes time proportional to the
    file and needs exclusive write access — if collection is writing, this
    returns 409 rather than queueing silently.
    """
    from sqlalchemy.exc import OperationalError

    from src.database.maintenance import vacuum_database

    try:
        report = vacuum_database(engine)
    except OperationalError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "the database is busy (a collection pass or import is writing); "
                "stop it or retry when it finishes"
            ),
        ) from exc
    _cache.clear()
    return report


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
    import os as _os

    # Close the open descriptor BEFORE unlinking/reopening the path: Windows
    # cannot delete a file that still has an open handle (WinError 32).
    _os.close(fd)
    Path(tmp).unlink(missing_ok=True)  # mkstemp created it; backup_to recreates cleanly
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


# NOTE: the destructive POST /api/database/restore (replace the live corpus with
# an uploaded SQLite file) was REMOVED on 2026-06-13 (maintainer ruling: restore
# is ADDITIVE-ONLY). Restoring goes exclusively through the merge engine at
# POST /api/database/v2/restore/{preview,commit}, which complements the corpus
# and never overwrites it. (Backup CREATION — GET /api/database/backup — stays.)
