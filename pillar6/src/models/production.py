"""
Rare Earth Production Model

Defines the RareEarthProduction dataclass for representing production data.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
import hashlib
import json


class ProductionType(Enum):
    """Type of production data."""
    MINE = "mine"
    REFINED = "refined"
    PROCESSED = "processed"
    RECYCLED = "recycled"
    TOTAL = "total"
    ESTIMATED = "estimated"
    ACTUAL = "actual"


class ProductionUnit(Enum):
    """Unit of production measurement."""
    TONNES = "tonnes"
    KG = "kg"
    GRAMS = "grams"
    OUNCES = "ounces"
    LBS = "lbs"


@dataclass
class RareEarthProduction:
    """
    Represents rare earth production data.
    
    Attributes:
        element_symbol: Chemical symbol of the element
        country: Country of production
        company: Producing company (if applicable)
        production_type: Type of production
        amount: Production amount
        production_unit: Unit of measurement
        year: Year of production
        quarter: Quarter (1-4, if applicable)
        month: Month (1-12, if applicable)
        date: Specific date (if applicable)
        source: Data source
        source_url: URL where data was scraped from
        is_estimated: Whether the data is estimated
        confidence: Confidence score (0-1)
        notes: Additional notes
        created_at: Creation timestamp
    """
    element_symbol: str
    country: str
    amount: float
    production_type: ProductionType = ProductionType.TOTAL
    production_unit: ProductionUnit = ProductionUnit.TONNES
    year: int = field(default_factory=lambda: datetime.utcnow().year)
    quarter: Optional[int] = None
    month: Optional[int] = None
    date: Optional[date] = None
    company: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    is_estimated: bool = True
    confidence: float = 1.0
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate production data after initialization."""
        if not self.element_symbol or len(self.element_symbol) > 3:
            raise ValueError(f"Invalid element symbol: {self.element_symbol}")
        if not self.country:
            raise ValueError("Country cannot be empty")
        if self.amount < 0:
            raise ValueError(f"Production amount cannot be negative: {self.amount}")
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1: {self.confidence}")
        if self.quarter and (self.quarter < 1 or self.quarter > 4):
            raise ValueError(f"Quarter must be between 1 and 4: {self.quarter}")
        if self.month and (self.month < 1 or self.month > 12):
            raise ValueError(f"Month must be between 1 and 12: {self.month}")
        
    @property
    def production_id(self) -> str:
        """Generate a unique identifier for the production data."""
        parts = [self.element_symbol, self.country, str(self.year)]
        if self.quarter:
            parts.append(f"Q{self.quarter}")
        if self.month:
            parts.append(f"M{self.month}")
        if self.company:
            parts.append(self.company)
        return "-".join(parts)
    
    @property
    def hash(self) -> str:
        """Generate a hash for the production data."""
        data = f"{self.element_symbol}{self.country}{self.amount}{self.year}{self.production_type.value}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @property
    def tonnes(self) -> float:
        """Convert production amount to tonnes."""
        if self.production_unit == ProductionUnit.TONNES:
            return self.amount
        elif self.production_unit == ProductionUnit.KG:
            return self.amount / 1000
        elif self.production_unit == ProductionUnit.GRAMS:
            return self.amount / 1000000
        elif self.production_unit == ProductionUnit.OUNCES:
            return self.amount * 0.0283495  # troy ounce to kg, then / 1000 for tonnes
        elif self.production_unit == ProductionUnit.LBS:
            return self.amount * 0.000453592  # lb to tonnes
        return self.amount
    
    @property
    def display_amount(self) -> str:
        """Get display string for the production amount."""
        unit_map = {
            ProductionUnit.TONNES: "t",
            ProductionUnit.KG: "kg",
            ProductionUnit.GRAMS: "g",
            ProductionUnit.OUNCES: "oz",
            ProductionUnit.LBS: "lbs",
        }
        unit = unit_map.get(self.production_unit, "unit")
        return f"{self.amount:.2f} {unit}"
    
    @property
    def period(self) -> str:
        """Get the time period as a string."""
        if self.date:
            return self.date.isoformat()
        parts = [str(self.year)]
        if self.quarter:
            parts.append(f"Q{self.quarter}")
        elif self.month:
            parts.append(f"M{self.month}")
        return "-".join(parts)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "country": self.country,
            "amount": self.amount,
            "production_type": self.production_type.value,
            "production_unit": self.production_unit.value,
            "year": self.year,
            "quarter": self.quarter,
            "month": self.month,
            "date": self.date.isoformat() if self.date else None,
            "company": self.company,
            "source": self.source,
            "source_url": self.source_url,
            "is_estimated": self.is_estimated,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "production_id": self.production_id,
            "tonnes": self.tonnes,
            "display_amount": self.display_amount,
            "period": self.period,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthProduction':
        """Create from dictionary."""
        return cls(
            element_symbol=data.get("element_symbol"),
            country=data.get("country"),
            amount=data.get("amount"),
            production_type=ProductionType(data.get("production_type", "total")),
            production_unit=ProductionUnit(data.get("production_unit", "tonnes")),
            year=data.get("year", datetime.utcnow().year),
            quarter=data.get("quarter"),
            month=data.get("month"),
            date=date.fromisoformat(data.get("date")) if data.get("date") else None,
            company=data.get("company"),
            source=data.get("source", ""),
            source_url=data.get("source_url"),
            is_estimated=data.get("is_estimated", True),
            confidence=data.get("confidence", 1.0),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else datetime.utcnow(),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RareEarthProduction':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on production_id."""
        if not isinstance(other, RareEarthProduction):
            return False
        return self.production_id == other.production_id
    
    def __hash__(self) -> int:
        """Hash based on production_id."""
        return hash(self.production_id)
    
    def __lt__(self, other: 'RareEarthProduction') -> bool:
        """Compare by year, then quarter, then month."""
        if self.year != other.year:
            return self.year < other.year
        if self.quarter and other.quarter:
            return self.quarter < other.quarter
        if self.month and other.month:
            return self.month < other.month
        return self.created_at < other.created_at


@dataclass
class ProductionHistory:
    """
    Represents a collection of production data for an element and country.
    """
    element_symbol: str
    country: str
    productions: List[RareEarthProduction] = field(default_factory=list)
    
    @property
    def latest_production(self) -> Optional[RareEarthProduction]:
        """Get the most recent production data."""
        if not self.productions:
            return None
        return max(self.productions, key=lambda p: (p.year, p.quarter or 0, p.month or 0))
    
    @property
    def oldest_production(self) -> Optional[RareEarthProduction]:
        """Get the oldest production data."""
        if not self.productions:
            return None
        return min(self.productions, key=lambda p: (p.year, p.quarter or 0, p.month or 0))
    
    @property
    def total_production(self) -> float:
        """Get total production in tonnes."""
        return sum(p.tonnes for p in self.productions)
    
    @property
    def average_annual_production(self) -> float:
        """Get average annual production in tonnes."""
        if not self.productions:
            return 0.0
        # Group by year and sum
        yearly = {}
        for p in self.productions:
            year = p.year
            yearly[year] = yearly.get(year, 0) + p.tonnes
        return sum(yearly.values()) / len(yearly) if yearly else 0.0
    
    def add_production(self, production: RareEarthProduction) -> None:
        """Add production data to the history."""
        self.productions.append(production)
        # Sort by year, quarter, month
        self.productions.sort(key=lambda p: (p.year, p.quarter or 0, p.month or 0))
    
    def get_production_by_year(self, year: int) -> List[RareEarthProduction]:
        """Get production data for a specific year."""
        return [p for p in self.productions if p.year == year]
    
    def get_production_by_company(self, company: str) -> List[RareEarthProduction]:
        """Get production data for a specific company."""
        return [p for p in self.productions if p.company and p.company.lower() == company.lower()]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "country": self.country,
            "productions": [p.to_dict() for p in self.productions],
            "latest_production": self.latest_production.to_dict() if self.latest_production else None,
            "oldest_production": self.oldest_production.to_dict() if self.oldest_production else None,
            "total_production_tonnes": self.total_production,
            "average_annual_production_tonnes": self.average_annual_production,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProductionHistory':
        """Create from dictionary."""
        productions = [RareEarthProduction.from_dict(p) for p in data.get("productions", [])]
        return cls(
            element_symbol=data.get("element_symbol"),
            country=data.get("country"),
            productions=productions,
        )
