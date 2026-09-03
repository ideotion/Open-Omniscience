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

from src.api import served_cache
from src.database.session import engine, get_db

router = APIRouter(prefix="/api/database", tags=["database"])

# Count aggregations are full table scans in SQLite, and the Library storage view
# polls this endpoint every 4 s (Home every 15 s). They are served through
# :mod:`src.api.served_cache`: the last real counts are returned immediately with
# a visible as_of, and a recompute runs in the BACKGROUND. A poll never pays the
# scan.
#
# This REPLACES a cache keyed on (PRAGMA data_version, total_changes()) that was
# described as verified and, measured through these very functions, had a 0% hit
# rate on a pooled engine -- both probe components are per-connection, so every
# poll recomputed inline. served_cache's module docstring carries the numbers and
# the probe that replaced them.
_CACHE_TTL_S = 30


def _cached(key: str, compute, db: Session) -> dict:
    """Serve ``key`` from the shared background-refreshed cache.

    ``compute`` takes the Session to read from rather than closing over the
    request's: the background refresher re-runs the SAME callable on its own
    thread, over its own session, long after this request's session is closed.

    Keys are namespaced per module because the cache dict is process-global and
    shared with the other endpoints that use it -- an unprefixed "overview" or
    "stats" added on either side would silently serve the other's payload.
    """
    return served_cache.cached(f"db:{key}", compute, db, ttl_s=_CACHE_TTL_S)


# Human-facing label -> table name. Counted only if the table is present.
# Deliberately NOT shown (maintainer 2026-06-18): ``article_analyses`` (LLM
# summaries/translations — an internal artifact, not a corpus metric), and
# ``external_sources``/``source_groups`` (both empty, never-wired concepts —
# "external" is redundant since every source IS external, and source GROUPS
# duplicate source TAGS, the mechanism the app actually uses).
_COUNTED_TABLES: dict[str, str] = {
    "articles": "articles",
    "sources": "sources",
    "keywords": "keywords",
    "commodity_prices": "commodity_prices",
    "article_links": "article_links",
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

    ``counts["sources"]`` is the flat table COUNT(*) -- kept for backward
    compatibility -- but it BLENDS actively-collecting sources with disabled
    discovery candidates awaiting review and enabled-but-not-yet-qualified
    sources. ``counts["sources_qualified"]`` (enabled AND status=qualified --
    exactly what ``select_sources`` admits to collection), ``sources_pending``
    (enabled AND status!=qualified) and ``sources_candidates`` (enabled=False)
    are the honest three-class PARTITION (2026-07-23 field-feedback S1.3; a
    first two-class cut did not sum back to the total -- amended after review):
    never show the flat figure alone where it could read as one number
    describing the corpus.
    """

    def _compute(db: Session) -> dict:
        from sqlalchemy import func, select, table, text

        present = set(inspect(engine).get_table_names())

        counts: dict[str, int] = {}
        for label, tbl in _COUNTED_TABLES.items():
            if tbl in present:
                # COUNT(*) over a table named from our own fixed map (never user input).
                counts[label] = int(
                    db.execute(select(func.count()).select_from(table(tbl))).scalar() or 0
                )

        # THREE-CLASS SOURCES SPLIT (2026-07-23 field-feedback S1.3, amended after
        # adversarial review): the flat "sources" COUNT(*) above blends enabled+
        # qualified/actively-collecting sources with disabled discovery/world-catalog
        # CANDIDATES awaiting review — exactly the figure a field export showed as
        # "~50k sources" against a ~5k-article corpus, read as an alarm rather than the
        # discovery funnel working as ruled. A first cut split into only two buckets
        # (qualified vs candidates), but those did NOT sum back to "sources" — an
        # enabled-but-not-yet-qualified source (e.g. a freshly-seeded catalog source
        # awaiting its first pass) was invisible in BOTH buckets. This is the honest
        # PARTITION — the three sum to the flat total by construction:
        #   sources_qualified  = enabled AND status=qualified (== select_sources' own
        #                        admission-gate filter -- what is ACTUALLY collecting)
        #   sources_pending    = enabled AND status!=qualified (awaiting an initial
        #                        judgment, or enabled but disqualified — not collecting
        #                        right now, but not a review-queue candidate either)
        #   sources_candidates = enabled=False (discovered, awaiting qualification review)
        if "sources" in present:
            from src.catalog.qualification import STATUS_QUALIFIED
            from src.database.models import Source

            counts["sources_qualified"] = int(
                db.query(func.count(Source.id))
                .filter(Source.enabled.is_(True), Source.status == STATUS_QUALIFIED)
                .scalar()
                or 0
            )
            counts["sources_pending"] = int(
                db.query(func.count(Source.id))
                .filter(Source.enabled.is_(True), Source.status != STATUS_QUALIFIED)
                .scalar()
                or 0
            )
            counts["sources_candidates"] = int(
                db.query(func.count(Source.id)).filter(Source.enabled.is_(False)).scalar() or 0
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


# The Library figures get their OWN longer interval: the single full
# keyword_mentions COUNT measured 43 s on the field corpus, so it must not ride
# the 4 s stats poll. Before S3.2 that was a plain time cache whose expiry
# recomputed INLINE -- so once a minute one poll still waited out the whole scan
# on the request thread. It now goes through served_cache like /stats: the last
# real figures are served immediately and the recompute happens in the
# background.
_FIGURES_TTL_S = 60


def _compute_figures(db: Session, now: datetime) -> dict:
    """Averages + ingestion rate for the Library tab. All index-backed (word_count and
    created_at are indexed); counts only, no score. The keyword_mentions COUNT is the
    one O(n) query — kept off the request thread entirely by served_cache, which
    recomputes it in the background and serves the previous real figures meanwhile."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from src.database.models import Article, KeywordMention

    n = int(db.execute(select(func.count()).select_from(Article)).scalar() or 0)
    out: dict = {"articles": n}
    if not n:
        return out
    avg_wc = db.execute(select(func.avg(Article.word_count))).scalar()  # idx_article_word_count
    out["avg_word_count"] = round(float(avg_wc), 1) if avg_wc is not None else None
    n_mentions = int(db.execute(select(func.count()).select_from(KeywordMention)).scalar() or 0)
    out["keyword_mentions"] = n_mentions
    out["avg_keywords_per_article"] = round(n_mentions / n, 1)
    first = db.execute(select(func.min(Article.created_at))).scalar()  # idx_article_created_at
    if first is not None:
        if first.tzinfo is None:
            first = first.replace(tzinfo=UTC)
        span_days = max((now - first).total_seconds() / 86400.0, 1.0 / 24)
        out["span_days"] = round(span_days, 2)
        out["articles_per_day"] = round(n / span_days, 1)  # lifetime average additions/day
    cutoff = now - timedelta(hours=24)  # producers.py's aware-UTC cutoff pattern
    recent = int(
        db.execute(
            select(func.count()).select_from(Article).where(Article.created_at >= cutoff)
        ).scalar()
        or 0
    )
    out["articles_last_24h"] = recent
    out["articles_per_hour_recent"] = round(recent / 24.0, 2)  # current rate over the last day
    return out


@router.get("/figures")
def library_figures(db: Session = Depends(get_db)) -> dict:
    """Computed Library figures: average article word count, average keyword mentions
    per article, and the ingestion RATE (lifetime average articles/day + the current
    articles/hour over the last 24 h). Served from the background-refreshed cache,
    so a poll never waits on the whole-table mentions count; ``as_of``/``cache_age_s``
    state the figures' real age."""

    # `now` is read INSIDE the compute rather than captured here: a background
    # rebuild runs minutes after the request that kicked it, and the 24 h window
    # must be measured from when the figures were actually computed.
    def _compute(session: Session) -> dict:
        return _compute_figures(session, datetime.now(UTC))

    # Namespaced like every other key here: it does NOT go through _cached (the
    # figures carry their own longer interval), so the prefix has to be written
    # out, or this one key sits unprefixed in a dict shared with another module.
    return served_cache.cached("db:figures", _compute, db, ttl_s=_FIGURES_TTL_S)


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

    def _compute(db: Session) -> dict:
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

    2026-07-26 hardware diagnostics: this was a bare ``SCAN sources`` on every
    request (``tags`` isn't index-covered), the dominant server-cost item on all 7
    field instances (12-81% of uptime). Now served from an off-peak-refreshed
    in-memory rollup (:mod:`src.analytics.source_country_rollup`, mirrors
    ``reconcile_source_counters``) when warm; falls back to the identical live scan
    otherwise (cold start, a differently-bound session, or any rollup error) — the
    response is never wrong, only sometimes not-yet-warm.
    """
    from src.analytics import source_country_rollup

    def _compute(db: Session) -> dict:
        served = source_country_rollup.served(db)
        if served is not None:
            return served
        return source_country_rollup._live_sources_by_country(db)

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
    # A VACUUM rewrites the file wholesale through a raw connection that never
    # touches the write gate, so the `grants` probe cannot see it. Drop the
    # served counts by name rather than leaving them to a probe that is blind to
    # exactly this path (reclaimable_bytes is what changes here, and it is served
    # from the same "stats" entry).
    served_cache.invalidate()
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
