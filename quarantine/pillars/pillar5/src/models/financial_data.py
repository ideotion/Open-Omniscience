"""
Financial Data Point Model

Represents a single OHLC (Open, High, Low, Close) data point for a financial instrument.
Updated to use instrument_id instead of company_id to support all asset classes.
Includes both dataclass and SQLAlchemy model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


@dataclass
class FinancialDataPoint:
    """
    Represents a single OHLC data point for a financial instrument.
    
    Attributes:
        id: UUID for this data point
        instrument_id: Reference to the financial instrument (replaces company_id)
        timestamp: Date/time of this data point
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        adjusted_close: Closing price adjusted for dividends/splits
        volume: Trading volume (number of shares or units)
        currency: Currency of the prices (from instrument)
        is_dividend_adjusted: Whether prices are dividend-adjusted
        data_source: Source of this data point (e.g., "yahoo_finance")
        metadata: Additional information (e.g., split factor, dividend amount)
        created_at: When this data point was added to the system
    """
    id: str
    instrument_id: str  # Updated from company_id
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float  # Use float for crypto/forex volumes
    currency: str = "USD"
    adjusted_close: Optional[float] = None
    is_dividend_adjusted: bool = False
    data_source: Optional[str] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate financial data point."""
        if not self.id:
            raise ValueError("Data point ID cannot be empty")
        if not self.instrument_id:
            raise ValueError("Instrument ID cannot be empty")
        if not self.timestamp:
            raise ValueError("Timestamp cannot be empty")
        if self.open is None or self.high is None or self.low is None or self.close is None:
            raise ValueError("OHLC values cannot be None")
        if self.volume is None or self.volume < 0:
            raise ValueError("Volume must be a non-negative number")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
    
    @property
    def daily_return(self) -> Optional[float]:
        """Calculate daily return percentage."""
        if self.open and self.open != 0:
            return ((self.close - self.open) / self.open) * 100
        return None
    
    @property
    def price_range(self) -> float:
        """Calculate price range (high - low)."""
        return self.high - self.low
    
    @property
    def price_range_pct(self) -> float:
        """Calculate price range as percentage of open."""
        if self.open and self.open != 0:
            return (self.price_range / self.open) * 100
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert data point to dictionary."""
        return {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adjusted_close": self.adjusted_close,
            "volume": self.volume,
            "currency": self.currency,
            "is_dividend_adjusted": self.is_dividend_adjusted,
            "data_source": self.data_source,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat(),
            "daily_return": self.daily_return,
            "price_range": self.price_range,
            "price_range_pct": self.price_range_pct,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinancialDataPoint":
        """Create data point from dictionary."""
        return cls(
            id=data.get("id"),
            instrument_id=data.get("instrument_id") or data.get("company_id"),  # Backward compatibility
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.utcnow(),
            open=data.get("open"),
            high=data.get("high"),
            low=data.get("low"),
            close=data.get("close"),
            volume=data.get("volume", 0),
            currency=data.get("currency", "USD"),
            adjusted_close=data.get("adjusted_close"),
            is_dividend_adjusted=data.get("is_dividend_adjusted", False),
            data_source=data.get("data_source"),
            extra_metadata=data.get("extra_metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"FinancialDataPoint(id={self.id!r}, instrument_id={self.instrument_id!r}, timestamp={self.timestamp!r}, close={self.close!r})"


# SQLAlchemy model
class FinancialDataPointDB(Base):
    """SQLAlchemy model for the financial_data_points table."""
    __tablename__ = 'financial_data_points'
    
    id = Column(String(36), primary_key=True)  # UUID
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(Float)  # Use Float for crypto/forex volumes
    currency = Column(String(3), default="USD")
    is_dividend_adjusted = Column(Boolean, default=False)
    data_source = Column(String(100))  # e.g., "yahoo_finance", "investing_com"
    extra_metadata = Column(JSON)  # e.g., {"split_factor": 2.0, "dividend": 0.5}
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="data_points")
    
    # Indexes
    __table_args__ = (
        Index('idx_data_point_instrument', 'instrument_id'),
        Index('idx_data_point_timestamp', 'timestamp'),
        Index('idx_data_point_instrument_timestamp', 'instrument_id', 'timestamp'),
    )
    
    def to_dataclass(self) -> FinancialDataPoint:
        """Convert SQLAlchemy model to dataclass."""
        return FinancialDataPoint(
            id=self.id,
            instrument_id=self.instrument_id,
            timestamp=self.timestamp,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            currency=self.currency,
            adjusted_close=self.adjusted_close,
            is_dividend_adjusted=self.is_dividend_adjusted,
            data_source=self.data_source,
            metadata=self.metadata or {},
            created_at=self.created_at,
        )
    
    @classmethod
    def from_dataclass(cls, data_point: FinancialDataPoint) -> "FinancialDataPointDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=data_point.id,
            instrument_id=data_point.instrument_id,
            timestamp=data_point.timestamp,
            open=data_point.open,
            high=data_point.high,
            low=data_point.low,
            close=data_point.close,
            volume=data_point.volume,
            currency=data_point.currency,
            adjusted_close=data_point.adjusted_close,
            is_dividend_adjusted=data_point.is_dividend_adjusted,
            data_source=data_point.data_source,
            extra_metadata=data_point.extra_metadata,
            created_at=data_point.created_at,
        )
