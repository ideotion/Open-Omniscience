"""
Financial Data Point Model

Represents a single OHLC (Open, High, Low, Close) data point for a company.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class FinancialDataPoint:
    """
    Represents a single OHLC data point for a company.
    
    Attributes:
        id: UUID for this data point
        company_id: Reference to the company
        timestamp: Date/time of this data point
        open: Opening price
        high: Highest price during the period
        low: Lowest price during the period
        close: Closing price
        adjusted_close: Closing price adjusted for dividends/splits
        volume: Trading volume (number of shares)
        currency: Currency of the prices (from exchange)
        is_dividend_adjusted: Whether prices are dividend-adjusted
        data_source: Source of this data (e.g., "yahoo_finance")
        metadata: Additional information (e.g., split factor, dividend amount)
        created_at: When this data point was added to the system
    """
    id: str
    company_id: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    currency: str = "USD"
    adjusted_close: Optional[float] = None
    is_dividend_adjusted: bool = False
    data_source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate financial data point."""
        if not self.id:
            raise ValueError("Data point ID cannot be empty")
        if not self.company_id:
            raise ValueError("Company ID cannot be empty")
        if not self.timestamp:
            raise ValueError("Timestamp cannot be empty")
        if self.open is None or self.high is None or self.low is None or self.close is None:
            raise ValueError("OHLC values cannot be None")
        if self.volume is None or self.volume < 0:
            raise ValueError("Volume must be a non-negative integer")
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
            "company_id": self.company_id,
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
            "metadata": self.metadata,
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
            company_id=data.get("company_id"),
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
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"FinancialDataPoint(id={self.id!r}, company_id={self.company_id!r}, timestamp={self.timestamp!r}, close={self.close!r})"
