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
Keyword Management API for Open Omniscience

This module provides FastAPI endpoints for keyword extraction and management.

Author: Open Omniscience Team
"""


from fastapi import APIRouter, HTTPException, Query, Request

# Import database models and session
# Import services
from src.services.keyword_extractor import keyword_extractor
from src.services.text_processor import text_processor

# Configure logging
from src.utils.logging_config import setup_logging

logger = setup_logging("api.keyword")

# Create router
router = APIRouter(prefix="/api/keywords", tags=["Keywords"])

# Rate limiter
from src.api.ratelimit import limiter


@router.get("/extract", response_model=dict)
@limiter.limit("100/hour")
def extract_keywords(
    request: Request,
    text: str = Query(..., description="Text to extract keywords from"),
    language: str = Query("en", description="Language code"),
    include_ngrams: bool = Query(True, description="Whether to include n-grams"),
    min_frequency: int | None = Query(None, description="Minimum frequency for keywords"),
    top_n: int | None = Query(None, description="Number of top keywords to return")
):
    """Extract keywords from text."""
    try:
        result = keyword_extractor.extract_keywords(
            text, language=language, include_ngrams=include_ngrams,
            min_frequency=min_frequency
        )
        
        if top_n:
            result["keywords"] = result["keywords"][:top_n]
        
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Error extracting keywords: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/article", response_model=dict)
@limiter.limit("100/hour")
def extract_article_keywords(
    request: Request,
    article_text: str = Query(..., description="Article content"),
    title: str | None = Query("", description="Article title"),
    language: str = Query("en", description="Language code"),
    title_weight: float = Query(2.0, description="Weight for title keywords")
):
    """Extract keywords from an article with title weighting."""
    try:
        result = keyword_extractor.extract_keywords_from_article(
            article_text, title=title, language=language, title_weight=title_weight
        )
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Error extracting article keywords: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories", response_model=dict)
@limiter.limit("100/hour")
def get_keyword_categories(request: Request):
    """Get all keyword categories."""
    try:
        categories = list(keyword_extractor.keyword_categories.keys())
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categorize", response_model=dict)
@limiter.limit("100/hour")
def categorize_keywords(
    request: Request,
    keywords: list[str] = Query(..., description="List of keywords to categorize")
):
    """Categorize a list of keywords."""
    try:
        categories = keyword_extractor.categorize_keywords(keywords)
        return {"success": True, "categories": categories}
    except Exception as e:
        logger.error(f"Error categorizing keywords: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top", response_model=dict)
@limiter.limit("100/hour")
def get_top_keywords(
    request: Request,
    text: str = Query(..., description="Text to analyze"),
    language: str = Query("en", description="Language code"),
    top_n: int = Query(10, description="Number of top keywords"),
    include_scores: bool = Query(False, description="Whether to include relevance scores")
):
    """Get top N keywords from text."""
    try:
        top_keywords = keyword_extractor.get_top_keywords(
            text, language=language, top_n=top_n, include_scores=include_scores
        )
        return {"success": True, "top_keywords": top_keywords}
    except Exception as e:
        logger.error(f"Error getting top keywords: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/phrases", response_model=dict)
@limiter.limit("100/hour")
def extract_key_phrases(
    request: Request,
    text: str = Query(..., description="Text to analyze"),
    language: str = Query("en", description="Language code"),
    min_phrase_length: int = Query(2, description="Minimum phrase length"),
    max_phrase_length: int = Query(5, description="Maximum phrase length"),
    top_n: int = Query(10, description="Number of top phrases")
):
    """Extract key phrases from text."""
    try:
        phrases = keyword_extractor.extract_key_phrases(
            text, language=language, min_phrase_length=min_phrase_length,
            max_phrase_length=max_phrase_length, top_n=top_n
        )
        return {"success": True, "phrases": phrases}
    except Exception as e:
        logger.error(f"Error extracting key phrases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", response_model=dict)
@limiter.limit("100/hour")
def get_keyword_statistics(
    request: Request,
    text: str = Query(..., description="Text to analyze"),
    language: str = Query("en", description="Language code")
):
    """Get comprehensive keyword statistics for text."""
    try:
        stats = keyword_extractor.get_keyword_statistics(text, language=language)
        return {"success": True, "statistics": stats}
    except Exception as e:
        logger.error(f"Error getting keyword statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/process", response_model=dict)
@limiter.limit("100/hour")
def process_text(
    request: Request,
    text: str = Query(..., description="Text to process"),
    language: str = Query("en", description="Language code")
):
    """Process text through the complete pipeline."""
    try:
        result = text_processor.process_text(text, language=language)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frequencies", response_model=dict)
@limiter.limit("100/hour")
def get_word_frequencies(
    request: Request,
    text: str = Query(..., description="Text to analyze"),
    language: str = Query("en", description="Language code")
):
    """Get word frequencies from text."""
    try:
        frequencies = text_processor.get_word_frequency(text, language=language)
        return {"success": True, "frequencies": frequencies}
    except Exception as e:
        logger.error(f"Error getting word frequencies: {e}")
        raise HTTPException(status_code=500, detail=str(e))
