"""
Pillar 6: Rare Earth Market Intelligence

A comprehensive system for scraping, analyzing, and correlating rare earth element
market data with news articles for investigative journalism.

This module provides:
- Web scraping of rare earth prices, production, and inventory data
- Time-series analysis and normalization
- Correlation with news articles
- REST API for data access
- Visualization-ready normalized data
"""

from .models import (
    RareEarthElement,
    RareEarthMarket,
    RareEarthPrice,
    RareEarthProduction,
    RareEarthInventory,
    RareEarthAnalysis,
    ArticleRareEarthLink,
)
from .scraping import (
    RareEarthScraper,
    PriceScraper,
    ProductionScraper,
    InventoryScraper,
)
from .analysis import (
    RareEarthAnalyzer,
    PriceAnalyzer,
    TrendAnalyzer,
    CorrelationAnalyzer,
    NormalizationAnalyzer,
)
from .storage import (
    RareEarthDatabase,
    RareEarthStorage,
)
from .api import (
    RareEarthAPI,
    PriceRouter,
    ProductionRouter,
    AnalysisRouter,
)

__version__ = "0.1.0"
__all__ = [
    # Models
    "RareEarthElement",
    "RareEarthMarket",
    "RareEarthPrice",
    "RareEarthProduction",
    "RareEarthInventory",
    "RareEarthAnalysis",
    "ArticleRareEarthLink",
    # Scraping
    "RareEarthScraper",
    "PriceScraper",
    "ProductionScraper",
    "InventoryScraper",
    # Analysis
    "RareEarthAnalyzer",
    "PriceAnalyzer",
    "TrendAnalyzer",
    "CorrelationAnalyzer",
    "NormalizationAnalyzer",
    # Storage
    "RareEarthDatabase",
    "RareEarthStorage",
    # API
    "RareEarthAPI",
    "PriceRouter",
    "ProductionRouter",
    "AnalysisRouter",
]
