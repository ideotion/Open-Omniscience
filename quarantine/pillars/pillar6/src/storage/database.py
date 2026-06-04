"""
Pillar 6 Database Models

SQLAlchemy models for rare earth market intelligence data.
Integrates with the existing Open Omniscience database.
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, 
    Float, Date, Enum, Index, JSON, LargeBinary
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy import create_engine
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import os
from pathlib import Path

# Import existing base and session from main database
# Use relative import to go up to the parent project
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

try:
    from database.models import Base, Session, engine, DATABASE_URL
    Pillar6Base = Base
except ImportError:
    # Fallback: create our own base if main database not available
    from sqlalchemy.orm import declarative_base
    Pillar6Base = declarative_base()
    Base = Pillar6Base
    Session = None
    engine = None
    DATABASE_URL = "sqlite:///pillar6.db"


class RareEarthElementDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth elements.
    
    Represents the 17 rare earth elements with their properties.
    """
    __tablename__ = "rare_earth_elements"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(3), nullable=False, unique=True)
    name = Column(String(50), nullable=False)
    atomic_number = Column(Integer, nullable=False, unique=True)
    category = Column(String(20), nullable=False)  # 'light' or 'heavy'
    element_type = Column(String(20), nullable=False, default="lanthanide")
    atomic_weight = Column(Float)
    melting_point = Column(Float)  # in Celsius
    boiling_point = Column(Float)  # in Celsius
    density = Column(Float)  # in g/cm³
    discovery_year = Column(Integer)
    common_uses = Column(JSON, default=[])
    is_critical = Column(Boolean, default=False)
    aliases = Column(JSON, default=[])
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    prices = relationship("RareEarthPriceDB", back_populates="element")
    productions = relationship("RareEarthProductionDB", back_populates="element")
    inventories = relationship("RareEarthInventoryDB", back_populates="element")
    analyses = relationship("RareEarthAnalysisDB", back_populates="element")
    correlations = relationship("ArticleRareEarthLinkDB", back_populates="element")
    
    __table_args__ = (
        Index("idx_ree_symbol", "symbol", unique=True),
        Index("idx_ree_atomic_number", "atomic_number", unique=True),
        Index("idx_ree_category", "category"),
        Index("idx_ree_critical", "is_critical"),
    )
    
    def __repr__(self) -> str:
        return f"<RareEarthElementDB(symbol={self.symbol}, name={self.name})>"


class RareEarthMarketDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth markets.
    
    Represents markets where rare earth elements are traded.
    """
    __tablename__ = "rare_earth_markets"
    
    id = Column(Integer, primary_key=True)
    market_id = Column(String(50), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    market_type = Column(String(20), nullable=False)  # 'spot', 'futures', 'otc', etc.
    region = Column(String(50), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    description = Column(Text)
    website = Column(String(500))
    is_active = Column(Boolean, default=True)
    data_sources = Column(JSON, default=[])
    supported_elements = Column(JSON, default=[])
    update_frequency = Column(String(20), default="daily")
    last_updated = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    prices = relationship("RareEarthPriceDB", back_populates="market")
    
    __table_args__ = (
        Index("idx_rem_market_id", "market_id", unique=True),
        Index("idx_rem_region", "region"),
        Index("idx_rem_active", "is_active"),
        Index("idx_rem_currency", "currency"),
    )
    
    def __repr__(self) -> str:
        return f"<RareEarthMarketDB(market_id={self.market_id}, name={self.name})>"


class RareEarthPriceDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth price data.
    
    Stores historical price data for rare earth elements from various markets.
    """
    __tablename__ = "rare_earth_prices"
    
    id = Column(Integer, primary_key=True)
    element_id = Column(Integer, ForeignKey("rare_earth_elements.id"), nullable=False)
    market_id = Column(Integer, ForeignKey("rare_earth_markets.id"), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    price_type = Column(String(20), nullable=False, default="spot")  # 'spot', 'futures', etc.
    price_unit = Column(String(20), nullable=False, default="per_kg")  # 'per_kg', 'per_ton', etc.
    purity_grade = Column(String(20), nullable=False, default="commercial")
    date = Column(Date, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.utcnow())
    source_url = Column(String(1000))
    is_verified = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    element = relationship("RareEarthElementDB", back_populates="prices")
    market = relationship("RareEarthMarketDB", back_populates="prices")
    
    __table_args__ = (
        Index("idx_rep_element_date", "element_id", "date"),
        Index("idx_rep_market_date", "market_id", "date"),
        Index("idx_rep_timestamp", "timestamp"),
        Index("idx_rep_element_market", "element_id", "market_id"),
    )
    
    @property
    def price_per_kg(self) -> float:
        """Convert price to per kg."""
        if self.price_unit == "per_kg":
            return self.price
        elif self.price_unit == "per_ton":
            return self.price / 1000
        elif self.price_unit == "per_gram":
            return self.price * 1000
        return self.price
    
    def __repr__(self) -> str:
        return f"<RareEarthPriceDB(element_id={self.element_id}, market_id={self.market_id}, date={self.date}, price={self.price})>"


class RareEarthProductionDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth production data.
    
    Stores production data by element, country, and company.
    """
    __tablename__ = "rare_earth_productions"
    
    id = Column(Integer, primary_key=True)
    element_id = Column(Integer, ForeignKey("rare_earth_elements.id"), nullable=False)
    country = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    production_type = Column(String(20), nullable=False, default="total")  # 'mine', 'refined', etc.
    production_unit = Column(String(20), nullable=False, default="tonnes")
    year = Column(Integer, nullable=False)
    quarter = Column(Integer)
    month = Column(Integer)
    date = Column(Date)
    company = Column(String(200))
    source = Column(String(200))
    source_url = Column(String(1000))
    is_estimated = Column(Boolean, default=True)
    confidence = Column(Float, default=1.0)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    element = relationship("RareEarthElementDB", back_populates="productions")
    
    __table_args__ = (
        Index("idx_rep_element_country_year", "element_id", "country", "year"),
        Index("idx_rep_country_year", "country", "year"),
        Index("idx_rep_company", "company"),
        Index("idx_rep_year", "year"),
    )
    
    @property
    def tonnes(self) -> float:
        """Convert production amount to tonnes."""
        if self.production_unit == "tonnes":
            return self.amount
        elif self.production_unit == "kg":
            return self.amount / 1000
        elif self.production_unit == "grams":
            return self.amount / 1000000
        return self.amount
    
    def __repr__(self) -> str:
        return f"<RareEarthProductionDB(element_id={self.element_id}, country={self.country}, year={self.year}, amount={self.amount})>"


class RareEarthInventoryDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth inventory/stockpile data.
    
    Stores inventory data by element, country, and holder.
    """
    __tablename__ = "rare_earth_inventories"
    
    id = Column(Integer, primary_key=True)
    element_id = Column(Integer, ForeignKey("rare_earth_elements.id"), nullable=False)
    country = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    inventory_type = Column(String(50), nullable=False, default="commercial")  # 'stockpile', 'strategic_reserve', etc.
    inventory_unit = Column(String(20), nullable=False, default="tonnes")
    year = Column(Integer, nullable=False)
    date = Column(Date)
    holder = Column(String(200))
    source = Column(String(200))
    source_url = Column(String(1000))
    is_estimated = Column(Boolean, default=True)
    confidence = Column(Float, default=1.0)
    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    element = relationship("RareEarthElementDB", back_populates="inventories")
    
    __table_args__ = (
        Index("idx_rei_element_country_year", "element_id", "country", "year"),
        Index("idx_rei_country_year", "country", "year"),
        Index("idx_rei_holder", "holder"),
        Index("idx_rei_inventory_type", "inventory_type"),
    )
    
    @property
    def tonnes(self) -> float:
        """Convert inventory amount to tonnes."""
        if self.inventory_unit == "tonnes":
            return self.amount
        elif self.inventory_unit == "kg":
            return self.amount / 1000
        elif self.inventory_unit == "grams":
            return self.amount / 1000000
        return self.amount
    
    def __repr__(self) -> str:
        return f"<RareEarthInventoryDB(element_id={self.element_id}, country={self.country}, year={self.year}, amount={self.amount})>"


class RareEarthAnalysisDB(Pillar6Base):
    """
    SQLAlchemy model for rare earth analysis results.
    
    Stores analysis results for price fluctuations, trends, anomalies, etc.
    """
    __tablename__ = "rare_earth_analyses"
    
    id = Column(Integer, primary_key=True)
    element_id = Column(Integer, ForeignKey("rare_earth_elements.id"), nullable=False)
    analysis_type = Column(String(50), nullable=False)  # 'price_fluctuation', 'trend', 'anomaly', etc.
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    results = Column(JSON, default={})
    severity = Column(String(20), default="medium")  # 'low', 'medium', 'high', 'critical'
    confidence = Column(Float, default=1.0)
    direction = Column(String(20), default="stable")  # 'up', 'down', 'stable', 'volatile'
    magnitude = Column(Float, default=0.0)
    insights = Column(Text)
    recommendations = Column(JSON, default=[])
    related_articles = Column(JSON, default=[])
    related_markets = Column(JSON, default=[])
    extra_metadata = Column(JSON, default={})
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    element = relationship("RareEarthElementDB", back_populates="analyses")
    
    __table_args__ = (
        Index("idx_rea_element_type", "element_id", "analysis_type"),
        Index("idx_rea_dates", "start_date", "end_date"),
        Index("idx_rea_severity", "severity"),
        Index("idx_rea_created_at", "created_at"),
    )
    
    @property
    def significance(self) -> float:
        """Calculate significance score (0-100)."""
        severity_weight = {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }
        severity_score = severity_weight.get(self.severity, 1) * 25
        confidence_score = self.confidence * 100
        magnitude_score = min(self.magnitude * 10, 100)
        
        significance = (severity_score * 0.4) + (confidence_score * 0.3) + (magnitude_score * 0.3)
        return min(significance, 100)
    
    def __repr__(self) -> str:
        return f"<RareEarthAnalysisDB(element_id={self.element_id}, analysis_type={self.analysis_type}, start_date={self.start_date}, end_date={self.end_date})>"


class ArticleRareEarthLinkDB(Pillar6Base):
    """
    SQLAlchemy model for correlations between articles and rare earth data.
    
    Links articles from the main database to rare earth market data.
    """
    __tablename__ = "article_rare_earth_links"
    
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    element_id = Column(Integer, ForeignKey("rare_earth_elements.id"), nullable=False)
    correlation_type = Column(String(50), nullable=False, default="price_news")  # 'price_news', 'production_news', etc.
    correlation_score = Column(Float, default=0.0)
    correlation_strength = Column(String(20), default="none")  # 'none', 'weak', 'moderate', 'strong', 'very_strong'
    sentiment = Column(String(20), default="neutral")  # 'positive', 'negative', 'neutral', 'mixed'
    sentiment_score = Column(Float, default=0.0)
    date = Column(Date, nullable=False, default=lambda: date.today())
    time_lag_days = Column(Integer, default=0)
    price_change_pct = Column(Float)
    volume_change_pct = Column(Float)
    keywords = Column(JSON, default=[])
    entities = Column(JSON, default=[])
    confidence = Column(Float, default=1.0)
    insights = Column(Text)
    is_significant = Column(Boolean, default=False)
    p_value = Column(Float)
    extra_metadata = Column(JSON, default={})
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, onupdate=lambda: datetime.utcnow())
    
    # Relationships
    element = relationship("RareEarthElementDB", back_populates="correlations")
    
    __table_args__ = (
        Index("idx_arel_article_element", "article_id", "element_id", unique=True),
        Index("idx_arel_correlation_type", "correlation_type"),
        Index("idx_arel_correlation_score", "correlation_score"),
        Index("idx_arel_sentiment", "sentiment"),
        Index("idx_arel_date", "date"),
        Index("idx_arel_significant", "is_significant"),
    )
    
    @property
    def strength_level(self) -> int:
        """Get numerical strength level (0-4)."""
        strength_map = {
            "none": 0,
            "weak": 1,
            "moderate": 2,
            "strong": 3,
            "very_strong": 4,
        }
        return strength_map.get(self.correlation_strength, 0)
    
    @property
    def significance_score(self) -> float:
        """Calculate overall significance score (0-100)."""
        correlation_score = self.correlation_score * 100
        confidence_score = self.confidence * 100
        strength_score = self.strength_level * 25
        significance_score = (1 - self.p_value) * 100 if self.p_value else 0
        
        significance = (
            correlation_score * 0.4 +
            confidence_score * 0.2 +
            strength_score * 0.2 +
            significance_score * 0.2
        )
        return min(significance, 100)
    
    def __repr__(self) -> str:
        return f"<ArticleRareEarthLinkDB(article_id={self.article_id}, element_id={self.element_id}, correlation_type={self.correlation_type})>"


# Time-series optimized tables for high-frequency data
class RareEarthPriceTimeSeriesDB(Pillar6Base):
    """
    Time-series optimized table for high-frequency price data.
    
    Uses a more compact storage format for time-series analysis.
    """
    __tablename__ = "rare_earth_price_timeseries"
    
    id = Column(Integer, primary_key=True)
    element_symbol = Column(String(3), nullable=False)
    market_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    price_unit = Column(String(20), nullable=False, default="per_kg")
    is_normalized = Column(Boolean, default=False)
    normalized_price = Column(Float)
    
    __table_args__ = (
        Index("idx_repts_element_market_timestamp", "element_symbol", "market_id", "timestamp"),
        Index("idx_repts_timestamp", "timestamp"),
        Index("idx_repts_element_timestamp", "element_symbol", "timestamp"),
    )
    
    def __repr__(self) -> str:
        return f"<RareEarthPriceTimeSeriesDB(symbol={self.element_symbol}, market={self.market_id}, timestamp={self.timestamp}, price={self.price})>"


# Create all tables
def create_tables():
    """Create all Pillar 6 database tables."""
    Pillar6Base.metadata.create_all(bind=engine)
    print("Pillar 6 database tables created successfully.")


def drop_tables():
    """Drop all Pillar 6 database tables."""
    Pillar6Base.metadata.drop_all(bind=engine)
    print("Pillar 6 database tables dropped successfully.")


# Database session utilities
class RareEarthDatabase:
    """
    Database manager for Pillar 6 operations.
    
    Provides a high-level interface for database operations.
    """
    
    def __init__(self, session_factory=Session):
        """Initialize the database manager."""
        self.Session = session_factory
        self.engine = engine
    
    def get_session(self):
        """Get a new database session."""
        return self.Session()
    
    def create_all_tables(self):
        """Create all Pillar 6 tables."""
        create_tables()
    
    def drop_all_tables(self):
        """Drop all Pillar 6 tables."""
        drop_tables()
    
    def initialize_database(self):
        """Initialize the database with default data."""
        from .seed_data import seed_rare_earth_elements, seed_rare_earth_markets
        
        create_tables()
        
        # Seed default data
        seed_rare_earth_elements()
        seed_rare_earth_markets()
        
        print("Pillar 6 database initialized with default data.")


# Export all models
__all__ = [
    "Pillar6Base",
    "RareEarthElementDB",
    "RareEarthMarketDB",
    "RareEarthPriceDB",
    "RareEarthProductionDB",
    "RareEarthInventoryDB",
    "RareEarthAnalysisDB",
    "ArticleRareEarthLinkDB",
    "RareEarthPriceTimeSeriesDB",
    "RareEarthDatabase",
    "create_tables",
    "drop_tables",
]
