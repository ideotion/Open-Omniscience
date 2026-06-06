"""
Source-catalog CSV import / export API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mounted under /api/catalog (not /api/sources) so it never collides with the
``/api/sources/{source_id}`` integer route. Export streams the whole catalog as
CSV; import upserts by domain and returns an honest summary (created / updated /
skipped + per-row errors).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.catalog.csv_io import (
    EXPORT_COLUMNS,
    parse_sources_csv,
    template_csv,
    upsert_sources,
    write_csv,
)
from src.database.models import Source
from src.database.session import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

# Cap the upload size defensively (a catalog of a few thousand rows is well under this).
_MAX_IMPORT_BYTES = 64 * 1024 * 1024


def _source_to_row(s: Source) -> dict:
    return {
        "name": s.name, "domain": s.domain, "rss_url": s.rss_url,
        "source_type": s.source_type, "country": s.country, "language": s.language,
        "region": s.region, "tags": s.tags, "priority": s.priority,
        "rate_limit_ms": s.rate_limit_ms, "enabled": s.enabled,
        "reliability_score": s.reliability_score,
    }


@router.get("/columns")
def columns() -> dict:
    """The defined CSV columns (name + domain required; the rest optional)."""
    return {"columns": EXPORT_COLUMNS, "required": ["name", "domain"]}


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    """Download the entire source catalog as CSV (round-trips with import)."""
    rows = [_source_to_row(s) for s in db.query(Source).order_by(Source.name).all()]
    csv_text = write_csv(rows)
    return StreamingResponse(
        iter([csv_text]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=open-omniscience-sources.csv"},
    )


@router.get("/template.csv")
def export_template() -> StreamingResponse:
    """Download a CSV template (header + documented example rows)."""
    return StreamingResponse(
        iter([template_csv()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sources-template.csv"},
    )


@router.post("/import")
async def import_csv(file: UploadFile, db: Session = Depends(get_db)) -> dict:
    """Upsert sources from an uploaded CSV (create new, update existing by domain).

    Returns created/updated/skipped counts plus per-row parse and write errors, so
    nothing fails silently.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large")
    text = raw.decode("utf-8", errors="replace")
    rows, parse_errors = parse_sources_csv(text)
    if not rows and parse_errors:
        raise HTTPException(status_code=400, detail="; ".join(parse_errors[:5]))

    result = upsert_sources(db, rows)
    # Surface parse errors alongside write errors for a complete picture.
    result["parse_errors"] = parse_errors[:50]
    result["skipped"] += len(parse_errors)
    result["received_rows"] = len(rows)
    return result
