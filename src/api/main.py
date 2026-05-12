"""
FastAPI Backend for Open Omniscience

This module provides the FastAPI backend for the Open Omniscience project,
including endpoints for searching articles, exporting data, and listing sources.
It also serves the HTML5 frontend static files and includes rate limiting.

Author: Ideotion
"""

import sys
from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime
import os

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

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
from database.models import Article, Source, get_session

# Import security utilities
from utils.security import (
    sanitize_html, escape_html, validate_and_sanitize_search_query,
    get_security_headers, SecurityError
)

# Import source management router
from api.source_management import router as source_management_router

# Import keyword management router
from api.keyword_management import router as keyword_management_router

# Import keyword analysis router
from api.keyword_analysis import router as keyword_analysis_router

# Import link analysis router
from api.link_analysis import router as link_analysis_router

# Import LLM router
from api.routes.llm import router as llm_router

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("api")

# Database setup - use environment variable or default
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{Path(__file__).parent.parent.parent / 'data' / 'open_omniscience.db'}")

# Initialize FastAPI app
app = FastAPI(title="Open Omniscience API", version="0.02")

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

# General health check endpoint
@app.get("/api/health")
async def health_check():
    """Check API health status"""
    return {
        "status": "healthy",
        "version": "0.02",
        "timestamp": datetime.utcnow().isoformat() + "Z"
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

# Update metrics on startup
@app.on_event("startup")
async def startup_event():
    session = get_session()
    try:
        from database.models import Article, Source
        articles_count = session.query(Article).count()
        sources_count = session.query(Source).count()
        ARTICLES_COUNT.set(articles_count)
        SOURCES_COUNT.set(sources_count)
        logger.info(f"Metrics initialized: {articles_count} articles, {sources_count} sources")
    finally:
        session.close()

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


def parse_search_query(query: str) -> dict:
    """
    Parse a search query into a structured format for Boolean searches.
    Supports:
    - AND: "term1 AND term2"
    - OR: "term1 OR term2"
    - NOT: "term1 NOT term2"
    - Phrases: "\"exact phrase\""
    - Parentheses: "(term1 OR term2) AND term3"

    Args:
        query: The raw search query.

    Returns:
        A dictionary with parsed terms and operators.
        
    Raises:
        HTTPException: If the query contains potentially dangerous content.
    """
    if not query:
        return {"terms": [], "operators": []}

    # Validate and sanitize the search query
    try:
        query = validate_and_sanitize_search_query(query)
    except SecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Replace parentheses with spaces for now (simplified)
    query = query.replace("(", " ").replace(")", " ")

    # Tokenize the query
    tokens = re.split(r'\s+(AND|OR|NOT)\s+', query, flags=re.IGNORECASE)
    tokens = [token.strip() for token in tokens if token.strip()]

    # Process tokens
    terms = []
    operators = []
    current_operator = "AND"  # Default operator

    for token in tokens:
        if token.upper() in ["AND", "OR", "NOT"]:
            operators.append(token.upper())
            current_operator = token.upper()
        else:
            # Remove quotes for exact phrases
            if token.startswith('"') and token.endswith('"'):
                terms.append({"value": token[1:-1], "exact": True, "operator": current_operator})
            else:
                terms.append({"value": token, "exact": False, "operator": current_operator})
            current_operator = "AND"  # Reset to default

    return {"terms": terms, "operators": operators}


def build_sqlalchemy_filter(parsed_query: dict, session) -> List:
    """
    Build SQLAlchemy filter conditions from a parsed query.

    Args:
        parsed_query: The parsed query dictionary.
        session: SQLAlchemy session (unused but kept for compatibility).

    Returns:
        A list of SQLAlchemy filter conditions.
    """
    from sqlalchemy import or_, and_, not_, bindparam

    filters = []
    for term in parsed_query["terms"]:
        if term["exact"]:
            # Use bindparam for safe parameter binding to prevent SQL injection
            param = bindparam('search_term', term["value"])
            filters.append(Article.content.ilike('%' + param + '%'))
        else:
            # Split into words for OR logic
            words = term["value"].split()
            word_conditions = []
            for word in words:
                param = bindparam('search_word', word)
                word_conditions.append(Article.content.ilike('%' + param + '%'))
            filters.append(or_(*word_conditions))

    # Combine filters based on operators (simplified: assume AND for all)
    return and_(*filters) if filters else []


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
    offset: int = 0
):
    """
    Search and filter articles with advanced options.

    Parameters:
    - query: Text to search in article content (supports Boolean operators).
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
    - language: Filter by language code (e.g., "en", "fr").
    - tags: Filter by source tags (comma-separated).
    - limit: Maximum number of results to return (default: 100).
    - offset: Offset for pagination (default: 0).
    """
    logger.info(f"Search request: query={query}, source={source}, limit={limit}, offset={offset}")

    # Validate pagination parameters
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")

    # Validate date formats
    if start_date:
        try:
            datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
    if end_date:
        try:
            datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    session = get_session()
    try:
        filters = []

        # Parse and apply text query
        if query:
            parsed_query = parse_search_query(query)
            query_filters = build_sqlalchemy_filter(parsed_query, session)
            # query_filters is either a SQLAlchemy clause or empty list
            if not (isinstance(query_filters, list) and len(query_filters) == 0):
                if isinstance(query_filters, list):
                    filters.extend(query_filters)
                else:
                    filters.append(query_filters)

        # Apply source filter
        if source:
            source_obj = session.query(Source).filter_by(name=source).first()
            if source_obj:
                filters.append(Article.source_id == source_obj.id)
            else:
                raise HTTPException(status_code=404, detail=f"Source '{source}' not found.")

        # Apply date filters
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(Article.published_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                filters.append(Article.published_at <= end_dt)
            except ValueError:
                pass

        # Apply language filter
        if language:
            filters.append(Article.language == language)

        # Apply tags filter (filter by source tags)
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",")]
            # Find sources with any of the tags
            from sqlalchemy import or_
            tag_conditions = []
            for tag in tag_list:
                param = bindparam('tag_param', tag)
                tag_conditions.append(Source.tags.ilike('%' + param + '%'))
            source_ids = session.query(Source.id).filter(or_(*tag_conditions)).distinct().all()
            source_ids = [sid for (sid,) in source_ids]
            if source_ids:
                filters.append(Article.source_id.in_(source_ids))

        # Execute query
        from sqlalchemy import and_
        query_filters = and_(*filters) if filters else True
        articles_query = session.query(Article).filter(query_filters)

        # Count total results
        total = articles_query.count()

        # Apply pagination
        articles = articles_query.offset(offset).limit(limit).all()

        # Format results
        results = [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "canonical_url": a.canonical_url,
                "source": a.source.name if a.source else "Unknown",
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "language": a.language,
                "content": a.content[:500] + "..." if len(a.content) > 500 else a.content,  # Truncate long content
                "hash": a.hash
            } for a in articles
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": results
        }
    finally:
        session.close()


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
    tags: Optional[str] = None
):
    """
    Export articles in CSV or JSON format with advanced filters.

    Parameters:
    - format: Export format (csv or json).
    - query: Text to search in article content.
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
    - language: Filter by language code (e.g., "en", "fr").
    - tags: Filter by source tags (comma-separated).
    """
    logger.info(f"Export request: format={format}, query={query}, source={source}")

    # Validate date formats
    if start_date:
        try:
            datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
    if end_date:
        try:
            datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    session = get_session()
    try:
        filters = []

        # Parse and apply text query
        if query:
            parsed_query = parse_search_query(query)
            query_filters = build_sqlalchemy_filter(parsed_query, session)
            # query_filters is either a SQLAlchemy clause or empty list
            if not (isinstance(query_filters, list) and len(query_filters) == 0):
                if isinstance(query_filters, list):
                    filters.extend(query_filters)
                else:
                    filters.append(query_filters)

        # Apply source filter
        if source:
            source_obj = session.query(Source).filter_by(name=source).first()
            if source_obj:
                filters.append(Article.source_id == source_obj.id)

        # Apply date filters
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                filters.append(Article.published_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                filters.append(Article.published_at <= end_dt)
            except ValueError:
                pass

        # Apply language filter
        if language:
            filters.append(Article.language == language)

        # Apply tags filter
        if tags:
            tag_list = [tag.strip() for tag in tags.split(",")]
            from sqlalchemy import or_
            tag_conditions = []
            for tag in tag_list:
                param = bindparam('tag_param', tag)
                tag_conditions.append(Source.tags.ilike('%' + param + '%'))
            source_ids = session.query(Source.id).filter(or_(*tag_conditions)).distinct().all()
            source_ids = [sid for (sid,) in source_ids]
            if source_ids:
                filters.append(Article.source_id.in_(source_ids))

        # Execute query
        from sqlalchemy import and_
        query_filters = and_(*filters) if filters else True
        articles = session.query(Article).filter(query_filters).all()

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
                    a.hash or ""
                ])
            response = StreamingResponse(
                iter([stream.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=articles.csv"}
            )
            return response

        elif format == "json":
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
                        "hash": a.hash
                    } for a in articles
                ]
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported format. Use 'csv' or 'json'.")

    finally:
        session.close()


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
