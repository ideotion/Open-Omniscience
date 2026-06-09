"""Article date-tag API: extracted, human-confirmable dates mentioned in article text.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The dates a story is *about* (not its publication date) become per-article tags: a
high-precision extractor proposes candidates with provenance; the user confirms or
rejects; and the corpus can be filtered by a mentioned date. Read/write, offline, local.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.database.models import Article
from src.database.session import get_db
from src.timemap import datestore

router = APIRouter(prefix="/api/article-dates", tags=["article-dates"])

_CAVEAT = ("Dates mentioned in the article's text, extracted high-precision (explicit "
           "dates only — no bare years or relative phrases). Each is a candidate with its "
           "matched snippet; you confirm or reject. The date is when the story refers to, "
           "not when it was published.")


@router.get("/article/{article_id}")
def list_for_article(article_id: int, db: Session = Depends(get_db)) -> dict:
    """The date tags already stored for one article."""
    return {"article_id": article_id, "tags": datestore.for_article(db, article_id),
            "caveat": _CAVEAT}


@router.post("/article/{article_id}")
def extract_for_article(article_id: int, db: Session = Depends(get_db)) -> dict:
    """Extract dates from one article's text now and store any new candidates."""
    art = db.get(Article, article_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Article not found")
    added = datestore.store_for_article(db, art)
    return {"article_id": article_id, "added": added,
            "tags": datestore.for_article(db, article_id), "caveat": _CAVEAT}


@router.post("/index")
def index(days: int | None = Query(None, ge=1, le=36500),
          limit: int = Query(500, ge=1, le=5000),
          db: Session = Depends(get_db)) -> dict:
    """Batch-extract date tags for recent articles (mirrors Insights corpus indexing)."""
    return datestore.index_recent(db, days=days, limit=limit)


@router.post("/{tag_id}/confirm")
def confirm(tag_id: int, db: Session = Depends(get_db)) -> dict:
    row = datestore.set_status(db, tag_id, "confirmed")
    if row is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return row


@router.post("/{tag_id}/reject")
def reject(tag_id: int, db: Session = Depends(get_db)) -> dict:
    row = datestore.set_status(db, tag_id, "rejected")
    if row is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return row


@router.get("/by-date")
def by_date(date: str = Query(..., description="ISO date, e.g. 2001-09-11"),
            precision: str | None = Query(None, description="day|month"),
            status: str | None = Query(None, description="candidate|confirmed|rejected"),
            limit: int = Query(100, ge=1, le=1000),
            db: Session = Depends(get_db)) -> dict:
    """Articles that mention a given date — filter the corpus by a date tag."""
    items = datestore.articles_for_date(db, date_str=date, precision=precision,
                                        status=status, limit=limit)
    return {"date": date, "count": len(items), "articles": items}
