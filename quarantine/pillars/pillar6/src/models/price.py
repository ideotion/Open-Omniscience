"""
Rare Earth Price Model

Defines the RareEarthPrice dataclass for representing price data points.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
import hashlib
import json


class PriceType(Enum):
    """Type of price."""
    SPOT = "spot"
    FUTURES = "futures"
    AVERAGE = "average"
    HIGH = "high"
    LOW = "low"
    OPEN = "open"
    CLOSE = "close"
    SETTLEMENT = "settlement"
    ASK = "ask"
    BID = "bid"
    MID = "mid"


class PriceUnit(Enum):
    """Unit of price measurement."""
    PER_KG = "per_kg"
    PER_TON = "per_ton"
    PER_OUNCE = "per_ounce"
    PER_GRAM = "per_gram"
    PER_LB = "per_lb"


class PurityGrade(Enum):
    """Purity grade of the rare earth material."""
    COMMERCIAL = "commercial"
    HIGH = "high"
    ULTRA_HIGH = "ultra_high"
    TECHNICAL = "technical"
    RESEARCH = "research"
    INDUSTRIAL = "industrial"


@dataclass
class RareEarthPrice:
    """
    Represents a rare earth price data point.
    
    Attributes:
        element_symbol: Chemical symbol of the element
        market_id: ID of the market where price was observed
        price: Price value
        currency: Currency of the price
        price_type: Type of price (spot, futures, etc.)
        price_unit: Unit of measurement
        purity_grade: Purity grade of the material
        date: Date of the price observation
        timestamp: Timestamp of the price observation
        source_url: URL where price was scraped from
        is_verified: Whether the price has been verified
        confidence: Confidence score (0-1)
        notes: Additional notes or comments
        created_at: Creation timestamp
    """
    element_symbol: str
    market_id: str
    price: float
    currency: str
    price_type: PriceType = PriceType.SPOT
    price_unit: PriceUnit = PriceUnit.PER_KG
    purity_grade: PurityGrade = PurityGrade.COMMERCIAL
    date: date = field(default_factory=date.today)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source_url: Optional[str] = None
    is_verified: bool = False
    confidence: float = 1.0
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate price data after initialization."""
        if not self.element_symbol or len(self.element_symbol) > 3:
            raise ValueError(f"Invalid element symbol: {self.element_symbol}")
        if not self.market_id:
            raise ValueError("Market ID cannot be empty")
        if self.price < 0:
            raise ValueError(f"Price cannot be negative: {self.price}")
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1: {self.confidence}")
        
    @property
    def price_id(self) -> str:
        """Generate a unique identifier for the price point."""
        date_str = self.date.isoformat()
        return f"{self.element_symbol}-{self.market_id}-{self.price_type.value}-{date_str}"
    
    @property
    def hash(self) -> str:
        """Generate a hash for the price point."""
        data = f"{self.element_symbol}{self.market_id}{self.price}{self.date.isoformat()}{self.price_type.value}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @property
    def price_per_kg(self) -> float:
        """Convert price to per kg if possible."""
        if self.price_unit == PriceUnit.PER_KG:
            return self.price
        elif self.price_unit == PriceUnit.PER_TON:
            return self.price / 1000
        elif self.price_unit == PriceUnit.PER_GRAM:
            return self.price * 1000
        elif self.price_unit == PriceUnit.PER_OUNCE:
            return self.price * 35.274  # troy ounce to kg
        elif self.price_unit == PriceUnit.PER_LB:
            return self.price * 0.453592  # lb to kg
        return self.price
    
    @property
    def normalized_price(self) -> float:
        """Get normalized price (per kg in USD)."""
        # This is a simplified normalization
        # In practice, you'd need exchange rates for currency conversion
        price_kg = self.price_per_kg
        # For now, just return the price per kg
        # Currency conversion would be handled separately
        return price_kg
    
    @property
    def display_price(self) -> str:
        """Get display string for the price."""
        unit_map = {
            PriceUnit.PER_KG: "kg",
            PriceUnit.PER_TON: "ton",
            PriceUnit.PER_OUNCE: "oz",
            PriceUnit.PER_GRAM: "g",
            PriceUnit.PER_LB: "lb",
        }
        unit = unit_map.get(self.price_unit, "unit")
        return f"{self.price:.2f} {self.currency}/{unit}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "market_id": self.market_id,
            "price": self.price,
            "currency": self.currency,
            "price_type": self.price_type.value,
            "price_unit": self.price_unit.value,
            "purity_grade": self.purity_grade.value,
            "date": self.date.isoformat(),
            "timestamp": self.timestamp.isoformat(),
            "source_url": self.source_url,
            "is_verified": self.is_verified,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "price_id": self.price_id,
            "price_per_kg": self.price_per_kg,
            "normalized_price": self.normalized_price,
            "display_price": self.display_price,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthPrice':
        """Create from dictionary."""
        return cls(
            element_symbol=data.get("element_symbol"),
            market_id=data.get("market_id"),
            price=data.get("price"),
            currency=data.get("currency", "USD"),
            price_type=PriceType(data.get("price_type", "spot")),
            price_unit=PriceUnit(data.get("price_unit", "per_kg")),
            purity_grade=PurityGrade(data.get("purity_grade", "commercial")),
            date=date.fromisoformat(data.get("date")) if data.get("date") else date.today(),
            timestamp=datetime.fromisoformat(data.get("timestamp")) if data.get("timestamp") else datetime.utcnow(),
            source_url=data.get("source_url"),
            is_verified=data.get("is_verified", False),
            confidence=data.get("confidence", 1.0),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else datetime.utcnow(),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RareEarthPrice':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on price_id."""
        if not isinstance(other, RareEarthPrice):
            return False
        return self.price_id == other.price_id
    
    def __hash__(self) -> int:
        """Hash based on price_id."""
        return hash(self.price_id)
    
    def __lt__(self, other: 'RareEarthPrice') -> bool:
        """Compare by timestamp."""
        return self.timestamp < other.timestamp


@dataclass
class PriceHistory:
    """
    Represents a collection of price points for an element from a market.
    """
    element_symbol: str
    market_id: str
    prices: List[RareEarthPrice] = field(default_factory=list)
    
    @property
    def latest_price(self) -> Optional[RareEarthPrice]:
        """Get the most recent price."""
        if not self.prices:
            return None
        return max(self.prices, key=lambda p: p.timestamp)
    
    @property
    def oldest_price(self) -> Optional[RareEarthPrice]:
        """Get the oldest price."""
        if not self.prices:
            return None
        return min(self.prices, key=lambda p: p.timestamp)
    
    @property
    def price_range(self) -> tuple:
        """Get min and max prices."""
        if not self.prices:
            return (0, 0)
        prices = [p.price for p in self.prices]
        return (min(prices), max(prices))
    
    @property
    def average_price(self) -> float:
        """Get average price."""
        if not self.prices:
            return 0.0
        return sum(p.price for p in self.prices) / len(self.prices)
    
    @property
    def volatility(self) -> float:
        """Calculate price volatility (standard deviation)."""
        if len(self.prices) < 2:
            return 0.0
        prices = [p.price for p in self.prices]
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return variance ** 0.5
    
    def add_price(self, price: RareEarthPrice) -> None:
        """Add a price to the history."""
        self.prices.append(price)
        # Sort by timestamp
        self.prices.sort(key=lambda p: p.timestamp)
    
    def get_prices_in_range(self, start_date: date, end_date: date) -> List[RareEarthPrice]:
        """Get prices within a date range."""
        return [p for p in self.prices if start_date <= p.date <= end_date]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "market_id": self.market_id,
            "prices": [p.to_dict() for p in self.prices],
            "latest_price": self.latest_price.to_dict() if self.latest_price else None,
            "oldest_price": self.oldest_price.to_dict() if self.oldest_price else None,
            "price_range": self.price_range,
            "average_price": self.average_price,
            "volatility": self.volatility,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PriceHistory':
        """Create from dictionary."""
        prices = [RareEarthPrice.from_dict(p) for p in data.get("prices", [])]
        return cls(
            element_symbol=data.get("element_symbol"),
            market_id=data.get("market_id"),
            prices=prices,
        )
