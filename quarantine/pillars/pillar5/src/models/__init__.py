"""
Pillar 5 Models

Data models for the financial intelligence system.
Includes models for exchanges, instruments, OHLC data, fundamentals, metrics, and correlations.
"""

from pillar5.src.models.base import Base, engine, SessionLocal, init_db, drop_db, get_db
from pillar5.src.models.exchange import Exchange, ExchangeDB
from pillar5.src.models.financial_instrument import FinancialInstrument, FinancialInstrumentDB
from pillar5.src.models.financial_data import FinancialDataPoint, FinancialDataPointDB
from pillar5.src.models.instrument_fundamentals import InstrumentFundamentals, InstrumentFundamentalsDB
from pillar5.src.models.analysis import FinancialAnalysis, FinancialAnalysisDB
from pillar5.src.models.correlation import ArticleFinancialLink, ArticleFinancialLinkDB
from pillar5.src.models.financial_metric import FinancialMetric, FinancialMetricDB
from pillar5.src.models.instrument_keyword import InstrumentKeyword, InstrumentKeywordDB

__all__ = [
    # Base and utilities
    "Base",
    "engine",
    "SessionLocal",
    "init_db",
    "drop_db",
    "get_db",
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
]
