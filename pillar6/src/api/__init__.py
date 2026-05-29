"""
Pillar 6 API Module

REST API functionality for rare earth market data.
"""

from .api import RareEarthAPI
from .routers.price_router import PriceRouter
from .routers.production_router import ProductionRouter
from .routers.analysis_router import AnalysisRouter

__all__ = [
    "RareEarthAPI",
    "PriceRouter",
    "ProductionRouter",
    "AnalysisRouter",
]
