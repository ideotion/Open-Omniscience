"""
Pillar 6 Production Router

Router for rare earth production data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from datetime import date, datetime
import logging

from src.database.models import Session
from ..storage import storage
from ..api import (
    ProductionResponse,
    StatisticsResponse,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/pillar6/productions", tags=["Productions"])


class ProductionRouter:
    """Router class for production-related endpoints."""
    
    def __init__(self):
        """Initialize the production router."""
        self.router = router
        self._setup_endpoints()
    
    def _setup_endpoints(self):
        """Setup all production endpoints."""
        
        @router.get(
            "/",
            summary="List All Productions",
            response_description="List of all rare earth production data points",
            response_model=List[ProductionResponse],
        )
        async def list_productions(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            company: Optional[str] = Query(None, description="Filter by company"),
            year: Optional[int] = Query(None, description="Filter by year"),
            production_type: Optional[str] = Query(None, description="Filter by production type"),
            limit: int = Query(100, description="Maximum number of results"),
        ):
            """List all rare earth production data points with optional filters."""
            try:
                if element:
                    productions = storage.get_productions_by_element(element)
                elif country:
                    productions = storage.get_productions_by_country(country)
                elif company:
                    productions = storage.get_productions_by_company(company)
                elif year:
                    productions = storage.get_productions_by_year(year)
                elif production_type:
                    productions = storage.get_productions_by_type(production_type)
                else:
                    # Get all productions (limited)
                    productions = storage.get_all_productions(limit)
                
                # Apply limit
                productions = productions[:limit]
                
                # Enrich with element info
                enriched_productions = []
                for production in productions:
                    production_dict = production.to_dict()
                    
                    # Add element symbol
                    if production.element_id:
                        element_obj = storage.get_element_by_id(production.element_id)
                        if element_obj:
                            production_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_productions.append(ProductionResponse(**production_dict))
                
                return enriched_productions
                
            except Exception as e:
                logger.error(f"Failed to list productions: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/by-element/{element}",
            summary="Get Productions by Element",
            response_description="Production data for a specific element",
            response_model=List[ProductionResponse],
        )
        async def get_productions_by_element(
            element: str = Path(..., description="Element chemical symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            company: Optional[str] = Query(None, description="Filter by company"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Get production data for a specific element."""
            try:
                productions = storage.get_productions_by_element(element)
                
                # Apply filters
                if country:
                    productions = [p for p in productions if p.country == country]
                if company:
                    productions = [p for p in productions if p.company == company]
                if start_year:
                    productions = [p for p in productions if p.year >= start_year]
                if end_year:
                    productions = [p for p in productions if p.year <= end_year]
                
                # Enrich with element info
                enriched_productions = []
                for production in productions:
                    production_dict = production.to_dict()
                    production_dict["element_symbol"] = element
                    enriched_productions.append(ProductionResponse(**production_dict))
                
                return enriched_productions
                
            except Exception as e:
                logger.error(f"Failed to get productions for element {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/by-country/{country}",
            summary="Get Productions by Country",
            response_description="Production data for a specific country",
            response_model=List[ProductionResponse],
        )
        async def get_productions_by_country(
            country: str = Path(..., description="Country name"),
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            company: Optional[str] = Query(None, description="Filter by company"),
            year: Optional[int] = Query(None, description="Filter by year"),
        ):
            """Get production data for a specific country."""
            try:
                productions = storage.get_productions_by_country(country)
                
                # Apply filters
                if element:
                    productions = [p for p in productions if p.element_id and storage.get_element_by_id(p.element_id).symbol == element]
                if company:
                    productions = [p for p in productions if p.company == company]
                if year:
                    productions = [p for p in productions if p.year == year]
                
                # Enrich with element info
                enriched_productions = []
                for production in productions:
                    production_dict = production.to_dict()
                    
                    # Add element symbol
                    if production.element_id:
                        element_obj = storage.get_element_by_id(production.element_id)
                        if element_obj:
                            production_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_productions.append(ProductionResponse(**production_dict))
                
                return enriched_productions
                
            except Exception as e:
                logger.error(f"Failed to get productions for country {country}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/by-company/{company}",
            summary="Get Productions by Company",
            response_description="Production data for a specific company",
            response_model=List[ProductionResponse],
        )
        async def get_productions_by_company(
            company: str = Path(..., description="Company name"),
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            year: Optional[int] = Query(None, description="Filter by year"),
        ):
            """Get production data for a specific company."""
            try:
                productions = storage.get_productions_by_company(company)
                
                # Apply filters
                if element:
                    productions = [p for p in productions if p.element_id and storage.get_element_by_id(p.element_id).symbol == element]
                if country:
                    productions = [p for p in productions if p.country == country]
                if year:
                    productions = [p for p in productions if p.year == year]
                
                # Enrich with element info
                enriched_productions = []
                for production in productions:
                    production_dict = production.to_dict()
                    
                    # Add element symbol
                    if production.element_id:
                        element_obj = storage.get_element_by_id(production.element_id)
                        if element_obj:
                            production_dict["element_symbol"] = element_obj.symbol
                    
                    enriched_productions.append(ProductionResponse(**production_dict))
                
                return enriched_productions
                
            except Exception as e:
                logger.error(f"Failed to get productions for company {company}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/statistics/{element}",
            summary="Get Production Statistics",
            response_description="Production statistics for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_production_statistics(
            element: str = Path(..., description="Element chemical symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Get production statistics for a specific element."""
            try:
                stats = storage.get_production_statistics(element, country, start_year, end_year)
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get production statistics for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/statistics-by-country/{country}",
            summary="Get Production Statistics by Country",
            response_description="Production statistics for a specific country",
            response_model=Dict[str, Any],
        )
        async def get_production_statistics_by_country(
            country: str = Path(..., description="Country name"),
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Get production statistics for a specific country."""
            try:
                stats = storage.get_production_statistics_by_country(country, element, start_year, end_year)
                return stats
                
            except Exception as e:
                logger.error(f"Failed to get production statistics for country {country}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/trends/{element}",
            summary="Get Production Trends",
            response_description="Production trends for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_production_trends(
            element: str = Path(..., description="Element chemical symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Get production trends for a specific element."""
            try:
                trends = storage.get_production_trends(element, country, start_year, end_year)
                return trends
                
            except Exception as e:
                logger.error(f"Failed to get production trends for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/comparison",
            summary="Compare Production Across Countries",
            response_description="Compare production for an element across different countries",
            response_model=Dict[str, Any],
        )
        async def compare_production(
            element: str = Query(..., description="Element chemical symbol"),
            countries: Optional[List[str]] = Query(None, description="List of countries to compare"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Compare production for an element across different countries."""
            try:
                if countries:
                    countries_list = countries
                else:
                    # Get all countries that produce this element
                    all_productions = storage.get_productions_by_element(element)
                    countries_list = list(set([p.country for p in all_productions]))
                
                comparison = {}
                for country in countries_list:
                    productions = storage.get_productions_by_country(country)
                    element_productions = [p for p in productions if p.element_id and storage.get_element_by_id(p.element_id).symbol == element]
                    
                    # Apply year filters
                    if start_year:
                        element_productions = [p for p in element_productions if p.year >= start_year]
                    if end_year:
                        element_productions = [p for p in element_productions if p.year <= end_year]
                    
                    if element_productions:
                        comparison[country] = [p.to_dict() for p in element_productions]
                
                return {
                    "element": element,
                    "comparison": comparison,
                    "countries": countries_list,
                    "start_year": start_year,
                    "end_year": end_year,
                }
                
            except Exception as e:
                logger.error(f"Failed to compare production for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/rankings",
            summary="Get Production Rankings",
            response_description="Ranking of countries by production volume",
            response_model=Dict[str, Any],
        )
        async def get_production_rankings(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            year: Optional[int] = Query(None, description="Filter by year"),
            limit: int = Query(10, description="Number of top producers to return"),
        ):
            """Get ranking of countries by production volume."""
            try:
                rankings = storage.get_production_rankings(element, year, limit)
                return rankings
                
            except Exception as e:
                logger.error(f"Failed to get production rankings: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/growth/{element}",
            summary="Get Production Growth",
            response_description="Production growth for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_production_growth(
            element: str = Path(..., description="Element chemical symbol"),
            country: Optional[str] = Query(None, description="Filter by country"),
            start_year: Optional[int] = Query(None, description="Start year"),
            end_year: Optional[int] = Query(None, description="End year"),
        ):
            """Get production growth for a specific element."""
            try:
                growth = storage.get_production_growth(element, country, start_year, end_year)
                return growth
                
            except Exception as e:
                logger.error(f"Failed to get production growth for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))


# Create router instance
production_router = ProductionRouter()

# Export router
__all__ = ["router", "ProductionRouter"]
