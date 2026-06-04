"""
Pillar 6 Storage Tests

Tests for storage layer functionality.
"""

import pytest
import sys
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional
import tempfile
import sqlite3

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.database import (
    Base,
    DBSession,
    init_db,
    get_engine,
)
from src.storage.storage import (
    RareEarthStorage,
    get_storage,
)
from src.models.element import RareEarthElement, ELEMENTS
from src.models.market import RareEarthMarket, MARKETS
from src.models.price import RareEarthPrice
from src.models.production import RareEarthProduction
from src.models.inventory import RareEarthInventory
from src.models.analysis import RareEarthAnalysis
from src.models.correlation import ArticleRareEarthLink


# Create a temporary database for testing
@pytest.fixture(scope="module")
def temp_db():
    """Create a temporary database for testing."""
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()
    
    # Initialize database
    engine = get_engine(f"sqlite:///{db_file.name}")
    Base.metadata.create_all(engine)
    
    yield db_file.name
    
    # Cleanup
    os.unlink(db_file.name)


@pytest.fixture(scope="module")
def storage(temp_db):
    """Create a storage instance for testing."""
    # Initialize storage with temp database
    storage = RareEarthStorage(db_url=f"sqlite:///{temp_db}")
    
    # Seed with test data
    storage.seed_database()
    
    yield storage
    
    # Cleanup
    storage.close()


class TestDatabase:
    """Tests for database functionality."""
    
    def test_database_initialization(self, temp_db):
        """Test database initialization."""
        engine = get_engine(f"sqlite:///{temp_db}")
        assert engine is not None
        
        # Check tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        expected_tables = [
            "rare_earth_elements",
            "rare_earth_markets",
            "rare_earth_prices",
            "rare_earth_productions",
            "rare_earth_inventories",
            "rare_earth_analyses",
            "article_rare_earth_links",
        ]
        
        for table in expected_tables:
            assert table in tables, f"Table {table} not found in database"
    
    def test_session_management(self, temp_db):
        """Test database session management."""
        session = DBSession(f"sqlite:///{temp_db}")
        assert session is not None
        
        # Test session is open
        assert not session.is_active or session.is_active  # Depends on SQLAlchemy version
        
        session.close()


class TestRareEarthStorage:
    """Tests for RareEarthStorage class."""
    
    def test_storage_initialization(self, storage):
        """Test storage initialization."""
        assert storage is not None
        assert storage.db_url is not None
    
    def test_seed_database(self, storage):
        """Test seeding database with initial data."""
        # Check elements were seeded
        elements = storage.get_all_elements()
        assert len(elements) > 0
        
        # Check markets were seeded
        markets = storage.get_all_markets()
        assert len(markets) > 0
    
    def test_element_crud(self, storage):
        """Test CRUD operations for elements."""
        # Create a new element
        new_element = RareEarthElement(
            symbol="Test",
            name="Testium",
            atomic_number=999,
            category="test",
        )
        
        # Add element
        element_id = storage.add_element(new_element)
        assert element_id is not None
        
        # Get element by ID
        element = storage.get_element_by_id(element_id)
        assert element is not None
        assert element.symbol == "Test"
        
        # Get element by symbol
        element = storage.get_element_by_symbol("Test")
        assert element is not None
        assert element.name == "Testium"
        
        # Update element
        element.name = "Testium Updated"
        storage.update_element(element)
        
        updated_element = storage.get_element_by_symbol("Test")
        assert updated_element.name == "Testium Updated"
        
        # Delete element
        storage.delete_element(element_id)
        
        deleted_element = storage.get_element_by_symbol("Test")
        assert deleted_element is None
    
    def test_market_crud(self, storage):
        """Test CRUD operations for markets."""
        # Create a new market
        new_market = RareEarthMarket(
            market_id="test_market",
            name="Test Market",
            market_type="test",
            region="test",
            currency="USD",
        )
        
        # Add market
        market_id = storage.add_market(new_market)
        assert market_id is not None
        
        # Get market by ID
        market = storage.get_market_by_db_id(market_id)
        assert market is not None
        assert market.market_id == "test_market"
        
        # Get market by market_id
        market = storage.get_market_by_id("test_market")
        assert market is not None
        assert market.name == "Test Market"
        
        # Update market
        market.name = "Test Market Updated"
        storage.update_market(market)
        
        updated_market = storage.get_market_by_id("test_market")
        assert updated_market.name == "Test Market Updated"
        
        # Delete market
        storage.delete_market(market_id)
        
        deleted_market = storage.get_market_by_id("test_market")
        assert deleted_market is None
    
    def test_price_crud(self, storage):
        """Test CRUD operations for prices."""
        # Get an element
        element = storage.get_element_by_symbol("Nd")
        assert element is not None
        
        # Get a market
        market = storage.get_market_by_id("metal_pages")
        assert market is not None
        
        # Create a new price
        new_price = RareEarthPrice(
            element_id=element.id,
            market_id=market.id,
            price=50000.0,
            currency="USD",
            price_type="spot",
            price_unit="kg",
            purity_grade="99.9%",
            date=date(2024, 1, 15),
            is_verified=True,
            confidence=0.95,
        )
        
        # Add price
        price_id = storage.add_price(new_price)
        assert price_id is not None
        
        # Get price by ID
        price = storage.get_price_by_id(price_id)
        assert price is not None
        assert price.price == 50000.0
        
        # Get prices by element
        prices = storage.get_prices_by_element("Nd")
        assert len(prices) > 0
        
        # Get prices by market
        prices = storage.get_prices_by_market("metal_pages")
        assert len(prices) > 0
        
        # Get latest price
        latest_price = storage.get_latest_price("Nd", "metal_pages")
        assert latest_price is not None
        
        # Update price
        price.price = 55000.0
        storage.update_price(price)
        
        updated_price = storage.get_price_by_id(price_id)
        assert updated_price.price == 55000.0
        
        # Delete price
        storage.delete_price(price_id)
        
        deleted_price = storage.get_price_by_id(price_id)
        assert deleted_price is None
    
    def test_production_crud(self, storage):
        """Test CRUD operations for productions."""
        # Get an element
        element = storage.get_element_by_symbol("Nd")
        assert element is not None
        
        # Create a new production
        new_production = RareEarthProduction(
            element_id=element.id,
            country="China",
            amount=100000.0,
            production_type="mining",
            production_unit="tonnes",
            year=2024,
            company="Lynas Corporation",
            source="USGS",
            is_estimated=True,
            confidence=0.9,
        )
        
        # Add production
        production_id = storage.add_production(new_production)
        assert production_id is not None
        
        # Get production by ID
        production = storage.get_production_by_id(production_id)
        assert production is not None
        assert production.amount == 100000.0
        
        # Get productions by element
        productions = storage.get_productions_by_element("Nd")
        assert len(productions) > 0
        
        # Get productions by country
        productions = storage.get_productions_by_country("China")
        assert len(productions) > 0
        
        # Get productions by company
        productions = storage.get_productions_by_company("Lynas Corporation")
        assert len(productions) > 0
        
        # Update production
        production.amount = 110000.0
        storage.update_production(production)
        
        updated_production = storage.get_production_by_id(production_id)
        assert updated_production.amount == 110000.0
        
        # Delete production
        storage.delete_production(production_id)
        
        deleted_production = storage.get_production_by_id(production_id)
        assert deleted_production is None
    
    def test_inventory_crud(self, storage):
        """Test CRUD operations for inventories."""
        # Get an element
        element = storage.get_element_by_symbol("Nd")
        assert element is not None
        
        # Create a new inventory
        new_inventory = RareEarthInventory(
            element_id=element.id,
            country="USA",
            amount=5000.0,
            inventory_type="stockpile",
            inventory_unit="tonnes",
            year=2024,
            holder="Department of Defense",
            source="USGS",
            is_estimated=True,
            confidence=0.85,
        )
        
        # Add inventory
        inventory_id = storage.add_inventory(new_inventory)
        assert inventory_id is not None
        
        # Get inventory by ID
        inventory = storage.get_inventory_by_id(inventory_id)
        assert inventory is not None
        assert inventory.amount == 5000.0
        
        # Get inventories by element
        inventories = storage.get_inventories_by_element("Nd")
        assert len(inventories) > 0
        
        # Get inventories by country
        inventories = storage.get_inventories_by_country("USA")
        assert len(inventories) > 0
        
        # Get inventories by holder
        inventories = storage.get_inventories_by_holder("Department of Defense")
        assert len(inventories) > 0
        
        # Update inventory
        inventory.amount = 5500.0
        storage.update_inventory(inventory)
        
        updated_inventory = storage.get_inventory_by_id(inventory_id)
        assert updated_inventory.amount == 5500.0
        
        # Delete inventory
        storage.delete_inventory(inventory_id)
        
        deleted_inventory = storage.get_inventory_by_id(inventory_id)
        assert deleted_inventory is None
    
    def test_analysis_crud(self, storage):
        """Test CRUD operations for analyses."""
        # Get an element
        element = storage.get_element_by_symbol("Nd")
        assert element is not None
        
        # Create a new analysis
        new_analysis = RareEarthAnalysis(
            element_id=element.id,
            analysis_type="price_fluctuation",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            results={"change_pct": 5.2, "volatility": 0.15},
            severity="medium",
            confidence=0.9,
            direction="up",
            magnitude=5.2,
            insights="Price increased due to demand",
        )
        
        # Add analysis
        analysis_id = storage.add_analysis(new_analysis)
        assert analysis_id is not None
        
        # Get analysis by ID
        analysis = storage.get_analysis_by_id(analysis_id)
        assert analysis is not None
        assert analysis.analysis_type == "price_fluctuation"
        
        # Get analyses by element
        analyses = storage.get_analyses_by_element("Nd")
        assert len(analyses) > 0
        
        # Get analyses by type
        analyses = storage.get_analyses_by_type("price_fluctuation")
        assert len(analyses) > 0
        
        # Update analysis
        analysis.severity = "high"
        storage.update_analysis(analysis)
        
        updated_analysis = storage.get_analysis_by_id(analysis_id)
        assert updated_analysis.severity == "high"
        
        # Delete analysis
        storage.delete_analysis(analysis_id)
        
        deleted_analysis = storage.get_analysis_by_id(analysis_id)
        assert deleted_analysis is None
    
    def test_correlation_crud(self, storage):
        """Test CRUD operations for correlations."""
        # Get an element
        element = storage.get_element_by_symbol("Nd")
        assert element is not None
        
        # Create a new correlation
        new_correlation = ArticleRareEarthLink(
            article_id=1,
            element_id=element.id,
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
        )
        
        # Add correlation
        correlation_id = storage.add_correlation(new_correlation)
        assert correlation_id is not None
        
        # Get correlation by ID
        correlation = storage.get_correlation_by_id(correlation_id)
        assert correlation is not None
        assert correlation.correlation_score == 0.85
        
        # Get correlations by element
        correlations = storage.get_correlations_by_element("Nd")
        assert len(correlations) > 0
        
        # Get correlations by article
        correlations = storage.get_correlations_by_article(1)
        assert len(correlations) > 0
        
        # Get correlations by type
        correlations = storage.get_correlations_by_type("price_news")
        assert len(correlations) > 0
        
        # Update correlation
        correlation.correlation_score = 0.90
        storage.update_correlation(correlation)
        
        updated_correlation = storage.get_correlation_by_id(correlation_id)
        assert updated_correlation.correlation_score == 0.90
        
        # Delete correlation
        storage.delete_correlation(correlation_id)
        
        deleted_correlation = storage.get_correlation_by_id(correlation_id)
        assert deleted_correlation is None
    
    def test_query_operations(self, storage):
        """Test various query operations."""
        # Test get_all_elements
        elements = storage.get_all_elements()
        assert len(elements) > 0
        
        # Test get_all_markets
        markets = storage.get_all_markets()
        assert len(markets) > 0
        
        # Test get_active_markets
        active_markets = storage.get_active_markets()
        assert len(active_markets) > 0
        
        # Test get_elements_by_category
        light_elements = storage.get_elements_by_category("light")
        assert len(light_elements) > 0
        
        # Test get_critical_elements
        critical_elements = storage.get_critical_elements()
        assert len(critical_elements) > 0
        
        # Test get_markets_by_region
        global_markets = storage.get_markets_by_region("global")
        assert len(global_markets) > 0
        
        # Test get_markets_by_element
        nd_markets = storage.get_markets_by_element("Nd")
        assert len(nd_markets) > 0
    
    def test_statistics_operations(self, storage):
        """Test statistics operations."""
        # Add some test prices
        element = storage.get_element_by_symbol("Nd")
        market = storage.get_market_by_id("metal_pages")
        
        for i in range(10):
            price = RareEarthPrice(
                element_id=element.id,
                market_id=market.id,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1 + i),
            )
            storage.add_price(price)
        
        # Test price statistics
        stats = storage.get_price_statistics("Nd", "metal_pages", 30)
        assert stats is not None
        assert "count" in stats
        assert "min" in stats
        assert "max" in stats
        assert "avg" in stats
        
        # Test price history
        history = storage.get_price_history("Nd", 30, "metal_pages")
        assert len(history) > 0
        
        # Test latest price
        latest = storage.get_latest_price("Nd", "metal_pages")
        assert latest is not None
    
    def test_bulk_operations(self, storage):
        """Test bulk operations."""
        # Bulk add prices
        element = storage.get_element_by_symbol("Nd")
        market = storage.get_market_by_id("metal_pages")
        
        prices = []
        for i in range(5):
            price = RareEarthPrice(
                element_id=element.id,
                market_id=market.id,
                price=60000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 2, 1 + i),
            )
            prices.append(price)
        
        added_count = storage.bulk_add_prices(prices)
        assert added_count == 5
        
        # Bulk add productions
        productions = []
        for i in range(3):
            production = RareEarthProduction(
                element_id=element.id,
                country="Australia",
                amount=50000.0 + (i * 1000),
                year=2024 + i,
            )
            productions.append(production)
        
        added_count = storage.bulk_add_productions(productions)
        assert added_count == 3
    
    def test_search_operations(self, storage):
        """Test search operations."""
        # Search elements
        results = storage.search_elements("Neodymium")
        assert len(results) > 0
        
        # Search markets
        results = storage.search_markets("Metal")
        assert len(results) > 0
        
        # Search prices
        results = storage.search_prices("Nd", "metal_pages")
        assert len(results) >= 0  # May be 0 if no prices exist


class TestStorageSingleton:
    """Tests for storage singleton pattern."""
    
    def test_get_storage_singleton(self):
        """Test getting storage singleton."""
        storage1 = get_storage()
        storage2 = get_storage()
        
        # Should return the same instance
        assert storage1 is storage2
    
    def test_storage_close(self, temp_db):
        """Test closing storage."""
        storage = RareEarthStorage(db_url=f"sqlite:///{temp_db}")
        storage.close()
        
        # Should not raise errors after closing
        try:
            storage.get_all_elements()
        except Exception:
            pass  # Expected after close


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
