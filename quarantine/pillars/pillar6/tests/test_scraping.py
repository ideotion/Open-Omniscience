"""
Pillar 6 Scraping Tests

Tests for web scraping functionality.
"""

import pytest
import sys
import os
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from unittest.mock import Mock, patch, MagicMock
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraping.base_scraper import (
    RareEarthScraper,
    ScraperConfig,
    ScraperFactory,
)
from src.scraping.price_scraper import PriceScraper
from src.scraping.production_scraper import ProductionScraper
from src.scraping.inventory_scraper import InventoryScraper
from src.models.element import RareEarthElement, ELEMENTS, get_element_by_symbol
from src.models.market import RareEarthMarket, MARKETS, get_market_by_id
from src.models.price import RareEarthPrice
from src.models.production import RareEarthProduction
from src.models.inventory import RareEarthInventory


class TestScraperConfig:
    """Tests for ScraperConfig class."""
    
    def test_default_config(self):
        """Test default scraper configuration."""
        config = ScraperConfig()
        
        assert config.request_timeout == 30
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.rate_limit_delay == 0.5
        assert config.user_agent is not None
        assert config.respect_robots_txt is True
        assert config.cache_enabled is True
        assert config.cache_dir == ".scraper_cache"
        assert config.log_level == "INFO"
    
    def test_custom_config(self):
        """Test custom scraper configuration."""
        config = ScraperConfig(
            request_timeout=60,
            max_retries=5,
            retry_delay=2.0,
            rate_limit_delay=1.0,
            user_agent="CustomAgent",
            respect_robots_txt=False,
            cache_enabled=False,
            cache_dir="/tmp/cache",
            log_level="DEBUG",
        )
        
        assert config.request_timeout == 60
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.rate_limit_delay == 1.0
        assert config.user_agent == "CustomAgent"
        assert config.respect_robots_txt is False
        assert config.cache_enabled is False
        assert config.cache_dir == "/tmp/cache"
        assert config.log_level == "DEBUG"
    
    def test_config_to_dict(self):
        """Test converting config to dictionary."""
        config = ScraperConfig()
        config_dict = config.to_dict()
        
        assert "request_timeout" in config_dict
        assert "max_retries" in config_dict
        assert "user_agent" in config_dict
        assert config_dict["request_timeout"] == 30
    
    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        config_data = {
            "request_timeout": 45,
            "max_retries": 4,
            "user_agent": "TestAgent",
        }
        
        config = ScraperConfig.from_dict(config_data)
        
        assert config.request_timeout == 45
        assert config.max_retries == 4
        assert config.user_agent == "TestAgent"


class TestRareEarthScraper:
    """Tests for RareEarthScraper base class."""
    
    def test_scraper_initialization(self):
        """Test scraper initialization."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        assert scraper.config is not None
        assert scraper.session is not None
        assert scraper.cache is not None
        assert scraper.robots_txt_cache is not None
    
    def test_scraper_with_custom_config(self):
        """Test scraper with custom config."""
        config = ScraperConfig(
            request_timeout=60,
            user_agent="TestScraper",
        )
        scraper = RareEarthScraper(config)
        
        assert scraper.config.request_timeout == 60
        assert scraper.config.user_agent == "TestScraper"
    
    def test_fetch_url(self):
        """Test fetching a URL."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Mock the requests.get function
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "<html>Test</html>"
            mock_response.headers = {}
            mock_get.return_value = mock_response
            
            result = scraper.fetch_url("https://example.com")
            
            assert result is not None
            assert result["status_code"] == 200
            assert result["content"] == "<html>Test</html>"
    
    def test_fetch_url_with_retry(self):
        """Test fetching a URL with retries."""
        config = ScraperConfig(max_retries=2)
        scraper = RareEarthScraper(config)
        
        # Mock the requests.get function to fail first, then succeed
        with patch('requests.get') as mock_get:
            mock_response_fail = Mock()
            mock_response_fail.status_code = 500
            
            mock_response_success = Mock()
            mock_response_success.status_code = 200
            mock_response_success.text = "<html>Success</html>"
            mock_response_success.headers = {}
            
            mock_get.side_effect = [mock_response_fail, mock_response_success]
            
            result = scraper.fetch_url("https://example.com")
            
            assert result is not None
            assert result["status_code"] == 200
    
    def test_fetch_url_max_retries_exceeded(self):
        """Test fetching a URL when max retries exceeded."""
        config = ScraperConfig(max_retries=2)
        scraper = RareEarthScraper(config)
        
        # Mock the requests.get function to always fail
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_get.return_value = mock_response
            
            result = scraper.fetch_url("https://example.com")
            
            assert result is None
    
    def test_check_robots_txt(self):
        """Test checking robots.txt."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Mock the requests.get function
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "User-agent: *\nDisallow: /private/"
            mock_get.return_value = mock_response
            
            result = scraper.check_robots_txt("https://example.com")
            
            assert result is True
    
    def test_is_allowed_by_robots_txt(self):
        """Test checking if URL is allowed by robots.txt."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Mock the robots.txt cache
        scraper.robots_txt_cache["https://example.com"] = {
            "user_agents": ["*"],
            "disallowed": ["/private/"]
        }
        
        # Allowed URL
        assert scraper.is_allowed_by_robots_txt("https://example.com/public/") is True
        
        # Disallowed URL
        assert scraper.is_allowed_by_robots_txt("https://example.com/private/") is False
    
    def test_rate_limit(self):
        """Test rate limiting."""
        config = ScraperConfig(rate_limit_delay=0.1)
        scraper = RareEarthScraper(config)
        
        import time
        
        start_time = time.time()
        
        # Call rate_limit multiple times
        for _ in range(3):
            scraper.rate_limit()
        
        elapsed = time.time() - start_time
        
        # Should have waited at least 0.3 seconds (3 * 0.1)
        assert elapsed >= 0.3
    
    def test_rotate_user_agent(self):
        """Test user agent rotation."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Get initial user agent
        initial_ua = scraper.get_user_agent()
        
        # Rotate user agent
        scraper.rotate_user_agent()
        
        # Get new user agent
        new_ua = scraper.get_user_agent()
        
        # Should be different
        assert initial_ua != new_ua
    
    def test_cache_get_set(self):
        """Test cache get and set."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Set cache value
        scraper.cache.set("test_key", "test_value", ttl=60)
        
        # Get cache value
        value = scraper.cache.get("test_key")
        
        assert value == "test_value"
    
    def test_cache_miss(self):
        """Test cache miss."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        # Get non-existent cache value
        value = scraper.cache.get("non_existent_key")
        
        assert value is None
    
    def test_close(self):
        """Test closing scraper."""
        config = ScraperConfig()
        scraper = RareEarthScraper(config)
        
        scraper.close()
        
        # Session should be closed
        assert scraper.session is None


class TestPriceScraper:
    """Tests for PriceScraper class."""
    
    def test_price_scraper_initialization(self):
        """Test price scraper initialization."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        assert scraper.config is not None
        assert scraper.market_selectors is not None
        assert len(scraper.market_selectors) > 0
    
    def test_get_supported_markets(self):
        """Test getting supported markets."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        markets = scraper.get_supported_markets()
        
        assert len(markets) > 0
        assert all(isinstance(m, RareEarthMarket) for m in markets)
    
    def test_get_element_mapping(self):
        """Test getting element mapping for a market."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        # Test with a known market
        mapping = scraper.get_element_mapping("metal_pages")
        
        assert mapping is not None
        assert isinstance(mapping, dict)
    
    def test_parse_price(self):
        """Test parsing price from text."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        # Test parsing a simple price
        price = scraper.parse_price("$50,000.00")
        assert price == 50000.0
        
        # Test parsing with currency symbol
        price = scraper.parse_price("€45,000.50")
        assert price == 45000.5
        
        # Test parsing with different formats
        price = scraper.parse_price("50000")
        assert price == 50000.0
        
        # Test parsing with commas
        price = scraper.parse_price("50,000")
        assert price == 50000.0
    
    def test_parse_date(self):
        """Test parsing date from text."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        # Test parsing different date formats
        date_obj = scraper.parse_date("2024-01-15")
        assert date_obj == date(2024, 1, 15)
        
        date_obj = scraper.parse_date("15/01/2024")
        assert date_obj == date(2024, 1, 15)
        
        date_obj = scraper.parse_date("Jan 15, 2024")
        assert date_obj == date(2024, 1, 15)
    
    def test_scrape_prices(self):
        """Test scraping prices from a market."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        # Mock the fetch_url method
        with patch.object(scraper, 'fetch_url') as mock_fetch:
            mock_fetch.return_value = {
                "status_code": 200,
                "content": "<html>Test content</html>",
            }
            
            # Mock the parse_price_page method
            with patch.object(scraper, 'parse_price_page') as mock_parse:
                mock_parse.return_value = [
                    RareEarthPrice(
                        element_id=1,
                        market_id=1,
                        price=50000.0,
                        currency="USD",
                        date=date(2024, 1, 15),
                    )
                ]
                
                prices = scraper.scrape_prices("metal_pages")
                
                assert len(prices) == 1
                assert prices[0].price == 50000.0
    
    def test_scrape_all_prices(self):
        """Test scraping prices from all markets."""
        config = ScraperConfig()
        scraper = PriceScraper(config)
        
        # Mock the scrape_prices method
        with patch.object(scraper, 'scrape_prices') as mock_scrape:
            mock_scrape.return_value = [
                RareEarthPrice(
                    element_id=1,
                    market_id=1,
                    price=50000.0,
                    currency="USD",
                    date=date(2024, 1, 15),
                )
            ]
            
            all_prices = scraper.scrape_all_prices()
            
            assert len(all_prices) > 0


class TestProductionScraper:
    """Tests for ProductionScraper class."""
    
    def test_production_scraper_initialization(self):
        """Test production scraper initialization."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        assert scraper.config is not None
        assert scraper.data_sources is not None
        assert len(scraper.data_sources) > 0
    
    def test_get_supported_sources(self):
        """Test getting supported data sources."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        sources = scraper.get_supported_sources()
        
        assert len(sources) > 0
    
    def test_get_country_mapping(self):
        """Test getting country mapping."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        mapping = scraper.get_country_mapping()
        
        assert mapping is not None
        assert isinstance(mapping, dict)
    
    def test_get_company_mapping(self):
        """Test getting company mapping."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        mapping = scraper.get_company_mapping()
        
        assert mapping is not None
        assert isinstance(mapping, dict)
    
    def test_parse_production(self):
        """Test parsing production value from text."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        # Test parsing a simple production value
        production = scraper.parse_production("100,000 tonnes")
        assert production == 100000.0
        
        # Test parsing with different units
        production = scraper.parse_production("50,000 kg")
        assert production == 50.0  # Converted to tonnes
        
        # Test parsing with different formats
        production = scraper.parse_production("100000")
        assert production == 100000.0
    
    def test_scrape_productions(self):
        """Test scraping productions from a source."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        # Mock the fetch_url method
        with patch.object(scraper, 'fetch_url') as mock_fetch:
            mock_fetch.return_value = {
                "status_code": 200,
                "content": "<html>Test content</html>",
            }
            
            # Mock the parse_production_page method
            with patch.object(scraper, 'parse_production_page') as mock_parse:
                mock_parse.return_value = [
                    RareEarthProduction(
                        element_id=1,
                        country="China",
                        amount=100000.0,
                        year=2024,
                    )
                ]
                
                productions = scraper.scrape_productions("usgs")
                
                assert len(productions) == 1
                assert productions[0].amount == 100000.0
    
    def test_scrape_all_productions(self):
        """Test scraping productions from all sources."""
        config = ScraperConfig()
        scraper = ProductionScraper(config)
        
        # Mock the scrape_productions method
        with patch.object(scraper, 'scrape_productions') as mock_scrape:
            mock_scrape.return_value = [
                RareEarthProduction(
                    element_id=1,
                    country="China",
                    amount=100000.0,
                    year=2024,
                )
            ]
            
            all_productions = scraper.scrape_all_productions()
            
            assert len(all_productions) > 0


class TestInventoryScraper:
    """Tests for InventoryScraper class."""
    
    def test_inventory_scraper_initialization(self):
        """Test inventory scraper initialization."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        assert scraper.config is not None
        assert scraper.data_sources is not None
        assert len(scraper.data_sources) > 0
    
    def test_get_supported_sources(self):
        """Test getting supported data sources."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        sources = scraper.get_supported_sources()
        
        assert len(sources) > 0
    
    def test_get_holder_mapping(self):
        """Test getting holder mapping."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        mapping = scraper.get_holder_mapping()
        
        assert mapping is not None
        assert isinstance(mapping, dict)
    
    def test_parse_inventory(self):
        """Test parsing inventory value from text."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        # Test parsing a simple inventory value
        inventory = scraper.parse_inventory("5,000 tonnes")
        assert inventory == 5000.0
        
        # Test parsing with different units
        inventory = scraper.parse_inventory("1,000,000 kg")
        assert inventory == 1000.0  # Converted to tonnes
    
    def test_scrape_inventories(self):
        """Test scraping inventories from a source."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        # Mock the fetch_url method
        with patch.object(scraper, 'fetch_url') as mock_fetch:
            mock_fetch.return_value = {
                "status_code": 200,
                "content": "<html>Test content</html>",
            }
            
            # Mock the parse_inventory_page method
            with patch.object(scraper, 'parse_inventory_page') as mock_parse:
                mock_parse.return_value = [
                    RareEarthInventory(
                        element_id=1,
                        country="USA",
                        amount=5000.0,
                        year=2024,
                        holder="Department of Defense",
                    )
                ]
                
                inventories = scraper.scrape_inventories("usgs")
                
                assert len(inventories) == 1
                assert inventories[0].amount == 5000.0
    
    def test_scrape_all_inventories(self):
        """Test scraping inventories from all sources."""
        config = ScraperConfig()
        scraper = InventoryScraper(config)
        
        # Mock the scrape_inventories method
        with patch.object(scraper, 'scrape_inventories') as mock_scrape:
            mock_scrape.return_value = [
                RareEarthInventory(
                    element_id=1,
                    country="USA",
                    amount=5000.0,
                    year=2024,
                )
            ]
            
            all_inventories = scraper.scrape_all_inventories()
            
            assert len(all_inventories) > 0


class TestScraperFactory:
    """Tests for ScraperFactory class."""
    
    def test_create_price_scraper(self):
        """Test creating a price scraper."""
        config = ScraperConfig()
        scraper = ScraperFactory.create_scraper("price", config)
        
        assert isinstance(scraper, PriceScraper)
    
    def test_create_production_scraper(self):
        """Test creating a production scraper."""
        config = ScraperConfig()
        scraper = ScraperFactory.create_scraper("production", config)
        
        assert isinstance(scraper, ProductionScraper)
    
    def test_create_inventory_scraper(self):
        """Test creating an inventory scraper."""
        config = ScraperConfig()
        scraper = ScraperFactory.create_scraper("inventory", config)
        
        assert isinstance(scraper, InventoryScraper)
    
    def test_create_unknown_scraper(self):
        """Test creating an unknown scraper type."""
        config = ScraperConfig()
        
        with pytest.raises(ValueError):
            ScraperFactory.create_scraper("unknown", config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
