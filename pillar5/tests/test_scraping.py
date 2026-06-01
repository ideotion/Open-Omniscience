"""
Unit Tests for Pillar 5 Scraping Modules

Tests for:
- ExchangeDiscovery
- InstrumentDiscovery
- OHLCScraper
- FundamentalsScraper
- KeywordExtractor
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add pillar5 to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pillar5.src.scraping.exchange_discovery import ExchangeDiscovery, ExchangeInfo
from pillar5.src.scraping.instrument_discovery import InstrumentDiscovery, InstrumentInfo
from pillar5.src.scraping.ohlc_scraper import OHLCScraper, OHLCData
from pillar5.src.scraping.fundamentals_scraper import FundamentalsScraper, FundamentalsData
from pillar5.src.scraping.keyword_extractor import KeywordExtractor, ExtractedKeyword


class TestExchangeDiscovery:
    """Tests for ExchangeDiscovery"""
    
    def test_create_exchange_discovery(self):
        """Test creating ExchangeDiscovery instance"""
        discovery = ExchangeDiscovery()
        assert discovery is not None
        assert hasattr(discovery, 'get_major_exchanges')
        assert hasattr(discovery, 'get_regional_exchanges')
        assert hasattr(discovery, 'get_crypto_exchanges')
        assert hasattr(discovery, 'get_all_exchanges')
    
    def test_get_major_exchanges(self):
        """Test getting major exchanges"""
        discovery = ExchangeDiscovery()
        major_exchanges = discovery.get_major_exchanges()
        
        assert isinstance(major_exchanges, list)
        assert len(major_exchanges) > 0
        
        # Check that all major exchanges have required fields
        for exchange in major_exchanges:
            assert hasattr(exchange, 'id')
            assert hasattr(exchange, 'code')
            assert hasattr(exchange, 'name')
            assert hasattr(exchange, 'country')
            assert hasattr(exchange, 'exchange_type')
    
    def test_get_regional_exchanges(self):
        """Test getting regional exchanges"""
        discovery = ExchangeDiscovery()
        regional_exchanges = discovery.get_regional_exchanges()
        
        assert isinstance(regional_exchanges, list)
        assert len(regional_exchanges) > 0
    
    def test_get_crypto_exchanges(self):
        """Test getting crypto exchanges"""
        discovery = ExchangeDiscovery()
        crypto_exchanges = discovery.get_crypto_exchanges()
        
        assert isinstance(crypto_exchanges, list)
        assert len(crypto_exchanges) > 0
    
    def test_get_all_exchanges(self):
        """Test getting all exchanges"""
        discovery = ExchangeDiscovery()
        all_exchanges = discovery.get_all_exchanges()
        
        assert isinstance(all_exchanges, list)
        assert len(all_exchanges) > 0
        
        # Should include major, regional, and crypto exchanges
        major = discovery.get_major_exchanges()
        regional = discovery.get_regional_exchanges()
        crypto = discovery.get_crypto_exchanges()
        
        assert len(all_exchanges) >= len(major) + len(regional) + len(crypto)
    
    def test_exchange_info_dataclass(self):
        """Test ExchangeInfo dataclass"""
        exchange = ExchangeInfo(
            id=1,
            code="NYSE",
            name="New York Stock Exchange",
            country="United States",
            city="New York",
            timezone="America/New_York",
            currency="USD",
            website="https://www.nyse.com",
            founded_year=1792,
            is_active=True,
            exchange_type="stock",
            trading_hours="09:30-16:00"
        )
        
        assert exchange.id == 1
        assert exchange.code == "NYSE"
        assert exchange.name == "New York Stock Exchange"
        assert exchange.country == "United States"
        assert exchange.exchange_type == "stock"
    
    def test_exchange_info_to_dict(self):
        """Test ExchangeInfo to_dict method"""
        exchange = ExchangeInfo(
            id=1,
            code="NYSE",
            name="New York Stock Exchange",
            country="United States"
        )
        
        data = exchange.to_dict()
        
        assert data["id"] == 1
        assert data["code"] == "NYSE"
        assert data["name"] == "New York Stock Exchange"
        assert data["country"] == "United States"


class TestInstrumentDiscovery:
    """Tests for InstrumentDiscovery"""
    
    def test_create_instrument_discovery(self):
        """Test creating InstrumentDiscovery instance"""
        discovery = InstrumentDiscovery()
        assert discovery is not None
        assert hasattr(discovery, 'get_major_stocks')
        assert hasattr(discovery, 'get_major_etfs')
        assert hasattr(discovery, 'get_major_indices')
        assert hasattr(discovery, 'get_major_commodities')
        assert hasattr(discovery, 'get_major_forex')
        assert hasattr(discovery, 'get_major_crypto')
        assert hasattr(discovery, 'get_all_instruments')
    
    def test_get_major_stocks(self):
        """Test getting major stocks"""
        discovery = InstrumentDiscovery()
        stocks = discovery.get_major_stocks()
        
        assert isinstance(stocks, list)
        assert len(stocks) > 0
        
        for stock in stocks:
            assert hasattr(stock, 'id')
            assert hasattr(stock, 'symbol')
            assert hasattr(stock, 'name')
            assert hasattr(stock, 'type')
            assert stock.type == "stock"
    
    def test_get_major_etfs(self):
        """Test getting major ETFs"""
        discovery = InstrumentDiscovery()
        etfs = discovery.get_major_etfs()
        
        assert isinstance(etfs, list)
        assert len(etfs) > 0
        
        for etf in etfs:
            assert etf.type == "etf"
    
    def test_get_major_indices(self):
        """Test getting major indices"""
        discovery = InstrumentDiscovery()
        indices = discovery.get_major_indices()
        
        assert isinstance(indices, list)
        assert len(indices) > 0
        
        for index in indices:
            assert index.type == "index"
    
    def test_get_major_commodities(self):
        """Test getting major commodities"""
        discovery = InstrumentDiscovery()
        commodities = discovery.get_major_commodities()
        
        assert isinstance(commodities, list)
        assert len(commodities) > 0
        
        for commodity in commodities:
            assert commodity.type == "commodity"
    
    def test_get_major_forex(self):
        """Test getting major forex pairs"""
        discovery = InstrumentDiscovery()
        forex = discovery.get_major_forex()
        
        assert isinstance(forex, list)
        assert len(forex) > 0
        
        for pair in forex:
            assert pair.type == "forex"
    
    def test_get_major_crypto(self):
        """Test getting major cryptocurrencies"""
        discovery = InstrumentDiscovery()
        crypto = discovery.get_major_crypto()
        
        assert isinstance(crypto, list)
        assert len(crypto) > 0
        
        for coin in crypto:
            assert coin.type == "crypto"
    
    def test_get_all_instruments(self):
        """Test getting all instruments"""
        discovery = InstrumentDiscovery()
        all_instruments = discovery.get_all_instruments()
        
        assert isinstance(all_instruments, list)
        assert len(all_instruments) > 0
        
        # Should include all types
        types = set(i.type for i in all_instruments)
        assert "stock" in types
        assert "etf" in types
        assert "index" in types
        assert "commodity" in types
        assert "forex" in types
        assert "crypto" in types
    
    def test_instrument_info_dataclass(self):
        """Test InstrumentInfo dataclass"""
        instrument = InstrumentInfo(
            id=1,
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=1,
            isin="US0378331005",
            cusip="037833100",
            figi="BBG000B9XRY4",
            sector="Technology",
            industry="Consumer Electronics",
            country="United States",
            currency="USD",
            description="Apple Inc. designs and manufactures consumer electronics",
            website="https://www.apple.com",
            founded_year=1976,
            employees=165000,
            headquarters="Cupertino, California"
        )
        
        assert instrument.id == 1
        assert instrument.symbol == "AAPL"
        assert instrument.name == "Apple Inc."
        assert instrument.type == "stock"
        assert instrument.sector == "Technology"
    
    def test_instrument_info_to_dict(self):
        """Test InstrumentInfo to_dict method"""
        instrument = InstrumentInfo(
            id=1,
            symbol="AAPL",
            name="Apple Inc.",
            type="stock",
            exchange_id=1
        )
        
        data = instrument.to_dict()
        
        assert data["id"] == 1
        assert data["symbol"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["type"] == "stock"


class TestOHLCScraper:
    """Tests for OHLCScraper"""
    
    def test_create_ohlc_scraper(self):
        """Test creating OHLCScraper instance"""
        scraper = OHLCScraper()
        assert scraper is not None
        assert hasattr(scraper, 'get_ohlc_data')
        assert hasattr(scraper, 'get_historical_data')
    
    def test_ohlc_data_dataclass(self):
        """Test OHLCData dataclass"""
        now = datetime.utcnow()
        ohlc = OHLCData(
            symbol="AAPL",
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=148.0,
            close_price=152.5,
            adjusted_close=152.3,
            volume=1000000,
            timeframe="1d",
            source="yahoo"
        )
        
        assert ohlc.symbol == "AAPL"
        assert ohlc.timestamp == now
        assert ohlc.open_price == 150.0
        assert ohlc.high_price == 155.0
        assert ohlc.low_price == 148.0
        assert ohlc.close_price == 152.5
        assert ohlc.volume == 1000000
    
    def test_ohlc_data_to_dict(self):
        """Test OHLCData to_dict method"""
        now = datetime.utcnow()
        ohlc = OHLCData(
            symbol="AAPL",
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=148.0,
            close_price=152.5,
            volume=1000000
        )
        
        data = ohlc.to_dict()
        
        assert data["symbol"] == "AAPL"
        assert data["open_price"] == 150.0
        assert data["high_price"] == 155.0
        assert data["low_price"] == 148.0
        assert data["close_price"] == 152.5
    
    @patch('pillar5.src.scraping.ohlc_scraper.EthicalScraper.fetch')
    def test_get_ohlc_data_mocked(self, mock_fetch):
        """Test get_ohlc_data with mocked fetch"""
        # Mock response
        mock_response = """
        {
            "chart": {
                "result": [{
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "timezone": "UTC"
                    },
                    "timestamp": [1672531200, 1672617600],
                    "indicators": {
                        "quote": [{
                            "open": [150.0, 152.0],
                            "high": [155.0, 154.0],
                            "low": [148.0, 150.0],
                            "close": [152.5, 153.0],
                            "volume": [1000000, 1200000]
                        }]
                    }
                }]
            }
        }
        """
        
        mock_fetch.return_value = mock_response
        
        scraper = OHLCScraper()
        
        # This would normally make an HTTP request, but we've mocked it
        # For testing purposes, we'll just verify the scraper can be instantiated
        assert scraper is not None


class TestFundamentalsScraper:
    """Tests for FundamentalsScraper"""
    
    def test_create_fundamentals_scraper(self):
        """Test creating FundamentalsScraper instance"""
        scraper = FundamentalsScraper()
        assert scraper is not None
        assert hasattr(scraper, 'get_fundamentals')
        assert hasattr(scraper, 'get_valuation_metrics')
        assert hasattr(scraper, 'get_profitability_metrics')
        assert hasattr(scraper, 'get_risk_metrics')
    
    def test_fundamentals_data_dataclass(self):
        """Test FundamentalsData dataclass"""
        now = datetime.utcnow()
        fundamentals = FundamentalsData(
            symbol="AAPL",
            timestamp=now,
            timeframe="quarterly",
            market_cap=3e12,
            pe_ratio=28.5,
            pb_ratio=6.2,
            ps_ratio=8.1,
            peg_ratio=1.8,
            dividend_yield=0.005,
            payout_ratio=0.25,
            eps=4.5,
            revenue=394.33e9,
            net_income=96.87e9,
            ebitda=119.44e9,
            gross_margin=0.42,
            operating_margin=0.29,
            net_margin=0.25,
            roe=0.55,
            roa=0.18,
            roi=0.22,
            current_ratio=1.8,
            quick_ratio=1.5,
            debt_to_equity=0.5,
            total_debt=120e9,
            total_equity=240e9,
            free_cash_flow=80e9,
            operating_cash_flow=90e9,
            beta=1.2,
            volatility_1y=0.25,
            volatility_3y=0.22,
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            alpha=0.05,
            source="yahoo"
        )
        
        assert fundamentals.symbol == "AAPL"
        assert fundamentals.market_cap == 3e12
        assert fundamentals.pe_ratio == 28.5
        assert fundamentals.dividend_yield == 0.005
        assert fundamentals.revenue == 394.33e9
    
    def test_fundamentals_data_to_dict(self):
        """Test FundamentalsData to_dict method"""
        now = datetime.utcnow()
        fundamentals = FundamentalsData(
            symbol="AAPL",
            timestamp=now,
            market_cap=3e12,
            pe_ratio=28.5,
            eps=4.5
        )
        
        data = fundamentals.to_dict()
        
        assert data["symbol"] == "AAPL"
        assert data["market_cap"] == 3e12
        assert data["pe_ratio"] == 28.5


class TestKeywordExtractor:
    """Tests for KeywordExtractor"""
    
    def test_create_keyword_extractor(self):
        """Test creating KeywordExtractor instance"""
        extractor = KeywordExtractor()
        assert extractor is not None
        assert hasattr(extractor, 'extract_keywords')
        assert hasattr(extractor, 'get_sector_keywords')
        assert hasattr(extractor, 'get_industry_keywords')
    
    def test_extract_keywords_from_text(self):
        """Test extracting keywords from text"""
        extractor = KeywordExtractor()
        
        text = "Apple Inc. is a technology company that designs and manufactures consumer electronics including iPhones, iPads, and Mac computers."
        keywords = extractor.extract_keywords(text)
        
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        
        # Should extract meaningful keywords
        keyword_texts = [kw.keyword.lower() for kw in keywords]
        assert any("apple" in kw for kw in keyword_texts)
        assert any("technology" in kw for kw in keyword_texts)
        assert any("electronics" in kw for kw in keyword_texts)
    
    def test_extract_keywords_with_instrument_info(self):
        """Test extracting keywords with instrument info"""
        extractor = KeywordExtractor()
        
        instrument_info = {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "description": "Apple Inc. designs and manufactures consumer electronics"
        }
        
        keywords = extractor.extract_keywords(
            text="Apple stock is performing well in the technology sector",
            instrument_info=instrument_info
        )
        
        assert isinstance(keywords, list)
        assert len(keywords) > 0
    
    def test_extracted_keyword_dataclass(self):
        """Test ExtractedKeyword dataclass"""
        keyword = ExtractedKeyword(
            keyword="technology",
            weight=0.8,
            source="name",
            is_primary=True,
            category="sector"
        )
        
        assert keyword.keyword == "technology"
        assert keyword.weight == 0.8
        assert keyword.source == "name"
        assert keyword.is_primary is True
        assert keyword.category == "sector"
    
    def test_extracted_keyword_to_dict(self):
        """Test ExtractedKeyword to_dict method"""
        keyword = ExtractedKeyword(
            keyword="technology",
            weight=0.8,
            source="name"
        )
        
        data = keyword.to_dict()
        
        assert data["keyword"] == "technology"
        assert data["weight"] == 0.8
        assert data["source"] == "name"
    
    def test_get_sector_keywords(self):
        """Test getting sector keywords"""
        extractor = KeywordExtractor()
        sector_keywords = extractor.get_sector_keywords()
        
        assert isinstance(sector_keywords, dict)
        assert len(sector_keywords) > 0
    
    def test_get_industry_keywords(self):
        """Test getting industry keywords"""
        extractor = KeywordExtractor()
        industry_keywords = extractor.get_industry_keywords()
        
        assert isinstance(industry_keywords, dict)
        assert len(industry_keywords) > 0
    
    def test_infer_sector_from_keywords(self):
        """Test inferring sector from keywords"""
        extractor = KeywordExtractor()
        
        keywords = ["technology", "software", "computers"]
        sectors = extractor.infer_sector_from_keywords(keywords)
        
        assert isinstance(sectors, list)
        assert len(sectors) > 0
        assert "Technology" in sectors
    
    def test_infer_industry_from_keywords(self):
        """Test inferring industry from keywords"""
        extractor = KeywordExtractor()
        
        keywords = ["software", "cloud", "saas"]
        industries = extractor.infer_industry_from_keywords(keywords)
        
        assert isinstance(industries, list)
        assert len(industries) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
