"""
Instrument Keyword Model

Represents a keyword extracted from a financial instrument's name, description, or sector.
Used for hybrid linking with articles.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Index
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


@dataclass
class InstrumentKeyword:
    """
    Keyword extracted from an instrument's name, description, or related text.
    
    Attributes:
        id: UUID
        instrument_id: Reference to instrument
        keyword: The extracted keyword (normalized, lowercase)
        source: Source of the keyword (e.g., "name", "description", "sector")
        weight: Importance weight (0-1)
        language: Language of the keyword (e.g., "en")
        created_at: When the keyword was extracted
    """
    id: str
    instrument_id: str
    keyword: str
    source: str = "name"  # "name", "description", "sector", "article"
    weight: float = 1.0
    language: str = "en"
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate instrument keyword data."""
        if not self.id:
            raise ValueError("Keyword ID cannot be empty")
        if not self.instrument_id:
            raise ValueError("Instrument ID cannot be empty")
        if not self.keyword:
            raise ValueError("Keyword cannot be empty")
        if not self.source:
            raise ValueError("Source cannot be empty")
        if self.weight < 0 or self.weight > 1:
            raise ValueError("Weight must be between 0 and 1")
        if not self.language:
            raise ValueError("Language cannot be empty")
        
        # Normalize keyword to lowercase
        self.keyword = self.keyword.lower().strip()
    
    @property
    def is_high_weight(self) -> bool:
        """Check if this is a high-weight keyword."""
        return self.weight >= 0.8
    
    @property
    def is_from_name(self) -> bool:
        """Check if keyword is from the instrument name."""
        return self.source == "name"
    
    @property
    def is_from_sector(self) -> bool:
        """Check if keyword is from the sector/industry."""
        return self.source in ["sector", "industry"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert keyword to dictionary."""
        return {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "keyword": self.keyword,
            "source": self.source,
            "weight": self.weight,
            "language": self.language,
            "is_high_weight": self.is_high_weight,
            "is_from_name": self.is_from_name,
            "is_from_sector": self.is_from_sector,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstrumentKeyword":
        """Create keyword from dictionary."""
        return cls(
            id=data.get("id"),
            instrument_id=data.get("instrument_id"),
            keyword=data.get("keyword", ""),
            source=data.get("source", "name"),
            weight=data.get("weight", 1.0),
            language=data.get("language", "en"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"InstrumentKeyword(id={self.id!r}, instrument_id={self.instrument_id!r}, keyword={self.keyword!r}, source={self.source!r}, weight={self.weight!r})"


# SQLAlchemy model
class InstrumentKeywordDB(Base):
    """SQLAlchemy model for the instrument_keywords table."""
    __tablename__ = 'instrument_keywords'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    keyword = Column(String(100), nullable=False)
    source = Column(String(20), default="name")  # name, description, sector, article
    weight = Column(Float, default=1.0)
    language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="keywords")
    
    # Indexes
    __table_args__ = (
        Index('idx_keyword_instrument', 'instrument_id'),
        Index('idx_keyword_keyword', 'keyword'),
        Index('idx_keyword_source', 'source'),
        Index('idx_keyword_instrument_keyword', 'instrument_id', 'keyword'),
    )
    
    def to_dataclass(self) -> InstrumentKeyword:
        """Convert SQLAlchemy model to dataclass."""
        return InstrumentKeyword(
            id=self.id,
            instrument_id=self.instrument_id,
            keyword=self.keyword,
            source=self.source,
            weight=self.weight,
            language=self.language,
            created_at=self.created_at,
        )
    
    @classmethod
    def from_dataclass(cls, keyword: InstrumentKeyword) -> "InstrumentKeywordDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=keyword.id,
            instrument_id=keyword.instrument_id,
            keyword=keyword.keyword,
            source=keyword.source,
            weight=keyword.weight,
            language=keyword.language,
            created_at=keyword.created_at,
        )
