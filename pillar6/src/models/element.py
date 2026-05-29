"""
Rare Earth Element Model

Defines the RareEarthElement dataclass for representing rare earth elements.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
import hashlib
import json


class RareEarthCategory(Enum):
    """Category of rare earth elements."""
    LIGHT = "light"
    HEAVY = "heavy"
    ALL = "all"


class RareEarthElementType(Enum):
    """Type classification of rare earth elements."""
    LANTHANIDE = "lanthanide"
    ACTINIDE = "actinide"
    SCANDIUM = "scandium"
    YTTRIUM = "yttrium"


@dataclass
class RareEarthElement:
    """
    Represents a rare earth element with its properties.
    
    Attributes:
        symbol: Chemical symbol (e.g., 'La', 'Ce', 'Nd')
        name: Full element name (e.g., 'Lanthanum', 'Cerium', 'Neodymium')
        atomic_number: Atomic number of the element
        category: Light or Heavy rare earth element
        element_type: Classification type
        atomic_weight: Atomic weight in g/mol
        melting_point: Melting point in Celsius
        boiling_point: Boiling point in Celsius
        density: Density in g/cm³
        discovery_year: Year of discovery
        common_uses: List of common industrial uses
        is_critical: Whether this is a critical rare earth element
        aliases: Alternative names or symbols
    """
    symbol: str
    name: str
    atomic_number: int
    category: RareEarthCategory
    element_type: RareEarthElementType = RareEarthElementType.LANTHANIDE
    atomic_weight: Optional[float] = None
    melting_point: Optional[float] = None
    boiling_point: Optional[float] = None
    density: Optional[float] = None
    discovery_year: Optional[int] = None
    common_uses: List[str] = field(default_factory=list)
    is_critical: bool = False
    aliases: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate element data after initialization."""
        if not self.symbol or len(self.symbol) > 3:
            raise ValueError(f"Invalid symbol: {self.symbol}")
        if not self.name:
            raise ValueError("Element name cannot be empty")
        if self.atomic_number < 1 or self.atomic_number > 118:
            raise ValueError(f"Invalid atomic number: {self.atomic_number}")
        
    @property
    def display_name(self) -> str:
        """Get display name with symbol."""
        return f"{self.name} ({self.symbol})"
    
    @property
    def element_id(self) -> str:
        """Generate a unique identifier for the element."""
        return f"REE-{self.symbol}"
    
    @property
    def hash(self) -> str:
        """Generate a hash for the element."""
        data = f"{self.symbol}{self.name}{self.atomic_number}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "name": self.name,
            "atomic_number": self.atomic_number,
            "category": self.category.value,
            "element_type": self.element_type.value,
            "atomic_weight": self.atomic_weight,
            "melting_point": self.melting_point,
            "boiling_point": self.boiling_point,
            "density": self.density,
            "discovery_year": self.discovery_year,
            "common_uses": self.common_uses,
            "is_critical": self.is_critical,
            "aliases": self.aliases,
            "element_id": self.element_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthElement':
        """Create from dictionary."""
        return cls(
            symbol=data.get("symbol"),
            name=data.get("name"),
            atomic_number=data.get("atomic_number"),
            category=RareEarthCategory(data.get("category", "light")),
            element_type=RareEarthElementType(data.get("element_type", "lanthanide")),
            atomic_weight=data.get("atomic_weight"),
            melting_point=data.get("melting_point"),
            boiling_point=data.get("boiling_point"),
            density=data.get("density"),
            discovery_year=data.get("discovery_year"),
            common_uses=data.get("common_uses", []),
            is_critical=data.get("is_critical", False),
            aliases=data.get("aliases", []),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RareEarthElement':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on symbol."""
        if not isinstance(other, RareEarthElement):
            return False
        return self.symbol == other.symbol
    
    def __hash__(self) -> int:
        """Hash based on symbol."""
        return hash(self.symbol)
    
    def __lt__(self, other: 'RareEarthElement') -> bool:
        """Compare by atomic number."""
        return self.atomic_number < other.atomic_number


# Predefined rare earth elements
RARE_EARTH_ELEMENTS = [
    RareEarthElement(
        symbol="Sc",
        name="Scandium",
        atomic_number=21,
        category=RareEarthCategory.LIGHT,
        element_type=RareEarthElementType.SCANDIUM,
        atomic_weight=44.955908,
        melting_point=1541,
        boiling_point=2836,
        density=2.985,
        discovery_year=1879,
        common_uses=["aluminum alloys", "fuel cells", "aerospace"],
        is_critical=True,
        aliases=["Scandium"],
    ),
    RareEarthElement(
        symbol="Y",
        name="Yttrium",
        atomic_number=39,
        category=RareEarthCategory.LIGHT,
        element_type=RareEarthElementType.YTTRIUM,
        atomic_weight=88.905842,
        melting_point=1522,
        boiling_point=3345,
        density=4.469,
        discovery_year=1794,
        common_uses=["phosphors", "ceramics", "lasers", "superconductors"],
        is_critical=True,
        aliases=["Yttrium"],
    ),
    RareEarthElement(
        symbol="La",
        name="Lanthanum",
        atomic_number=57,
        category=RareEarthCategory.LIGHT,
        atomic_weight=138.90547,
        melting_point=920,
        boiling_point=3464,
        density=6.145,
        discovery_year=1839,
        common_uses=["batteries", "camera lenses", "catalysts"],
        is_critical=True,
        aliases=["Lanthanum"],
    ),
    RareEarthElement(
        symbol="Ce",
        name="Cerium",
        atomic_number=58,
        category=RareEarthCategory.LIGHT,
        atomic_weight=140.116,
        melting_point=795,
        boiling_point=3443,
        density=6.77,
        discovery_year=1803,
        common_uses=["catalysts", "glass polishing", "alloying agent"],
        is_critical=True,
        aliases=["Cerium"],
    ),
    RareEarthElement(
        symbol="Pr",
        name="Praseodymium",
        atomic_number=59,
        category=RareEarthCategory.LIGHT,
        atomic_weight=140.90766,
        melting_point=935,
        boiling_point=3520,
        density=6.773,
        discovery_year=1885,
        common_uses=["magnets", "alloying agent", "glass coloring"],
        is_critical=True,
        aliases=["Praseodymium"],
    ),
    RareEarthElement(
        symbol="Nd",
        name="Neodymium",
        atomic_number=60,
        category=RareEarthCategory.LIGHT,
        atomic_weight=144.242,
        melting_point=1024,
        boiling_point=3074,
        density=7.007,
        discovery_year=1885,
        common_uses=["permanent magnets", "lasers", "glass coloring"],
        is_critical=True,
        aliases=["Neodymium"],
    ),
    RareEarthElement(
        symbol="Pm",
        name="Promethium",
        atomic_number=61,
        category=RareEarthCategory.LIGHT,
        atomic_weight=145,
        melting_point=1042,
        boiling_point=3000,
        density=7.26,
        discovery_year=1945,
        common_uses=["nuclear batteries", "luminous paint"],
        is_critical=False,
        aliases=["Promethium"],
    ),
    RareEarthElement(
        symbol="Sm",
        name="Samarium",
        atomic_number=62,
        category=RareEarthCategory.LIGHT,
        atomic_weight=150.36,
        melting_point=1072,
        boiling_point=1794,
        density=7.52,
        discovery_year=1879,
        common_uses=["magnets", "catalysts", "cancer treatment"],
        is_critical=True,
        aliases=["Samarium"],
    ),
    RareEarthElement(
        symbol="Eu",
        name="Europium",
        atomic_number=63,
        category=RareEarthCategory.LIGHT,
        atomic_weight=151.964,
        melting_point=822,
        boiling_point=1529,
        density=5.244,
        discovery_year=1901,
        common_uses=["phosphors", "TV screens", "fluorescent lamps"],
        is_critical=True,
        aliases=["Europium"],
    ),
    RareEarthElement(
        symbol="Gd",
        name="Gadolinium",
        atomic_number=64,
        category=RareEarthCategory.HEAVY,
        atomic_weight=157.25,
        melting_point=1313,
        boiling_point=3273,
        density=7.90,
        discovery_year=1880,
        common_uses=["MRI contrast agent", "neutron absorber", "memory devices"],
        is_critical=True,
        aliases=["Gadolinium"],
    ),
    RareEarthElement(
        symbol="Tb",
        name="Terbium",
        atomic_number=65,
        category=RareEarthCategory.HEAVY,
        atomic_weight=158.92535,
        melting_point=1356,
        boiling_point=3230,
        density=8.229,
        discovery_year=1843,
        common_uses=["phosphors", "magnets", "sonar systems"],
        is_critical=True,
        aliases=["Terbium"],
    ),
    RareEarthElement(
        symbol="Dy",
        name="Dysprosium",
        atomic_number=66,
        category=RareEarthCategory.HEAVY,
        atomic_weight=162.500,
        melting_point=1412,
        boiling_point=2567,
        density=8.54,
        discovery_year=1886,
        common_uses=["magnets", "lasers", "nuclear reactors"],
        is_critical=True,
        aliases=["Dysprosium"],
    ),
    RareEarthElement(
        symbol="Ho",
        name="Holmium",
        atomic_number=67,
        category=RareEarthCategory.HEAVY,
        atomic_weight=164.93033,
        melting_point=1474,
        boiling_point=2700,
        density=8.795,
        discovery_year=1878,
        common_uses=["magnets", "lasers", "nuclear control rods"],
        is_critical=True,
        aliases=["Holmium"],
    ),
    RareEarthElement(
        symbol="Er",
        name="Erbium",
        atomic_number=68,
        category=RareEarthCategory.HEAVY,
        atomic_weight=167.259,
        melting_point=1529,
        boiling_point=2868,
        density=9.066,
        discovery_year=1843,
        common_uses=["fiber optics", "lasers", "metallurgy"],
        is_critical=True,
        aliases=["Erbium"],
    ),
    RareEarthElement(
        symbol="Tm",
        name="Thulium",
        atomic_number=69,
        category=RareEarthCategory.HEAVY,
        atomic_weight=168.93422,
        melting_point=1545,
        boiling_point=1950,
        density=9.32,
        discovery_year=1879,
        common_uses=["portable X-rays", "lasers", "nuclear reactors"],
        is_critical=False,
        aliases=["Thulium"],
    ),
    RareEarthElement(
        symbol="Yb",
        name="Ytterbium",
        atomic_number=70,
        category=RareEarthCategory.HEAVY,
        atomic_weight=173.054,
        melting_point=819,
        boiling_point=1196,
        density=6.90,
        discovery_year=1878,
        common_uses=["stress gauges", "alloying agent", "catalysts"],
        is_critical=False,
        aliases=["Ytterbium"],
    ),
    RareEarthElement(
        symbol="Lu",
        name="Lutetium",
        atomic_number=71,
        category=RareEarthCategory.HEAVY,
        atomic_weight=174.9668,
        melting_point=1663,
        boiling_point=3402,
        density=9.84,
        discovery_year=1907,
        common_uses=["catalysts", "PET scans", "refining"],
        is_critical=False,
        aliases=["Lutetium"],
    ),
]


def get_element_by_symbol(symbol: str) -> Optional[RareEarthElement]:
    """Get a rare earth element by its symbol."""
    symbol = symbol.upper()
    for element in RARE_EARTH_ELEMENTS:
        if element.symbol == symbol:
            return element
        if symbol in element.aliases:
            return element
    return None


def get_element_by_name(name: str) -> Optional[RareEarthElement]:
    """Get a rare earth element by its name."""
    name = name.lower()
    for element in RARE_EARTH_ELEMENTS:
        if element.name.lower() == name:
            return element
        if name in [u.lower() for u in element.common_uses]:
            return element
    return None


def get_elements_by_category(category: RareEarthCategory) -> List[RareEarthElement]:
    """Get all elements in a specific category."""
    return [e for e in RARE_EARTH_ELEMENTS if e.category == category]


def get_critical_elements() -> List[RareEarthElement]:
    """Get all critical rare earth elements."""
    return [e for e in RARE_EARTH_ELEMENTS if e.is_critical]


def get_light_ree() -> List[RareEarthElement]:
    """Get all light rare earth elements (LREE)."""
    return get_elements_by_category(RareEarthCategory.LIGHT)


def get_heavy_ree() -> List[RareEarthElement]:
    """Get all heavy rare earth elements (HREE)."""
    return get_elements_by_category(RareEarthCategory.HEAVY)
