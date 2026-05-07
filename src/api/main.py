from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime
from typing import Optional
import csv
import io

# Import database models and session
from database.models import Article, Source, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database setup
DATABASE_URL = "sqlite:///../../data/open_omniscience.db"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Open Omniscience API")

# Serve static files (HTML5 frontend)
app.mount("/", StaticFiles(directory="../static", html=True), name="static")


# API Endpoints
@app.get("/api/articles", response_model=list)
def search_articles(
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
    session = Session()
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
    session.close()
    
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


@app.get("/api/articles/export")
def export_articles(
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
    session = Session()
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
    session.close()
    
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


@app.get("/api/sources", response_model=list)
def list_sources():
    """List all available news sources."""
    session = Session()
    sources = session.query(Source).all()
    session.close()
    return [{"id": s.id, "name": s.name, "domain": s.domain} for s in sources]


# Root endpoint to serve index.html
@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("../static/index.html", "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)
