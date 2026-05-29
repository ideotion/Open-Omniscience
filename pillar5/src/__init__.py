"""
Pillar 5: Global Financial Intelligence

Open Omniscience - Financial Data Analysis & Stock Fluctuation Intelligence

This pillar implements a comprehensive global financial intelligence system that:
- Scrapes financial data from worldwide stock exchanges
- Analyzes stock price fluctuations and patterns
- Correlates financial movements with news articles
- Provides visualization-ready data for investigative journalism

Author: Ideotion
License: GNU GPLv3
"""

__version__ = "1.0.0"
__author__ = "Ideotion"
__license__ = "GNU GPLv3"

# Import key modules for easy access
from pillar5.src.models import (
    Exchange,
    Company,
    FinancialDataPoint,
    CompanyFundamentals,
    FinancialAnalysis,
    ArticleFinancialLink,
)

from pillar5.src.scraping import (
    ExchangeDiscovery,
    CompanyDiscovery,
    OHLCScraper,
    FundamentalsScraper,
)

from pillar5.src.analysis import (
    FluctuationDetector,
    FinancialPatternRecognizer,
    FinancialAnomalyDetector,
    FinancialCorrelationEngine,
    FinancialNormalizer,
)

from pillar5.src.storage import (
    TimeSeriesStorage,
    AggregationEngine,
    RetentionManager,
)

__all__ = [
    # Models
    "Exchange",
    "Company",
    "FinancialDataPoint",
    "CompanyFundamentals",
    "FinancialAnalysis",
    "ArticleFinancialLink",
    # Scraping
    "ExchangeDiscovery",
    "CompanyDiscovery",
    "OHLCScraper",
    "FundamentalsScraper",
    # Analysis
    "FluctuationDetector",
    "FinancialPatternRecognizer",
    "FinancialAnomalyDetector",
    "FinancialCorrelationEngine",
    "FinancialNormalizer",
    # Storage
    "TimeSeriesStorage",
    "AggregationEngine",
    "RetentionManager",
]
