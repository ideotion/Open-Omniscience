"""
Pillar 6 REST API

Main FastAPI application for rare earth market intelligence.
"""

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field
import logging

from src.database.models import Session
from ..storage import storage
from ..models import (
    RareEarthElement,
    RareEarthMarket,
    RareEarthPrice,
    RareEarthProduction,
    RareEarthInventory,
    RareEarthAnalysis,
    ArticleRareEarthLink,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Pillar 6: Rare Earth Market Intelligence API",
    description="REST API for rare earth market data, analysis, and correlations",
    version="0.1.0",
    docs_url="/pillar6/docs",
    redoc_url="/pillar6/redoc",
    openapi_url="/pillar6/openapi.json",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create router
router = APIRouter(prefix="/pillar6", tags=["Pillar 6"])


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================

class ElementResponse(BaseModel):
    """Response model for rare earth element."""
    id: Optional[int] = None
    symbol: str
    name: str
    atomic_number: int
    category: str
    element_type: str
    atomic_weight: Optional[float] = None
    melting_point: Optional[float] = None
    boiling_point: Optional[float] = None
    density: Optional[float] = None
    discovery_year: Optional[int] = None
    common_uses: List[str] = []
    is_critical: bool = False
    aliases: List[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class MarketResponse(BaseModel):
    """Response model for rare earth market."""
    id: Optional[int] = None
    market_id: str
    name: str
    market_type: str
    region: str
    currency: str
    description: str = ""
    website: Optional[str] = None
    is_active: bool = True
    data_sources: List[str] = []
    supported_elements: List[str] = []
    update_frequency: str = "daily"
    last_updated: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class PriceResponse(BaseModel):
    """Response model for rare earth price."""
    id: Optional[int] = None
    element_id: Optional[int] = None
    market_id: Optional[int] = None
    element_symbol: Optional[str] = None
    market_name: Optional[str] = None
    price: float
    currency: str
    price_type: str
    price_unit: str
    purity_grade: str
    date: date
    timestamp: Optional[str] = None
    source_url: Optional[str] = None
    is_verified: bool = False
    confidence: float = 1.0
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    price_per_kg: Optional[float] = None
    
    class Config:
        from_attributes = True


class ProductionResponse(BaseModel):
    """Response model for rare earth production."""
    id: Optional[int] = None
    element_id: Optional[int] = None
    element_symbol: Optional[str] = None
    country: str
    amount: float
    production_type: str
    production_unit: str
    year: int
    quarter: Optional[int] = None
    month: Optional[int] = None
    date: Optional[date] = None
    company: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    is_estimated: bool = True
    confidence: float = 1.0
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    tonnes: Optional[float] = None
    
    class Config:
        from_attributes = True


class InventoryResponse(BaseModel):
    """Response model for rare earth inventory."""
    id: Optional[int] = None
    element_id: Optional[int] = None
    element_symbol: Optional[str] = None
    country: str
    amount: float
    inventory_type: str
    inventory_unit: str
    year: int
    date: Optional[date] = None
    holder: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    is_estimated: bool = True
    confidence: float = 1.0
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    tonnes: Optional[float] = None
    
    class Config:
        from_attributes = True


class AnalysisResponse(BaseModel):
    """Response model for rare earth analysis."""
    id: Optional[int] = None
    element_id: Optional[int] = None
    element_symbol: Optional[str] = None
    analysis_type: str
    start_date: date
    end_date: date
    results: Dict[str, Any] = {}
    severity: str
    confidence: float = 1.0
    direction: str
    magnitude: float = 0.0
    insights: str = ""
    recommendations: List[str] = []
    related_articles: List[str] = []
    related_markets: List[str] = []
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    significance: Optional[float] = None
    summary: Optional[str] = None
    
    class Config:
        from_attributes = True


class CorrelationResponse(BaseModel):
    """Response model for article-REE correlation."""
    id: Optional[int] = None
    article_id: int
    element_id: Optional[int] = None
    element_symbol: Optional[str] = None
    correlation_type: str
    correlation_score: float = 0.0
    correlation_strength: str
    sentiment: str
    sentiment_score: float = 0.0
    date: date
    time_lag_days: int = 0
    price_change_pct: Optional[float] = None
    volume_change_pct: Optional[float] = None
    keywords: List[str] = []
    entities: List[str] = []
    confidence: float = 1.0
    insights: str = ""
    is_significant: bool = False
    p_value: Optional[float] = None
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    strength_level: Optional[int] = None
    sentiment_label: Optional[str] = None
    significance_score: Optional[float] = None
    summary: Optional[str] = None
    
    class Config:
        from_attributes = True


class StatisticsResponse(BaseModel):
    """Response model for statistics."""
    count: int = 0
    min: Optional[float] = None
    max: Optional[float] = None
    avg: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    latest: Optional[float] = None
    volatility: Optional[float] = None
    
    class Config:
        from_attributes = True


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/", summary="API Root", response_description="Pillar 6 API information")
async def api_root():
    """Get Pillar 6 API information."""
    return {
        "name": "Pillar 6: Rare Earth Market Intelligence API",
        "version": "0.1.0",
        "description": "REST API for rare earth market data, analysis, and correlations",
        "endpoints": {
            "elements": "/pillar6/elements",
            "markets": "/pillar6/markets",
            "prices": "/pillar6/prices",
            "productions": "/pillar6/productions",
            "inventories": "/pillar6/inventories",
            "analyses": "/pillar6/analyses",
            "correlations": "/pillar6/correlations",
            "statistics": "/pillar6/statistics",
        },
    }


@router.get("/health", summary="Health Check", response_description="API health status")
async def health_check():
    """Check API health status."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
    }


# =============================================================================
# Element Endpoints
# =============================================================================

@router.get(
    "/elements",
    summary="List All Elements",
    response_description="List of all rare earth elements",
    response_model=List[ElementResponse],
)
async def list_elements(
    category: Optional[str] = Query(None, description="Filter by category (light/heavy)"),
    critical: Optional[bool] = Query(None, description="Filter by critical status"),
):
    """List all rare earth elements with optional filters."""
    try:
        if category:
            elements = storage.get_elements_by_category(category)
        elif critical is not None:
            if critical:
                elements = storage.get_critical_elements()
            else:
                all_elements = storage.get_all_elements()
                elements = [e for e in all_elements if not e.is_critical]
        else:
            elements = storage.get_all_elements()
        
        return [ElementResponse.model_validate(e) for e in elements]
        
    except Exception as e:
        logger.error(f"Failed to list elements: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/elements/{symbol}",
    summary="Get Element by Symbol",
    response_description="Details of a specific rare earth element",
    response_model=ElementResponse,
)
async def get_element(
    symbol: str = Path(..., description="Element chemical symbol (e.g., Nd, La)"),
):
    """Get a specific rare earth element by its chemical symbol."""
    try:
        element = storage.get_element_by_symbol(symbol)
        if not element:
            raise HTTPException(status_code=404, detail=f"Element {symbol} not found")
        return ElementResponse.model_validate(element)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get element {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Market Endpoints
# =============================================================================

@router.get(
    "/markets",
    summary="List All Markets",
    response_description="List of all rare earth markets",
    response_model=List[MarketResponse],
)
async def list_markets(
    region: Optional[str] = Query(None, description="Filter by region"),
    active: Optional[bool] = Query(None, description="Filter by active status"),
    element: Optional[str] = Query(None, description="Filter by supported element"),
):
    """List all rare earth markets with optional filters."""
    try:
        if region:
            markets = storage.get_markets_by_region(region)
        elif active is not None:
            if active:
                markets = storage.get_active_markets()
            else:
                all_markets = storage.get_all_markets()
                markets = [m for m in all_markets if not m.is_active]
        elif element:
            markets = storage.get_markets_by_element(element)
        else:
            markets = storage.get_all_markets()
        
        return [MarketResponse.model_validate(m) for m in markets]
        
    except Exception as e:
        logger.error(f"Failed to list markets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/markets/{market_id}",
    summary="Get Market by ID",
    response_description="Details of a specific rare earth market",
    response_model=MarketResponse,
)
async def get_market(
    market_id: str = Path(..., description="Market identifier (e.g., metal_pages, baotou)"),
):
    """Get a specific rare earth market by its ID."""
    try:
        market = storage.get_market_by_id(market_id)
        if not market:
            raise HTTPException(status_code=404, detail=f"Market {market_id} not found")
        return MarketResponse.model_validate(market)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get market {market_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Price Endpoints
# =============================================================================

@router.get(
    "/prices",
    summary="List All Prices",
    response_description="List of all rare earth price data points",
    response_model=List[PriceResponse],
)
async def list_prices(
    element: Optional[str] = Query(None, description="Filter by element symbol"),
    market: Optional[str] = Query(None, description="Filter by market ID"),
    limit: int = Query(100, description="Maximum number of results"),
):
    """List all rare earth price data points with optional filters."""
    try:
        if element and market:
            prices = storage.get_prices_by_element_and_market(element, market, limit)
        elif element:
            prices = storage.get_prices_by_element(element, limit)
        elif market:
            prices = storage.get_prices_by_market(market, limit)
        else:
            # Get all prices (limited)
            all_prices = storage.get_prices_by_element("Nd", limit)  # Default to Nd
            prices = all_prices[:limit]
        
        # Enrich with element and market info
        enriched_prices = []
        for price in prices:
            price_dict = price.to_dict()
            
            # Add element symbol
            if price.element_id:
                element_obj = storage.get_element_by_id(price.element_id)
                if element_obj:
                    price_dict["element_symbol"] = element_obj.symbol
            
            # Add market name
            if price.market_id:
                market_obj = storage.get_market_by_db_id(price.market_id)
                if market_obj:
                    price_dict["market_name"] = market_obj.name
            
            enriched_prices.append(PriceResponse(**price_dict))
        
        return enriched_prices
        
    except Exception as e:
        logger.error(f"Failed to list prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/prices/latest",
    summary="Get Latest Prices",
    response_description="Latest prices for all elements and markets",
    response_model=List[PriceResponse],
)
async def get_latest_prices():
    """Get the latest price for each element-market combination."""
    try:
        # Get all elements and markets
        elements = storage.get_all_elements()
        markets = storage.get_active_markets()
        
        latest_prices = []
        for element in elements:
            for market in markets:
                latest_price = storage.get_latest_price(element.symbol, market.market_id)
                if latest_price:
                    price_dict = latest_price.to_dict()
                    price_dict["element_symbol"] = element.symbol
                    price_dict["market_name"] = market.name
                    latest_prices.append(PriceResponse(**price_dict))
        
        return latest_prices
        
    except Exception as e:
        logger.error(f"Failed to get latest prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/prices/{element}/{market}",
    summary="Get Prices for Element and Market",
    response_description="Price history for a specific element and market",
    response_model=List[PriceResponse],
)
async def get_prices_for_element_market(
    element: str = Path(..., description="Element chemical symbol"),
    market: str = Path(..., description="Market identifier"),
    days: int = Query(30, description="Number of days of history"),
):
    """Get price history for a specific element and market."""
    try:
        prices = storage.get_price_history(element, days, market)
        
        # Enrich with element and market info
        enriched_prices = []
        for price in prices:
            price_dict = price.to_dict()
            
            # Add element symbol
            if price.element_id:
                element_obj = storage.get_element_by_id(price.element_id)
                if element_obj:
                    price_dict["element_symbol"] = element_obj.symbol
            
            # Add market name
            if price.market_id:
                market_obj = storage.get_market_by_db_id(price.market_id)
                if market_obj:
                    price_dict["market_name"] = market_obj.name
            
            enriched_prices.append(PriceResponse(**price_dict))
        
        return enriched_prices
        
    except Exception as e:
        logger.error(f"Failed to get prices for {element}/{market}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/prices/statistics/{element}",
    summary="Get Price Statistics",
    response_description="Price statistics for a specific element",
    response_model=StatisticsResponse,
)
async def get_price_statistics(
    element: str = Path(..., description="Element chemical symbol"),
    market: Optional[str] = Query(None, description="Filter by market ID"),
    days: int = Query(30, description="Number of days of history"),
):
    """Get price statistics for a specific element."""
    try:
        stats = storage.get_price_statistics(element, market, days)
        return StatisticsResponse(**stats)
        
    except Exception as e:
        logger.error(f"Failed to get price statistics for {element}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Production Endpoints
# =============================================================================

@router.get(
    "/productions",
    summary="List All Productions",
    response_description="List of all rare earth production data points",
    response_model=List[ProductionResponse],
)
async def list_productions(
    element: Optional[str] = Query(None, description="Filter by element symbol"),
    country: Optional[str] = Query(None, description="Filter by country"),
    company: Optional[str] = Query(None, description="Filter by company"),
    year: Optional[int] = Query(None, description="Filter by year"),
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
        else:
            # Get all productions (limited)
            productions = storage.get_productions_by_element("Nd")[:100]
        
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
    "/productions/statistics/{element}",
    summary="Get Production Statistics",
    response_description="Production statistics for a specific element",
    response_model=Dict[str, Any],
)
async def get_production_statistics(
    element: str = Path(..., description="Element chemical symbol"),
    country: Optional[str] = Query(None, description="Filter by country"),
):
    """Get production statistics for a specific element."""
    try:
        stats = storage.get_production_statistics(element, country)
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get production statistics for {element}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Inventory Endpoints
# =============================================================================

@router.get(
    "/inventories",
    summary="List All Inventories",
    response_description="List of all rare earth inventory data points",
    response_model=List[InventoryResponse],
)
async def list_inventories(
    element: Optional[str] = Query(None, description="Filter by element symbol"),
    country: Optional[str] = Query(None, description="Filter by country"),
    holder: Optional[str] = Query(None, description="Filter by holder"),
):
    """List all rare earth inventory data points with optional filters."""
    try:
        if element:
            inventories = storage.get_inventories_by_element(element)
        elif country:
            inventories = storage.get_inventories_by_country(country)
        elif holder:
            inventories = storage.get_inventories_by_holder(holder)
        else:
            # Get all inventories (limited)
            inventories = storage.get_inventories_by_element("Nd")[:100]
        
        # Enrich with element info
        enriched_inventories = []
        for inventory in inventories:
            inventory_dict = inventory.to_dict()
            
            # Add element symbol
            if inventory.element_id:
                element_obj = storage.get_element_by_id(inventory.element_id)
                if element_obj:
                    inventory_dict["element_symbol"] = element_obj.symbol
            
            enriched_inventories.append(InventoryResponse(**inventory_dict))
        
        return enriched_inventories
        
    except Exception as e:
        logger.error(f"Failed to list inventories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Analysis Endpoints
# =============================================================================

@router.get(
    "/analyses",
    summary="List All Analyses",
    response_description="List of all rare earth analysis results",
    response_model=List[AnalysisResponse],
)
async def list_analyses(
    element: Optional[str] = Query(None, description="Filter by element symbol"),
    analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
    days: int = Query(7, description="Number of days of history"),
):
    """List all rare earth analysis results with optional filters."""
    try:
        if element:
            analyses = storage.get_analyses_by_element(element)
        elif analysis_type:
            analyses = storage.get_analyses_by_type(analysis_type)
        else:
            analyses = storage.get_recent_analyses(days)
        
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
    "/analyses/{analysis_id}",
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


# =============================================================================
# Correlation Endpoints
# =============================================================================

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


# =============================================================================
# Statistics and Market Coverage Endpoints
# =============================================================================

@router.get(
    "/statistics/market-coverage",
    summary="Get Market Coverage Statistics",
    response_description="Statistics about market coverage",
    response_model=Dict[str, Any],
)
async def get_market_coverage():
    """Get statistics about market coverage."""
    try:
        coverage = storage.get_market_coverage()
        return coverage
        
    except Exception as e:
        logger.error(f"Failed to get market coverage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Include Router
# =============================================================================

app.include_router(router)


# =============================================================================
# Main App Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# Export everything
__all__ = [
    "app",
    "router",
    "ElementResponse",
    "MarketResponse",
    "PriceResponse",
    "ProductionResponse",
    "InventoryResponse",
    "AnalysisResponse",
    "CorrelationResponse",
    "StatisticsResponse",
]
