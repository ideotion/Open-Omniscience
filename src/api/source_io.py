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
    tag_mode: str = "any",
    enabled: bool | None = None,
    sort: str = Query("name"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Filterable, sortable source list with per-source article counts.

    Powers the Sources tab's quick filters + sortable columns. Filters: free-text
    (name/domain), country, language, source_type, tag, enabled. Sort by any of:
    name, domain, source_type, country, language, priority, articles.

    MULTI-SELECT (field test 2026-06-22, #23): country/language/source_type/tag accept
    COMMA-SEPARATED values — WITHIN a filter the values are OR'd (French OR English),
    ACROSS filters they are AND'd (French/English AND tagged news). ``tag_mode`` toggles
    tags between ``any`` (OR, default) and ``all`` (a source must carry EVERY tag). A
    single value still works exactly as before (backward compatible).
    """
    from sqlalchemy import and_, or_

    def _vals(raw: str | None) -> list[str]:
        return [v.strip() for v in (raw or "").split(",") if v.strip()]

    # S6: read the MAINTAINED per-source counter instead of an O(articles) join.
    base = db.query(Source)

    filters = []
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            func.lower(Source.name).like(func.lower(like))
            | func.lower(Source.domain).like(func.lower(like))
        )
    countries = _vals(country)
    if countries:
        # Forgiving filter through the one conversion layer: ?country=France,
        # ?country=FR and ?country=fr all match the canonical stored code. OR within.
        from src.catalog.countries import normalize_country

        ccs = [normalize_country(c) or c.strip().lower() for c in countries]
        filters.append(func.lower(Source.country).in_(ccs))
    langs = _vals(language)
    if langs:
        filters.append(func.lower(Source.language).in_([x.lower() for x in langs]))
    types = _vals(source_type)
    if types:
        filters.append(func.lower(Source.source_type).in_([x.lower() for x in types]))
    tag_list = _vals(tag)
    if tag_list:
        conds = [Source.tags.ilike(f"%{t}%") for t in tag_list]
        filters.append(and_(*conds) if tag_mode == "all" else or_(*conds))
    if enabled is not None:
        filters.append(Source.enabled.is_(enabled))
    for f in filters:
        base = base.filter(f)

    total = db.query(func.count(Source.id))
    for f in filters:
        total = total.filter(f)
    total_n = total.scalar() or 0

    from datetime import UTC, datetime, timedelta

    sort_key = sort if sort in _SORTABLE else "name"
    # Sort on the maintained counter for "articles". COALESCE NULL->0 so a not-yet-reconciled
    # source never sorts as SQLite's lowest value while its row shows a live count (the boot
    # self-heal backfill makes NULLs rare; count_basis discloses any that remain). No join.
    col = func.coalesce(Source.article_count, 0) if sort_key == "articles" else getattr(Source, sort_key)
    base = base.order_by(col.desc() if order == "desc" else col.asc(), Source.id)
    sources = base.limit(limit).offset(offset).all()

    # Batched live fallback for any source whose counter is NULL (never reconciled) — ONE
    # grouped query for the whole page, so the endpoint never does a per-source COUNT. After a
    # reconcile/self-heal there are no NULLs, so this is skipped entirely (the perf win).
    null_ids = [s.id for s in sources if s.article_count is None]
    live: dict = {}
    if null_ids:
        live = {
            sid: cnt
            for sid, cnt in db.query(Article.source_id, func.count(Article.id))
            .filter(Article.source_id.in_(null_ids))
            .group_by(Article.source_id)
            .all()
        }

    def _count(s) -> int:
        return int(s.article_count) if s.article_count is not None else int(live.get(s.id, 0))

    _now = datetime.now(UTC)

    def _basis(s) -> str:
        # Honesty envelope: "live" = counted now (NULL counter); "exact" = maintained + fresh;
        # "estimated" = maintained but STALE (never presented as exact — the skeptic's finding).
        if s.article_count is None:
            return "live"
        ra = s.counter_reconciled_at
        if ra is None:
            return "estimated"
        aware = ra if ra.tzinfo is not None else ra.replace(tzinfo=UTC)
        return "exact" if (_now - aware) < timedelta(hours=24) else "estimated"

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
                "article_count": _count(s),
                "count_basis": _basis(s),  # exact (fresh) | estimated (stale) | live (NULL)
                "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
            }
            for s in sources
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
