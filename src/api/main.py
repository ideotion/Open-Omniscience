"""
FastAPI Backend for Open Omniscience

This module provides the FastAPI backend for the Open Omniscience project,
including endpoints for searching articles, exporting data, and listing sources.
It also serves the HTML5 frontend static files and includes rate limiting.

Author: Ideotion
"""

import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from datetime import datetime
from typing import Optional
import csv
import io
import logging

# Import database models and session
from database.models import Article, Source, get_session

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("api")

# Database setup
DATABASE_URL = f"sqlite:///{Path(__file__).parent.parent.parent / 'data' / 'open_omniscience.db'}"

# Initialize FastAPI app
app = FastAPI(title="Open Omniscience API", version="0.1.0")

# Rate limiter setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# CORS middleware (optional, for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (HTML5 frontend)
app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "static"), html=True), name="static")


# Rate limit exceeded handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"Rate limit exceeded for {get_remote_address(request)}: {request.url}")
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
        headers={"Retry-After": str(exc.retry_after)}
    )


# API Endpoints
@app.get("/api/articles", response_model=list)
@limiter.limit("100/hour")
async def search_articles(
    request: Request,
    query: Optional[str] = None,
    source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
):
    """
    Search and filter articles.
    
    Parameters:
    - query: Text to search in article content.
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
    - limit: Maximum number of results to return.
    """
    logger.info(f"Search request: query={query}, source={source}, limit={limit}")
    
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
        
        if query:
            filters.append(Article.content.ilike(f"%{query}%"))
        if source:
            source_obj = session.query(Source).filter_by(name=source).first()
            if source_obj:
                filters.append(Article.source_id == source_obj.id)
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
        
        articles = session.query(Article).filter(*filters).limit(limit).all()
        
        return [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source": a.source.name if a.source else "Unknown",
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "content": a.content
            } for a in articles
        ]
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
    end_date: Optional[str] = None
):
    """
    Export articles in CSV or JSON format.
    
    Parameters:
    - format: Export format (csv or json).
    - query: Text to search in article content.
    - source: Filter by source name.
    - start_date: Filter by start date (YYYY-MM-DD).
    - end_date: Filter by end date (YYYY-MM-DD).
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
        
        if query:
            filters.append(Article.content.ilike(f"%{query}%"))
        if source:
            source_obj = session.query(Source).filter_by(name=source).first()
            if source_obj:
                filters.append(Article.source_id == source_obj.id)
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
        
        articles = session.query(Article).filter(*filters).all()
        
        if format == "csv":
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(["ID", "Title", "URL", "Source", "Published At", "Content"])
            for a in articles:
                writer.writerow([
                    a.id,
                    a.title or "",
                    a.url or "",
                    a.source.name if a.source else "",
                    a.published_at.isoformat() if a.published_at else "",
                    a.content or ""
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
                        "source": a.source.name if a.source else "Unknown",
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "content": a.content
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
    """List all available news sources."""
    logger.info("List sources request")
    session = get_session()
    try:
        sources = session.query(Source).all()
        return [{"id": s.id, "name": s.name, "domain": s.domain} for s in sources]
    finally:
        session.close()


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    with open(index_path, "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)