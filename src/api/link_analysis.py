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
Link Analysis API Endpoints for Open Omniscience

This module provides REST API endpoints for the Source/Link Tracking System,
including endpoints for:
- Link extraction and analysis
- Source identification and tracking
- Temporal analysis
- Network analysis
- Credibility scoring

Author: Open Omniscience Team
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import APIRouter, HTTPException, Query, Request, Body
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

# Import database models and session
from database.models import (
    Article, ExternalSource, SourceArticle, ArticleLink, 
    ArticleSourceRelationship, LinkClassificationRule, SourceCredibilityRule,
    get_session
)

# Import link analyzer services
from services.link_analyzer import (
    LinkAnalyzerService, LinkExtractor, LinkClassifier, 
    SourceIdentifier, SourceScraper, RelationshipTracker,
    TemporalAnalyzer, NetworkAnalyzer, CredibilityScorer, link_analyzer
)

# Configure logging
from utils.logging_config import setup_logging
logger = setup_logging("api.link_analysis")

# Create router
router = APIRouter(prefix="/api/link-analysis", tags=["Link Analysis"])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize services
link_extractor = LinkExtractor()
link_classifier = LinkClassifier()
source_identifier = SourceIdentifier()
source_scraper = SourceScraper()
relationship_tracker = RelationshipTracker()
temporal_analyzer = TemporalAnalyzer()
network_analyzer = NetworkAnalyzer()
credibility_scorer = CredibilityScorer()


# ============================================================================
# Link Extraction Endpoints
# ============================================================================

@router.post("/extract-links", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def extract_links(
    request: Request,
    html_content: str = Query(..., description="HTML content to extract links from"),
    base_url: Optional[str] = Query(None, description="Base URL for resolving relative links"),
    article_id: Optional[int] = Query(None, description="ID of the article")
):
    """
    Extract links from HTML content.
    
    This endpoint extracts all links from provided HTML content, including:
    - URL normalization
    - Link type detection
    - Link text extraction
    - Position tracking
    
    Returns:
        List of extracted links with metadata
    """
    try:
        links = link_extractor.extract_links(html_content, base_url, article_id)
        return JSONResponse(content={
            "success": True,
            "links": links,
            "count": len(links),
            "statistics": link_extractor.get_link_statistics(links)
        })
    except Exception as e:
        logger.error(f"Error extracting links: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify-links", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def classify_links(
    request: Request,
    links: List[Dict[str, Any]] = Body(..., description="List of links to classify")
):
    """
    Classify a list of links into categories.
    
    This endpoint classifies links into categories such as:
    - source: News articles, research papers, etc.
    - reference: Supporting information or citations
    - ad: Advertisement links
    - social: Social media links
    - navigation: Site navigation links
    - other: Other types of links
    
    Returns:
        List of classified links with classification field
    """
    try:
        classified_links = link_classifier.classify_links(links)
        return JSONResponse(content={
            "success": True,
            "classified_links": classified_links,
            "count": len(classified_links),
            "statistics": link_classifier.get_classification_statistics(classified_links)
        })
    except Exception as e:
        logger.error(f"Error classifying links: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/identify-sources", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def identify_sources(
    request: Request,
    links: List[Dict[str, Any]] = Body(..., description="List of links to identify sources from")
):
    """
    Identify external sources from a list of links.
    
    This endpoint analyzes links and identifies the external sources they reference,
    including source type, name, and other metadata.
    
    Returns:
        List of identified sources with metadata
    """
    try:
        sources = source_identifier.identify_sources(links)
        return JSONResponse(content={
            "success": True,
            "sources": sources,
            "count": len(sources),
            "statistics": source_identifier.get_source_statistics(sources)
        })
    except Exception as e:
        logger.error(f"Error identifying sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Comprehensive Analysis Endpoints
# ============================================================================

@router.post("/analyze-article", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def analyze_article(
    request: Request,
    html_content: str = Body(..., description="HTML content of the article"),
    article_url: Optional[str] = Body(None, description="URL of the article"),
    article_id: Optional[int] = Body(None, description="ID of the article in database"),
    published_at: Optional[str] = Body(None, description="Publication date of the article (ISO format)")
):
    """
    Perform comprehensive analysis of an article's links and sources.
    
    This endpoint performs a complete analysis pipeline:
    1. Extract all links from the HTML content
    2. Classify each link into categories
    3. Identify external sources
    4. Track relationships between article and sources
    5. Perform temporal analysis
    
    Returns:
        Comprehensive analysis results
    """
    try:
        # Extract links
        extracted_links = link_extractor.extract_links(html_content, article_url, article_id)
        
        # Classify links
        classified_links = link_classifier.classify_links(extracted_links)
        
        # Identify sources
        identified_sources = source_identifier.identify_sources(classified_links)
        
        # Track relationships
        relationships = relationship_tracker.track_relationships(
            article_id or 0, 
            classified_links, 
            identified_sources,
            article_published_at=published_at
        )
        
        # Perform temporal analysis
        temporal_analysis = temporal_analyzer.analyze_temporal_patterns(
            article_id or 0, 
            relationships,
            article_published_at=published_at
        )
        
        return JSONResponse(content={
            "success": True,
            "article_id": article_id,
            "article_url": article_url,
            "published_at": published_at,
            "extracted_links": extracted_links,
            "classified_links": classified_links,
            "identified_sources": identified_sources,
            "relationships": relationships,
            "temporal_analysis": temporal_analysis,
            "statistics": {
                "total_links": len(extracted_links),
                "total_sources": len(identified_sources),
                "total_relationships": len(relationships)
            }
        })
    except Exception as e:
        logger.error(f"Error analyzing article: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Source Scraping Endpoints
# ============================================================================

@router.post("/scrape-source", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def scrape_source(
    request: Request,
    url: str = Body(..., description="URL of the source article to scrape")
):
    """
    Scrape an article from an external source.
    
    This endpoint fetches and parses an article from a given URL, extracting:
    - Title
    - Author
    - Publication date
    - Main content
    - Summary
    - Language
    - Metadata
    
    Returns:
        Scraped article information
    """
    try:
        article_info = source_scraper.scrape_source_article(url)
        if not article_info:
            raise HTTPException(status_code=404, detail="Failed to scrape article")
        
        return JSONResponse(content={
            "success": True,
            "article": article_info
        })
    except Exception as e:
        logger.error(f"Error scraping source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-url", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def check_url(
    request: Request,
    url: str = Query(..., description="URL to check")
):
    """
    Check if a URL is accessible.
    
    Returns:
        URL accessibility information
    """
    try:
        is_accessible, http_status, redirect_url = source_scraper.check_url_accessibility(url)
        return JSONResponse(content={
            "success": True,
            "url": url,
            "is_accessible": is_accessible,
            "http_status": http_status,
            "redirect_url": redirect_url
        })
    except Exception as e:
        logger.error(f"Error checking URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Temporal Analysis Endpoints
# ============================================================================

@router.post("/temporal-analysis", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def temporal_analysis(request: Request, 
    relationships: List[Dict[str, Any]] = Body(..., description="List of relationships to analyze"),
    article_published_at: Optional[str] = Body(None, description="Publication date of the article")
):
    """
    Perform temporal analysis on article-source relationships.
    
    Returns:
        Temporal analysis results
    """
    try:
        analysis = temporal_analyzer.analyze_temporal_patterns(
            0, relationships, article_published_at
        )
        return JSONResponse(content={
            "success": True,
            "analysis": analysis
        })
    except Exception as e:
        logger.error(f"Error performing temporal analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect-anomalies", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def detect_anomalies(request: Request, 
    relationships: List[Dict[str, Any]] = Body(..., description="List of relationships to check for anomalies"),
    threshold_days: float = Body(0.0, description="Time delta threshold for anomaly detection")
):
    """
    Detect temporal anomalies in article-source relationships.
    
    Returns:
        List of relationships with temporal anomalies
    """
    try:
        anomalies = temporal_analyzer.detect_temporal_anomalies(relationships, threshold_days)
        return JSONResponse(content={
            "success": True,
            "anomalies": anomalies,
            "count": len(anomalies)
        })
    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Network Analysis Endpoints
# ============================================================================

@router.post("/network-analysis", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def network_analysis(request: Request, 
    relationships: List[Dict[str, Any]] = Body(..., description="List of relationships to analyze"),
    graph_type: str = Body("directed", description="Type of graph to build")
):
    """
    Perform network analysis on article-source relationships.
    
    Returns:
        Network analysis results
    """
    try:
        analysis = network_analyzer.analyze_network(relationships, graph_type)
        return JSONResponse(content={
            "success": True,
            "analysis": analysis
        })
    except Exception as e:
        logger.error(f"Error performing network analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/network-statistics", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def network_statistics(request: Request, 
    relationships: List[Dict[str, Any]] = Body(..., description="List of relationships to analyze")
):
    """
    Get statistics about the source relationship network.
    
    Returns:
        Network statistics
    """
    try:
        stats = network_analyzer.get_network_statistics(relationships)
        return JSONResponse(content={
            "success": True,
            "statistics": stats
        })
    except Exception as e:
        logger.error(f"Error calculating network statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Credibility Scoring Endpoints
# ============================================================================

@router.post("/credibility-score", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def credibility_score(request: Request, 
    source_info: Dict[str, Any] = Body(..., description="Source information to score")
):
    """
    Calculate credibility score for a source.
    
    Returns:
        Credibility score and category
    """
    try:
        score = credibility_scorer.calculate_score(source_info)
        category = credibility_scorer.get_credibility_categories(score)
        return JSONResponse(content={
            "success": True,
            "source": source_info.get('domain', 'unknown'),
            "credibility_score": score,
            "category": category
        })
    except Exception as e:
        logger.error(f"Error calculating credibility score: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/credibility-scores", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def credibility_scores(request: Request, 
    sources: List[Dict[str, Any]] = Body(..., description="List of sources to score")
):
    """
    Calculate credibility scores for multiple sources.
    
    Returns:
        Credibility scores for each source
    """
    try:
        scores = credibility_scorer.calculate_scores(sources)
        return JSONResponse(content={
            "success": True,
            "scores": scores
        })
    except Exception as e:
        logger.error(f"Error calculating credibility scores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rank-sources", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def rank_sources(request: Request, 
    sources: List[Dict[str, Any]] = Body(..., description="List of sources to rank"),
    limit: int = Body(10, description="Maximum number of sources to return")
):
    """
    Rank sources by credibility score.
    
    Returns:
        List of ranked sources
    """
    try:
        ranked = credibility_scorer.rank_sources_by_credibility(sources, limit)
        return JSONResponse(content={
            "success": True,
            "ranked_sources": ranked
        })
    except Exception as e:
        logger.error(f"Error ranking sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/credibility-distribution", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def credibility_distribution(request: Request, 
    sources: List[Dict[str, Any]] = Body(..., description="List of sources to analyze"),
    bins: int = Body(10, description="Number of bins for histogram")
):
    """
    Get the distribution of credibility scores.
    
    Returns:
        Credibility score distribution
    """
    try:
        distribution = credibility_scorer.get_credibility_distribution(sources, bins)
        return JSONResponse(content={
            "success": True,
            "distribution": distribution
        })
    except Exception as e:
        logger.error(f"Error calculating credibility distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Classification Rule Management Endpoints
# ============================================================================

@router.get("/classification-rules", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def get_classification_rules(request: Request):
    """
    Get all link classification rules.
    
    Returns:
        List of classification rules
    """
    try:
        rules = link_classifier.get_rules()
        return JSONResponse(content={
            "success": True,
            "rules": rules
        })
    except Exception as e:
        logger.error(f"Error getting classification rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classification-rules", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def add_classification_rule(request: Request, 
    rule_name: str = Body(..., description="Name of the rule"),
    pattern: str = Body(..., description="Regex pattern to match"),
    classification_type: str = Body(..., description="Classification type"),
    priority: int = Body(1, description="Priority of the rule"),
    is_active: bool = Body(True, description="Whether the rule is active"),
    apply_to: List[str] = Body(["domain"], description="Fields to apply the rule to")
):
    """
    Add a custom classification rule.
    
    Returns:
        Success status
    """
    try:
        success = link_classifier.add_custom_rule(
            rule_name, pattern, classification_type, priority, is_active, apply_to
        )
        if success:
            return JSONResponse(content={"success": True, "message": "Rule added successfully"})
        else:
            raise HTTPException(status_code=400, detail="Failed to add rule")
    except Exception as e:
        logger.error(f"Error adding classification rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/classification-rules/{rule_name}", response_model=Dict[str, Any])
@limiter.limit("5/minute")
async def remove_classification_rule(request: Request, 
    rule_name: str
):
    """
    Remove a classification rule.
    
    Returns:
        Success status
    """
    try:
        success = link_classifier.remove_rule(rule_name)
        if success:
            return JSONResponse(content={"success": True, "message": "Rule removed successfully"})
        else:
            raise HTTPException(status_code=404, detail="Rule not found")
    except Exception as e:
        logger.error(f"Error removing classification rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check Endpoint
# ============================================================================

@router.get("/health", response_model=Dict[str, Any])
@limiter.limit("10/minute")
async def health_check(request: Request):
    """
    Health check endpoint for link analysis service.
    
    Returns:
        Service health status
    """
    return JSONResponse(content={
        "success": True,
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "link_extractor": "available",
            "link_classifier": "available",
            "source_identifier": "available",
            "source_scraper": "available",
            "relationship_tracker": "available",
            "temporal_analyzer": "available",
            "network_analyzer": "available",
            "credibility_scorer": "available"
        }
    })



