"""
Exchange Model

Represents a stock exchange.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class Exchange:
    """
    Represents a stock exchange.
    
    Attributes:
        id: Unique identifier (e.g., "NYSE", "NASDAQ")
        name: Full name (e.g., "New York Stock Exchange")
        country: ISO country code (e.g., "US", "GB")
        currency: Base currency (e.g., "USD", "GBP")
        timezone: Timezone identifier (e.g., "America/New_York")
        website: Official website URL
        trading_hours: Trading hours in ISO format
        is_active: Whether the exchange is currently operational
        last_scraped: Last successful scrape timestamp
        metadata: Additional exchange-specific information
        created_at: When the exchange was added to the system
        updated_at: When the exchange was last updated
    """
    id: str
    name: str
    country: str
    currency: str
    timezone: str
    website: Optional[str] = None
    trading_hours: Optional[str] = None
    is_active: bool = True
    last_scraped: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate exchange data."""
        if not self.id:
            raise ValueError("Exchange ID cannot be empty")
        if not self.name:
            raise ValueError("Exchange name cannot be empty")
        if not self.country or len(self.country) != 2:
            raise ValueError("Country must be a 2-letter ISO code")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a 3-letter ISO code")
        if not self.timezone:
            raise ValueError("Timezone cannot be empty")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exchange to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "currency": self.currency,
            "timezone": self.timezone,
            "website": self.website,
            "trading_hours": self.trading_hours,
            "is_active": self.is_active,
            "last_scraped": self.last_scraped.isoformat() if self.last_scraped else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Exchange":
        """Create exchange from dictionary."""
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            country=data.get("country"),
            currency=data.get("currency"),
            timezone=data.get("timezone"),
            website=data.get("website"),
            trading_hours=data.get("trading_hours"),
            is_active=data.get("is_active", True),
            last_scraped=datetime.fromisoformat(data["last_scraped"]) if data.get("last_scraped") else None,
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"Exchange(id={self.id!r}, name={self.name!r}, country={self.country!r})"
