"""
Keyword Analysis API for Open Omniscience

Author: Open Omniscience Team
"""

import sys
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from fastapi import APIRouter, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from database.models import get_session, Article, Source
from services.article_intelligence import article_intelligence_analyzer

from utils.logging_config import setup_logging
logger = setup_logging("api.keyword_analysis")

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/articles/similarity")
@limiter.limit("50/hour")
async def calculate_article_similarity(
    request: Request,
    article_id1: int = Query(..., description="First article ID"),
    article_id2: int = Query(..., description="Second article ID"),
    method: str = Query("cosine", description="Similarity method")
):
    session = get_session()
    try:
        article1 = session.query(Article).filter(Article.id == article_id1).first()
        article2 = session.query(Article).filter(Article.id == article_id2).first()
        if not article1 or not article2:
            raise HTTPException(status_code=404, detail="One or both articles not found")
        similarity = article_intelligence_analyzer.calculate_similarity(
            article1.content, article2.content, method=method
        )
        return {"article_id1": article_id1, "article_id2": article_id2, "similarity": similarity, "method": method}
    finally:
        session.close()
