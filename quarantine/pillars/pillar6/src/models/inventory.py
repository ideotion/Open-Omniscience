"""
Rare Earth Inventory Model

Defines the RareEarthInventory dataclass for representing inventory/stockpile data.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
import hashlib
import json


class InventoryType(Enum):
    """Type of inventory."""
    STOCKPILE = "stockpile"
    STRATEGIC_RESERVE = "strategic_reserve"
    COMMERCIAL = "commercial"
    GOVERNMENT = "government"
    MILITARY = "military"
    INDUSTRIAL = "industrial"
    WAREHOUSE = "warehouse"
    PORT = "port"


class InventoryUnit(Enum):
    """Unit of inventory measurement."""
    TONNES = "tonnes"
    KG = "kg"
    GRAMS = "grams"
    OUNCES = "ounces"
    LBS = "lbs"


@dataclass
class RareEarthInventory:
    """
    Represents rare earth inventory/stockpile data.
    
    Attributes:
        element_symbol: Chemical symbol of the element
        country: Country holding the inventory
        holder: Entity holding the inventory (company, government, etc.)
        inventory_type: Type of inventory
        amount: Inventory amount
        inventory_unit: Unit of measurement
        year: Year of inventory data
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
    inventory_type: InventoryType = InventoryType.COMMERCIAL
    inventory_unit: InventoryUnit = InventoryUnit.TONNES
    year: int = field(default_factory=lambda: datetime.utcnow().year)
    date: Optional[date] = None
    holder: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    is_estimated: bool = True
    confidence: float = 1.0
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate inventory data after initialization."""
        if not self.element_symbol or len(self.element_symbol) > 3:
            raise ValueError(f"Invalid element symbol: {self.element_symbol}")
        if not self.country:
            raise ValueError("Country cannot be empty")
        if self.amount < 0:
            raise ValueError(f"Inventory amount cannot be negative: {self.amount}")
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1: {self.confidence}")
        
    @property
    def inventory_id(self) -> str:
        """Generate a unique identifier for the inventory data."""
        parts = [self.element_symbol, self.country, str(self.year)]
        if self.holder:
            parts.append(self.holder)
        if self.inventory_type:
            parts.append(self.inventory_type.value)
        return "-".join(parts)
    
    @property
    def hash(self) -> str:
        """Generate a hash for the inventory data."""
        data = f"{self.element_symbol}{self.country}{self.amount}{self.year}{self.inventory_type.value}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @property
    def tonnes(self) -> float:
        """Convert inventory amount to tonnes."""
        if self.inventory_unit == InventoryUnit.TONNES:
            return self.amount
        elif self.inventory_unit == InventoryUnit.KG:
            return self.amount / 1000
        elif self.inventory_unit == InventoryUnit.GRAMS:
            return self.amount / 1000000
        elif self.inventory_unit == InventoryUnit.OUNCES:
            return self.amount * 0.0283495  # troy ounce to kg, then / 1000 for tonnes
        elif self.inventory_unit == InventoryUnit.LBS:
            return self.amount * 0.000453592  # lb to tonnes
        return self.amount
    
    @property
    def display_amount(self) -> str:
        """Get display string for the inventory amount."""
        unit_map = {
            InventoryUnit.TONNES: "t",
            InventoryUnit.KG: "kg",
            InventoryUnit.GRAMS: "g",
            InventoryUnit.OUNCES: "oz",
            InventoryUnit.LBS: "lbs",
        }
        unit = unit_map.get(self.inventory_unit, "unit")
        return f"{self.amount:.2f} {unit}"
    
    @property
    def period(self) -> str:
        """Get the time period as a string."""
        if self.date:
            return self.date.isoformat()
        return str(self.year)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "country": self.country,
            "amount": self.amount,
            "inventory_type": self.inventory_type.value,
            "inventory_unit": self.inventory_unit.value,
            "year": self.year,
            "date": self.date.isoformat() if self.date else None,
            "holder": self.holder,
            "source": self.source,
            "source_url": self.source_url,
            "is_estimated": self.is_estimated,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "inventory_id": self.inventory_id,
            "tonnes": self.tonnes,
            "display_amount": self.display_amount,
            "period": self.period,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthInventory':
        """Create from dictionary."""
        return cls(
            element_symbol=data.get("element_symbol"),
            country=data.get("country"),
            amount=data.get("amount"),
            inventory_type=InventoryType(data.get("inventory_type", "commercial")),
            inventory_unit=InventoryUnit(data.get("inventory_unit", "tonnes")),
            year=data.get("year", datetime.utcnow().year),
            date=date.fromisoformat(data.get("date")) if data.get("date") else None,
            holder=data.get("holder"),
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
    def from_json(cls, json_str: str) -> 'RareEarthInventory':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on inventory_id."""
        if not isinstance(other, RareEarthInventory):
            return False
        return self.inventory_id == other.inventory_id
    
    def __hash__(self) -> int:
        """Hash based on inventory_id."""
        return hash(self.inventory_id)
    
    def __lt__(self, other: 'RareEarthInventory') -> bool:
        """Compare by year, then date."""
        if self.year != other.year:
            return self.year < other.year
        if self.date and other.date:
            return self.date < other.date
        return self.created_at < other.created_at


@dataclass
class InventoryHistory:
    """
    Represents a collection of inventory data for an element and country.
    """
    element_symbol: str
    country: str
    inventories: List[RareEarthInventory] = field(default_factory=list)
    
    @property
    def latest_inventory(self) -> Optional[RareEarthInventory]:
        """Get the most recent inventory data."""
        if not self.inventories:
            return None
        return max(self.inventories, key=lambda i: (i.year, i.date if i.date else datetime.min))
    
    @property
    def oldest_inventory(self) -> Optional[RareEarthInventory]:
        """Get the oldest inventory data."""
        if not self.inventories:
            return None
        return min(self.inventories, key=lambda i: (i.year, i.date if i.date else datetime.min))
    
    @property
    def total_inventory(self) -> float:
        """Get total inventory in tonnes."""
        return sum(i.tonnes for i in self.inventories)
    
    @property
    def average_inventory(self) -> float:
        """Get average inventory in tonnes."""
        if not self.inventories:
            return 0.0
        return sum(i.tonnes for i in self.inventories) / len(self.inventories)
    
    def add_inventory(self, inventory: RareEarthInventory) -> None:
        """Add inventory data to the history."""
        self.inventories.append(inventory)
        # Sort by year, then date
        self.inventories.sort(key=lambda i: (i.year, i.date if i.date else datetime.min))
    
    def get_inventory_by_year(self, year: int) -> List[RareEarthInventory]:
        """Get inventory data for a specific year."""
        return [i for i in self.inventories if i.year == year]
    
    def get_inventory_by_holder(self, holder: str) -> List[RareEarthInventory]:
        """Get inventory data for a specific holder."""
        return [i for i in self.inventories if i.holder and i.holder.lower() == holder.lower()]
    
    def get_inventory_by_type(self, inventory_type: InventoryType) -> List[RareEarthInventory]:
        """Get inventory data by type."""
        return [i for i in self.inventories if i.inventory_type == inventory_type]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "country": self.country,
            "inventories": [i.to_dict() for i in self.inventories],
            "latest_inventory": self.latest_inventory.to_dict() if self.latest_inventory else None,
            "oldest_inventory": self.oldest_inventory.to_dict() if self.oldest_inventory else None,
            "total_inventory_tonnes": self.total_inventory,
            "average_inventory_tonnes": self.average_inventory,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'InventoryHistory':
        """Create from dictionary."""
        inventories = [RareEarthInventory.from_dict(i) for i in data.get("inventories", [])]
        return cls(
            element_symbol=data.get("element_symbol"),
            country=data.get("country"),
            inventories=inventories,
        )
