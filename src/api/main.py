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
import mimetypes
import os
import re
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
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# Import database models and session
from sqlalchemy.orm import Session

# Router wiring (every include_router call) lives in _wiring.py (audit PR H).
from src.api._wiring import wire
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


def run_deferred_startup() -> None:
    """Everything that needs an OPEN database: schema/FTS, error log, janitor,
    seeds, metrics, scheduler. Runs at every unlocked lifespan (each step is
    idempotent — init_db has always self-healed a damaged schema on boot) and
    again the moment the operator unlocks/creates an encrypted store."""
    init_db()
    # Query-planner statistics (performance batch 2026-06-12): bounded ANALYZE
    # on first boot at a schema, PRAGMA optimize after — best-effort, never
    # blocks startup, and repeat boots are near-free.
    try:
        from src.database.maintenance import optimize_at_boot
        from src.database.session import engine as _engine

        optimize_at_boot(_engine)
    except Exception:  # noqa: BLE001 - upkeep must never block startup
        logger.warning("planner-statistics refresh failed", exc_info=True)
    # Rolling WARNING+ error log (the debug bundle's heart) — best-effort.
    try:
        from src.monitoring.errorlog import install as _install_errorlog

        _install_errorlog()
    except Exception:  # noqa: BLE001 - logging must never block startup
        logger.warning("could not install the error-log handler", exc_info=True)
    # Reclaim staging dirs orphaned by a crashed restore (DB-reliability batch).
    try:
        from src.backup.artifact import cleanup_stale_staging

        _n = cleanup_stale_staging()
        if _n:
            logger.info(f"removed {_n} stale restore staging dir(s)")
    except Exception:  # noqa: BLE001 - the janitor must never block startup
        logger.warning("stale-staging cleanup failed", exc_info=True)
    # Bundled initial super-groups (maintainer-ruled 2026-06-11): created only
    # where missing; the user's own curation always wins. Offline, best-effort.
    try:
        from src.analytics.supergroup_seed import seed_supergroups

        with session_scope() as _s:
            seed_supergroups(_s)
    except Exception:  # noqa: BLE001 - seeding must never block startup
        logger.warning("super-group seeding failed", exc_info=True)
    try:
        with session_scope() as session:
            ARTICLES_COUNT.set(session.query(Article).count())
            SOURCES_COUNT.set(session.query(Source).count())
    except Exception as exc:  # noqa: BLE001 - never block startup on metrics
        logger.warning(f"Could not initialise metrics at startup: {exc}")

    # Content-first (maintainer 2026-06-13): the app BOOTS IN AIRPLANE MODE
    # (offline) every time — nothing scrapes until the operator crosses online
    # once (the one consent, POST /api/scheduler/start), after which collection
    # is continuous. Zero-network boot is preserved AND now explicit/visible: we
    # engage the offline state at boot and never auto-start scraping (the old
    # autostart-at-boot is retired by this ruling). Gated by OO_NO_SCHEDULER so
    # tests/headless setups, which manage the kill switch themselves, are
    # untouched.
    if os.getenv("OO_NO_SCHEDULER", "0") != "1":
        try:
            from src.ingest import activate_kill_switch

            activate_kill_switch()
            logger.info("Booted in airplane mode (offline); awaiting the online consent to collect.")
        except Exception as exc:  # noqa: BLE001 - never block startup
            logger.warning(f"Could not engage airplane mode at boot: {exc}")

    logger.info(f"Open Omniscience API {APP_VERSION} started")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan. When the store is encrypted and no passphrase is
    available yet (and on first launch without OO_DB_PLAINTEXT), the app boots
    LOCKED: only the unlock flow is served; the deferred startup runs the
    moment the operator supplies THE passphrase. A plaintext store boots
    exactly as before — never a lock screen over a plaintext file."""
    from src.api.unlock import app_lock_state

    state = app_lock_state()
    if state.startswith("unlocked"):
        run_deferred_startup()
    else:
        logger.info(f"started LOCKED ({state}): serving the unlock flow only")
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
    "open_omniscience_requests_total", "Total HTTP Requests", ["method", "endpoint", "http_status"]
)
REQUEST_LATENCY = Histogram(
    "open_omniscience_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)
ACTIVE_REQUESTS = Gauge("open_omniscience_active_requests", "Number of active HTTP requests")
ARTICLES_COUNT = Gauge("open_omniscience_articles_count", "Total number of articles in database")
SOURCES_COUNT = Gauge("open_omniscience_sources_count", "Total number of sources configured")

# Add Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Rate limiter setup
from src.api.ratelimit import limiter

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# CORS middleware - more secure configuration
# In production, set ALLOWED_ORIGINS environment variable with comma-separated origins
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(
    ","
)

# Fixed: Remove trailing whitespace and empty strings from allowed origins
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # The app has no cookies/sessions/auth, so credentials are never needed; allowing
    # them is a latent misconfiguration if origins are ever widened (S-007).
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    # The app has NO authentication, so `Authorization` was dead surface; `Origin` and
    # `User-Agent` are browser-controlled headers a page cannot set in a CORS request, so
    # listing them bought nothing. The frontend only ever sends JSON, so `Content-Type`
    # (plus the simple `Accept`) is all the preflight needs.
    allow_headers=["Content-Type", "Accept"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=600,  # 10 minutes: a no-auth loopback API gains little from a 24h preflight cache
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
    "script-src 'self' 'unsafe-inline'; "  # UI is inline-heavy; nonce-based CSP is future work
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
        host = _origin_host(request.headers.get("origin")) or _origin_host(
            request.headers.get("referer")
        )
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


# Wire every API router (after the app + middleware exist). See _wiring.py.
wire(app)


# General health check endpoint
@app.get("/api/health")
async def health_check():
    """Check API health status"""
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# Serve static files (HTML5 frontend). Register the JS/CSS MIME types explicitly so
# the externalised /static/app.js + app.css are served as text/javascript & text/css
# on EVERY platform: StaticFiles falls back to the OS registry otherwise, and Windows
# can map .js to "text/jscript" (PR H decomposition relies on correct script serving).
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent.parent / "static"), html=True),
    name="static",
)


# The passphrase gate (PR-E): while the store is locked/fresh, only the unlock
# flow is reachable; every other API answers 503 {"locked": true} and the
# Console redirects itself to /unlock. A plaintext store never hits this.
@app.middleware("http")
async def _lock_gate(request: Request, call_next):
    from src.api.unlock import ALLOWED_WHILE_LOCKED, app_is_locked

    if app_is_locked():
        path = request.url.path
        if path == "/" or path == "/index.html":
            return RedirectResponse(url="/unlock", status_code=307)
        if not any(path == p or path.startswith(p) for p in ALLOWED_WHILE_LOCKED):
            return JSONResponse(
                status_code=503,
                content={"detail": "the database is locked: unlock it first", "locked": True},
            )
    return await call_next(request)


@app.get("/unlock", response_class=HTMLResponse, include_in_schema=False)
async def unlock_page():
    """The passphrase gate page (also reachable unlocked: it then offers /)."""
    page = Path(__file__).parent.parent / "static" / "unlock.html"
    return HTMLResponse(content=page.read_text(encoding="utf-8"), status_code=200)


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
    # slowapi's RateLimitExceeded does not expose a public `retry_after`; only
    # emit the header when an explicit value is present (avoids an AttributeError
    # inside the very handler meant to degrade gracefully).
    retry_after = getattr(exc, "retry_after", None)
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
        headers=headers,
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
            ) from None


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
                sid for (sid,) in session.query(Source.id).filter(or_(*tag_conditions)).distinct()
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
        session,
        source=source,
        start_date=start_date,
        end_date=end_date,
        language=language,
        tags=tags,
    )

    fts_ids: list | None = None
    if query:
        try:
            fts_ids = search_ids(session, query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid search query: {exc}") from exc

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
            rows = rows[offset : offset + limit]
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
        db,
        query=query,
        source=source,
        start_date=start_date,
        end_date=end_date,
        language=language,
        tags=tags,
        limit=limit,
        offset=offset,
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
            "content": (a.content[:500] + "...")
            if a.content and len(a.content) > 500
            else (a.content or ""),
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
        db,
        query=query,
        source=source,
        start_date=start_date,
        end_date=end_date,
        language=language,
        tags=tags,
        limit=None,
        offset=0,
    )

    if format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        # Neutralize spreadsheet formula injection: ingested title/url/content are
        # attacker-controlled, so every cell is passed through csv_safe_cell (S-004).
        from src.utils.security import csv_safe_cell as _c

        writer.writerow(
            [
                "ID",
                "Title",
                "URL",
                "Canonical URL",
                "Source",
                "Published At",
                "Language",
                "Content",
                "Hash",
            ]
        )
        for a in articles:
            writer.writerow(
                [
                    a.id,
                    _c(a.title or ""),
                    _c(a.url or ""),
                    _c(a.canonical_url or ""),
                    _c(a.source.name if a.source else ""),
                    a.published_at.isoformat() if a.published_at else "",
                    _c(a.language or ""),
                    _c(a.content or ""),
                    _c(a.hash or ""),
                ]
            )
        from src.utils.export_envelope import envelope_headers

        return StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=articles.csv",
                # Versioned export contract (WP2/RM-15): provenance travels as
                # headers so the CSV body stays plain columns.
                **envelope_headers(
                    kind="articles",
                    query={"query": query, "source": source, "start_date": start_date,
                           "end_date": end_date, "language": language, "tags": tags},
                ),
            },
        )

    # format == "json" (validated above). Versioned envelope (WP2/RM-15): the
    # list moves under "articles" inside a self-describing wrapper -- schema,
    # app version, generated-at, and the exact generating query.
    from src.utils.export_envelope import envelope

    rows = [
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
    return JSONResponse(
        content=envelope(
            kind="articles",
            query={"query": query, "source": source, "start_date": start_date,
                   "end_date": end_date, "language": language, "tags": tags},
            count=len(rows),
            payload=rows,
        )
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
    paras = (
        "".join(f"<p>{_html.escape(line)}</p>" for line in content.split("\n") if line.strip())
        or "<p class='muted'>(no stored body)</p>"
    )

    title = _html.escape(a.title or "(untitled)")
    lang = _html.escape(a.language or "en")

    def _row(label: str, value: str | None) -> str:
        return f"<div class='mrow'><span>{label}</span><b>{value}</b></div>" if value else ""

    src_name = _html.escape(a.source.name) if a.source else None
    published = a.published_at.date().isoformat() if a.published_at else None
    captured = a.created_at.date().isoformat() if a.created_at else None
    hash_short = (a.hash[:12] + "…") if a.hash else None
    safe_src = safe_href(a.url)

    # TWO metadata classes, clearly differentiated (maintainer-ruled 2026-06-11):
    # what the SOURCE asserted vs what THIS APP deduced (explicitly less reliable).
    source_rows = "".join(
        [
            _row("Source", src_name),
            _row("Published", _html.escape(published) if published else None),
            _row("Author", _html.escape(a.author) if a.author else None),
            _row("Language", lang if a.language else None),
        ]
    )
    # App-deduced: capture facts + extracted event dates/locations + keywords.
    deduced_extra = []
    try:
        from src.timemap import datestore

        # Prefer the persisted (T12) date tags (article_mentioned_dates) — the
        # SAME stored rows the "Dates mentioned in this text" section already
        # reads, no recompute. A user-REJECTED tag is excluded from this compact
        # summary (rejected = "not a real date here"). Fall back to the live
        # extractor only when an article carries NO stored date tags.
        ds = [
            {"date": t["date"], "precision": t["precision"]}
            for t in datestore.for_article(db, a.id)
            if t.get("status") != "rejected" and t.get("date")
        ][:5]
        if not ds:
            from src.timemap.dateextract import extract_dates

            anchor = a.published_at.date() if a.published_at else None
            ds = extract_dates(content, anchor=anchor, language=a.language, limit=5)
        if ds:
            deduced_extra.append(
                _row(
                    "Event dates in text",
                    " · ".join(
                        f"{_html.escape(d['date'])} <span class='muted'>({_html.escape(d['precision'])})</span>"
                        for d in ds
                    ),
                )
            )
    except Exception:  # noqa: BLE001 - extraction must never break the reader
        logger.warning("date extraction failed in reader", exc_info=True)
    try:
        from src.timemap import whostore

        # Prefer the persisted T12 rows (article_mentioned_places) — consistent
        # with the corpus-wide WHERE (/api/insights/where), no recompute. Fall
        # back to the live extractor only when an article has NO stored rows
        # (older articles ingested before T12 persistence).
        locs = whostore.places_for_article(db, a.id, limit=5)
        if not locs:
            from src.timemap.locextract import extract_locations

            locs = extract_locations(content, source_country=a.country, limit=5)
        if locs:
            deduced_extra.append(
                _row(
                    "Places in text",
                    " · ".join(
                        f"{_html.escape(loc['name'])}"
                        + (f" <span class='muted'>({_html.escape(loc.get('country') or '')})</span>" if loc.get("country") else "")
                        for loc in locs
                    ),
                )
            )
    except Exception:  # noqa: BLE001
        logger.warning("location extraction failed in reader", exc_info=True)
    try:
        from src.timemap import whostore

        # Prefer the persisted T12 rows (article_entities) — consistent with the
        # corpus-wide WHO (/api/insights/who), no recompute. Fall back to the
        # live extractor only when an article has NO stored rows.
        ents = whostore.entities_for_article(db, a.id, limit=5)
        if not ents["people"] and not ents["organizations"]:
            from src.timemap.entextract import extract_entities

            ents = extract_entities(content, limit=5)
        if ents["people"]:
            deduced_extra.append(
                _row(
                    "People in text",
                    " · ".join(
                        f"{_html.escape(p['name'])}"
                        + (f" <span class='muted'>×{p['mentions']}</span>" if p["mentions"] > 1 else "")
                        for p in ents["people"]
                    ),
                )
            )
        if ents["organizations"]:
            deduced_extra.append(
                _row(
                    "Organizations in text",
                    " · ".join(
                        f"{_html.escape(o['name'])}"
                        + (f" <span class='muted'>×{o['mentions']}</span>" if o["mentions"] > 1 else "")
                        for o in ents["organizations"]
                    ),
                )
            )
    except Exception:  # noqa: BLE001
        logger.warning("entity extraction failed in reader", exc_info=True)
    deduced_rows = "".join(
        [
            _row("Captured (downloaded)", _html.escape(captured) if captured else None),
            _row(
                "Region (from the source's catalog entry)",
                _html.escape(a.country or a.region or "") if (a.country or a.region) else None,
            ),
            *deduced_extra,
            _row(
                "Content hash", f"<code>{_html.escape(hash_short)}</code>" if hash_short else None
            ),
        ]
    )
    meta_rows = (
        "<div class='mgrp'><h3>From the source</h3>" + (source_rows or "<div class='mrow muted'>—</div>") + "</div>"
        "<div class='mgrp deduced'><h3>Deduced by this app — less reliable</h3>"
        + (deduced_rows or "<div class='mrow muted'>—</div>")
        + "<div class='mnote'>Extractions are lexical candidates with snippet provenance — "
        "an event date, place, person or organization mentioned in the text, "
        "never a confirmed fact.</div></div>"
    )

    # Co-citation: the external links THIS article cites, each with how many distinct
    # articles in the corpus cite the same normalized URL (in-degree). > 1 means a
    # shared source — the "multiple articles point to the same link" signal.
    links = (
        db.query(ArticleLink)
        .filter_by(article_id=a.id, link_type="external")
        .order_by(ArticleLink.position)
        .all()
    )
    cite_items = []
    for ln in links[:40]:
        safe_ln = safe_href(ln.url)
        if not safe_ln:
            continue
        indeg = (
            db.query(func.count(func.distinct(ArticleLink.article_id)))
            .filter(ArticleLink.normalized_url == ln.normalized_url)
            .scalar()
            or 1
        )
        host = _html.escape((safe_ln.split("//", 1)[-1].split("/", 1)[0]).replace("www.", ""))
        label = (
            _html.escape(ln.link_text.strip()) if (ln.link_text and ln.link_text.strip()) else host
        )
        shared = (
            f"<span class='shared'>also cited by {indeg - 1} of your article(s)</span>"
            if indeg > 1
            else "<span class='muted'>only here</span>"
        )
        cite_items.append(
            f"<li><a class='ext' href='{_html.escape(safe_ln)}' rel='noopener noreferrer'>{label}</a>"
            f"<span class='muted'> · {host}</span> {shared}</li>"
        )
    cites_html = (
        "<section class='cites'><h2>Sources this article cites</h2><ul>"
        + "".join(cite_items)
        + "</ul></section>"
        if cite_items
        else ""
    )

    orig_html = (
        "Original source: <a class='ext src-link' href='"
        + _html.escape(safe_src)
        + f"' rel='noopener noreferrer'>{_html.escape(safe_src)}</a>"
        if safe_src
        else "<span class='muted'>No original (http/https) URL recorded.</span>"
    )

    # Source profile (the reader's "Source" tab): DESCRIPTIVE provenance from your
    # source catalogue + this source's footprint in YOUR corpus. Server-rendered
    # like Related/Links (no extra fetch). No score, no ranking, no credibility
    # verdict — reliability_score (operator-set, guarded) is deliberately NOT shown.
    src = a.source
    if src:
        src_footprint = (
            db.query(func.count(Article.id)).filter(Article.source_id == a.source_id).scalar() or 0
        )
        _place = " · ".join(
            p for p in (
                _html.escape(src.country) if src.country else None,
                _html.escape(src.region) if src.region else None,
            ) if p
        ) or None
        source_profile_rows = "".join(
            [
                _row("Name", _html.escape(src.name) if src.name else None),
                _row("Domain", f"<code>{_html.escape(src.domain)}</code>" if src.domain else None),
                _row("Place", _place),
                _row("Type", _html.escape(src.source_type) if src.source_type else None),
                _row("Language", _html.escape(src.language) if src.language else None),
                _row("Tags", _html.escape(src.tags) if src.tags else None),
                _row("In your corpus", f"{src_footprint:,} article(s) collected from this source"),
            ]
        )
        source_block = (
            "<section><h2>Source profile</h2>"
            "<div class='meta'>" + (source_profile_rows or "<div class='mrow muted'>—</div>") + "</div>"
            "<div class='mnote'>Descriptive provenance from your source catalogue — no score, no "
            "ranking, no credibility verdict. “In your corpus” counts what you have collected, "
            "not the source's total output.</div></section>"
        )
    else:
        source_block = (
            "<section><h2>Source profile</h2>"
            "<p class='muted'>No source is recorded for this article.</p></section>"
        )

    # Dates mentioned in the text — extracted, human-confirmable per-article tags.
    from src.timemap import datestore

    _amd_tags = datestore.for_article(db, a.id)
    _stcol = {"confirmed": "#3fb950", "rejected": "#e5484d"}

    def _amd_chip(t: dict) -> str:
        col = _stcol.get(t["status"], "var(--mut)")
        snip = _html.escape((t.get("snippet") or "")[:140])
        return (
            "<li style='padding:7px 0;border-top:1px solid var(--line)'>"
            f"<b>{_html.escape(t['date'])}</b> <span class='muted'>· {_html.escape(t['precision'])}</span> "
            f"<span style='color:{col};font-weight:600'>· {_html.escape(t['status'])}</span>"
            + (
                f"<div class='muted' style='font-size:13px;margin-top:2px'>“…{snip}…”</div>"
                if snip
                else ""
            )
            + "<div style='margin-top:4px;display:flex;gap:6px'>"
            f"<button class='amd-act' data-id='{t['id']}' data-act='confirm' "
            "style='font:12px system-ui;padding:2px 9px;cursor:pointer'>confirm</button>"
            f"<button class='amd-act' data-id='{t['id']}' data-act='reject' "
            "style='font:12px system-ui;padding:2px 9px;cursor:pointer'>reject</button>"
            "</div></li>"
        )

    _amd_list = (
        (
            "<ul style='list-style:none;margin:0;padding:0;font:14px/1.5 system-ui,sans-serif'>"
            + "".join(_amd_chip(t) for t in _amd_tags)
            + "</ul>"
        )
        if _amd_tags
        else "<p class='muted' style='font:13px system-ui,sans-serif'>No date tags yet — extract to find dates this text mentions.</p>"
    )
    dates_section = (
        "<section class='cites'><h2>Dates mentioned in this text</h2>"
        "<p class='muted' style='font:13px/1.5 system-ui,sans-serif;margin:0 0 8px'>"
        "Dates the article refers to (extracted high-precision: explicit dates plus relative "
        "ones — yesterday, weekdays, a day and month with no year — resolved against the "
        "publication date; never bare years). Each is a candidate; confirm or reject. The "
        "date is <em>when the story refers to</em>, not when it was published.</p>"
        + _amd_list
        + "<div style='margin-top:8px'><button id='amd-extract' "
        "style='font:12px system-ui,sans-serif;padding:3px 11px;cursor:pointer'>"
        "Extract dates from this article</button></div></section>"
    )
    dates_script = (
        "<script>(function(){var aid=" + str(a.id) + ";"
        "function reload(){location.reload();}"
        "document.addEventListener('click',function(e){"
        "var b=e.target.closest&&e.target.closest('.amd-act');"
        "if(b){e.preventDefault();fetch('/api/article-dates/'+b.dataset.id+'/'+b.dataset.act,"
        "{method:'POST'}).then(reload).catch(function(){});return;}"
        "var x=e.target.closest&&e.target.closest('#amd-extract');"
        "if(x){e.preventDefault();x.disabled=true;x.textContent='Extracting…';"
        "fetch('/api/article-dates/article/'+aid,{method:'POST'}).then(reload).catch(function(){});}"
        "});})();</script>"
    )

    # Related in your corpus: other articles sharing the most keywords with this
    # one (maintainer feedback: read locally, then branch out by similarity --
    # source-agnostic). Pure counting over the keyword association table; the
    # number shown IS the method.
    related_html = ""
    try:
        from src.database.models import article_keyword_association as aka

        my_kw = [r[0] for r in db.query(aka.c.keyword_id).filter(aka.c.article_id == a.id)]
        if my_kw:
            rows = (
                db.query(Article.id, Article.title, func.count(aka.c.keyword_id).label("shared"))
                .join(aka, aka.c.article_id == Article.id)
                .filter(aka.c.keyword_id.in_(my_kw), Article.id != a.id)
                .group_by(Article.id, Article.title)
                .order_by(func.count(aka.c.keyword_id).desc())
                .limit(8)
                .all()
            )
            if rows:
                items = "".join(
                    f'<li><a href="/api/articles/{rid}/view">{_html.escape(rtitle or "(untitled)")}</a>'
                    f' <span class="muted">— {shared} shared keyword{"s" if shared != 1 else ""}</span></li>'
                    for rid, rtitle, shared in rows
                )
                related_html = (
                    '<section><h2>Related in your corpus</h2>'
                    '<p class="muted">Ranked by shared extracted keywords — overlap counts, '
                    "not a similarity score. All links stay local.</p>"
                    f"<ul>{items}</ul></section>"
                )
    except Exception:  # noqa: BLE001 - related list is optional, never breaks the reader
        logger.warning("related-articles block failed", exc_info=True)

    # Tab panes always exist (consistent tab bar); an empty Related/Links pane
    # shows an honest empty state instead of vanishing.
    related_block = related_html or (
        "<p class='muted'>No related articles yet — they appear once this and "
        "other articles share extracted keywords.</p>"
    )
    links_block = cites_html or (
        "<p class='muted'>No external links are recorded in your stored copy.</p>"
    )

    # Inline "1 voice" near-dup badge (maintainer-ruled): flag when THIS article is
    # one of several NEAR-IDENTICAL copies in the corpus (= effectively one voice, not
    # independent confirmation). Bounded + honest: a high-precision MinHash check over
    # this article's most keyword-related neighbours (near-dups share many keywords),
    # never a corpus-wide scan here. The ≈N pill is a number (language-neutral); the
    # caption is a keyed string so i18n.js translates it to the UI language.
    dup_badge = ""
    try:
        from src.database.models import article_keyword_association as _aka
        from src.signals.near_dup import near_duplicate_clusters

        _mk = [r[0] for r in db.query(_aka.c.keyword_id).filter(_aka.c.article_id == a.id)]
        _cand = (
            [
                r[0]
                for r in db.query(Article.id)
                .join(_aka, _aka.c.article_id == Article.id)
                .filter(_aka.c.keyword_id.in_(_mk), Article.id != a.id)
                .group_by(Article.id)
                .order_by(func.count(_aka.c.keyword_id).desc())
                .limit(40)
                .all()
            ]
            if _mk
            else []
        )
        if _cand:
            docs = {str(a.id): ((a.title or "") + "\n" + (a.get_content() or ""))}
            titles: dict[str, str] = {}
            for c in db.query(Article).filter(Article.id.in_(_cand)).all():
                docs[str(c.id)] = (c.title or "") + "\n" + (c.get_content() or "")
                titles[str(c.id)] = c.title or "(untitled)"
            res = near_duplicate_clusters(docs, threshold=0.7)
            mine = next(
                (cl for cl in res.clusters if str(a.id) in cl.members and len(cl.members) >= 2),
                None,
            )
            if mine:
                others = [m for m in mine.members if m != str(a.id)][:8]
                lis = "".join(
                    f'<li><a href="/api/articles/{m}/view">{_html.escape(titles.get(m, "(untitled)"))}</a></li>'
                    for m in others
                )
                dup_badge = (
                    '<div class="dup-badge" role="note">'
                    f'<span class="dup-pill">≈{len(mine.members)}</span> '
                    '<span class="dup-cap">Near-identical copies in your corpus — effectively one '
                    "voice, not independent confirmation. See Related.</span>"
                    f'<details><summary class="muted">Show the copies</summary><ul>{lis}</ul></details>'
                    "</div>"
                )
    except Exception:  # noqa: BLE001 - the badge is optional, never breaks the reader
        logger.warning("near-dup reader badge failed", exc_info=True)

    doc = f"""<!DOCTYPE html><html lang="{lang}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{(title[:40] + "…") if len(title) > 40 else title} · FOOS</title><style>
  .mgrp {{ margin:8px 0; padding:8px 10px; border:1px solid var(--line); border-radius:8px; }}
  .mgrp h3 {{ margin:0 0 6px; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--mut); }}
  .mgrp.deduced {{ border-style:dashed; }}
  .mgrp.deduced h3 {{ color:var(--warn); }}
  .mnote {{ margin-top:6px; font-size:11px; color:var(--mut); }}
  :root {{ color-scheme: light dark; --ink:#0b0d10; --paper:#0e1116; --fg:#e7e9ee; --mut:#8b93a1;
    --line:#222833; --accent:#5ea0ff; --card:#141923; --warn:#f0a23a; }}
  @media (prefers-color-scheme: light) {{ :root {{ --paper:#faf8f4; --fg:#1a1d22; --mut:#6b7280;
    --line:#e4e0d8; --card:#fff; --accent:#2b6cd4; }} }}
  /* Bundled OFL reading serif (src/static/fonts) — local file, zero network. */
  @font-face {{ font-family:"Source Serif 4"; src:url("/static/fonts/SourceSerif4-Variable.woff2")
    format("woff2"); font-weight:200 900; font-display:swap; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--fg);
    font: 18px/1.72 "Source Serif 4",Georgia,'Times New Roman',serif; }}
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
  .dup-badge {{ margin: 0 0 18px; padding:10px 14px; border:1px solid var(--warn);
    border-radius:10px; background:var(--card); font: 13px/1.5 system-ui,sans-serif; }}
  .dup-pill {{ display:inline-block; font-weight:700; color:var(--warn); margin-inline-end:6px; }}
  .dup-cap {{ color:var(--fg); }}
  .dup-badge details {{ margin-top:6px; }} .dup-badge ul {{ margin:6px 0 0; padding-inline-start:18px; }}
</style>
<link rel="stylesheet" href="/static/reader.css">
<!-- i18n engine: makes the reader follow the UI language (same localStorage as the
     SPA); auto-translates every keyed string + the dynamic reader.js panes. -->
<script src="/static/i18n.js" defer></script>
<script src="/static/reader.js" defer></script>
</head><body>
<div class="wrap" data-article-id="{a.id}">
  <div class="crumb"><span class="dot"></span> Open Omniscience · offline stored copy</div>
  <h1>{title}</h1>
  <nav class="rtabs" role="tablist" aria-label="Article views">
    <button class="rtab active" data-rtab="read" role="tab" aria-selected="true" tabindex="0">Read</button>
    <button class="rtab" data-rtab="keywords" role="tab" aria-selected="false" tabindex="-1">Keywords</button>
    <button class="rtab" data-rtab="mindmap" role="tab" aria-selected="false" tabindex="-1">Mindmap</button>
    <button class="rtab" data-rtab="sentiment" role="tab" aria-selected="false" tabindex="-1">Sentiment</button>
    <button class="rtab" data-rtab="related" role="tab" aria-selected="false" tabindex="-1">Related</button>
    <button class="rtab" data-rtab="source" role="tab" aria-selected="false" tabindex="-1">Source</button>
    <button class="rtab" data-rtab="links" role="tab" aria-selected="false" tabindex="-1">Links</button>
  </nav>
  <section class="rpane" id="rp-read" role="tabpanel" aria-label="Read">
    <div class="meta">{meta_rows}</div>
    {dup_badge}
    <article>{paras}</article>
    {dates_section}
  </section>
  <section class="rpane" id="rp-keywords" role="tabpanel" aria-label="Keywords" data-lazy="keywords" hidden></section>
  <section class="rpane" id="rp-mindmap" role="tabpanel" aria-label="Mindmap" data-lazy="mindmap" hidden></section>
  <section class="rpane" id="rp-sentiment" role="tabpanel" aria-label="Sentiment" data-lazy="sentiment" hidden></section>
  <section class="rpane" id="rp-related" role="tabpanel" aria-label="Related" hidden>{related_block}</section>
  <section class="rpane" id="rp-source" role="tabpanel" aria-label="Source" hidden>{source_block}</section>
  <section class="rpane" id="rp-links" role="tabpanel" aria-label="Links" hidden>{links_block}</section>
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
{dates_script}
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
    "user-manual": {
        "file": "USER_MANUAL.md",
        "title": "User Manual",
        "blurb": "The complete guide: install, every tool, workflows, reference, and per-feature deep-dives.",
    },
    "quickstart": {
        "file": "QUICKSTART.md",
        "title": "Quickstart",
        "blurb": "The fastest path from install to your first results.",
    },
    "ethics": {
        "file": "ETHICS.md",
        "title": "Ethics, compliance & notices",
        "blurb": "The principles this tool upholds, plus licensing and attributions.",
    },
    "governance": {
        "file": "GOVERNANCE.md",
        "title": "Governance & acceptable use",
        "blurb": "What the tool is for, the dual-use red lines, and independence.",
    },
    "security": {
        "file": "SECURITY.md",
        "title": "Security",
        "blurb": "Threat model, local-first posture, and the security audit.",
    },
    "design": {
        "file": "DESIGN.md",
        "title": "Design",
        "blurb": "What the app is and isn't, the pillar map, and the GUI reasoning.",
    },
    "roadmap": {
        "file": "ROADMAP.md",
        "title": "Roadmap",
        "blurb": "Design memory, the phased plan + status, and open questions.",
    },
    "architecture": {
        "file": "ARCHITECTURE.md",
        "title": "Architecture",
        "blurb": "Database/config, the HTTP API map, and internationalisation.",
    },
    "contributing": {
        "file": "CONTRIBUTING.md",
        "title": "Contributing",
        "blurb": "How to contribute, and the (deliberately under-stated) versioning policy.",
    },
    "changes": {
        "file": "CHANGES.md",
        "title": "Changelog",
        "blurb": "What changed, release by release.",
    },
}
_DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

# Translated documentation (maintainer-ruled 2026-06-10): community-perfectible
# drafts live in docs/i18n/<lang>/<FILE>. English stays authoritative; a missing
# translation falls back to English (same rule as the UI chrome). The lang code
# is validated against this pattern so it can never traverse the filesystem.
_LANG_RE = re.compile(r"^[a-z]{2}$")


def _doc_path(meta: dict[str, str], lang: str | None) -> tuple[Path, str]:
    """The on-disk file for a doc in the requested language ('' = English)."""
    if lang and lang != "en" and _LANG_RE.fullmatch(lang):
        candidate = _DOCS_DIR / "i18n" / lang / meta["file"]
        if candidate.exists():
            return candidate, lang
    return _DOCS_DIR / meta["file"], "en"


@app.get("/api/docs")
async def list_docs(lang: str | None = None) -> dict:
    """List the in-app documentation available to the Help reader."""
    return {
        "docs": [
            {
                "slug": slug,
                "title": meta["title"],
                "blurb": meta["blurb"],
                "available": (_DOCS_DIR / meta["file"]).exists(),
                "translated": _doc_path(meta, lang)[1] != "en" if lang else False,
            }
            for slug, meta in _DOCS.items()
        ]
    }


@app.get("/api/docs/{slug}")
async def get_doc(slug: str, lang: str | None = None) -> PlainTextResponse:
    """Return one whitelisted doc as raw Markdown (rendered client-side).

    ``?lang=fr`` serves ``docs/i18n/fr/<file>`` when a translation exists and
    falls back to the English original otherwise; the ``X-OO-Doc-Lang`` header
    states which one was actually served, so the reader can show an honest
    "translated draft — English is authoritative" banner.
    """
    meta = _DOCS.get(slug)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown doc: {slug}")
    path, served_lang = _doc_path(meta, lang)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Doc not found on disk: {meta['file']}")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"), headers={"X-OO-Doc-Lang": served_lang}
    )


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    else:
        return HTMLResponse(
            content="<h1>Welcome to Open Omniscience</h1><p>API is running. See <a href='/docs'>API Documentation</a></p>",
            status_code=200,
        )


# The experimental "Desk" UI was retired (maintainer verdict 2026-06-10): ONE
# interface — the Console (see docs/DESIGN.md). Old bookmarks and launchers
# from earlier installs still hit this path, so redirect instead of 404ing.
@app.get("/desk", include_in_schema=False)
async def read_desk():
    return RedirectResponse(url="/", status_code=308)


# The investigation dashboard (0.0.8 WP9 / RM-20): a dedicated, URL-parameterised
# view a Home recipe card opens in a NEW browser tab (?view=<recipe>&<params>).
# Second page alongside the Console: same server, same corpus, no CDN.
@app.get("/investigate", response_class=HTMLResponse)
async def read_investigate():
    page = Path(__file__).parent.parent / "static" / "investigate.html"
    if page.exists():
        return HTMLResponse(content=page.read_text(encoding="utf-8"), status_code=200)
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
            "and is intended for single-user local use only.",
            host,
        )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
