"""
Pillar 6 Analysis Router

Router for rare earth analysis and correlation endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from datetime import date, datetime
import logging

from src.database.models import Session
from ..storage import storage
from ..api import (
    AnalysisResponse,
    CorrelationResponse,
    StatisticsResponse,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/pillar6/analyses", tags=["Analyses"])


class AnalysisRouter:
    """Router class for analysis-related endpoints."""
    
    def __init__(self):
        """Initialize the analysis router."""
        self.router = router
        self._setup_endpoints()
    
    def _setup_endpoints(self):
        """Setup all analysis endpoints."""
        
        @router.get(
            "/",
            summary="List All Analyses",
            response_description="List of all rare earth analysis results",
            response_model=List[AnalysisResponse],
        )
        async def list_analyses(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
            severity: Optional[str] = Query(None, description="Filter by severity level"),
            days: int = Query(7, description="Number of days of history"),
            limit: int = Query(100, description="Maximum number of results"),
        ):
            """List all rare earth analysis results with optional filters."""
            try:
                if element:
                    analyses = storage.get_analyses_by_element(element)
                elif analysis_type:
                    analyses = storage.get_analyses_by_type(analysis_type)
                elif severity:
                    analyses = storage.get_analyses_by_severity(severity)
                else:
                    analyses = storage.get_recent_analyses(days)
                
                # Apply limit
                analyses = analyses[:limit]
                
                # Enrich with element info
                enriched_analyses = []
                for analysis in analyses:
                    analysis_dict = analysis.to_dict()
                    
                    # Add element symbol
                    if analysis.element_id:
                        element_obj = storage.get_element_by_id(analysis.element_id)
                        if element_obj:
                            analysis_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_analyses.append(AnalysisResponse(**analysis_dict))
                
                return enriched_analyses
                
            except Exception as e:
                logger.error(f"Failed to list analyses: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/by-element/{element}",
            summary="Get Analyses by Element",
            response_description="Analysis results for a specific element",
            response_model=List[AnalysisResponse],
        )
        async def get_analyses_by_element(
            element: str = Path(..., description="Element chemical symbol"),
            analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
            days: int = Query(30, description="Number of days of history"),
            severity: Optional[str] = Query(None, description="Filter by severity"),
        ):
            """Get analysis results for a specific element."""
            try:
                analyses = storage.get_analyses_by_element(element)
                
                # Apply filters
                if analysis_type:
                    analyses = [a for a in analyses if a.analysis_type == analysis_type]
                if severity:
                    analyses = [a for a in analyses if a.severity == severity]
                
                # Filter by days
                if days > 0:
                    cutoff_date = datetime.utcnow().date() - timedelta(days=days)
                    analyses = [a for a in analyses if a.end_date >= cutoff_date]
                
                # Enrich with element info
                enriched_analyses = []
                for analysis in analyses:
                    analysis_dict = analysis.to_dict()
                    analysis_dict["element_symbol"] = element
                    enriched_analyses.append(AnalysisResponse(**analysis_dict))
                
                return enriched_analyses
                
            except Exception as e:
                logger.error(f"Failed to get analyses for element {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/by-type/{analysis_type}",
            summary="Get Analyses by Type",
            response_description="Analysis results of a specific type",
            response_model=List[AnalysisResponse],
        )
        async def get_analyses_by_type(
            analysis_type: str = Path(..., description="Analysis type"),
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get analysis results of a specific type."""
            try:
                analyses = storage.get_analyses_by_type(analysis_type)
                
                # Apply filters
                if element:
                    analyses = [a for a in analyses if a.element_id and storage.get_element_by_id(a.element_id).symbol == element]
                
                # Filter by days
                if days > 0:
                    cutoff_date = datetime.utcnow().date() - timedelta(days=days)
                    analyses = [a for a in analyses if a.end_date >= cutoff_date]
                
                # Enrich with element info
                enriched_analyses = []
                for analysis in analyses:
                    analysis_dict = analysis.to_dict()
                    
                    # Add element symbol
                    if analysis.element_id:
                        element_obj = storage.get_element_by_id(analysis.element_id)
                        if element_obj:
                            analysis_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_analyses.append(AnalysisResponse(**analysis_dict))
                
                return enriched_analyses
                
            except Exception as e:
                logger.error(f"Failed to get analyses by type {analysis_type}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/{analysis_id}",
            summary="Get Analysis by ID",
            response_description="Details of a specific analysis",
            response_model=AnalysisResponse,
        )
        async def get_analysis(
            analysis_id: int = Path(..., description="Analysis ID"),
        ):
            """Get a specific analysis by its ID."""
            try:
                analysis = storage.get_analysis_by_id(analysis_id)
                if not analysis:
                    raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")
                
                analysis_dict = analysis.to_dict()
                
                # Add element symbol
                if analysis.element_id:
                    element_obj = storage.get_element_by_id(analysis.element_id)
                    if element_obj:
                        analysis_dict["element_symbol"] = element_obj.symbol
                
                return AnalysisResponse(**analysis_dict)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to get analysis {analysis_id}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/trends/{element}",
            summary="Get Analysis Trends",
            response_description="Analysis trends for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_analysis_trends(
            element: str = Path(..., description="Element chemical symbol"),
            analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
            days: int = Query(90, description="Number of days of history"),
        ):
            """Get analysis trends for a specific element."""
            try:
                trends = storage.get_analysis_trends(element, analysis_type, days)
                return trends
                
            except Exception as e:
                logger.error(f"Failed to get analysis trends for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/statistics",
            summary="Get Analysis Statistics",
            response_description="Statistics about analysis results",
            response_model=Dict[str, Any],
        )
        async def get_analysis_statistics(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get statistics about analysis results."""
            try:
                stats = storage.get_analysis_statistics(element, analysis_type, days)
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get analysis statistics: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations",
            summary="List All Correlations",
            response_description="List of all article-REE correlations",
            response_model=List[CorrelationResponse],
        )
        async def list_correlations(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            article_id: Optional[int] = Query(None, description="Filter by article ID"),
            correlation_type: Optional[str] = Query(None, description="Filter by correlation type"),
            min_score: float = Query(0.0, description="Minimum correlation score"),
            limit: int = Query(100, description="Maximum number of results"),
        ):
            """List all article-REE correlations with optional filters."""
            try:
                if element:
                    correlations = storage.get_correlations_by_element(element)
                elif article_id:
                    correlations = storage.get_correlations_by_article(article_id)
                elif correlation_type:
                    correlations = storage.get_correlations_by_type(correlation_type)
                else:
                    correlations = storage.get_significant_correlations(min_score)
                
                # Apply limit
                correlations = correlations[:limit]
                
                # Enrich with element info
                enriched_correlations = []
                for correlation in correlations:
                    correlation_dict = correlation.to_dict()
                    
                    # Add element symbol
                    if correlation.element_id:
                        element_obj = storage.get_element_by_id(correlation.element_id)
                        if element_obj:
                            correlation_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_correlations.append(CorrelationResponse(**correlation_dict))
                
                return enriched_correlations
                
            except Exception as e:
                logger.error(f"Failed to list correlations: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations/{correlation_id}",
            summary="Get Correlation by ID",
            response_description="Details of a specific correlation",
            response_model=CorrelationResponse,
        )
        async def get_correlation(
            correlation_id: int = Path(..., description="Correlation ID"),
        ):
            """Get a specific correlation by its ID."""
            try:
                correlation = storage.get_correlation_by_id(correlation_id)
                if not correlation:
                    raise HTTPException(status_code=404, detail=f"Correlation {correlation_id} not found")
                
                correlation_dict = correlation.to_dict()
                
                # Add element symbol
                if correlation.element_id:
                    element_obj = storage.get_element_by_id(correlation.element_id)
                    if element_obj:
                        correlation_dict["element_symbol"] = element_obj.symbol
                
                return CorrelationResponse(**correlation_dict)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to get correlation {correlation_id}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations/by-element/{element}",
            summary="Get Correlations by Element",
            response_description="Correlations for a specific element",
            response_model=List[CorrelationResponse],
        )
        async def get_correlations_by_element(
            element: str = Path(..., description="Element chemical symbol"),
            correlation_type: Optional[str] = Query(None, description="Filter by correlation type"),
            min_score: float = Query(0.0, description="Minimum correlation score"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get correlations for a specific element."""
            try:
                correlations = storage.get_correlations_by_element(element)
                
                # Apply filters
                if correlation_type:
                    correlations = [c for c in correlations if c.correlation_type == correlation_type]
                if min_score > 0:
                    correlations = [c for c in correlations if c.correlation_score >= min_score]
                
                # Filter by days
                if days > 0:
                    cutoff_date = datetime.utcnow().date() - timedelta(days=days)
                    correlations = [c for c in correlations if c.date >= cutoff_date]
                
                # Enrich with element info
                enriched_correlations = []
                for correlation in correlations:
                    correlation_dict = correlation.to_dict()
                    correlation_dict["element_symbol"] = element
                    enriched_correlations.append(CorrelationResponse(**correlation_dict))
                
                return enriched_correlations
                
            except Exception as e:
                logger.error(f"Failed to get correlations for element {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations/by-article/{article_id}",
            summary="Get Correlations by Article",
            response_description="Correlations for a specific article",
            response_model=List[CorrelationResponse],
        )
        async def get_correlations_by_article(
            article_id: int = Path(..., description="Article ID"),
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            min_score: float = Query(0.0, description="Minimum correlation score"),
        ):
            """Get correlations for a specific article."""
            try:
                correlations = storage.get_correlations_by_article(article_id)
                
                # Apply filters
                if element:
                    correlations = [c for c in correlations if c.element_id and storage.get_element_by_id(c.element_id).symbol == element]
                if min_score > 0:
                    correlations = [c for c in correlations if c.correlation_score >= min_score]
                
                # Enrich with element info
                enriched_correlations = []
                for correlation in correlations:
                    correlation_dict = correlation.to_dict()
                    
                    # Add element symbol
                    if correlation.element_id:
                        element_obj = storage.get_element_by_id(correlation.element_id)
                        if element_obj:
                            correlation_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_correlations.append(CorrelationResponse(**correlation_dict))
                
                return enriched_correlations
                
            except Exception as e:
                logger.error(f"Failed to get correlations for article {article_id}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations/statistics",
            summary="Get Correlation Statistics",
            response_description="Statistics about correlations",
            response_model=Dict[str, Any],
        )
        async def get_correlation_statistics(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get statistics about correlations."""
            try:
                stats = storage.get_correlation_statistics(element, days)
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get correlation statistics: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/correlations/strongest",
            summary="Get Strongest Correlations",
            response_description="List of strongest correlations",
            response_model=List[CorrelationResponse],
        )
        async def get_strongest_correlations(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            limit: int = Query(10, description="Number of results"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get the strongest correlations."""
            try:
                correlations = storage.get_strongest_correlations(element, limit, days)
                
                # Enrich with element info
                enriched_correlations = []
                for correlation in correlations:
                    correlation_dict = correlation.to_dict()
                    
                    # Add element symbol
                    if correlation.element_id:
                        element_obj = storage.get_element_by_id(correlation.element_id)
                        if element_obj:
                            correlation_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_correlations.append(CorrelationResponse(**correlation_dict))
                
                return enriched_correlations
                
            except Exception as e:
                logger.error(f"Failed to get strongest correlations: {e}")
                raise HTTPException(status_code=500, detail=str(e))


# Import timedelta for date calculations
from datetime import timedelta

# Create router instance
analysis_router = AnalysisRouter()

# Export router
__all__ = ["router", "AnalysisRouter"]
