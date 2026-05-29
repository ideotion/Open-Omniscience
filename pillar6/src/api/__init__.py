"""
Pillar 6 API Module

REST API functionality for rare earth market data.
"""

from .api import RareEarthAPI
from .routers.price_router import PriceRouter, router as price_router
from .routers.production_router import ProductionRouter, router as production_router
from .routers.analysis_router import AnalysisRouter, router as analysis_router

__all__ = [
    "RareEarthAPI",
    "PriceRouter",
    "ProductionRouter",
    "AnalysisRouter",
    "price_router",
    "production_router",
    "analysis_router",
]
