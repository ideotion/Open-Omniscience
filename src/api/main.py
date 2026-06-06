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
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
# source scraper, network analyzer) produced fabricated outputs (see docs/AUDIT_2026-06.md).

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

# Import verification router (honest image metadata/EXIF)
from src.api.verification import router as verification_router
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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "User-Agent"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=86400,  # 24 hours
)

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

# Include LLM router
app.include_router(llm_router)

# Include ingestion router
app.include_router(ingestion_router)

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
        writer.writerow(["ID", "Title", "URL", "Canonical URL", "Source", "Published At", "Language", "Content", "Hash"])
        for a in articles:
            writer.writerow([
                a.id,
                a.title or "",
                a.url or "",
                a.canonical_url or "",
                a.source.name if a.source else "",
                a.published_at.isoformat() if a.published_at else "",
                a.language or "",
                a.content or "",
                a.hash or "",
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


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    if index_path.exists():
        with open(index_path) as f:
            return HTMLResponse(content=f.read(), status_code=200)
    else:
        return HTMLResponse(content="<h1>Welcome to Open Omniscience</h1><p>API is running. See <a href='/docs'>API Documentation</a></p>", status_code=200)


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
            "Usage: open-omniscience [serve|doctor]\n"
            "  serve   (default) run the local web app at http://127.0.0.1:8000\n"
            "  doctor  print a health-check report (Python, data, db, LLM, launcher)\n"
        )
        return
    _serve()


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
            with session_scope() as session:
                result = seed_default_sources(session)
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
