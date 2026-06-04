"""
Pillar 5: Financial Intelligence API

This module provides FastAPI endpoints for Pillar 5's financial intelligence system.
Includes endpoints for:
- Exchanges
- Instruments
- OHLC data
- Fundamentals
- Metrics
- Keywords
- Correlations
"""

from pillar5.src.api.financial_routes import router as financial_router

__all__ = ["financial_router"]
