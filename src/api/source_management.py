"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Source Management API Endpoints for Open Omniscience

This module provides FastAPI endpoints for comprehensive source management,
including groups, metadata, and discovery functionality.

Author: Ideotion
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

# Import database models and SourceManager
from src.database.session import get_db
from src.database.source_manager import SourceManager

# Import logging config
from src.utils.logging_config import setup_logging

logger = setup_logging("source_management_api")

# Create router
router = APIRouter(prefix="/api/sources", tags=["Source Management"])

# Rate limiter
from src.api.ratelimit import limiter

# ==================== DISCOVERY CANDIDATES (WP5 / RM-19) ====================
# Machine-suggested sources, staged for the operator's decision. Transparent by
# construction: evidence travels with every candidate; promotion creates a
# DISABLED Source the operator must still enable; dismissal is remembered.


@router.get("/candidates", response_model=dict)
@limiter.limit("100/hour")
async def list_source_candidates(
    request: Request,
    status: str = Query("candidate", pattern="^(candidate|promoted|dismissed|all)$"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List discovery candidates with their channel + evidence."""
    import json as _json

    from src.database.models import SourceCandidate

    q = db.query(SourceCandidate)
    if status != "all":
        q = q.filter(SourceCandidate.status == status)
    rows = q.order_by(SourceCandidate.first_seen.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "candidates": [
            {
                "id": c.id,
                "domain": c.domain,
                "suggested_name": c.suggested_name,
                "channel": c.channel,
                "evidence": _json.loads(c.evidence) if c.evidence else {},
                "status": c.status,
                "first_seen": c.first_seen.isoformat() if c.first_seen else None,
            }
            for c in rows
        ],
    }


@router.post("/candidates/{candidate_id}/promote", response_model=dict)
@limiter.limit("100/hour")
async def promote_source_candidate(
    request: Request, candidate_id: int, db: Session = Depends(get_db)
):
    """Promote a candidate into a DISABLED Source (the operator enables it)."""
    from src.database.models import Source, SourceCandidate

    cand = db.query(SourceCandidate).filter_by(id=candidate_id).first()
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if cand.status != "candidate":
        raise HTTPException(status_code=409, detail=f"Candidate is already {cand.status}")
    existing = db.query(Source).filter(Source.domain == cand.domain).first()
    if existing is None:
        db.add(
            Source(
                name=cand.suggested_name or cand.domain,
                domain=cand.domain,
                enabled=False,  # the operator's deliberate act stays required
                source_type="news",
            )
        )
    cand.status = "promoted"
    db.commit()
    return {
        "promoted": cand.domain,
        "enabled": False,
        "note": "Created disabled -- review and enable it in the source list.",
    }


@router.post("/candidates/{candidate_id}/dismiss", response_model=dict)
@limiter.limit("100/hour")
async def dismiss_source_candidate(
    request: Request, candidate_id: int, db: Session = Depends(get_db)
):
    """Dismiss a candidate (remembered; the channels never re-suggest it)."""
    from src.database.models import SourceCandidate

    cand = db.query(SourceCandidate).filter_by(id=candidate_id).first()
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    cand.status = "dismissed"
    db.commit()
    return {"dismissed": cand.domain}


@router.post("/preflight", response_model=dict)
@limiter.limit("10/hour")
async def run_source_preflight(
    request: Request, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)
):
    """Test enabled sources NOW (reachability + robots.txt) and update their
    scraper settings. Appends every verdict to data/source_preflight.jsonl --
    hand that file back when reporting source issues."""
    from src.monitoring.preflight import preflight_sources

    summary = preflight_sources(db, limit=limit)
    db.commit()
    return summary


@router.get("/unmanaged-languages", response_model=dict)
async def unmanaged_language_sources(db: Session = Depends(get_db)):
    """How many ENABLED sources publish in a language the keyword engine cannot yet
    manage (no stoplist, or unsegmented like zh/ja). These pollute analytics with
    function-word junk and inflate the corpus. Read-only: counts + per-language
    breakdown, plus the managed-language list for transparency. The operator
    decides whether to disable them (POST /disable-unmanaged-languages)."""
    from src.analytics.managed import MANAGED_LANGUAGES, is_unmanaged, normalize_lang
    from src.database.models import Source

    by_language: dict[str, int] = {}
    for (lang,) in db.query(Source.language).filter(Source.enabled.is_(True)).all():
        if is_unmanaged(lang):
            code = normalize_lang(lang)
            by_language[code] = by_language.get(code, 0) + 1
    return {
        "enabled_unmanaged": sum(by_language.values()),
        "by_language": dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        "managed_languages": sorted(MANAGED_LANGUAGES),
        "method": (
            "Enabled sources whose language has no stoplist or is unsegmented (zh/ja) — "
            "the keyword engine cannot analyse them yet, so scraping them adds junk. "
            "Kept and re-enablable; disabling is the operator's choice."
        ),
    }


@router.post("/disable-unmanaged-languages", response_model=dict)
async def disable_unmanaged_language_sources(db: Session = Depends(get_db)):
    """DISABLE (never delete) every enabled source in an unmanaged language so the
    app stops accumulating un-analysable junk. Reversible: the sources stay in the
    catalogue, filterable, and re-enablable once a stoplist for their language lands.
    Returns the count + per-language breakdown of what was disabled."""
    from src.analytics.managed import is_unmanaged, normalize_lang
    from src.database.models import Source

    by_language: dict[str, int] = {}
    for src in db.query(Source).filter(Source.enabled.is_(True)).all():
        if is_unmanaged(src.language):
            src.enabled = False
            code = normalize_lang(src.language)
            by_language[code] = by_language.get(code, 0) + 1
    db.commit()
    return {
        "disabled": sum(by_language.values()),
        "by_language": dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        "note": "Sources kept and re-enablable; re-enable them when their language gains a stoplist.",
    }


@router.post("/promote-cited", response_model=dict)
@limiter.limit("30/hour")
async def promote_cited_sources_endpoint(
    request: Request,
    min_source_citers: int | None = Query(None, ge=1, le=100),
    cap: int = Query(200, ge=1, le=2000),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Auto-integrate in-article SECONDARY sources: register a domain cited by enough
    DISTINCT sources as a new DISABLED ``cited`` source (metadata only -- never fetched
    until you enable it). Independence is measured by distinct SOURCES, not article
    count; commerce/social storefronts are excluded and existing outlets are alias-
    deduped. ``cited`` is a DESCRIPTIVE provenance class, never a quality score.
    ``dry_run=true`` previews the candidates without creating anything.
    """
    from src.discovery.cited_sources import promote_cited_sources

    result = promote_cited_sources(db, min_source_citers=min_source_citers, cap=cap, dry_run=dry_run)
    if not dry_run:
        db.commit()
    return result


@router.get("/preflight/log", response_model=dict)
@limiter.limit("100/hour")
async def source_preflight_log(request: Request, limit: int = Query(200, ge=1, le=1000)):
    """Latest preflight verdict per domain (newest first), from the JSONL log."""
    from src.monitoring.preflight import recent_results

    rows = recent_results(limit=limit)
    return {"count": len(rows), "results": rows}


# ==================== SOURCE ENDPOINTS ====================


@router.get("/", response_model=list[dict])
@limiter.limit("100/hour")
async def list_sources(
    request: Request,
    enabled: bool | None = None,
    priority: int | None = None,
    tags: str | None = None,
    tag_mode: str = "any",
    languages: str | None = None,
    countries: str | None = None,
    types: str | None = None,
    q: str | None = None,
    group_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    List all sources with optional filters.

    Multi-select filters (field test 2026-06-22, #23): ``languages``/``countries``/
    ``types``/``tags`` are comma-separated. Semantics are EXPLICIT — WITHIN a filter
    the values are OR'd (French OR English), ACROSS filters they are AND'd (French/
    English AND tagged news). ``tag_mode`` toggles tags between ``any`` (OR, default)
    and ``all`` (AND — a source must carry every selected tag). ``q`` is a free-text
    substring over name/domain. Filtering happens in SQL BEFORE pagination (so a filter
    spans the whole catalogue, not just the first page).

    Parameters:
    - enabled: Filter by enabled status
    - priority: Filter by priority level
    - tags / tag_mode: tags (comma-separated) with any|all combination
    - languages / countries / types: comma-separated, OR within each
    - q: free-text name/domain substring
    - group_id: Filter by group ID
    - limit / offset: pagination
    """
    logger.info(
        "List sources: enabled=%s tags=%s langs=%s countries=%s types=%s q=%s",
        enabled, tags, languages, countries, types, q,
    )

    from sqlalchemy import and_, or_

    from src.database.models import Source

    def _vals(raw: str | None) -> list[str]:
        return [v.strip() for v in (raw or "").split(",") if v.strip()]

    with SourceManager(session=db) as manager:
        if group_id:
            # Legacy group filter keeps its existing path (in-memory, group sizes are small).
            sources = manager.get_sources_by_group(group_id)
            if enabled is not None:
                sources = [s for s in sources if s.enabled == enabled]
            if priority is not None:
                sources = [s for s in sources if s.priority == priority]
        else:
            query = db.query(Source)
            if enabled is not None:
                query = query.filter(Source.enabled.is_(enabled))
            if priority is not None:
                query = query.filter(Source.priority == priority)
            langs, ctrys, tps = _vals(languages), _vals(countries), _vals(types)
            if langs:
                query = query.filter(Source.language.in_(langs))          # OR within
            if ctrys:
                query = query.filter(Source.country.in_(ctrys))           # OR within
            if tps:
                query = query.filter(Source.source_type.in_(tps))         # OR within
            tag_list = _vals(tags)
            if tag_list:
                conds = [Source.tags.ilike(f"%{t}%") for t in tag_list]
                query = query.filter(and_(*conds) if tag_mode == "all" else or_(*conds))
            if q:
                like = f"%{q.strip()}%"
                query = query.filter(or_(Source.name.ilike(like), Source.domain.ilike(like)))
            query = query.order_by(Source.priority.asc(), Source.id.asc())
            sources = query.offset(offset).limit(limit).all()

        # Format results
        results = [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "rate_limit_ms": s.rate_limit_ms,
                "enabled": s.enabled,
                "priority": s.priority,
                "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
                "article_count": len(s.articles) if s.articles else 0,
                "groups": [g.name for g in s.groups.all()] if s.groups else [],
                "has_metadata": s.source_metadata is not None,
                # Geo/type metadata — powers the batch-ingest source picker's filters.
                "language": s.language,
                "country": s.country,
                "region": s.region,
                "source_type": s.source_type,
            }
            for s in sources
        ]

        return results


@router.get("/facets", response_model=dict)
@limiter.limit("120/hour")
async def source_facets(
    request: Request,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    """Distinct catalog values (with real counts) for the Sources multi-select filters
    (field test 2026-06-22, #23): languages · countries · types · tags. ONE column-
    projected query over the small (~3.2k-row) sources table — never the N+1 article/
    group loads list_sources does — so it is cheap on the encrypted store. Counts only,
    no score. `enabled_only` restricts to the active set (the default shows everything so
    a user can find a disabled source to enable)."""
    from src.database.models import Source

    q = db.query(Source.language, Source.country, Source.source_type, Source.tags)
    if enabled_only:
        q = q.filter(Source.enabled.is_(True))
    lang_n: dict[str, int] = {}
    country_n: dict[str, int] = {}
    type_n: dict[str, int] = {}
    tag_n: dict[str, int] = {}
    for language, country, source_type, tags in q:
        if language:
            lang_n[language] = lang_n.get(language, 0) + 1
        if country:
            country_n[country] = country_n.get(country, 0) + 1
        if source_type:
            type_n[source_type] = type_n.get(source_type, 0) + 1
        for t in (tags or "").split(","):
            t = t.strip()
            if t:
                tag_n[t] = tag_n.get(t, 0) + 1

    def _facet(counts: dict[str, int]) -> list[dict]:
        # Most-common first, then alphabetical — a stable, honest ordering (no score).
        return [{"key": k, "n": n} for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "languages": _facet(lang_n),
        "countries": _facet(country_n),
        "types": _facet(type_n),
        "tags": _facet(tag_n),
        "enabled_only": enabled_only,
    }


@router.get("/{source_id}", response_model=dict)
@limiter.limit("100/hour")
async def get_source(request: Request, source_id: int, db: Session = Depends(get_db)):
    """
    Get a specific source by ID.
    """
    logger.info(f"Get source request: source_id={source_id}")

    with SourceManager(session=db) as manager:
        source = manager.get_source_by_id(source_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source with ID {source_id} not found")

        # Get groups for this source
        groups = manager.get_source_groups(source_id)

        # Get metadata
        metadata = manager.get_metadata(source_id)

        result = {
            "id": source.id,
            "name": source.name,
            "domain": source.domain,
            "rss_url": source.rss_url,
            "rate_limit_ms": source.rate_limit_ms,
            "enabled": source.enabled,
            "priority": source.priority,
            "tags": [t.strip() for t in (source.tags or "").split(",") if t.strip()],
            "article_count": len(source.articles) if source.articles else 0,
            "groups": [
                {"id": g.id, "name": g.name, "color": g.color, "description": g.description}
                for g in groups
            ],
            "metadata": {
                "language": metadata.language if metadata else None,
                "country": metadata.country if metadata else None,
                "region": metadata.region if metadata else None,
                "city": metadata.city if metadata else None,
                "timezone": metadata.timezone if metadata else None,
                "robots_allowed": metadata.robots_allowed if metadata else True,
                "crawl_delay": metadata.crawl_delay if metadata else None,
                "robots_txt_url": metadata.robots_txt_url if metadata else None,
                "sitemap_url": metadata.sitemap_url if metadata else None,
                "favicon_url": metadata.favicon_url if metadata else None,
                "logo_url": metadata.logo_url if metadata else None,
                "contact_email": metadata.contact_email if metadata else None,
                "social_twitter": metadata.social_twitter if metadata else None,
                "social_facebook": metadata.social_facebook if metadata else None,
                "social_linkedin": metadata.social_linkedin if metadata else None,
                "alexa_rank": metadata.alexa_rank if metadata else None,
                "notes": metadata.notes if metadata else None,
            },
        }

        return result


@router.get("/{source_id}/observed-ips", response_model=dict)
@limiter.limit("100/hour")
async def get_source_observed_ips(request: Request, source_id: int, db: Session = Depends(get_db)):
    """Per-source aggregated view of the already-captured server IPs (SOURCE IPs
    ruling, 2026-07-20, ask 2): distinct observed IPs + first/last seen + each IP's
    geolocated country. An aggregation over the existing ``Article.server_ip`` /
    ``ip_observed_at`` columns -- no new capture. A source legitimately carries
    MULTIPLE IPs over time (CDN edges, rotation); the caveat travels with the data.
    """
    from src.analytics.queries import source_observed_ips

    with SourceManager(session=db) as manager:
        source = manager.get_source_by_id(source_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source with ID {source_id} not found")

    return source_observed_ips(db, source_id)


@router.post("/", response_model=dict)
@limiter.limit("50/hour")
async def create_source(request: Request, source_data: dict, db: Session = Depends(get_db)):
    """
    Create a new source.
    """
    logger.info(f"Create source request: {source_data}")

    required_fields = ["name", "domain"]
    for field in required_fields:
        if field not in source_data:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        # Reject blank/whitespace-only values, which would otherwise create a junk
        # source (e.g. an empty domain). Keep the existing 400 status for consistency.
        if not isinstance(source_data[field], str) or not source_data[field].strip():
            raise HTTPException(
                status_code=400, detail=f"Field '{field}' must be a non-empty string"
            )

    with SourceManager(session=db) as manager:
        source = manager.create_source(
            name=source_data["name"],
            domain=source_data["domain"],
            rss_url=source_data.get("rss_url"),
            rate_limit_ms=source_data.get("rate_limit_ms", 2000),
            enabled=source_data.get("enabled", True),
            priority=source_data.get("priority", 2),
            tags=source_data.get("tags", ""),
        )

        return {
            "id": source.id,
            "name": source.name,
            "domain": source.domain,
            "message": "Source created successfully",
        }


@router.put("/{source_id}", response_model=dict)
@limiter.limit("50/hour")
async def update_source(
    request: Request, source_id: int, source_data: dict, db: Session = Depends(get_db)
):
    """
    Update a source.
    """
    logger.info(f"Update source request: source_id={source_id}, data={source_data}")

    with SourceManager(session=db) as manager:
        source = manager.update_source(source_id, **source_data)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source with ID {source_id} not found")

        return {
            "id": source.id,
            "name": source.name,
            "domain": source.domain,
            "message": "Source updated successfully",
        }


@router.delete("/{source_id}", response_model=dict)
@limiter.limit("20/hour")
async def delete_source(request: Request, source_id: int, db: Session = Depends(get_db)):
    """
    Delete a source.
    """
    logger.info(f"Delete source request: source_id={source_id}")

    with SourceManager(session=db) as manager:
        success = manager.delete_source(source_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Source with ID {source_id} not found")

        return {"message": f"Source {source_id} deleted successfully"}


# ==================== BATCH SOURCE OPERATIONS ====================


@router.post("/batch/enable", response_model=dict)
@limiter.limit("50/hour")
async def batch_enable_sources(
    request: Request, source_ids: list[int], db: Session = Depends(get_db)
):
    """
    Enable multiple sources.
    """
    logger.info(f"Batch enable sources: {source_ids}")

    with SourceManager(session=db) as manager:
        count = manager.enable_sources(source_ids)
        return {"message": f"Enabled {count} sources"}


@router.post("/batch/disable", response_model=dict)
@limiter.limit("50/hour")
async def batch_disable_sources(
    request: Request, source_ids: list[int], db: Session = Depends(get_db)
):
    """
    Disable multiple sources.
    """
    logger.info(f"Batch disable sources: {source_ids}")

    with SourceManager(session=db) as manager:
        count = manager.disable_sources(source_ids)
        return {"message": f"Disabled {count} sources"}


@router.post("/batch/priority", response_model=dict)
@limiter.limit("50/hour")
async def batch_set_priority(
    request: Request,
    source_ids: list[int],
    priority: int = Query(..., ge=1, le=3),
    db: Session = Depends(get_db),
):
    """
    Set priority for multiple sources.
    """
    logger.info(f"Batch set priority: {source_ids} to {priority}")

    with SourceManager(session=db) as manager:
        count = manager.set_source_priority(source_ids, priority)
        return {"message": f"Set priority {priority} for {count} sources"}


@router.post("/batch/rate-limit", response_model=dict)
@limiter.limit("50/hour")
async def batch_set_rate_limit(
    request: Request,
    source_ids: list[int],
    rate_limit_ms: int = Query(..., ge=100, le=60000),
    db: Session = Depends(get_db),
):
    """
    Set rate limit for multiple sources.
    """
    logger.info(f"Batch set rate limit: {source_ids} to {rate_limit_ms}ms")

    with SourceManager(session=db) as manager:
        count = manager.set_source_rate_limit(source_ids, rate_limit_ms)
        return {"message": f"Set rate limit {rate_limit_ms}ms for {count} sources"}


@router.post("/batch/tags/add", response_model=dict)
@limiter.limit("50/hour")
async def batch_add_tags(
    request: Request, source_ids: list[int], tags: list[str], db: Session = Depends(get_db)
):
    """
    Add tags to multiple sources.
    """
    logger.info(f"Batch add tags: {tags} to {source_ids}")

    with SourceManager(session=db) as manager:
        count = manager.add_tags_to_sources(source_ids, tags)
        return {"message": f"Added tags {tags} to {count} sources"}


@router.post("/batch/tags/remove", response_model=dict)
@limiter.limit("50/hour")
async def batch_remove_tags(
    request: Request, source_ids: list[int], tags: list[str], db: Session = Depends(get_db)
):
    """
    Remove tags from multiple sources.
    """
    logger.info(f"Batch remove tags: {tags} from {source_ids}")

    with SourceManager(session=db) as manager:
        count = manager.remove_tags_from_sources(source_ids, tags)
        return {"message": f"Removed tags {tags} from {count} sources"}


# ==================== GROUP ENDPOINTS ====================


@router.get("/groups/", response_model=list[dict])
@limiter.limit("100/hour")
async def list_groups(
    request: Request, tag_based: bool | None = None, db: Session = Depends(get_db)
):
    """
    List all source groups.
    """
    logger.info(f"List groups request: tag_based={tag_based}")

    with SourceManager(session=db) as manager:
        groups = manager.get_all_groups()

        if tag_based is not None:
            groups = [g for g in groups if g.is_tag_based == tag_based]

        results = [
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "color": g.color,
                "is_tag_based": g.is_tag_based,
                "tag_pattern": g.tag_pattern,
                "priority": g.priority,
                "rate_limit_ms": g.rate_limit_ms,
                "enabled": g.enabled,
                "source_count": len(g.sources.all()) if g.sources else 0,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            }
            for g in groups
        ]

        return results


@router.get("/groups/{group_id}", response_model=dict)
@limiter.limit("100/hour")
async def get_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    """
    Get a specific group by ID.
    """
    logger.info(f"Get group request: group_id={group_id}")

    with SourceManager(session=db) as manager:
        group = manager.get_group_by_id(group_id)
        if not group:
            raise HTTPException(status_code=404, detail=f"Group with ID {group_id} not found")

        sources = group.sources.all() if group.sources else []

        result = {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "color": group.color,
            "is_tag_based": group.is_tag_based,
            "tag_pattern": group.tag_pattern,
            "priority": group.priority,
            "rate_limit_ms": group.rate_limit_ms,
            "enabled": group.enabled,
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "domain": s.domain,
                    "rss_url": s.rss_url,
                    "enabled": s.enabled,
                    "priority": s.priority,
                    "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
                }
                for s in sources
            ],
            "source_count": len(sources),
            "created_at": group.created_at.isoformat() if group.created_at else None,
            "updated_at": group.updated_at.isoformat() if group.updated_at else None,
        }

        return result


@router.post("/groups/", response_model=dict)
@limiter.limit("50/hour")
async def create_group(request: Request, group_data: dict, db: Session = Depends(get_db)):
    """
    Create a new source group.
    """
    logger.info(f"Create group request: {group_data}")

    required_fields = ["name"]
    for field in required_fields:
        if field not in group_data:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    with SourceManager(session=db) as manager:
        group = manager.create_group(
            name=group_data["name"],
            description=group_data.get("description", ""),
            color=group_data.get("color", "#666666"),
            is_tag_based=group_data.get("is_tag_based", False),
            tag_pattern=group_data.get("tag_pattern", ""),
            priority=group_data.get("priority", 2),
            rate_limit_ms=group_data.get("rate_limit_ms", 2000),
            enabled=group_data.get("enabled", True),
        )

        return {"id": group.id, "name": group.name, "message": "Group created successfully"}


@router.put("/groups/{group_id}", response_model=dict)
@limiter.limit("50/hour")
async def update_group(
    request: Request, group_id: int, group_data: dict, db: Session = Depends(get_db)
):
    """
    Update a source group.
    """
    logger.info(f"Update group request: group_id={group_id}, data={group_data}")

    with SourceManager(session=db) as manager:
        group = manager.update_group(group_id, **group_data)
        if not group:
            raise HTTPException(status_code=404, detail=f"Group with ID {group_id} not found")

        return {"id": group.id, "name": group.name, "message": "Group updated successfully"}


@router.delete("/groups/{group_id}", response_model=dict)
@limiter.limit("20/hour")
async def delete_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    """
    Delete a source group.
    """
    logger.info(f"Delete group request: group_id={group_id}")

    with SourceManager(session=db) as manager:
        success = manager.delete_group(group_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Group with ID {group_id} not found")

        return {"message": f"Group {group_id} deleted successfully"}


# ==================== GROUP-SOURCE ASSOCIATION ENDPOINTS ====================


@router.post("/groups/{group_id}/sources", response_model=dict)
@limiter.limit("50/hour")
async def add_sources_to_group(
    request: Request, group_id: int, source_ids: list[int], db: Session = Depends(get_db)
):
    """
    Add sources to a group.
    """
    logger.info(f"Add sources to group: {source_ids} to group {group_id}")

    with SourceManager(session=db) as manager:
        count = manager.add_sources_to_group(group_id, source_ids)
        return {"message": f"Added {count} sources to group {group_id}"}


@router.delete("/groups/{group_id}/sources", response_model=dict)
@limiter.limit("50/hour")
async def remove_sources_from_group(
    request: Request, group_id: int, source_ids: list[int], db: Session = Depends(get_db)
):
    """
    Remove sources from a group.
    """
    logger.info(f"Remove sources from group: {source_ids} from group {group_id}")

    with SourceManager(session=db) as manager:
        count = manager.remove_sources_from_group(group_id, source_ids)
        return {"message": f"Removed {count} sources from group {group_id}"}


@router.post("/{source_id}/groups", response_model=dict)
@limiter.limit("50/hour")
async def add_source_to_groups(
    request: Request, source_id: int, group_ids: list[int], db: Session = Depends(get_db)
):
    """
    Add a source to multiple groups.
    """
    logger.info(f"Add source to groups: source {source_id} to groups {group_ids}")

    with SourceManager(session=db) as manager:
        count = manager.add_source_to_groups(source_id, group_ids)
        return {"message": f"Added source {source_id} to {count} groups"}


@router.delete("/{source_id}/groups", response_model=dict)
@limiter.limit("50/hour")
async def remove_source_from_groups(
    request: Request, source_id: int, group_ids: list[int], db: Session = Depends(get_db)
):
    """
    Remove a source from multiple groups.
    """
    logger.info(f"Remove source from groups: source {source_id} from groups {group_ids}")

    with SourceManager(session=db) as manager:
        count = manager.remove_source_from_groups(source_id, group_ids)
        return {"message": f"Removed source {source_id} from {count} groups"}


# ==================== TAG-BASED GROUP ENDPOINTS ====================


@router.post("/groups/tag-based", response_model=dict)
@limiter.limit("50/hour")
async def create_tag_based_group(
    request: Request, name: str, tag_pattern: str, db: Session = Depends(get_db)
):
    """
    Create a tag-based group.
    """
    logger.info(f"Create tag-based group: {name} with pattern {tag_pattern}")

    with SourceManager(session=db) as manager:
        group = manager.create_tag_based_group(name, tag_pattern)
        return {
            "id": group.id,
            "name": group.name,
            "tag_pattern": group.tag_pattern,
            "message": "Tag-based group created successfully",
        }


@router.post("/groups/{group_id}/refresh", response_model=dict)
@limiter.limit("20/hour")
async def refresh_tag_based_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    """
    Refresh a tag-based group to update its source membership.
    """
    logger.info(f"Refresh tag-based group: {group_id}")

    with SourceManager(session=db) as manager:
        # First get the group to get its tag_pattern
        group = manager.get_group_by_id(group_id)
        if not group:
            raise HTTPException(status_code=404, detail=f"Group with ID {group_id} not found")

        # Update the tag-based group
        updated_group = manager.update_tag_based_group(
            group_id, group.tag_pattern if hasattr(group, "tag_pattern") else ""
        )
        if not updated_group:
            raise HTTPException(status_code=404, detail=f"Failed to refresh group {group_id}")

        return {"message": f"Refreshed tag-based group {group_id}"}


@router.post("/groups/refresh-all", response_model=dict)
@limiter.limit("10/hour")
async def refresh_all_tag_based_groups(request: Request, db: Session = Depends(get_db)):
    """
    Refresh all tag-based groups.
    """
    logger.info("Refresh all tag-based groups")

    with SourceManager(session=db) as manager:
        count = manager.refresh_tag_based_groups()
        return {"message": f"Refreshed {count} tag-based groups"}


# ==================== METADATA ENDPOINTS ====================


@router.get("/{source_id}/metadata", response_model=dict)
@limiter.limit("100/hour")
async def get_metadata(request: Request, source_id: int, db: Session = Depends(get_db)):
    """
    Get metadata for a source.
    """
    logger.info(f"Get metadata request: source_id={source_id}")

    with SourceManager(session=db) as manager:
        metadata = manager.get_metadata(source_id)
        if not metadata:
            raise HTTPException(
                status_code=404, detail=f"Metadata for source {source_id} not found"
            )

        return {
            "source_id": metadata.source_id,
            "language": metadata.language,
            "country": metadata.country,
            "region": metadata.region,
            "city": metadata.city,
            "timezone": metadata.timezone,
            "robots_txt_url": metadata.robots_txt_url,
            "robots_allowed": metadata.robots_allowed,
            "crawl_delay": metadata.crawl_delay,
            "sitemap_url": metadata.sitemap_url,
            "favicon_url": metadata.favicon_url,
            "logo_url": metadata.logo_url,
            "contact_email": metadata.contact_email,
            "social_twitter": metadata.social_twitter,
            "social_facebook": metadata.social_facebook,
            "social_linkedin": metadata.social_linkedin,
            "alexa_rank": metadata.alexa_rank,
            "last_checked": metadata.last_checked.isoformat() if metadata.last_checked else None,
            "notes": metadata.notes,
        }


@router.post("/{source_id}/metadata", response_model=dict)
@limiter.limit("50/hour")
async def create_metadata(
    request: Request, source_id: int, metadata_data: dict, db: Session = Depends(get_db)
):
    """
    Create metadata for a source.
    """
    logger.info(f"Create metadata request: source_id={source_id}, data={metadata_data}")

    with SourceManager(session=db) as manager:
        metadata = manager.create_metadata(source_id, **metadata_data)
        return {"source_id": metadata.source_id, "message": "Metadata created successfully"}


@router.put("/{source_id}/metadata", response_model=dict)
@limiter.limit("50/hour")
async def update_metadata(
    request: Request, source_id: int, metadata_data: dict, db: Session = Depends(get_db)
):
    """
    Update metadata for a source.
    """
    logger.info(f"Update metadata request: source_id={source_id}, data={metadata_data}")

    with SourceManager(session=db) as manager:
        metadata = manager.update_metadata(source_id, **metadata_data)
        if not metadata:
            raise HTTPException(
                status_code=404, detail=f"Metadata for source {source_id} not found"
            )

        return {"source_id": metadata.source_id, "message": "Metadata updated successfully"}


@router.delete("/{source_id}/metadata", response_model=dict)
@limiter.limit("20/hour")
async def delete_metadata(request: Request, source_id: int, db: Session = Depends(get_db)):
    """
    Delete metadata for a source.
    """
    logger.info(f"Delete metadata request: source_id={source_id}")

    with SourceManager(session=db) as manager:
        success = manager.delete_metadata(source_id)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"Metadata for source {source_id} not found"
            )

        return {"message": f"Metadata for source {source_id} deleted successfully"}


# ==================== BATCH GROUP OPERATIONS ====================


@router.post("/groups/batch/enable", response_model=dict)
@limiter.limit("50/hour")
async def batch_enable_groups(
    request: Request, group_ids: list[int], db: Session = Depends(get_db)
):
    """
    Enable all sources in multiple groups.
    """
    logger.info(f"Batch enable groups: {group_ids}")

    with SourceManager(session=db) as manager:
        count = manager.enable_groups(group_ids)
        return {"message": f"Enabled {count} sources in {len(group_ids)} groups"}


@router.post("/groups/batch/disable", response_model=dict)
@limiter.limit("50/hour")
async def batch_disable_groups(
    request: Request, group_ids: list[int], db: Session = Depends(get_db)
):
    """
    Disable all sources in multiple groups.
    """
    logger.info(f"Batch disable groups: {group_ids}")

    with SourceManager(session=db) as manager:
        count = manager.disable_groups(group_ids)
        return {"message": f"Disabled {count} sources in {len(group_ids)} groups"}


@router.post("/groups/batch/priority", response_model=dict)
@limiter.limit("50/hour")
async def batch_set_group_priority(
    request: Request,
    group_ids: list[int],
    priority: int = Query(..., ge=1, le=3),
    db: Session = Depends(get_db),
):
    """
    Set priority for all sources in multiple groups.
    """
    logger.info(f"Batch set group priority: {group_ids} to {priority}")

    with SourceManager(session=db) as manager:
        count = manager.set_group_priority(group_ids, priority)
        return {
            "message": f"Set priority {priority} for {count} sources in {len(group_ids)} groups"
        }


@router.post("/groups/batch/rate-limit", response_model=dict)
@limiter.limit("50/hour")
async def batch_set_group_rate_limit(
    request: Request,
    group_ids: list[int],
    rate_limit_ms: int = Query(..., ge=100, le=60000),
    db: Session = Depends(get_db),
):
    """
    Set rate limit for all sources in multiple groups.
    """
    logger.info(f"Batch set group rate limit: {group_ids} to {rate_limit_ms}ms")

    with SourceManager(session=db) as manager:
        count = manager.set_group_rate_limit(group_ids, rate_limit_ms)
        return {
            "message": f"Set rate limit {rate_limit_ms}ms for {count} sources in {len(group_ids)} groups"
        }


# ==================== SOURCE DISCOVERY ENDPOINTS ====================


@router.post("/discover/rss", response_model=dict)
@limiter.limit("20/hour")
async def discover_rss_feeds(
    request: Request,
    source_ids: list[int] | None = None,
    timeout: int = 10,
    db: Session = Depends(get_db),
):
    """
    Discover RSS feeds for sources that don't have them.

    Parameters:
    - source_ids: Optional list of source IDs to check. If None, checks all sources without RSS URLs.
    - timeout: Request timeout in seconds
    """
    logger.info(f"Discover RSS feeds request: source_ids={source_ids}")

    with SourceManager(session=db) as manager:
        results = manager.discover_rss_feeds(source_ids, timeout=timeout)

        # Count how many got RSS feeds
        with_rss = len([r for r in results if r.get("rss_url")])

        return {
            "total_checked": len(results),
            "with_rss_found": with_rss,
            "results": results,
            "message": f"Discovered RSS feeds for {with_rss} sources",
        }


@router.post("/discover/topic", response_model=dict)
@limiter.limit("20/hour")
async def discover_sources_by_topic(
    request: Request,
    topic: str,
    max_sources: int = 20,
    region: str = "wt-wt",
    db: Session = Depends(get_db),
):
    """
    Discover new sources for a specific topic.

    This is the ONE feature that contacts an external service (DuckDuckGo) —
    the topic query leaves the machine. Gated OFF by default behind
    Settings → Safety → "External topic discovery" (audit finding ETH-02 /
    roadmap RM-03); refuses honestly when disabled.

    Parameters:
    - topic: The topic to search for
    - max_sources: Maximum number of sources to return
    - region: Region code for localized results
    """
    from src.safety.settings import load_settings as load_safety_settings

    if not load_safety_settings().discovery_external_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "External topic discovery is disabled (the default). It sends your "
                "topic query to DuckDuckGo, an external service. Enable it knowingly "
                "in Settings → Safety → External topic discovery."
            ),
        )

    logger.info(f"Discover sources by topic: {topic}")

    with SourceManager(session=db) as manager:
        sources = manager.discover_sources_by_topic(topic, max_sources, region=region)

        return {
            "topic": topic,
            "max_sources": max_sources,
            "region": region,
            "sources": sources,
            "count": len(sources),
            "message": f"Discovered {len(sources)} sources for topic '{topic}'",
        }


@router.post("/discover/add", response_model=dict)
@limiter.limit("20/hour")
async def add_discovered_sources(
    request: Request,
    sources: list[dict],
    group_name: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Add discovered sources to the database.

    Parameters:
    - sources: List of discovered source dictionaries
    - group_name: Optional group name to add sources to
    """
    logger.info(f"Add discovered sources: {len(sources)} sources, group={group_name}")

    with SourceManager(session=db) as manager:
        created_sources = manager.add_discovered_sources(sources, group_name)

        return {
            "added": len(created_sources),
            "group_name": group_name,
            "sources": [
                {"id": s.id, "name": s.name, "domain": s.domain, "rss_url": s.rss_url}
                for s in created_sources
            ],
            "message": f"Added {len(created_sources)} discovered sources",
        }


# ==================== IMPORT/EXPORT ENDPOINTS ====================


@router.post("/import", response_model=dict)
@limiter.limit("10/hour")
async def import_sources(request: Request, db: Session = Depends(get_db)):
    """
    Import sources from YAML configuration.
    """
    logger.info("Import sources from YAML")

    # For now, use the existing sources.yml file
    yaml_path = Path(__file__).parent.parent.parent.parent / "configs" / "sources.yml"

    with SourceManager(session=db) as manager:
        result = manager.import_sources_from_yaml(str(yaml_path))

        return {
            "added": result["added"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "message": f"Imported {result['added']} sources, updated {result['updated']}, skipped {result['skipped']}",
        }


@router.get("/export", response_model=dict)
@limiter.limit("10/hour")
async def export_sources(
    request: Request, group_id: int | None = None, db: Session = Depends(get_db)
):
    """
    Export sources to YAML format.

    Parameters:
    - group_id: Optional group ID to export only sources from that group
    """
    logger.info(f"Export sources: group_id={group_id}")

    with SourceManager(session=db) as manager:
        # For now, return the data as JSON (YAML export would be a file download)
        if group_id:
            sources = manager.get_sources_by_group(group_id)
        else:
            sources = manager.get_all_sources()

        sources_data = [
            {
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "rate_limit_ms": s.rate_limit_ms,
                "enabled": s.enabled,
                "priority": s.priority,
                "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
            }
            for s in sources
        ]

        return {
            "project_name": "OpenOmniscience",
            "description": "Global Intelligence Platform for Investigative Journalism",
            "version": "0.2.0",
            "date_created": datetime.now().isoformat(),
            "sources": sources_data,
            "count": len(sources_data),
        }


# ==================== STATISTICS ENDPOINTS ====================


@router.get("/stats", response_model=dict)
@limiter.limit("100/hour")
async def get_source_statistics(request: Request, db: Session = Depends(get_db)):
    """
    Get statistics about sources, groups, and metadata.
    """
    logger.info("Get source statistics")

    with SourceManager(session=db) as manager:
        stats = manager.get_source_statistics()

        return {
            "sources": {
                "total": stats["total_sources"],
                "enabled": stats["enabled_sources"],
                "disabled": stats["disabled_sources"],
                "priority_distribution": stats["priority_counts"],
                "tag_counts": stats["tag_counts"],
                "with_rss": stats["with_rss"],
                "without_rss": stats["without_rss"],
            },
            "groups": {"total": stats["total_groups"], "tag_based": stats["tag_based_groups"]},
            "metadata": {
                "with_metadata": stats["with_metadata"],
                "with_country": stats["with_country"],
                "with_language": stats["with_language"],
            },
        }


# ==================== SEARCH AND DISCOVERY ENDPOINTS ====================


@router.get("/search", response_model=dict)
@limiter.limit("50/hour")
async def search_sources(
    request: Request, query: str, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)
):
    """
    Search for sources by name, domain, or tags.

    Parameters:
    - query: Search query (matches against name, domain, and tags)
    - limit: Maximum number of results
    - offset: Offset for pagination
    """
    logger.info(f"Search sources: query={query}")

    with SourceManager(session=db) as manager:
        # Search by name, domain, or tags
        query_lower = query.lower()

        # Get all sources and filter in memory (for simplicity)
        all_sources = manager.get_all_sources()

        results = []
        for source in all_sources:
            if (
                query_lower in source.name.lower()
                or query_lower in source.domain.lower()
                or (source.tags and query_lower in source.tags.lower())
            ):
                results.append(source)

        # Apply pagination
        results = results[offset : offset + limit]

        formatted_results = [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "enabled": s.enabled,
                "priority": s.priority,
                "tags": [t.strip() for t in (s.tags or "").split(",") if t.strip()],
            }
            for s in results
        ]

        return {
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results),
            "total": len(results),
        }
