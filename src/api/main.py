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

# FastAPI Backend for Open Omniscience
# This module provides the FastAPI backend for the Open Omniscience project,
# including endpoints for searching articles, exporting data, and listing sources.
# It also serves the HTML5 frontend static files and includes rate limiting.
# Author: Ideotion

import csv
import io
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# Import database models and session
from sqlalchemy.orm import Session

# Commodity, scientific-analysis and keyword routers all depend on the [analysis]
# extra (numpy/scipy/pandas/scikit-learn). Import them defensively so a core-only
# install still boots with the spine (ingest + search + export); they are included
# below only when their dependencies are present.
try:
    from src.api.commodity import router as commodity_router
    from src.api.analysis import router as analysis_router
    from src.api.keyword_analysis import router as keyword_analysis_router
    from src.api.keyword_management import router as keyword_management_router
    from src.api.framing import router as framing_router
    _ANALYSIS_AVAILABLE = True
except ImportError:
    commodity_router = analysis_router = None
    keyword_analysis_router = keyword_management_router = framing_router = None
    _ANALYSIS_AVAILABLE = False

# Import ingestion router (ethical scrape -> extract -> store)
from src.api.ingestion import router as ingestion_router

# Link-analysis router quarantined in v0.4: its services (credibility scorer,
# source scraper, network analyzer) produced fabricated outputs (see docs/HISTORY.md).

# Import LLM router (clean Ollama HTTP client; replaces the legacy routes.llm)
from src.api.llm import router as llm_router

# Import monitoring router (real source uptime + corpus anomalies)
from src.api.monitoring import router as monitoring_router

# Import reporting router (signed, tamper-evident evidence bundles)
from src.api.reporting import router as reporting_router

# Import custody router (append-only signed chain-of-custody log + anchoring)
from src.api.custody import router as custody_router

# Import source management router
from src.api.source_management import router as source_management_router

# Import database overview router (honest read-only corpus statistics + backup/restore)
from src.api.database import router as database_router

# Import application settings router (GUI-editable preferences)
from src.api.settings import router as settings_router

# Import scheduler router (in-app background ingester control surface)
from src.api.scheduler import router as scheduler_router

# Import markets router (per-source price-extraction rules + structured ingest)
from src.api.markets import router as markets_router

# Import source-catalog CSV import/export router
from src.api.source_io import router as source_io_router

# Import insights router (keyword & entity analytics)
from src.api.insights import router as insights_router

# Import briefing router (the Home triage feed of honest "cards" + draft accumulator)
from src.api.briefing import router as briefing_router

# Import source-integrity router (no-composite profile + user-guided actor-collapse)
from src.api.integrity import router as integrity_router

# Import annotations router (signed, portable, web-of-trust source annotations)
from src.api.annotations import router as annotations_router

# Import world-law change-tracking router (statutes/gazettes/IP, baseline→diff→flag)
from src.api.law import router as law_router

# Import link / co-citation analysis router (honest counts only)
from src.api.link_analysis import router as link_analysis_router

# Import Wikipedia change-tracking router
from src.api.wiki import router as wiki_router

# Import verification router (honest image metadata/EXIF)
from src.api.verification import router as verification_router

# Import safety router (at-risk-user safety: fetch-mode/proxy, encrypted backup, panic)
from src.api.safety import router as safety_router

# Import system router (loopback-only self-observation: live scraping + vitals)
from src.api.system import router as system_router

# Import hazards router (open natural-hazard/weather feeds, space-time relay)
from src.api.hazards import router as hazards_router
from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, Source
from src.database.session import dispose_engine, get_db, init_db, session_scope

# Configure logging using shared config
from src.utils.logging_config import setup_logging

# Import security utilities

logger = setup_logging("api")

# Single source of truth for the app version: the installed package metadata
# (pyproject.toml). Falls back gracefully if running from an uninstalled tree.
try:
    APP_VERSION = _pkg_version("open-omniscience")
except PackageNotFoundError:  # pragma: no cover - only when not pip-installed
    APP_VERSION = "0.0.0+local"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: create schema + FTS index, then dispose on shutdown.

    Replaces the deprecated @app.on_event hooks (D1). Metric initialisation is
    best-effort so the API still starts on a brand-new/empty database.
    """
    init_db()
    try:
        with session_scope() as session:
            ARTICLES_COUNT.set(session.query(Article).count())
            SOURCES_COUNT.set(session.query(Source).count())
    except Exception as exc:  # noqa: BLE001 - never block startup on metrics
        logger.warning(f"Could not initialise metrics at startup: {exc}")

    # Optionally start the background ingester. Off by default and gated on a
    # saved preference, so importing the app (e.g. in tests) never starts a thread
    # or any network activity; OO_NO_SCHEDULER=1 hard-disables it regardless.
    if os.getenv("OO_NO_SCHEDULER", "0") != "1":
        try:
            from src.scheduler.settings import load_settings as _sched_settings

            if _sched_settings().autostart:
                from src.scheduler.runner import get_scheduler

                get_scheduler().start()
                logger.info("Background scheduler autostarted (autostart=true).")
        except Exception as exc:  # noqa: BLE001 - never block startup on the scheduler
            logger.warning(f"Could not autostart scheduler: {exc}")

    logger.info(f"Open Omniscience API {APP_VERSION} started")
    yield

    # Stop the scheduler thread cleanly if it is running (no-op otherwise).
    try:
        from src.scheduler.runner import get_scheduler

        get_scheduler().stop()
    except Exception:  # noqa: BLE001 - best-effort shutdown
        logger.warning("Error stopping scheduler on shutdown", exc_info=True)

    dispose_engine()
    logger.info("Open Omniscience API shut down cleanly")


# Initialize FastAPI app
app = FastAPI(title="Open Omniscience API", version=APP_VERSION, lifespan=lifespan)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'open_omniscience_requests_total',
    'Total HTTP Requests',
    ['method', 'endpoint', 'http_status']
)
REQUEST_LATENCY = Histogram(
    'open_omniscience_request_latency_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint']
)
ACTIVE_REQUESTS = Gauge(
    'open_omniscience_active_requests',
    'Number of active HTTP requests'
)
ARTICLES_COUNT = Gauge(
    'open_omniscience_articles_count',
    'Total number of articles in database'
)
SOURCES_COUNT = Gauge(
    'open_omniscience_sources_count',
    'Total number of sources configured'
)

# Add Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Rate limiter setup
from src.api.ratelimit import limiter
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# CORS middleware - more secure configuration
# In production, set ALLOWED_ORIGINS environment variable with comma-separated origins
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

# Fixed: Remove trailing whitespace and empty strings from allowed origins
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # The app has no cookies/sessions/auth, so credentials are never needed; allowing
    # them is a latent misconfiguration if origins are ever widened (S-007).
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "User-Agent"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=86400,  # 24 hours
)

# --- CSRF (S-003) + security headers (S-006) -------------------------------- #
# No auth + a loopback API means a web page the user merely visits could POST to
# 127.0.0.1:8000 (a "simple request" needs no CORS preflight). We reject any
# state-changing request whose Origin/Referer is cross-origin (not loopback), and we
# attach defensive headers (a CSP backstop, anti-clickjacking, nosniff) to every
# response. The swagger docs (/docs, /redoc) load assets from a CDN, so they are
# exempt from the strict CSP (they render no ingested content).
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "   # UI is inline-heavy; nonce-based CSP is future work
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _origin_host(value: str | None) -> str | None:
    if not value:
        return None
    from urllib.parse import urlparse
    try:
        return urlparse(value).hostname
    except Exception:
        return None


@app.middleware("http")
async def csrf_and_security_headers(request: Request, call_next):
    # CSRF: a cross-origin browser request to a state-changing endpoint carries an
    # Origin (or at least a Referer); if present and not loopback, refuse. Requests
    # with no Origin/Referer (CLI, same-origin server-side) are allowed.
    if request.method in _STATE_CHANGING:
        host = _origin_host(request.headers.get("origin")) or _origin_host(request.headers.get("referer"))
        if host is not None and host not in _LOOPBACK_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin state-changing request refused (loopback only)."},
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
        response.headers.setdefault("Content-Security-Policy", _CSP)
    return response

# Include source management router
app.include_router(source_management_router)

# Include database overview router
app.include_router(database_router)

# Include application settings router
app.include_router(settings_router)

# Include scheduler router
app.include_router(scheduler_router)

# Include markets router
app.include_router(markets_router)

# Include source-catalog CSV import/export router
app.include_router(source_io_router)

# Include insights router
app.include_router(insights_router)

# Include briefing router (Home triage feed + newsletter draft)
app.include_router(briefing_router)

# Include source-integrity router (profile + anti-amplification)
app.include_router(integrity_router)

# Include annotations router (crowdsourced signed source annotations)
app.include_router(annotations_router)

# Include world-law change-tracking router
app.include_router(law_router)

# Include link / co-citation analysis router
app.include_router(link_analysis_router)

# Include Wikipedia change-tracking router
app.include_router(wiki_router)

# Include LLM router
app.include_router(llm_router)

# Include ingestion router
app.include_router(ingestion_router)

# Include system router (live scraping URL + process vitals; loopback-only)
app.include_router(system_router)
app.include_router(hazards_router)

# Include analysis-dependent routers only if the [analysis] extra is installed.
if _ANALYSIS_AVAILABLE:
    app.include_router(commodity_router)
    app.include_router(analysis_router)
    app.include_router(keyword_management_router)
    app.include_router(keyword_analysis_router)
    app.include_router(framing_router)
else:
    logger.warning(
        "Commodity, statistical-analysis & keyword endpoints disabled: install the "
        "[analysis] extra (pip install -e '.[analysis]') to enable them."
    )

# Include monitoring router
app.include_router(monitoring_router)

# Include reporting router
app.include_router(reporting_router)
app.include_router(custody_router)

# Include verification router
app.include_router(verification_router)

# Include safety router (encrypted backup, panic, protected-fetch settings)
app.include_router(safety_router)

# General health check endpoint
@app.get("/api/health")
async def health_check():
    """Check API health status"""
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
    }

# Serve static files (HTML5 frontend)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static"), html=True), name="static")

# Middleware for Prometheus metrics
@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    method = request.method
    endpoint = request.url.path
    
    ACTIVE_REQUESTS.inc()
    start_time = time.time()
    
    try:
        response = await call_next(request)
    except Exception as e:
        ACTIVE_REQUESTS.dec()
        raise e
    
    process_time = time.time() - start_time
    status_code = response.status_code
    
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=status_code).inc()
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(process_time)
    ACTIVE_REQUESTS.dec()
    
    return response

# Rate limit exceeded handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"Rate limit exceeded for {get_remote_address(request)}: {request.url}")
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, http_status=429).inc()
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
        headers={"Retry-After": str(exc.retry_after)}
    )


def _validate_date(value: str | None, field_name: str) -> None:
    """Raise HTTP 400 if `value` is set but not an ISO date (YYYY-MM-DD)."""
    if value:
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field_name} format. Use YYYY-MM-DD.",
            )


def _structured_filters(
    session,
    *,
    source: str | None,
    start_date: str | None,
    end_date: str | None,
    language: str | None,
    tags: str | None,
) -> list:
    """Build the non-text SQLAlchemy filter conditions.

    All values are bound as parameters by SQLAlchemy -- no string interpolation
    into SQL. Date strings are pre-validated by the caller.
    """
    from sqlalchemy import false, or_

    filters: list = []

    if source:
        source_obj = session.query(Source).filter_by(name=source).first()
        if not source_obj:
            raise HTTPException(status_code=404, detail=f"Source '{source}' not found.")
        filters.append(Article.source_id == source_obj.id)

    if start_date:
        filters.append(Article.published_at >= datetime.fromisoformat(start_date))
    if end_date:
        filters.append(Article.published_at <= datetime.fromisoformat(end_date))

    if language:
        filters.append(Article.language == language)

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            # .ilike(pattern) binds `pattern` as a parameter; the f-string only
            # builds the literal pattern value, not SQL. (No bindparam name reuse.)
            tag_conditions = [Source.tags.ilike(f"%{t}%") for t in tag_list]
            source_ids = [
                sid for (sid,) in session.query(Source.id)
                .filter(or_(*tag_conditions)).distinct()
            ]
            filters.append(Article.source_id.in_(source_ids) if source_ids else false())

    return filters


def _query_articles(
    session,
    *,
    query: str | None,
    source: str | None,
    start_date: str | None,
    end_date: str | None,
    language: str | None,
    tags: str | None,
    limit: int | None,
    offset: int,
) -> tuple[list, int]:
    """Return ``(articles, total)`` applying full-text search + structured filters.

    Text search uses SQLite FTS5 (real Boolean AND/OR/NOT, phrases, parenthesised
    precedence) and orders results by relevance; otherwise results are ordered by
    recency. ``limit=None`` returns every match (used by export).
    """
    from sqlalchemy import and_

    filters = _structured_filters(
        session, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags,
    )

    fts_ids: list | None = None
    if query:
        try:
            fts_ids = search_ids(session, query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid search query: {exc}")

    if fts_ids is not None:
        # A text query was given. fts_ids is relevance-ordered (best first).
        if not fts_ids:
            return [], 0
        q = session.query(Article).filter(Article.id.in_(fts_ids))
        if filters:
            q = q.filter(and_(*filters))
        rows = q.all()
        rank = {aid: i for i, aid in enumerate(fts_ids)}
        rows.sort(key=lambda a: rank.get(a.id, 1 << 30))
        total = len(rows)
        if limit is not None:
            rows = rows[offset:offset + limit]
        return rows, total

    # No text query: browse by recency.
    q = session.query(Article)
    if filters:
        q = q.filter(and_(*filters))
    total = q.count()
    q = q.order_by(Article.published_at.desc(), Article.id.desc())
    if limit is not None:
        q = q.offset(offset).limit(limit)
    return q.all(), total


# API Endpoints
@app.get("/api/articles", response_model=dict)
@limiter.limit("100/hour")
async def search_articles(
    request: Request,
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    Search and filter articles with advanced options.

    Parameters:
    - query: Boolean full-text search over title+content. Supports AND/OR/NOT,
      "quoted phrases", and parentheses with correct precedence (SQLite FTS5).
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
    - language: Filter by language code (e.g., "en", "fr").
    - tags: Filter by source tags (comma-separated).
    - limit: Maximum number of results to return (default: 100).
    - offset: Offset for pagination (default: 0).
    """
    logger.info(f"Search request: query={query}, source={source}, limit={limit}, offset={offset}")

    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")
    _validate_date(start_date, "start_date")
    _validate_date(end_date, "end_date")

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=limit, offset=offset,
    )

    results = [
        {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "canonical_url": a.canonical_url,
            "source": a.source.name if a.source else "Unknown",
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "language": a.language,
            "content": (a.content[:500] + "...") if a.content and len(a.content) > 500 else (a.content or ""),
            "hash": a.hash,
        }
        for a in articles
    ]

    return {"total": total, "limit": limit, "offset": offset, "results": results}


@app.get("/api/articles/export")
@limiter.limit("50/hour")
async def export_articles(
    request: Request,
    format: str = "csv",
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Export articles in CSV or JSON format with advanced filters.

    Parameters:
    - format: Export format (csv or json).
    - query: Boolean full-text search (same syntax as /api/articles).
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
    - language: Filter by language code (e.g., "en", "fr").
    - tags: Filter by source tags (comma-separated).
    """
    logger.info(f"Export request: format={format}, query={query}, source={source}")

    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="Unsupported format. Use 'csv' or 'json'.")
    _validate_date(start_date, "start_date")
    _validate_date(end_date, "end_date")

    # limit=None -> export every matching row, faithful to the filter.
    articles, _total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=None, offset=0,
    )

    if format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        # Neutralize spreadsheet formula injection: ingested title/url/content are
        # attacker-controlled, so every cell is passed through csv_safe_cell (S-004).
        from src.utils.security import csv_safe_cell as _c
        writer.writerow(["ID", "Title", "URL", "Canonical URL", "Source", "Published At", "Language", "Content", "Hash"])
        for a in articles:
            writer.writerow([
                a.id,
                _c(a.title or ""),
                _c(a.url or ""),
                _c(a.canonical_url or ""),
                _c(a.source.name if a.source else ""),
                a.published_at.isoformat() if a.published_at else "",
                _c(a.language or ""),
                _c(a.content or ""),
                _c(a.hash or ""),
            ])
        return StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=articles.csv"},
        )

    # format == "json" (validated above)
    return JSONResponse(
        content=[
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "canonical_url": a.canonical_url,
                "source": a.source.name if a.source else "Unknown",
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "language": a.language,
                "content": a.content,
                "hash": a.hash,
            }
            for a in articles
        ]
    )


@app.get("/api/articles/{article_id}/view", response_class=HTMLResponse)
@limiter.limit("300/hour")
async def view_article(request: Request, article_id: int, db: Session = Depends(get_db)):
    """Render the locally-stored copy of an article as a clean, offline reading page.

    Uses the text captured at ingest (no network), so it works fully offline and
    shows exactly what is in the corpus, with full provenance metadata. The links
    *this* article cites are listed with a co-citation signal ("also cited by N of
    your articles"). The only link that leaves the corpus is the original source,
    and it is rendered as an explicit, confirmed external action — opening it makes
    a live request from the user's machine, which a surveillance-conscious
    journalist must opt into knowingly.
    """
    import html as _html

    from sqlalchemy import func

    from src.database.models import ArticleLink
    from src.utils.security import safe_href

    a = db.query(Article).filter_by(id=article_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    content = a.get_content() if hasattr(a, "get_content") else (a.content or "")
    paras = "".join(
        f"<p>{_html.escape(line)}</p>" for line in content.split("\n") if line.strip()
    ) or "<p class='muted'>(no stored body)</p>"

    title = _html.escape(a.title or "(untitled)")
    lang = _html.escape(a.language or "en")

    def _row(label: str, value: str | None) -> str:
        return f"<div class='mrow'><span>{label}</span><b>{value}</b></div>" if value else ""

    src_name = _html.escape(a.source.name) if a.source else None
    published = a.published_at.date().isoformat() if a.published_at else None
    captured = a.created_at.date().isoformat() if a.created_at else None
    hash_short = (a.hash[:12] + "…") if a.hash else None
    safe_src = safe_href(a.url)

    meta_rows = "".join([
        _row("Source", src_name),
        _row("Published", _html.escape(published) if published else None),
        _row("Captured", _html.escape(captured) if captured else None),
        _row("Author", _html.escape(a.author) if a.author else None),
        _row("Language", lang if a.language else None),
        _row("Region", _html.escape(a.country or a.region) if (a.country or a.region) else None),
        _row("Content hash", f"<code>{_html.escape(hash_short)}</code>" if hash_short else None),
    ])

    # Co-citation: the external links THIS article cites, each with how many distinct
    # articles in the corpus cite the same normalized URL (in-degree). > 1 means a
    # shared source — the "multiple articles point to the same link" signal.
    links = (
        db.query(ArticleLink)
        .filter_by(article_id=a.id, link_type="external")
        .order_by(ArticleLink.position).all()
    )
    cite_items = []
    for ln in links[:40]:
        safe_ln = safe_href(ln.url)
        if not safe_ln:
            continue
        indeg = (
            db.query(func.count(func.distinct(ArticleLink.article_id)))
            .filter(ArticleLink.normalized_url == ln.normalized_url).scalar() or 1
        )
        host = _html.escape((safe_ln.split("//", 1)[-1].split("/", 1)[0]).replace("www.", ""))
        label = _html.escape(ln.link_text.strip()) if (ln.link_text and ln.link_text.strip()) else host
        shared = (
            f"<span class='shared'>also cited by {indeg - 1} of your article(s)</span>"
            if indeg > 1 else "<span class='muted'>only here</span>"
        )
        cite_items.append(
            f"<li><a class='ext' href='{_html.escape(safe_ln)}' rel='noopener noreferrer'>{label}</a>"
            f"<span class='muted'> · {host}</span> {shared}</li>"
        )
    cites_html = (
        "<section class='cites'><h2>Sources this article cites</h2><ul>"
        + "".join(cite_items) + "</ul></section>"
        if cite_items else ""
    )

    orig_html = (
        "Original source: <a class='ext src-link' href='" + _html.escape(safe_src)
        + f"' rel='noopener noreferrer'>{_html.escape(safe_src)}</a>"
        if safe_src else "<span class='muted'>No original (http/https) URL recorded.</span>"
    )

    doc = f"""<!DOCTYPE html><html lang="{lang}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>
  :root {{ color-scheme: light dark; --ink:#0b0d10; --paper:#0e1116; --fg:#e7e9ee; --mut:#8b93a1;
    --line:#222833; --accent:#5ea0ff; --card:#141923; --warn:#f0a23a; }}
  @media (prefers-color-scheme: light) {{ :root {{ --paper:#faf8f4; --fg:#1a1d22; --mut:#6b7280;
    --line:#e4e0d8; --card:#fff; --accent:#2b6cd4; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--fg);
    font: 18px/1.72 Georgia,'Times New Roman',serif; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 22px 80px; }}
  .crumb {{ font: 12px/1.4 system-ui,sans-serif; color:var(--mut); margin-bottom:18px;
    display:flex; gap:8px; align-items:center; }}
  .dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); display:inline-block; }}
  h1 {{ font-size: 30px; line-height: 1.22; margin: 0 0 14px; }}
  .meta {{ font: 13px/1.6 system-ui,sans-serif; background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:10px 14px; margin: 0 0 26px; }}
  .mrow {{ display:flex; justify-content:space-between; gap:14px; padding:3px 0; border-top:1px solid var(--line); }}
  .mrow:first-child {{ border-top:0; }}
  .mrow span {{ color:var(--mut); }} .mrow b {{ font-weight:600; text-align:right; }}
  code {{ font: 12px ui-monospace,Menlo,Consolas,monospace; color:var(--mut); }}
  article p {{ margin: 0 0 1.1em; }}
  .muted {{ color: var(--mut); }}
  .cites {{ margin-top: 34px; padding-top: 8px; }}
  .cites h2 {{ font: 600 14px system-ui,sans-serif; color:var(--mut); text-transform:uppercase;
    letter-spacing:.04em; margin: 0 0 8px; }}
  .cites ul {{ list-style:none; margin:0; padding:0; font: 14px/1.5 system-ui,sans-serif; }}
  .cites li {{ padding:6px 0; border-top:1px solid var(--line); }}
  .shared {{ color:var(--warn); font-weight:600; }}
  a {{ color: var(--accent); }}
  footer {{ margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--line);
    font: 13px/1.6 system-ui,sans-serif; color: var(--mut); }}
  .src-link {{ font-weight:500; word-break:break-all; }}
  .ext-note {{ font-size:12px; }}
</style></head><body>
<div class="wrap">
  <div class="crumb"><span class="dot"></span> Open Omniscience · offline stored copy</div>
  <article><h1>{title}</h1><div class="meta">{meta_rows}</div>{paras}</article>
  {cites_html}
  <footer>
    This is the copy captured at ingest — it does not change if the source is later edited or removed.
    <div style="margin-top:8px">{orig_html}</div>
    <div class="ext-note">Opening the source makes a live request from your machine; the site may see your visit. You'll be asked to confirm.</div>
  </footer>
</div>
<script>
  // Any link that leaves the corpus is confirmed first — honest about the exposure.
  document.addEventListener('click', function(e){{
    var a = e.target.closest && e.target.closest('a.ext');
    if(!a) return;
    e.preventDefault();
    var ok = window.confirm(
      "Open an EXTERNAL site on the public web?\\n\\n" + a.href +
      "\\n\\nThis leaves your local copy and makes a live request from your machine — " +
      "the site may see your visit. Continue?");
    if(ok) window.open(a.href, '_blank', 'noopener');
  }});
</script>
</body></html>"""
    return HTMLResponse(content=doc)


@app.get("/api/sources", response_model=list)
@limiter.limit("100/hour")
async def list_sources(request: Request, db: Session = Depends(get_db)):
    """List all available news sources with optional filters."""
    logger.info("List sources request")
    sources = db.query(Source).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "domain": s.domain,
            "rss_url": s.rss_url,
            "rate_limit_ms": s.rate_limit_ms,
            "enabled": s.enabled,
            "priority": s.priority,
            "tags": s.tags.split(",") if s.tags else [],
        }
        for s in sources
    ]


# In-app documentation. The UI's Help reader fetches these so the user can read
# the manual without leaving the (offline, loopback-only) app. Strictly a curated
# allow-list of repo docs — the slug never touches the filesystem path, so there
# is no traversal surface.
_DOCS: dict[str, dict[str, str]] = {
    "user-manual": {"file": "USER_MANUAL.md", "title": "User Manual",
                    "blurb": "The complete guide: install, every tool, workflows, reference, and per-feature deep-dives."},
    "quickstart": {"file": "QUICKSTART.md", "title": "Quickstart",
                   "blurb": "The fastest path from install to your first results."},
    "ethics": {"file": "ETHICS.md", "title": "Ethics, compliance & notices",
               "blurb": "The principles this tool upholds, plus licensing and attributions."},
    "governance": {"file": "GOVERNANCE.md", "title": "Governance & acceptable use",
                   "blurb": "What the tool is for, the dual-use red lines, and independence."},
    "security": {"file": "SECURITY.md", "title": "Security",
                 "blurb": "Threat model, local-first posture, and the security audit."},
    "design": {"file": "DESIGN.md", "title": "Design",
               "blurb": "What the app is and isn't, the pillar map, and the GUI reasoning."},
    "roadmap": {"file": "ROADMAP.md", "title": "Roadmap",
                "blurb": "Design memory, the phased plan + status, and open questions."},
    "architecture": {"file": "ARCHITECTURE.md", "title": "Architecture",
                     "blurb": "Database/config, the HTTP API map, and internationalisation."},
    "contributing": {"file": "CONTRIBUTING.md", "title": "Contributing",
                     "blurb": "How to contribute, and the (deliberately under-stated) versioning policy."},
    "changes": {"file": "CHANGES.md", "title": "Changelog",
                "blurb": "What changed, release by release."},
}
_DOCS_DIR = Path(__file__).parent.parent.parent / "docs"


@app.get("/api/docs")
async def list_docs() -> dict:
    """List the in-app documentation available to the Help reader."""
    return {
        "docs": [
            {"slug": slug, "title": meta["title"], "blurb": meta["blurb"],
             "available": (_DOCS_DIR / meta["file"]).exists()}
            for slug, meta in _DOCS.items()
        ]
    }


@app.get("/api/docs/{slug}", response_class=PlainTextResponse)
async def get_doc(slug: str) -> str:
    """Return one whitelisted doc as raw Markdown (rendered client-side)."""
    meta = _DOCS.get(slug)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown doc: {slug}")
    path = _DOCS_DIR / meta["file"]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Doc not found on disk: {meta['file']}")
    return path.read_text(encoding="utf-8")


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    if index_path.exists():
        with open(index_path) as f:
            return HTMLResponse(content=f.read(), status_code=200)
    else:
        return HTMLResponse(content="<h1>Welcome to Open Omniscience</h1><p>API is running. See <a href='/docs'>API Documentation</a></p>", status_code=200)


# Alternative UI ("Desk") served alongside the default ("Console") so both can be
# compared on the same backend/data — see docs/DESIGN.md. The installer
# creates a second desktop icon that opens this route.
@app.get("/desk", response_class=HTMLResponse)
async def read_desk():
    desk_path = Path(__file__).parent.parent / "static" / "desk.html"
    if desk_path.exists():
        return HTMLResponse(content=desk_path.read_text(encoding="utf-8"), status_code=200)
    # Fall back to the default UI if the alternative isn't present.
    return await read_root()


def main() -> None:
    """Console entrypoint (``open-omniscience``).

    Subcommands:
      (none) / serve   Run the local web app (loopback only).
      doctor           Print a health-check report and exit.

    Binds to loopback only by default: this is a single-user, local-first app and
    must never be exposed on a network interface (see PRODUCT_SYNTHESIS §0.3). Set
    OO_HOST/OO_PORT to override deliberately.
    """
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] in ("doctor", "check", "--doctor", "--check"):
        from src.diagnostics import run_doctor
        sys.exit(run_doctor())
    if argv and argv[0] in ("-h", "--help", "help"):
        print(
            "Usage: open-omniscience [serve|doctor|panic] [--ephemeral]\n"
            "  serve       (default) run the local web app at http://127.0.0.1:8000\n"
            "  doctor      print a health-check report (Python, data, db, LLM, launcher)\n"
            "  panic       irreversibly wipe the local data dir (asks to confirm)\n"
            "  --ephemeral run against a throwaway temp data dir, wiped on exit\n"
        )
        return
    if argv and argv[0] == "panic":
        _panic_cli(force=("--yes" in argv or "-y" in argv))
        return
    if "--ephemeral" in argv or os.getenv("OO_EPHEMERAL") == "1":
        _run_ephemeral([a for a in argv if a != "--ephemeral"])
        return
    _serve()


def _panic_cli(*, force: bool) -> None:
    """Wipe the data dir from the CLI (confirmed unless --yes)."""
    from src.paths import data_dir
    from src.safety import panic_wipe

    target = data_dir()
    if not force:
        ans = input(f"Irreversibly wipe ALL data under {target}? Type 'wipe' to confirm: ")
        if ans.strip().lower() != "wipe":
            print("Aborted.")
            return
    report = panic_wipe(confirm=True)
    print(f"Wiped {report['files_wiped']}/{report['files_seen']} files under {report['data_dir']}.")
    print(report["limit"])


def _run_ephemeral(argv: list[str]) -> None:
    """Run the app against a throwaway temp data dir, wiped on exit (leave-no-trace).

    Runs in a child process so the DB engine binds to the temp dir; the parent wipes it
    afterwards. Honest limit: this leaves no *application* trace; it cannot scrub OS-level
    swap/temp artefacts — pair with an amnesic OS (Tails) for that.
    """
    import shutil
    import subprocess
    import sys
    import tempfile

    tmp = tempfile.mkdtemp(prefix="oo-ephemeral-")
    env = {**os.environ, "OO_DATA_DIR": tmp, "OO_EPHEMERAL": "0"}
    print(f"Ephemeral mode: data in {tmp} (wiped on exit). Ctrl-C to stop.")
    try:
        subprocess.run([sys.executable, "-m", "src.api.main", *(argv or ["serve"])], env=env)
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"Ephemeral data wiped: {tmp}")


def _serve() -> None:
    import uvicorn

    # Preconfigure the database on first run so a fresh install is immediately
    # usable (the curated catalog is seeded only when the sources table is empty).
    # This runs for real launches but NOT during tests, which import `app`
    # directly rather than calling main(). Disable with OO_AUTOSEED=0.
    if os.getenv("OO_AUTOSEED", "1") != "0":
        try:
            init_db()
            from src.ingest.seed_sources import seed_default_sources
            from src.law.catalog import register_documents, seed_legal_sources
            with session_scope() as session:
                result = seed_default_sources(session)
                # Worldwide law & IP catalog (portals as ingestible sources) + the
                # curated set of trackable consolidated-law documents — on by default.
                seed_legal_sources(session)
                register_documents(session)
            if result["created"]:
                logger.info("Seeded %d starter sources on first run.", result["created"])
        except Exception as exc:  # noqa: BLE001 - never block startup on seeding
            logger.warning("Could not seed default sources: %s", exc)

    host = os.getenv("OO_HOST", "127.0.0.1")
    port = int(os.getenv("OO_PORT", "8000"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Binding to %s exposes the app beyond loopback; this app has no auth "
            "and is intended for single-user local use only.", host,
        )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
