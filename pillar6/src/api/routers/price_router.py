"""
Pillar 6 Price Router

Router for rare earth price data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from datetime import date, datetime
import logging

from src.database.models import Session
from ..storage import storage
from ..api import (
    PriceResponse,
    StatisticsResponse,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/pillar6/prices", tags=["Prices"])


class PriceRouter:
    """Router class for price-related endpoints."""
    
    def __init__(self):
        """Initialize the price router."""
        self.router = router
        self._setup_endpoints()
    
    def _setup_endpoints(self):
        """Setup all price endpoints."""
        
        @router.get(
            "/",
            summary="List All Prices",
            response_description="List of all rare earth price data points",
            response_model=List[PriceResponse],
        )
        async def list_prices(
            element: Optional[str] = Query(None, description="Filter by element symbol"),
            market: Optional[str] = Query(None, description="Filter by market ID"),
            start_date: Optional[date] = Query(None, description="Start date filter"),
            end_date: Optional[date] = Query(None, description="End date filter"),
            limit: int = Query(100, description="Maximum number of results"),
            verified: Optional[bool] = Query(None, description="Filter by verification status"),
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
                    all_prices = storage.get_all_prices(limit)
                    prices = all_prices[:limit]
                
                # Apply date filters
                if start_date or end_date:
                    filtered_prices = []
                    for price in prices:
                        price_date = price.date if hasattr(price, 'date') else None
                        if price_date:
                            if start_date and price_date < start_date:
                                continue
                            if end_date and price_date > end_date:
                                continue
                        filtered_prices.append(price)
                    prices = filtered_prices
                
                # Apply verification filter
                if verified is not None:
                    prices = [p for p in prices if p.is_verified == verified]
                
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
            "/latest",
            summary="Get Latest Prices",
            response_description="Latest prices for all elements and markets",
            response_model=List[PriceResponse],
        )
        async def get_latest_prices(
            elements: Optional[List[str]] = Query(None, description="List of element symbols to filter"),
            markets: Optional[List[str]] = Query(None, description="List of market IDs to filter"),
        ):
            """Get the latest price for each element-market combination."""
            try:
                # Get all elements and markets if not specified
                elements_list = elements or [e.symbol for e in storage.get_all_elements()]
                markets_list = markets or [m.market_id for m in storage.get_active_markets()]
                
                latest_prices = []
                for element_symbol in elements_list:
                    for market_id in markets_list:
                        latest_price = storage.get_latest_price(element_symbol, market_id)
                        if latest_price:
                            price_dict = latest_price.to_dict()
                            
                            # Add element symbol
                            element_obj = storage.get_element_by_symbol(element_symbol)
                            if element_obj:
                                price_dict["element_symbol"] = element_obj.symbol
                            
                            # Add market name
                            market_obj = storage.get_market_by_id(market_id)
                            if market_obj:
                                price_dict["market_name"] = market_obj.name
                            
                            latest_prices.append(PriceResponse(**price_dict))
                
                return latest_prices
                
            except Exception as e:
                logger.error(f"Failed to get latest prices: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/history/{element}",
            summary="Get Price History",
            response_description="Price history for a specific element",
            response_model=List[PriceResponse],
        )
        async def get_price_history(
            element: str = Path(..., description="Element chemical symbol"),
            market: Optional[str] = Query(None, description="Filter by market ID"),
            days: int = Query(30, description="Number of days of history"),
            start_date: Optional[date] = Query(None, description="Start date"),
            end_date: Optional[date] = Query(None, description="End date"),
        ):
            """Get price history for a specific element."""
            try:
                if market:
                    prices = storage.get_price_history(element, days, market)
                else:
                    prices = storage.get_price_history(element, days)
                
                # Apply date filters
                if start_date or end_date:
                    filtered_prices = []
                    for price in prices:
                        price_date = price.date if hasattr(price, 'date') else None
                        if price_date:
                            if start_date and price_date < start_date:
                                continue
                            if end_date and price_date > end_date:
                                continue
                        filtered_prices.append(price)
                    prices = filtered_prices
                
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
                logger.error(f"Failed to get price history for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/statistics/{element}",
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
        
        @router.get(
            "/compare",
            summary="Compare Prices Across Markets",
            response_description="Compare prices for an element across different markets",
            response_model=Dict[str, Any],
        )
        async def compare_prices(
            element: str = Query(..., description="Element chemical symbol"),
            markets: Optional[List[str]] = Query(None, description="List of market IDs to compare"),
            days: int = Query(7, description="Number of days of history"),
        ):
            """Compare prices for an element across different markets."""
            try:
                if markets:
                    markets_list = markets
                else:
                    markets_list = [m.market_id for m in storage.get_active_markets()]
                
                comparison = {}
                for market_id in markets_list:
                    prices = storage.get_price_history(element, days, market_id)
                    if prices:
                        market_name = storage.get_market_by_id(market_id).name if storage.get_market_by_id(market_id) else market_id
                        comparison[market_name] = [p.to_dict() for p in prices]
                
                return {
                    "element": element,
                    "comparison": comparison,
                    "markets": markets_list,
                    "days": days,
                }
                
            except Exception as e:
                logger.error(f"Failed to compare prices for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/trends/{element}",
            summary="Get Price Trends",
            response_description="Price trends for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_price_trends(
            element: str = Path(..., description="Element chemical symbol"),
            market: Optional[str] = Query(None, description="Filter by market ID"),
            days: int = Query(90, description="Number of days of history"),
        ):
            """Get price trends for a specific element."""
            try:
                trends = storage.get_price_trends(element, market, days)
                return trends
                
            except Exception as e:
                logger.error(f"Failed to get price trends for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @router.get(
            "/volatility/{element}",
            summary="Get Price Volatility",
            response_description="Price volatility for a specific element",
            response_model=Dict[str, Any],
        )
        async def get_price_volatility(
            element: str = Path(..., description="Element chemical symbol"),
            market: Optional[str] = Query(None, description="Filter by market ID"),
            days: int = Query(30, description="Number of days of history"),
        ):
            """Get price volatility for a specific element."""
            try:
                volatility = storage.get_price_volatility(element, market, days)
                return volatility
                
            except Exception as e:
                logger.error(f"Failed to get price volatility for {element}: {e}")
                raise HTTPException(status_code=500, detail=str(e))


# Create router instance
price_router = PriceRouter()

# Export router
__all__ = ["router", "PriceRouter"]
