"""
Test Suite for Pillar 5 - Financial Intelligence

This module contains unit and integration tests for all Pillar 5 components:
- Models (SQLAlchemy and dataclass)
- Scraping modules
- Services (MetricCalculator, HybridCorrelationEngine)
- API endpoints
- GUI components (future)

Run tests with:
    python -m pytest pillar5/tests/ -v
"""

from pillar5.tests.test_models import *
from pillar5.tests.test_scraping import *
from pillar5.tests.test_services import *
from pillar5.tests.test_api import *

__all__ = [
    # Models
    'TestFinancialInstrument',
    'TestFinancialDataPoint',
    'TestExchange',
    'TestFinancialMetric',
    'TestInstrumentKeyword',
    'TestArticleFinancialLink',
    'TestFinancialAnalysis',
    'TestInstrumentFundamentals',
    
    # Scraping
    'TestExchangeDiscovery',
    'TestInstrumentDiscovery',
    'TestOHLCScraper',
    'TestFundamentalsScraper',
    'TestKeywordExtractor',
    
    # Services
    'TestMetricCalculator',
    'TestHybridCorrelationEngine',
    
    # API
    'TestFinancialAPI',
]
