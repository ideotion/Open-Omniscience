"""
Pillar 6 Models Tests

Tests for rare earth data models.
"""

import pytest
import sys
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.element import (
    RareEarthElement,
    ELEMENTS,
    get_element_by_symbol,
    get_element_by_name,
    get_all_elements,
    get_light_rare_earths,
    get_heavy_rare_earths,
    get_critical_elements,
)
from src.models.market import (
    RareEarthMarket,
    MARKETS,
    get_market_by_id,
    get_market_by_name,
    get_all_markets,
    get_active_markets,
    get_markets_by_region,
    get_markets_by_type,
)
from src.models.price import RareEarthPrice
from src.models.production import RareEarthProduction
from src.models.inventory import RareEarthInventory
from src.models.analysis import (
    RareEarthAnalysis,
    PriceFluctuationAnalysis,
    TrendAnalysis,
    AnomalyDetection,
    NormalizationAnalysis,
)
from src.models.correlation import ArticleRareEarthLink


class TestRareEarthElement:
    """Tests for RareEarthElement model."""
    
    def test_element_creation(self):
        """Test creating a rare earth element."""
        element = RareEarthElement(
            symbol="Nd",
            name="Neodymium",
            atomic_number=60,
            category="light",
            element_type="lanthanide",
            atomic_weight=144.242,
            melting_point=1016.0,
            boiling_point=3074.0,
            density=7.007,
            discovery_year=1885,
            common_uses=["magnets", "lasers", "coloring glass"],
            is_critical=True,
            aliases=["Neodym"],
        )
        
        assert element.symbol == "Nd"
        assert element.name == "Neodymium"
        assert element.atomic_number == 60
        assert element.category == "light"
        assert element.is_critical is True
        assert len(element.common_uses) == 3
    
    def test_element_to_dict(self):
        """Test converting element to dictionary."""
        element = RareEarthElement(
            symbol="Nd",
            name="Neodymium",
            atomic_number=60,
        )
        
        element_dict = element.to_dict()
        
        assert element_dict["symbol"] == "Nd"
        assert element_dict["name"] == "Neodymium"
        assert element_dict["atomic_number"] == 60
    
    def test_element_from_dict(self):
        """Test creating element from dictionary."""
        element_data = {
            "symbol": "Dy",
            "name": "Dysprosium",
            "atomic_number": 66,
            "category": "heavy",
        }
        
        element = RareEarthElement.from_dict(element_data)
        
        assert element.symbol == "Dy"
        assert element.name == "Dysprosium"
        assert element.atomic_number == 66
        assert element.category == "heavy"
    
    def test_element_validation(self):
        """Test element validation."""
        # Valid element
        element = RareEarthElement(
            symbol="La",
            name="Lanthanum",
            atomic_number=57,
        )
        assert element.is_valid() is True
        
        # Invalid element (missing required fields)
        with pytest.raises(ValueError):
            RareEarthElement(symbol="", name="", atomic_number=0)
    
    def test_get_element_by_symbol(self):
        """Test getting element by symbol."""
        element = get_element_by_symbol("Nd")
        assert element is not None
        assert element.symbol == "Nd"
        assert element.name == "Neodymium"
        
        # Non-existent element
        element = get_element_by_symbol("XX")
        assert element is None
    
    def test_get_element_by_name(self):
        """Test getting element by name."""
        element = get_element_by_name("Neodymium")
        assert element is not None
        assert element.name == "Neodymium"
        
        # Non-existent element
        element = get_element_by_name("NonExistent")
        assert element is None
    
    def test_get_all_elements(self):
        """Test getting all elements."""
        elements = get_all_elements()
        assert len(elements) > 0
        assert all(isinstance(e, RareEarthElement) for e in elements)
    
    def test_get_light_rare_earths(self):
        """Test getting light rare earths."""
        light_ree = get_light_rare_earths()
        assert len(light_ree) > 0
        assert all(e.category == "light" for e in light_ree)
    
    def test_get_heavy_rare_earths(self):
        """Test getting heavy rare earths."""
        heavy_ree = get_heavy_rare_earths()
        assert len(heavy_ree) > 0
        assert all(e.category == "heavy" for e in heavy_ree)
    
    def test_get_critical_elements(self):
        """Test getting critical elements."""
        critical = get_critical_elements()
        assert len(critical) > 0
        assert all(e.is_critical is True for e in critical)
    
    def test_elements_list(self):
        """Test ELEMENTS list contains all expected elements."""
        assert len(ELEMENTS) == 17  # 15 lanthanides + Sc + Y
        symbols = [e.symbol for e in ELEMENTS]
        assert "Nd" in symbols
        assert "Dy" in symbols
        assert "La" in symbols


class TestRareEarthMarket:
    """Tests for RareEarthMarket model."""
    
    def test_market_creation(self):
        """Test creating a rare earth market."""
        market = RareEarthMarket(
            market_id="metal_pages",
            name="Metal Pages",
            market_type="price_data",
            region="global",
            currency="USD",
            description="Metal Pages rare earth prices",
            website="https://www.metal-pages.com",
            is_active=True,
            data_sources=["metal_pages"],
            supported_elements=["Nd", "Dy", "Pr"],
            update_frequency="daily",
        )
        
        assert market.market_id == "metal_pages"
        assert market.name == "Metal Pages"
        assert market.region == "global"
        assert market.is_active is True
    
    def test_market_to_dict(self):
        """Test converting market to dictionary."""
        market = RareEarthMarket(
            market_id="metal_pages",
            name="Metal Pages",
            market_type="price_data",
        )
        
        market_dict = market.to_dict()
        
        assert market_dict["market_id"] == "metal_pages"
        assert market_dict["name"] == "Metal Pages"
        assert market_dict["market_type"] == "price_data"
    
    def test_get_market_by_id(self):
        """Test getting market by ID."""
        market = get_market_by_id("metal_pages")
        assert market is not None
        assert market.market_id == "metal_pages"
        
        # Non-existent market
        market = get_market_by_id("non_existent")
        assert market is None
    
    def test_get_market_by_name(self):
        """Test getting market by name."""
        market = get_market_by_name("Metal Pages")
        assert market is not None
        assert market.name == "Metal Pages"
    
    def test_get_all_markets(self):
        """Test getting all markets."""
        markets = get_all_markets()
        assert len(markets) > 0
        assert all(isinstance(m, RareEarthMarket) for m in markets)
    
    def test_get_active_markets(self):
        """Test getting active markets."""
        markets = get_active_markets()
        assert len(markets) > 0
        assert all(m.is_active is True for m in markets)
    
    def test_get_markets_by_region(self):
        """Test getting markets by region."""
        markets = get_markets_by_region("global")
        assert len(markets) > 0
        assert all(m.region == "global" for m in markets)
    
    def test_get_markets_by_type(self):
        """Test getting markets by type."""
        markets = get_markets_by_type("price_data")
        assert len(markets) > 0
        assert all(m.market_type == "price_data" for m in markets)


class TestRareEarthPrice:
    """Tests for RareEarthPrice model."""
    
    def test_price_creation(self):
        """Test creating a price data point."""
        price = RareEarthPrice(
            element_id=1,
            market_id=1,
            price=50000.0,
            currency="USD",
            price_type="spot",
            price_unit="kg",
            purity_grade="99.9%",
            date=date(2024, 1, 15),
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            source_url="https://example.com/prices",
            is_verified=True,
            confidence=0.95,
            notes="High demand",
        )
        
        assert price.element_id == 1
        assert price.market_id == 1
        assert price.price == 50000.0
        assert price.currency == "USD"
        assert price.date == date(2024, 1, 15)
        assert price.is_verified is True
    
    def test_price_to_dict(self):
        """Test converting price to dictionary."""
        price = RareEarthPrice(
            element_id=1,
            market_id=1,
            price=50000.0,
            currency="USD",
            date=date(2024, 1, 15),
        )
        
        price_dict = price.to_dict()
        
        assert price_dict["element_id"] == 1
        assert price_dict["market_id"] == 1
        assert price_dict["price"] == 50000.0
        assert price_dict["currency"] == "USD"
    
    def test_price_per_kg(self):
        """Test price per kg calculation."""
        # Price is per kg
        price = RareEarthPrice(
            price=50000.0,
            price_unit="kg",
        )
        assert price.price_per_kg == 50000.0
        
        # Price is per tonne
        price = RareEarthPrice(
            price=50000.0,
            price_unit="tonne",
        )
        assert price.price_per_kg == 50.0
        
        # Price is per gram
        price = RareEarthPrice(
            price=50.0,
            price_unit="gram",
        )
        assert price.price_per_kg == 50000.0
    
    def test_price_normalization(self):
        """Test price normalization."""
        price = RareEarthPrice(
            price=50000.0,
            currency="USD",
        )
        
        # Normalize to USD (no conversion)
        normalized = price.normalize("USD")
        assert normalized == 50000.0


class TestRareEarthProduction:
    """Tests for RareEarthProduction model."""
    
    def test_production_creation(self):
        """Test creating a production data point."""
        production = RareEarthProduction(
            element_id=1,
            country="China",
            amount=100000.0,
            production_type="mining",
            production_unit="tonnes",
            year=2024,
            quarter=1,
            month=1,
            date=date(2024, 1, 15),
            company="Lynas Corporation",
            source="USGS",
            source_url="https://example.com/production",
            is_estimated=True,
            confidence=0.9,
            notes="Estimated production",
        )
        
        assert production.element_id == 1
        assert production.country == "China"
        assert production.amount == 100000.0
        assert production.year == 2024
        assert production.company == "Lynas Corporation"
    
    def test_production_to_dict(self):
        """Test converting production to dictionary."""
        production = RareEarthProduction(
            element_id=1,
            country="China",
            amount=100000.0,
            year=2024,
        )
        
        production_dict = production.to_dict()
        
        assert production_dict["element_id"] == 1
        assert production_dict["country"] == "China"
        assert production_dict["amount"] == 100000.0
        assert production_dict["year"] == 2024
    
    def test_production_tonnes(self):
        """Test tonnes calculation."""
        # Amount is in tonnes
        production = RareEarthProduction(
            amount=1000.0,
            production_unit="tonnes",
        )
        assert production.tonnes == 1000.0
        
        # Amount is in kg
        production = RareEarthProduction(
            amount=1000000.0,
            production_unit="kg",
        )
        assert production.tonnes == 1000.0


class TestRareEarthInventory:
    """Tests for RareEarthInventory model."""
    
    def test_inventory_creation(self):
        """Test creating an inventory data point."""
        inventory = RareEarthInventory(
            element_id=1,
            country="USA",
            amount=5000.0,
            inventory_type="stockpile",
            inventory_unit="tonnes",
            year=2024,
            date=date(2024, 1, 1),
            holder="Department of Defense",
            source="USGS",
            source_url="https://example.com/inventory",
            is_estimated=True,
            confidence=0.85,
            notes="Strategic stockpile",
        )
        
        assert inventory.element_id == 1
        assert inventory.country == "USA"
        assert inventory.amount == 5000.0
        assert inventory.holder == "Department of Defense"
    
    def test_inventory_to_dict(self):
        """Test converting inventory to dictionary."""
        inventory = RareEarthInventory(
            element_id=1,
            country="USA",
            amount=5000.0,
            year=2024,
        )
        
        inventory_dict = inventory.to_dict()
        
        assert inventory_dict["element_id"] == 1
        assert inventory_dict["country"] == "USA"
        assert inventory_dict["amount"] == 5000.0
    
    def test_inventory_tonnes(self):
        """Test tonnes calculation."""
        inventory = RareEarthInventory(
            amount=1000.0,
            inventory_unit="tonnes",
        )
        assert inventory.tonnes == 1000.0


class TestAnalysisModels:
    """Tests for analysis models."""
    
    def test_analysis_creation(self):
        """Test creating an analysis result."""
        analysis = RareEarthAnalysis(
            element_id=1,
            analysis_type="price_fluctuation",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"change_pct": 5.2, "volatility": 0.15},
            severity="medium",
            confidence=0.9,
            direction="up",
            magnitude=5.2,
            insights="Price increased due to demand",
            recommendations=["Monitor supply chain"],
            related_articles=["article1", "article2"],
            related_markets=["metal_pages"],
            metadata={"model": "v1"},
        )
        
        assert analysis.element_id == 1
        assert analysis.analysis_type == "price_fluctuation"
        assert analysis.severity == "medium"
        assert analysis.direction == "up"
    
    def test_price_fluctuation_analysis(self):
        """Test PriceFluctuationAnalysis."""
        analysis = PriceFluctuationAnalysis(
            element_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"change_pct": 5.2},
            price_change_pct=5.2,
            volatility=0.15,
        )
        
        assert analysis.analysis_type == "price_fluctuation"
        assert analysis.price_change_pct == 5.2
    
    def test_trend_analysis(self):
        """Test TrendAnalysis."""
        analysis = TrendAnalysis(
            element_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"slope": 0.5},
            trend_direction="up",
            trend_strength=0.8,
        )
        
        assert analysis.analysis_type == "trend"
        assert analysis.trend_direction == "up"
    
    def test_anomaly_detection(self):
        """Test AnomalyDetection."""
        analysis = AnomalyDetection(
            element_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"anomaly_score": 3.2},
            anomaly_score=3.2,
            is_anomaly=True,
            anomaly_type="price_spike",
        )
        
        assert analysis.analysis_type == "anomaly_detection"
        assert analysis.is_anomaly is True
    
    def test_normalization_analysis(self):
        """Test NormalizationAnalysis."""
        analysis = NormalizationAnalysis(
            element_id=1,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"zscore": 1.5},
            normalization_method="zscore",
            normalized_value=1.5,
        )
        
        assert analysis.analysis_type == "normalization"
        assert analysis.normalization_method == "zscore"


class TestCorrelationModel:
    """Tests for correlation model."""
    
    def test_correlation_creation(self):
        """Test creating a correlation link."""
        correlation = ArticleRareEarthLink(
            article_id=1,
            element_id=1,
            correlation_type="price_news",
            correlation_score=0.85,
            correlation_strength="strong",
            sentiment="positive",
            sentiment_score=0.7,
            date=date(2024, 1, 15),
            time_lag_days=2,
            price_change_pct=3.5,
            keywords=["neodymium", "price", "increase"],
            entities=["China", "Lynas"],
            confidence=0.9,
            insights="News article preceded price increase",
            is_significant=True,
            p_value=0.01,
            metadata={"source": "analysis"},
        )
        
        assert correlation.article_id == 1
        assert correlation.element_id == 1
        assert correlation.correlation_score == 0.85
        assert correlation.sentiment == "positive"
        assert correlation.is_significant is True
    
    def test_correlation_to_dict(self):
        """Test converting correlation to dictionary."""
        correlation = ArticleRareEarthLink(
            article_id=1,
            element_id=1,
            correlation_type="price_news",
            correlation_score=0.85,
        )
        
        correlation_dict = correlation.to_dict()
        
        assert correlation_dict["article_id"] == 1
        assert correlation_dict["element_id"] == 1
        assert correlation_dict["correlation_score"] == 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
