"""
Rare Earth Market Model

Defines the RareEarthMarket dataclass for representing market information.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
import hashlib
import json


class MarketType(Enum):
    """Type of market."""
    SPOT = "spot"
    FUTURES = "futures"
    OTC = "otc"
    AUCTION = "auction"
    TENDER = "tender"


class MarketRegion(Enum):
    """Geographic region of the market."""
    GLOBAL = "global"
    ASIA = "asia"
    CHINA = "china"
    EUROPE = "europe"
    NORTH_AMERICA = "north_america"
    SOUTH_AMERICA = "south_america"
    AFRICA = "africa"
    AUSTRALIA = "australia"


class Currency(Enum):
    """Currency for pricing."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CNY = "CNY"
    AUD = "AUD"
    CAD = "CAD"
    CHF = "CHF"
    INR = "INR"
    RUB = "RUB"


@dataclass
class RareEarthMarket:
    """
    Represents a rare earth market with its properties.
    
    Attributes:
        market_id: Unique identifier for the market
        name: Market name
        market_type: Type of market (spot, futures, etc.)
        region: Geographic region
        currency: Default currency
        description: Market description
        website: Market website URL
        is_active: Whether the market is currently active
        data_sources: List of data source URLs
        supported_elements: List of element symbols supported
        update_frequency: How often data is updated (e.g., 'daily', 'weekly')
        last_updated: Last update timestamp
        created_at: Creation timestamp
    """
    market_id: str
    name: str
    market_type: MarketType
    region: MarketRegion
    currency: Currency
    description: str = ""
    website: Optional[str] = None
    is_active: bool = True
    data_sources: List[str] = field(default_factory=list)
    supported_elements: List[str] = field(default_factory=list)
    update_frequency: str = "daily"
    last_updated: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate market data after initialization."""
        if not self.market_id:
            raise ValueError("Market ID cannot be empty")
        if not self.name:
            raise ValueError("Market name cannot be empty")
        if not self.supported_elements:
            raise ValueError("Market must support at least one element")
        
    @property
    def display_name(self) -> str:
        """Get display name with region."""
        return f"{self.name} ({self.region.value})"
    
    @property
    def market_key(self) -> str:
        """Generate a unique key for the market."""
        return f"{self.region.value}-{self.market_type.value}-{self.market_id}"
    
    @property
    def hash(self) -> str:
        """Generate a hash for the market."""
        data = f"{self.market_id}{self.name}{self.region.value}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def supports_element(self, symbol: str) -> bool:
        """Check if market supports a specific element."""
        return symbol.upper() in [s.upper() for s in self.supported_elements]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "name": self.name,
            "market_type": self.market_type.value,
            "region": self.region.value,
            "currency": self.currency.value,
            "description": self.description,
            "website": self.website,
            "is_active": self.is_active,
            "data_sources": self.data_sources,
            "supported_elements": self.supported_elements,
            "update_frequency": self.update_frequency,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "created_at": self.created_at.isoformat(),
            "display_name": self.display_name,
            "market_key": self.market_key,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthMarket':
        """Create from dictionary."""
        return cls(
            market_id=data.get("market_id"),
            name=data.get("name"),
            market_type=MarketType(data.get("market_type", "spot")),
            region=MarketRegion(data.get("region", "global")),
            currency=Currency(data.get("currency", "USD")),
            description=data.get("description", ""),
            website=data.get("website"),
            is_active=data.get("is_active", True),
            data_sources=data.get("data_sources", []),
            supported_elements=data.get("supported_elements", []),
            update_frequency=data.get("update_frequency", "daily"),
            last_updated=datetime.fromisoformat(data.get("last_updated")) if data.get("last_updated") else None,
            created_at=datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else datetime.utcnow(),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RareEarthMarket':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on market_id."""
        if not isinstance(other, RareEarthMarket):
            return False
        return self.market_id == other.market_id
    
    def __hash__(self) -> int:
        """Hash based on market_id."""
        return hash(self.market_id)


# Predefined major rare earth markets
MAJOR_MARKETS = [
    RareEarthMarket(
        market_id="baotou",
        name="Baotou Rare Earth Exchange",
        market_type=MarketType.SPOT,
        region=MarketRegion.CHINA,
        currency=Currency.CNY,
        description="China's primary rare earth trading hub",
        website="https://www.cxre.com",
        is_active=True,
        data_sources=[
            "https://www.cxre.com",
            "https://www.rex.com.cn",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Y", "Sc"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="shanghai",
        name="Shanghai Metal Market",
        market_type=MarketType.SPOT,
        region=MarketRegion.CHINA,
        currency=Currency.CNY,
        description="Major metal market with rare earth price reporting",
        website="https://www.smm.cn",
        is_active=True,
        data_sources=[
            "https://www.smm.cn",
            "https://news.smm.cn",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="metal_pages",
        name="Metal Pages",
        market_type=MarketType.SPOT,
        region=MarketRegion.GLOBAL,
        currency=Currency.USD,
        description="International metal pricing and news",
        website="https://www.metal-pages.com",
        is_active=True,
        data_sources=[
            "https://www.metal-pages.com",
            "https://www.metal-pages.com/metalprices/rare-earth/",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Er"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="argus_media",
        name="Argus Media",
        market_type=MarketType.SPOT,
        region=MarketRegion.GLOBAL,
        currency=Currency.USD,
        description="Commodity price reporting agency",
        website="https://www.argusmedia.com",
        is_active=True,
        data_sources=[
            "https://www.argusmedia.com",
            "https://www.argusmedia.com/en/rare-earths",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="fastmarkets",
        name="Fastmarkets (formerly Metal Bulletin)",
        market_type=MarketType.SPOT,
        region=MarketRegion.GLOBAL,
        currency=Currency.USD,
        description="Commodity price reporting and intelligence",
        website="https://www.fastmarkets.com",
        is_active=True,
        data_sources=[
            "https://www.fastmarkets.com",
            "https://www.fastmarkets.com/rare-earth-prices",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="asian_metal",
        name="Asian Metal",
        market_type=MarketType.SPOT,
        region=MarketRegion.ASIA,
        currency=Currency.USD,
        description="Asian metal market prices and news",
        website="https://www.asianmetal.com",
        is_active=True,
        data_sources=[
            "https://www.asianmetal.com",
            "https://www.asianmetal.com/rare-earth-prices",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy"],
        update_frequency="daily",
    ),
    RareEarthMarket(
        market_id="roskill",
        name="Roskill",
        market_type=MarketType.SPOT,
        region=MarketRegion.GLOBAL,
        currency=Currency.USD,
        description="Commodity research and price data",
        website="https://roskill.com",
        is_active=True,
        data_sources=[
            "https://roskill.com",
            "https://roskill.com/market-research/rare-earths/",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er"],
        update_frequency="weekly",
    ),
    RareEarthMarket(
        market_id="usgs",
        name="USGS Mineral Commodity Summaries",
        market_type=MarketType.SPOT,
        region=MarketRegion.NORTH_AMERICA,
        currency=Currency.USD,
        description="US Geological Survey rare earth statistics",
        website="https://www.usgs.gov",
        is_active=True,
        data_sources=[
            "https://www.usgs.gov/centers/national-minerals-information-center/rare-earths-statistics-and-information",
            "https://pubs.usgs.gov/periodicals/mcs2023/mcs2023.pdf",
        ],
        supported_elements=["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Y", "Sc"],
        update_frequency="annual",
    ),
]


def get_market_by_id(market_id: str) -> Optional[RareEarthMarket]:
    """Get a market by its ID."""
    market_id = market_id.lower()
    for market in MAJOR_MARKETS:
        if market.market_id == market_id:
            return market
    return None


def get_markets_by_region(region: MarketRegion) -> List[RareEarthMarket]:
    """Get all markets in a specific region."""
    return [m for m in MAJOR_MARKETS if m.region == region]


def get_markets_by_element(symbol: str) -> List[RareEarthMarket]:
    """Get all markets that support a specific element."""
    return [m for m in MAJOR_MARKETS if m.supports_element(symbol)]


def get_active_markets() -> List[RareEarthMarket]:
    """Get all active markets."""
    return [m for m in MAJOR_MARKETS if m.is_active]


def get_daily_markets() -> List[RareEarthMarket]:
    """Get all markets with daily updates."""
    return [m for m in MAJOR_MARKETS if m.update_frequency == "daily"]
