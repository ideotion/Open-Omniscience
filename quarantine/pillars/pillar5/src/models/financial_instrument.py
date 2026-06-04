"""
Financial Instrument Model

Represents a unified model for all financial instruments (stocks, ETFs, indices, commodities, forex, crypto).
This replaces the original Company model to support all asset classes.
Includes both dataclass and SQLAlchemy model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from sqlalchemy import Column, String, Boolean, DateTime, Text, Float, Integer, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


class InstrumentType(Enum):
    """Types of financial instruments."""
    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    COMMODITY = "commodity"
    FOREX = "forex"
    CRYPTO = "crypto"


@dataclass
class FinancialInstrument:
    """
    Unified model for all financial instruments.
    
    Attributes:
        id: Unique identifier (ISIN for stocks/ETFs, symbol for crypto/forex, or generated UUID)
        symbol: Trading symbol (e.g., "AAPL", "SPY", "BTC-USD", "EUR-USD", "XAU-USD")
        name: Full name (e.g., "Apple Inc.", "SPDR S&P 500 ETF", "Bitcoin")
        type: Instrument type (stock, etf, index, commodity, forex, crypto)
        exchange_id: Reference to exchange (if applicable; NULL for forex/crypto)
        sector: Industry sector (e.g., "Technology", "Energy"; NULL for non-stock types)
        industry: Specific industry (e.g., "Software", "Oil & Gas"; NULL for non-stock types)
        category: Sub-category (e.g., "Large Cap", "Small Cap", "Government Bond")
        base_currency: Base currency (e.g., "USD", "EUR")
        quote_currency: Quote currency (for forex/crypto; e.g., "USD" in "EUR-USD")
        description: Business/asset description
        founded_year: Year founded (for companies; NULL otherwise)
        headquarters: Headquarters location (for companies; NULL otherwise)
        website: Official website URL
        is_active: Whether the instrument is currently tradable
        last_updated: Last data update timestamp
        extra_metadata: Additional instrument-specific info (e.g., contract size for commodities)
        created_at: When the instrument was added to the system
        updated_at: When the instrument was last updated
    """
    id: str
    symbol: str
    name: str
    type: str  # InstrumentType enum as string
    exchange_id: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    category: Optional[str] = None
    base_currency: str = "USD"
    quote_currency: Optional[str] = None
    description: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    website: Optional[str] = None
    is_active: bool = True
    last_updated: Optional[datetime] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate financial instrument data."""
        if not self.id:
            raise ValueError("Instrument ID cannot be empty")
        if not self.symbol:
            raise ValueError("Instrument symbol cannot be empty")
        if not self.name:
            raise ValueError("Instrument name cannot be empty")
        if not self.type:
            raise ValueError("Instrument type cannot be empty")
        
        # Validate type is one of the allowed values
        valid_types = {e.value for e in InstrumentType}
        if self.type not in valid_types:
            raise ValueError(f"Instrument type must be one of {valid_types}")
        
        if not self.base_currency or len(self.base_currency) != 3:
            raise ValueError("Base currency must be a 3-letter ISO code")
        
        if self.quote_currency and len(self.quote_currency) != 3:
            raise ValueError("Quote currency must be a 3-letter ISO code")
    
    @property
    def display_name(self) -> str:
        """Get display name (symbol + name)."""
        return f"{self.symbol}: {self.name}"
    
    @property
    def is_forex(self) -> bool:
        """Check if this is a forex pair."""
        return self.type == InstrumentType.FOREX.value
    
    @property
    def is_crypto(self) -> bool:
        """Check if this is a cryptocurrency."""
        return self.type == InstrumentType.CRYPTO.value
    
    @property
    def is_traditional(self) -> bool:
        """Check if this is a traditional instrument (stock, ETF, index, commodity)."""
        return self.type in {InstrumentType.STOCK.value, InstrumentType.ETF.value, 
                             InstrumentType.INDEX.value, InstrumentType.COMMODITY.value}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert instrument to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "type": self.type,
            "exchange_id": self.exchange_id,
            "sector": self.sector,
            "industry": self.industry,
            "category": self.category,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "description": self.description,
            "founded_year": self.founded_year,
            "headquarters": self.headquarters,
            "website": self.website,
            "is_active": self.is_active,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinancialInstrument":
        """Create instrument from dictionary."""
        return cls(
            id=data.get("id"),
            symbol=data.get("symbol"),
            name=data.get("name"),
            type=data.get("type", InstrumentType.STOCK.value),
            exchange_id=data.get("exchange_id"),
            sector=data.get("sector"),
            industry=data.get("industry"),
            category=data.get("category"),
            base_currency=data.get("base_currency", "USD"),
            quote_currency=data.get("quote_currency"),
            description=data.get("description"),
            founded_year=data.get("founded_year"),
            headquarters=data.get("headquarters"),
            website=data.get("website"),
            is_active=data.get("is_active", True),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
            extra_metadata=data.get("extra_metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"FinancialInstrument(id={self.id!r}, symbol={self.symbol!r}, name={self.name!r}, type={self.type!r})"


# SQLAlchemy model
class FinancialInstrumentDB(Base):
    """SQLAlchemy model for the financial_instruments table."""
    __tablename__ = 'financial_instruments'
    
    id = Column(String(50), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False, index=True)  # stock, etf, index, commodity, forex, crypto
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    sector = Column(String(100), index=True)
    industry = Column(String(100), index=True)
    category = Column(String(100))
    base_currency = Column(String(3), default="USD")
    quote_currency = Column(String(3))  # For forex/crypto
    description = Column(Text)
    founded_year = Column(Integer)
    headquarters = Column(String(255))
    website = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime)
    extra_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    exchange = relationship("ExchangeDB", back_populates="instruments")
    data_points = relationship("FinancialDataPointDB", back_populates="instrument")
    fundamentals = relationship("InstrumentFundamentalsDB", back_populates="instrument")
    metrics = relationship("FinancialMetricDB", back_populates="instrument")
    keywords = relationship("InstrumentKeywordDB", back_populates="instrument")
    article_links = relationship("ArticleFinancialLinkDB", back_populates="instrument")
    analyses = relationship("FinancialAnalysisDB", back_populates="instrument")
    
    # Indexes
    __table_args__ = (
        Index('idx_instrument_symbol_type', 'symbol', 'type', unique=True),
        Index('idx_instrument_type', 'type'),
        Index('idx_instrument_sector', 'sector'),
        Index('idx_instrument_industry', 'industry'),
        Index('idx_instrument_exchange', 'exchange_id'),
    )
    
    def to_dataclass(self) -> FinancialInstrument:
        """Convert SQLAlchemy model to dataclass."""
        return FinancialInstrument(
            id=self.id,
            symbol=self.symbol,
            name=self.name,
            type=self.type,
            exchange_id=self.exchange_id,
            sector=self.sector,
            industry=self.industry,
            category=self.category,
            base_currency=self.base_currency,
            quote_currency=self.quote_currency,
            description=self.description,
            founded_year=self.founded_year,
            headquarters=self.headquarters,
            website=self.website,
            is_active=self.is_active,
            last_updated=self.last_updated,
            metadata=self.metadata or {},
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
    
    @classmethod
    def from_dataclass(cls, instrument: FinancialInstrument) -> "FinancialInstrumentDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=instrument.id,
            symbol=instrument.symbol,
            name=instrument.name,
            type=instrument.type,
            exchange_id=instrument.exchange_id,
            sector=instrument.sector,
            industry=instrument.industry,
            category=instrument.category,
            base_currency=instrument.base_currency,
            quote_currency=instrument.quote_currency,
            description=instrument.description,
            founded_year=instrument.founded_year,
            headquarters=instrument.headquarters,
            website=instrument.website,
            is_active=instrument.is_active,
            last_updated=instrument.last_updated,
            extra_metadata=instrument.extra_metadata,
            created_at=instrument.created_at,
            updated_at=instrument.updated_at,
        )
