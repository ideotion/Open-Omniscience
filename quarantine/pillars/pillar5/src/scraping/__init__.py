"""
Pillar 5: Scraping Module

This module provides ethical web scraping capabilities for financial data collection.
Includes:
- Base scraper with rate limiting and caching
- Exchange discovery
- Instrument discovery
- OHLC data scraping
- Fundamentals scraping
- Sector/keyword extraction
"""

from pillar5.src.scraping.base import EthicalScraper, RateLimiter, CacheManager, ScraperConfig
from pillar5.src.scraping.exchange_discovery import ExchangeDiscovery, ExchangeInfo
from pillar5.src.scraping.instrument_discovery import InstrumentDiscovery, InstrumentInfo
from pillar5.src.scraping.ohlc_scraper import OHLCScraper, OHLCData
from pillar5.src.scraping.fundamentals_scraper import FundamentalsScraper, FundamentalsData
from pillar5.src.scraping.keyword_extractor import KeywordExtractor, ExtractedKeyword

__all__ = [
    "EthicalScraper",
    "RateLimiter",
    "CacheManager",
    "ScraperConfig",
    "ExchangeDiscovery",
    "ExchangeInfo",
    "InstrumentDiscovery",
    "InstrumentInfo",
    "OHLCScraper",
    "OHLCData",
    "FundamentalsScraper",
    "FundamentalsData",
    "KeywordExtractor",
    "ExtractedKeyword",
]
