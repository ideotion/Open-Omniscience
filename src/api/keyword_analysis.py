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

"""
Keyword Analysis API for Open Omniscience

Author: Open Omniscience Team
"""

from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.database.models import get_session, Article, Source
from src.services.article_intelligence import article_intelligence_analyzer

from src.utils.logging_config import setup_logging
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
