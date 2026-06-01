"""
Pillar 5: Global Financial Intelligence

This package implements a comprehensive financial data analysis system
for Open Omniscience, including:
- Scraping of OHLC data, fundamentals, and metadata for stocks, ETFs, indices, commodities, forex, and crypto.
- Pre-computed metrics (80+ grouped by theme) for technical and fundamental analysis.
- Hybrid correlation engine to link financial data with news articles.
- Centralized storage in the same database as articles.

Author: Ideotion
License: GNU GPLv3
"""

from pillar5.src.models import (
    Exchange,
    FinancialInstrument,
    FinancialDataPoint,
    InstrumentFundamentals,
    FinancialAnalysis,
    ArticleFinancialLink,
    FinancialMetric,
    InstrumentKeyword,
    ExchangeDB,
    FinancialInstrumentDB,
    FinancialDataPointDB,
    InstrumentFundamentalsDB,
    FinancialAnalysisDB,
    ArticleFinancialLinkDB,
    FinancialMetricDB,
    InstrumentKeywordDB,
)

# Import scraping modules
try:
    from pillar5.src.scraping import (
        EthicalScraper,
        RateLimiter,
        CacheManager,
        ScraperConfig,
        ExchangeDiscovery,
        ExchangeInfo,
        InstrumentDiscovery,
        InstrumentInfo,
        OHLCScraper,
        OHLCData,
        FundamentalsScraper,
        FundamentalsData,
        KeywordExtractor,
        ExtractedKeyword,
    )
except ImportError:
    # Scraping dependencies not installed
    EthicalScraper = None
    RateLimiter = None
    CacheManager = None
    ScraperConfig = None
    ExchangeDiscovery = None
    ExchangeInfo = None
    InstrumentDiscovery = None
    InstrumentInfo = None
    OHLCScraper = None
    OHLCData = None
    FundamentalsScraper = None
    FundamentalsData = None
    KeywordExtractor = None
    ExtractedKeyword = None

# Import services modules
try:
    from pillar5.src.services import (
        MetricCalculator,
        MetricDefinition,
        MetricGroup,
    )
except ImportError:
    # Services dependencies not installed
    MetricCalculator = None
    MetricDefinition = None
    MetricGroup = None

__all__ = [
    # Dataclass models
    "Exchange",
    "FinancialInstrument",
    "FinancialDataPoint",
    "InstrumentFundamentals",
    "FinancialAnalysis",
    "ArticleFinancialLink",
    "FinancialMetric",
    "InstrumentKeyword",
    # SQLAlchemy models
    "ExchangeDB",
    "FinancialInstrumentDB",
    "FinancialDataPointDB",
    "InstrumentFundamentalsDB",
    "FinancialAnalysisDB",
    "ArticleFinancialLinkDB",
    "FinancialMetricDB",
    "InstrumentKeywordDB",
    # Scraping
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
    # Services
    "MetricCalculator",
    "MetricDefinition",
    "MetricGroup",
]
