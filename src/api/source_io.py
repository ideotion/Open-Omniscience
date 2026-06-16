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

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.catalog.csv_io import (
    EXPORT_COLUMNS,
    parse_sources_csv,
    template_csv,
    upsert_sources,
    write_csv,
)
from src.database.models import Article, Source
from src.database.session import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

# Columns the source list can be sorted by (maps label -> SQL expression below).
_SORTABLE = {"name", "domain", "source_type", "country", "language", "priority", "articles"}

# Cap the upload size defensively (a catalog of a few thousand rows is well under this).
_MAX_IMPORT_BYTES = 64 * 1024 * 1024


def _display_name(country: str | None) -> str | None:
    """Full name for a stored code (None stays None; junk comes back as-is)."""
    if not country:
        return None
    from src.catalog.countries import country_display_name

    return country_display_name(country)


def _source_to_row(s: Source) -> dict:
    return {
        "name": s.name,
        "domain": s.domain,
        "rss_url": s.rss_url,
        "source_type": s.source_type,
        "country": s.country,
        "language": s.language,
        "region": s.region,
        "tags": s.tags,
        "priority": s.priority,
        "rate_limit_ms": s.rate_limit_ms,
        "enabled": s.enabled,
        # Operator-asserted provenance metadata (1-10), NEVER computed/derived by the
        # app (intentional exemption to the no-composite-score rule; see ETHICS.md and
        # test_reliability_score_is_operator_set_never_computed). The UI labels it
        # "operator-set, not computed" wherever it is shown.
        "reliability_score": s.reliability_score,
    }


@router.get("/sources")
def list_sources(
    q: str | None = None,
    country: str | None = None,
    language: str | None = None,
    source_type: str | None = None,
    tag: str | None = None,
    enabled: bool | None = None,
    sort: str = Query("name"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Filterable, sortable source list with per-source article counts.

    Powers the Sources tab's quick filters + sortable columns. Filters: free-text
    (name/domain), country, language, source_type, tag (substring), enabled. Sort
    by any of: name, domain, source_type, country, language, priority, articles.
    """
    art_count = func.count(Article.id).label("articles")
    base = db.query(Source, art_count).outerjoin(Article, Article.source_id == Source.id)

    filters = []
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            func.lower(Source.name).like(func.lower(like))
            | func.lower(Source.domain).like(func.lower(like))
        )
    if country:
        # Forgiving filter through the one conversion layer: ?country=France,
        # ?country=FR and ?country=fr all match the canonical stored code.
        from src.catalog.countries import normalize_country

        cc = normalize_country(country) or country.strip().lower()
        filters.append(func.lower(Source.country) == cc)
    if language:
        filters.append(func.lower(Source.language) == language.strip().lower())
    if source_type:
        filters.append(func.lower(Source.source_type) == source_type.strip().lower())
    if tag:
        filters.append(Source.tags.ilike(f"%{tag.strip()}%"))
    if enabled is not None:
        filters.append(Source.enabled.is_(enabled))
    for f in filters:
        base = base.filter(f)

    total = db.query(func.count(Source.id))
    for f in filters:
        total = total.filter(f)
    total_n = total.scalar() or 0

    sort_key = sort if sort in _SORTABLE else "name"
    col = art_count if sort_key == "articles" else getattr(Source, sort_key)
    base = base.group_by(Source.id).order_by(col.desc() if order == "desc" else col.asc())
    rows = base.limit(limit).offset(offset).all()

    return {
        "total": int(total_n),
        "limit": limit,
        "offset": offset,
        "sort": sort_key,
        "order": order,
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "enabled": s.enabled,
                "priority": s.priority,
                "source_type": s.source_type,
                "country": s.country,
                "country_name": _display_name(s.country),
                "language": s.language,
                "article_count": int(n),
                "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
            }
            for s, n in rows
        ],
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
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=open-omniscience-sources.csv"},
    )


@router.get("/template.csv")
def export_template() -> StreamingResponse:
    """Download a CSV template (header + documented example rows)."""
    return StreamingResponse(
        iter([template_csv()]),
        media_type="text/csv",
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
