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

from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from importlib.metadata import version as _pkg_version, PackageNotFoundError
import os

from fastapi import FastAPI, Query, HTTPException, Request, Depends, Header
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram
import csv
import io
import logging
import re
import time

# Import database models and session
from sqlalchemy.orm import Session
from src.database.models import Article, Source, get_session
from src.database.session import get_db, init_db, dispose_engine, session_scope
from src.database.fts import search_ids, SearchQueryError

# Import security utilities
from src.utils.security import (
    sanitize_html, escape_html,
    get_security_headers, SecurityError
)

# Import source management router
from src.api.source_management import router as source_management_router

# Import keyword management router
from src.api.keyword_management import router as keyword_management_router

# Import keyword analysis router
from src.api.keyword_analysis import router as keyword_analysis_router

# Import link analysis router
from src.api.link_analysis import router as link_analysis_router

# Import LLM router (clean Ollama HTTP client; replaces the legacy routes.llm)
from src.api.llm import router as llm_router

# Import ingestion router (ethical scrape -> extract -> store)
from src.api.ingestion import router as ingestion_router

# Import commodity router (price time-series + honest news correlation)
from src.api.commodity import router as commodity_router

# Configure logging using shared config
from src.utils.logging_config import setup_logging
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
    logger.info(f"Open Omniscience API {APP_VERSION} started")
    yield
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
limiter = Limiter(key_func=get_remote_address)
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

# Include keyword management router
app.include_router(keyword_management_router)

# Include keyword analysis router
app.include_router(keyword_analysis_router)

# Include link analysis router
app.include_router(link_analysis_router)

# Include LLM router
app.include_router(llm_router)

# Include ingestion router
app.include_router(ingestion_router)

# Include commodity router
app.include_router(commodity_router)

# General health check endpoint
@app.get("/api/health")
async def health_check():
    """Check API health status"""
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


def _validate_date(value: Optional[str], field_name: str) -> None:
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
    source: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    language: Optional[str],
    tags: Optional[str],
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
    query: Optional[str],
    source: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    language: Optional[str],
    tags: Optional[str],
    limit: Optional[int],
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

    fts_ids: Optional[list] = None
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
    query: Optional[str] = None,
    source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    language: Optional[str] = None,
    tags: Optional[str] = None,
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
    query: Optional[str] = None,
    source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    language: Optional[str] = None,
    tags: Optional[str] = None,
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
async def list_sources(request: Request):
    """List all available news sources with optional filters."""
    logger.info("List sources request")
    session = get_session()
    try:
        sources = session.query(Source).all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "rate_limit_ms": s.rate_limit_ms,
                "enabled": s.enabled,
                "priority": s.priority,
                "tags": s.tags.split(",") if s.tags else []
            } for s in sources
        ]
    finally:
        session.close()


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    if index_path.exists():
        with open(index_path, "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    else:
        return HTMLResponse(content="<h1>Welcome to Open Omniscience</h1><p>API is running. See <a href='/docs'>API Documentation</a></p>", status_code=200)


def main() -> None:
    """Console entrypoint (``open-omniscience``).

    Binds to loopback only by default: this is a single-user, local-first app and
    must never be exposed on a network interface (see PRODUCT_SYNTHESIS §0.3). Set
    OO_HOST/OO_PORT to override deliberately.
    """
    import uvicorn

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
