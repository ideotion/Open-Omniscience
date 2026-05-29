"""
Company Model

Represents a company listed on a stock exchange.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class Company:
    """
    Represents a company listed on a stock exchange.
    
    Attributes:
        id: Unique identifier (ISIN, ticker, or generated UUID)
        ticker: Stock ticker symbol (e.g., "AAPL", "GOOGL")
        exchange_id: Reference to the exchange where company is listed
        name: Company name (e.g., "Apple Inc.")
        sector: Industry sector (e.g., "Technology", "Healthcare")
        industry: Specific industry (e.g., "Software", "Pharmaceuticals")
        founded_year: Year the company was founded
        headquarters: Headquarters location (city, country)
        website: Company website URL
        description: Business description
        is_active: Whether the company is currently listed
        last_updated: Last data update timestamp
        metadata: Additional company-specific information
        created_at: When the company was added to the system
        updated_at: When the company was last updated
    """
    id: str
    ticker: str
    exchange_id: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    last_updated: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate company data."""
        if not self.id:
            raise ValueError("Company ID cannot be empty")
        if not self.ticker:
            raise ValueError("Company ticker cannot be empty")
        if not self.exchange_id:
            raise ValueError("Exchange ID cannot be empty")
        if not self.name:
            raise ValueError("Company name cannot be empty")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert company to dictionary."""
        return {
            "id": self.id,
            "ticker": self.ticker,
            "exchange_id": self.exchange_id,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "founded_year": self.founded_year,
            "headquarters": self.headquarters,
            "website": self.website,
            "description": self.description,
            "is_active": self.is_active,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Company":
        """Create company from dictionary."""
        return cls(
            id=data.get("id"),
            ticker=data.get("ticker"),
            exchange_id=data.get("exchange_id"),
            name=data.get("name"),
            sector=data.get("sector"),
            industry=data.get("industry"),
            founded_year=data.get("founded_year"),
            headquarters=data.get("headquarters"),
            website=data.get("website"),
            description=data.get("description"),
            is_active=data.get("is_active", True),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else None,
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    @property
    def display_name(self) -> str:
        """Get display name (ticker + name)."""
        return f"{self.ticker}: {self.name}"
    
    def __repr__(self) -> str:
        return f"Company(id={self.id!r}, ticker={self.ticker!r}, name={self.name!r})"
