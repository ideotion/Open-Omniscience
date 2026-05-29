"""
Pillar 6 API Tests

Tests for REST API functionality.
"""

import pytest
import sys
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.api import app, router
from src.api.routers.price_router import PriceRouter, router as price_router
from src.api.routers.production_router import ProductionRouter, router as production_router
from src.api.routers.analysis_router import AnalysisRouter, router as analysis_router
from src.storage.storage import RareEarthStorage, get_storage
from src.models.element import RareEarthElement, ELEMENTS
from src.models.market import RareEarthMarket, MARKETS
from src.models.price import RareEarthPrice
from src.models.production import RareEarthProduction
from src.models.inventory import RareEarthInventory
from src.models.analysis import RareEarthAnalysis
from src.models.correlation import ArticleRareEarthLink


# Create a test client
client = TestClient(app)


class TestAPIRoot:
    """Tests for API root endpoints."""
    
    def test_api_root(self):
        """Test API root endpoint."""
        response = client.get("/pillar6/")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "Pillar 6" in data["name"]
        assert "version" in data
        assert "endpoints" in data
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = client.get("/pillar6/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data


class TestElementEndpoints:
    """Tests for element endpoints."""
    
    def test_list_elements(self):
        """Test listing all elements."""
        response = client.get("/pillar6/elements")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # Check first element has required fields
        first_element = data[0]
        assert "symbol" in first_element
        assert "name" in first_element
        assert "atomic_number" in first_element
    
    def test_list_elements_by_category(self):
        """Test listing elements by category."""
        response = client.get("/pillar6/elements?category=light")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # All elements should be light
        for element in data:
            assert element["category"] == "light"
    
    def test_list_elements_by_critical(self):
        """Test listing elements by critical status."""
        response = client.get("/pillar6/elements?critical=true")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # All elements should be critical
        for element in data:
            assert element["is_critical"] is True
    
    def test_get_element_by_symbol(self):
        """Test getting element by symbol."""
        response = client.get("/pillar6/elements/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "Nd"
        assert data["name"] == "Neodymium"
    
    def test_get_element_not_found(self):
        """Test getting non-existent element."""
        response = client.get("/pillar6/elements/XX")
        
        assert response.status_code == 404


class TestMarketEndpoints:
    """Tests for market endpoints."""
    
    def test_list_markets(self):
        """Test listing all markets."""
        response = client.get("/pillar6/markets")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # Check first market has required fields
        first_market = data[0]
        assert "market_id" in first_market
        assert "name" in first_market
        assert "region" in first_market
    
    def test_list_markets_by_region(self):
        """Test listing markets by region."""
        response = client.get("/pillar6/markets?region=global")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # All markets should be global
        for market in data:
            assert market["region"] == "global"
    
    def test_list_markets_by_active(self):
        """Test listing markets by active status."""
        response = client.get("/pillar6/markets?active=true")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # All markets should be active
        for market in data:
            assert market["is_active"] is True
    
    def test_get_market_by_id(self):
        """Test getting market by ID."""
        response = client.get("/pillar6/markets/metal_pages")
        
        assert response.status_code == 200
        data = response.json()
        assert data["market_id"] == "metal_pages"
        assert data["name"] == "Metal Pages"
    
    def test_get_market_not_found(self):
        """Test getting non-existent market."""
        response = client.get("/pillar6/markets/non_existent")
        
        assert response.status_code == 404


class TestPriceEndpoints:
    """Tests for price endpoints."""
    
    def test_list_prices(self):
        """Test listing all prices."""
        response = client.get("/pillar6/prices")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Note: May be empty if no prices in database
    
    def test_list_prices_by_element(self):
        """Test listing prices by element."""
        response = client.get("/pillar6/prices?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_prices_by_market(self):
        """Test listing prices by market."""
        response = client.get("/pillar6/prices?market=metal_pages")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_latest_prices(self):
        """Test getting latest prices."""
        response = client.get("/pillar6/prices/latest")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_price_history(self):
        """Test getting price history."""
        response = client.get("/pillar6/prices/history/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_price_statistics(self):
        """Test getting price statistics."""
        response = client.get("/pillar6/prices/statistics/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Note: May have limited data if no prices exist


class TestProductionEndpoints:
    """Tests for production endpoints."""
    
    def test_list_productions(self):
        """Test listing all productions."""
        response = client.get("/pillar6/productions")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_productions_by_element(self):
        """Test listing productions by element."""
        response = client.get("/pillar6/productions?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_productions_by_country(self):
        """Test listing productions by country."""
        response = client.get("/pillar6/productions?country=China")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_productions_by_company(self):
        """Test listing productions by company."""
        response = client.get("/pillar6/productions?company=Lynas")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_production_statistics(self):
        """Test getting production statistics."""
        response = client.get("/pillar6/productions/statistics/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestInventoryEndpoints:
    """Tests for inventory endpoints."""
    
    def test_list_inventories(self):
        """Test listing all inventories."""
        response = client.get("/pillar6/inventories")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_inventories_by_element(self):
        """Test listing inventories by element."""
        response = client.get("/pillar6/inventories?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_inventories_by_country(self):
        """Test listing inventories by country."""
        response = client.get("/pillar6/inventories?country=USA")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_inventories_by_holder(self):
        """Test listing inventories by holder."""
        response = client.get("/pillar6/inventories?holder=Department of Defense")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestAnalysisEndpoints:
    """Tests for analysis endpoints."""
    
    def test_list_analyses(self):
        """Test listing all analyses."""
        response = client.get("/pillar6/analyses")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_analyses_by_element(self):
        """Test listing analyses by element."""
        response = client.get("/pillar6/analyses?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_analyses_by_type(self):
        """Test listing analyses by type."""
        response = client.get("/pillar6/analyses?analysis_type=price_fluctuation")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestCorrelationEndpoints:
    """Tests for correlation endpoints."""
    
    def test_list_correlations(self):
        """Test listing all correlations."""
        response = client.get("/pillar6/correlations")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_correlations_by_element(self):
        """Test listing correlations by element."""
        response = client.get("/pillar6/correlations?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_correlations_by_article(self):
        """Test listing correlations by article."""
        response = client.get("/pillar6/correlations?article_id=1")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_list_correlations_by_type(self):
        """Test listing correlations by type."""
        response = client.get("/pillar6/correlations?correlation_type=price_news")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_strongest_correlations(self):
        """Test getting strongest correlations."""
        response = client.get("/pillar6/analyses/correlations/strongest")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestStatisticsEndpoints:
    """Tests for statistics endpoints."""
    
    def test_get_market_coverage(self):
        """Test getting market coverage statistics."""
        response = client.get("/pillar6/statistics/market-coverage")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestRouterEndpoints:
    """Tests for router-specific endpoints."""
    
    def test_price_router_list_prices(self):
        """Test price router list prices endpoint."""
        # Note: This tests the router-specific endpoint
        response = client.get("/pillar6/prices/")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_price_router_compare(self):
        """Test price router compare endpoint."""
        response = client.get("/pillar6/prices/compare?element=Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "element" in data
        assert "comparison" in data
    
    def test_production_router_by_element(self):
        """Test production router by element endpoint."""
        response = client.get("/pillar6/productions/by-element/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_production_router_rankings(self):
        """Test production router rankings endpoint."""
        response = client.get("/pillar6/productions/rankings")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
    
    def test_analysis_router_by_element(self):
        """Test analysis router by element endpoint."""
        response = client.get("/pillar6/analyses/by-element/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_analysis_router_correlations_by_element(self):
        """Test analysis router correlations by element endpoint."""
        response = client.get("/pillar6/analyses/correlations/by-element/Nd")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestAPIResponseModels:
    """Tests for API response models."""
    
    def test_element_response_model(self):
        """Test element response model."""
        response = client.get("/pillar6/elements/Nd")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        required_fields = ["symbol", "name", "atomic_number", "category"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_market_response_model(self):
        """Test market response model."""
        response = client.get("/pillar6/markets/metal_pages")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        required_fields = ["market_id", "name", "region", "currency"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_price_response_model(self):
        """Test price response model."""
        # This may return empty if no prices exist
        response = client.get("/pillar6/prices?limit=1")
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            first_price = data[0]
            # Check some expected fields
            expected_fields = ["price", "currency", "date"]
            for field in expected_fields:
                assert field in first_price, f"Missing expected field: {field}"


class TestAPIErrorHandling:
    """Tests for API error handling."""
    
    def test_invalid_element_symbol(self):
        """Test handling invalid element symbol."""
        response = client.get("/pillar6/elements/INVALID")
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
    
    def test_invalid_market_id(self):
        """Test handling invalid market ID."""
        response = client.get("/pillar6/markets/invalid_market")
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
    
    def test_invalid_endpoint(self):
        """Test handling invalid endpoint."""
        response = client.get("/pillar6/invalid_endpoint")
        
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
