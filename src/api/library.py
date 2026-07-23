"""
Library overview API: the central dashboard of everything DOWNLOADED + EXTRAPOLATED.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field remark 16 (2026-06-24): the Library tab is the at-a-glance view of the whole
local corpus AND its derived layers. This endpoint rolls up, in ONE cached call,
honest COUNTS and on-disk byte SIZES only -- never a score:

  - the RAW/downloaded layer: Wikipedia (tracked pages + revisions, downloaded
    dumps), offline maps (OSM regions), market series, law documents + revisions,
    official statistics, plus the corpus core (articles / sources / keywords);
  - the DERIVED/extrapolated layer: AI summaries / translations / synthesis
    (article_analyses by kind) and AI-extracted keywords (ai_keyword by kind) --
    clearly the AI-derived, unreliable layer, NEVER the trusted index.

Every figure is a real ``COUNT(*)`` or a real file byte size. Tables/managers
absent from a build (or an Ollama store that isn't readable) degrade to ``null``
/ an ``available: false`` flag rather than crashing -- so a core-only install
gets an honest, smaller picture. Cached briefly with the change-probe used by the
Database tab; computed_at + cache_ttl_s state the freshness window.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, inspect, select, table
from sqlalchemy.orm import Session

from src.database.session import engine, get_db
from src.utils.cache import SimpleCache

_LOG = logging.getLogger("api.library")
router = APIRouter(prefix="/api/library", tags=["library"])

# The history endpoint's read window is bounded even though storage retention is
# infinite (2026-07-23 field feedback: "I would prefer infinite retention" for
# STORAGE — a response is still a query-time concern). Defaults match the
# maintainer's own ask ("articles/hour past 7 days"); the counter-evolution
# graphs default to a longer, still-bounded window.
_HISTORY_DEFAULT_DAYS = 30
_HISTORY_MAX_DAYS = 3650  # ~10 years — generous, never literally unbounded

_CACHE_TTL_S = 30
_cache = SimpleCache(max_size=4, default_ttl=_CACHE_TTL_S)


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


def _downloads_done(get_manager) -> dict:
    """Count + total bytes of FINISHED downloads from a download manager (wiki dumps
    or OSM regions). Best-effort: a manager that isn't ready degrades to unavailable,
    never breaking the dashboard. Only ``status == "done"`` entries are counted (an
    in-flight download is not a stored artifact)."""
    try:
        done = [e for e in get_manager().list() if (e or {}).get("status") == "done"]
        return {
            "count": len(done),
            "total_bytes": sum(int((e.get("total_bytes") or 0)) for e in done),
        }
    except Exception:  # noqa: BLE001 - a missing/uninitialised manager must not break the view
        return {"count": 0, "total_bytes": 0, "available": False}


@router.get("/overview")
def library_overview(db: Session = Depends(get_db)) -> dict:
    """One cached roll-up of everything downloaded + extrapolated (counts + sizes only)."""

    def _compute() -> dict:
        present = set(inspect(engine).get_table_names())

        def _count(tbl: str) -> int | None:
            if tbl not in present:
                return None
            # COUNT(*) over a table named from our own fixed strings (never user input).
            return int(db.execute(select(func.count()).select_from(table(tbl))).scalar() or 0)

        def _by_kind(model, tbl: str) -> dict:
            if tbl not in present:
                return {}
            rows = db.query(model.kind, func.count()).group_by(model.kind).all()
            out: dict[str, int] = {}
            for k, n in rows:
                out[(k or "").strip() or "unknown"] = out.get((k or "").strip() or "unknown", 0) + int(n or 0)
            return out

        from src.database.models import AiKeyword, ArticleAnalysis, Watch

        # Reuse the Database tab's CACHED core counts + file size (no duplicate scans).
        from src.api.database import database_stats

        core = database_stats(db)
        counts = core.get("counts", {})

        analyses = _by_kind(ArticleAnalysis, "article_analyses")
        ai_kw = _by_kind(AiKeyword, "ai_keyword")

        watches_enabled = None
        if "watches" in present:
            watches_enabled = int(
                db.query(func.count(Watch.id)).filter(Watch.enabled.is_(True)).scalar() or 0
            )

        from src.geo.osm_downloads import get_manager as osm_manager
        from src.wiki.dumps import get_manager as wiki_dumps_manager

        ollama = {"count": 0, "total_bytes": 0}
        try:
            from src.backup.ollama_models import store_status

            st = store_status()
            ollama = {
                "count": len(st.get("models") or []),
                "total_bytes": int(st.get("total_bytes") or 0),
            }
        except Exception:  # noqa: BLE001 - an unreadable/absent Ollama store is honest "unavailable"
            ollama = {"count": 0, "total_bytes": 0, "available": False}

        return {
            # the corpus core (real COUNT(*), reused from the cached Database stats).
            "corpus": {
                "articles": counts.get("articles"),
                "sources": counts.get("sources"),
                "keywords": counts.get("keywords"),
            },
            # the RAW / downloaded layers.
            "downloaded": {
                "wikipedia": {
                    "tracked_pages": _count("wiki_pages"),
                    "revisions": _count("wiki_revisions"),
                    "dumps": _downloads_done(wiki_dumps_manager),
                },
                "maps": {"osm_regions": _downloads_done(osm_manager)},
                "markets": {"commodity_prices": counts.get("commodity_prices")},
                "laws": {
                    "documents": _count("law_documents"),
                    "revisions": _count("law_revisions"),
                },
                "statistics": {"figures": _count("stat_figures")},
                "models": ollama,
            },
            # the DERIVED / extrapolated layer (AI-derived, unreliable — NEVER the index).
            "derived": {
                "article_analyses": {"total": sum(analyses.values()), "by_kind": analyses},
                "ai_keywords": {"total": sum(ai_kw.values()), "by_kind": ai_kw},
                "watches_enabled": watches_enabled,
            },
            "database_file": core.get("file"),
        }

    return _cached("overview", _compute, db)


@router.get("/history")
def library_history(metric: str, days: int = _HISTORY_DEFAULT_DAYS, db: Session = Depends(get_db)) -> dict:
    """A bounded time series for one Library-tab counter, for the small evolution
    graphs (2026-07-23 field-feedback S2).

    ``metric="articles_per_hour"`` is DERIVED live from ``Article.created_at`` —
    real history that already existed since ingestion, so it backfills for free
    with no gap. Every other metric (sources / keywords / wiki_pages /
    wiki_revisions / law_documents / law_revisions) is served from the hourly
    snapshot table, which only started recording when this feature shipped —
    ``recording_began_at`` states that honestly rather than implying an empty
    window means nothing happened. ``days`` is clamped to a sane range; storage
    retention is infinite, the RESPONSE window is not.
    """
    from src.database.snapshots import ALL_METRICS, hourly_article_counts, metric_history

    if metric not in ALL_METRICS:
        raise HTTPException(status_code=400, detail=f"unknown metric: {metric}")
    days = max(1, min(int(days), _HISTORY_MAX_DAYS))
    if metric == "articles_per_hour":
        series = hourly_article_counts(db, days=days)
        return {"metric": metric, "series": series, "recording_began_at": None, "days": days}
    out = metric_history(db, metric=metric, days=days)
    out["days"] = days
    return out
