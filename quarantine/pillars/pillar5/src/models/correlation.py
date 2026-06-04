"""
Article-Financial Link Model

Represents a correlation between an article and a financial instrument.
Updated to support hybrid linking (temporal + keyword + sector + mention).
Includes both dataclass and SQLAlchemy model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from sqlalchemy import Column, String, DateTime, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


class CorrelationType(Enum):
    """Types of correlation between articles and financial data."""
    MENTION = "mention"           # Article mentions the instrument directly
    EVENT = "event"               # Article about a specific financial event
    SENTIMENT = "sentiment"       # Sentiment correlation
    TEMPORAL = "temporal"         # Temporal proximity
    STATISTICAL = "statistical"   # Statistical correlation
    KEYWORD = "keyword"           # Keyword-based correlation (new)
    SECTOR = "sector"             # Sector/industry-based correlation (new)


class Direction(Enum):
    """Direction of correlation (temporal)."""
    BEFORE = "before"            # Article published before financial event
    AFTER = "after"              # Article published after financial event
    SAME_TIME = "same_time"      # Article and event at the same time


@dataclass
class ArticleFinancialLink:
    """
    Represents a correlation between an article and a financial instrument.
    
    Attributes:
        id: UUID for this correlation link
        article_id: Reference to the article
        instrument_id: Reference to the instrument (replaces company_id)
        exchange_id: Reference to the exchange (optional)
        
        # Correlation metadata
        correlation_score: Strength of correlation (0-1)
        correlation_type: Type of correlation (mention, event, sentiment, temporal, keyword, sector)
        time_diff_hours: Hours between article and financial event
        direction: Temporal direction (before, after, same_time)
        
        # Keyword matching (new for hybrid linking)
        matched_keywords: List of keywords that matched
        matched_sector: Sector that matched (if correlation_type is "sector")
        
        # Sentiment analysis
        article_sentiment: Sentiment score from article (-1 to 1)
        financial_sentiment: Sentiment inferred from financial data (-1 to 1)
        
        # Analysis
        is_significant: Whether correlation is statistically significant
        confidence: Confidence in correlation (0-1)
        
        # Metadata
        created_at: When link was created
        updated_at: When link was last updated
    """
    id: str
    article_id: str
    instrument_id: Optional[str] = None  # Replaces company_id
    exchange_id: Optional[str] = None
    
    # Correlation metadata
    correlation_score: float = 0.0
    correlation_type: str = CorrelationType.MENTION.value  # Default to mention
    time_diff_hours: Optional[float] = None
    direction: str = Direction.SAME_TIME.value
    
    # Keyword matching (new)
    matched_keywords: List[str] = field(default_factory=list)
    matched_sector: Optional[str] = None
    
    # Sentiment analysis
    article_sentiment: Optional[float] = None
    financial_sentiment: Optional[float] = None
    
    # Analysis
    is_significant: bool = False
    confidence: float = 0.0
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate correlation link."""
        if not self.id:
            raise ValueError("Link ID cannot be empty")
        if not self.article_id:
            raise ValueError("Article ID cannot be empty")
        if self.correlation_score < 0 or self.correlation_score > 1:
            raise ValueError("Correlation score must be between 0 and 1")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
        if self.article_sentiment is not None and (self.article_sentiment < -1 or self.article_sentiment > 1):
            raise ValueError("Article sentiment must be between -1 and 1")
        if self.financial_sentiment is not None and (self.financial_sentiment < -1 or self.financial_sentiment > 1):
            raise ValueError("Financial sentiment must be between -1 and 1")
    
    @property
    def sentiment_match(self) -> Optional[bool]:
        """Check if article and financial sentiment match."""
        if self.article_sentiment is not None and self.financial_sentiment is not None:
            # Both positive or both negative
            return (self.article_sentiment > 0 and self.financial_sentiment > 0) or \
                   (self.article_sentiment < 0 and self.financial_sentiment < 0)
        return None
    
    @property
    def strength(self) -> str:
        """Get strength description based on correlation score."""
        if self.correlation_score >= 0.8:
            return "very_strong"
        elif self.correlation_score >= 0.6:
            return "strong"
        elif self.correlation_score >= 0.4:
            return "moderate"
        elif self.correlation_score >= 0.2:
            return "weak"
        else:
            return "none"
    
    @property
    def is_keyword_link(self) -> bool:
        """Check if this is a keyword-based link."""
        return self.correlation_type == CorrelationType.KEYWORD.value
    
    @property
    def is_sector_link(self) -> bool:
        """Check if this is a sector-based link."""
        return self.correlation_type == CorrelationType.SECTOR.value
    
    @property
    def is_hybrid_link(self) -> bool:
        """Check if this is a hybrid link (keyword or sector)."""
        return self.is_keyword_link or self.is_sector_link
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert correlation link to dictionary."""
        return {
            "id": self.id,
            "article_id": self.article_id,
            "instrument_id": self.instrument_id,
            "exchange_id": self.exchange_id,
            "correlation_score": self.correlation_score,
            "correlation_type": self.correlation_type,
            "time_diff_hours": self.time_diff_hours,
            "direction": self.direction,
            "matched_keywords": self.matched_keywords,
            "matched_sector": self.matched_sector,
            "article_sentiment": self.article_sentiment,
            "financial_sentiment": self.financial_sentiment,
            "is_significant": self.is_significant,
            "confidence": self.confidence,
            "sentiment_match": self.sentiment_match,
            "strength": self.strength,
            "is_keyword_link": self.is_keyword_link,
            "is_sector_link": self.is_sector_link,
            "is_hybrid_link": self.is_hybrid_link,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArticleFinancialLink":
        """Create correlation link from dictionary."""
        return cls(
            id=data.get("id"),
            article_id=data.get("article_id"),
            instrument_id=data.get("instrument_id") or data.get("company_id"),  # Backward compatibility
            exchange_id=data.get("exchange_id"),
            correlation_score=data.get("correlation_score", 0.0),
            correlation_type=data.get("correlation_type", CorrelationType.MENTION.value),
            time_diff_hours=data.get("time_diff_hours"),
            direction=data.get("direction", Direction.SAME_TIME.value),
            matched_keywords=data.get("matched_keywords", []),
            matched_sector=data.get("matched_sector"),
            article_sentiment=data.get("article_sentiment"),
            financial_sentiment=data.get("financial_sentiment"),
            is_significant=data.get("is_significant", False),
            confidence=data.get("confidence", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"ArticleFinancialLink(id={self.id!r}, article_id={self.article_id!r}, instrument_id={self.instrument_id!r}, score={self.correlation_score!r}, type={self.correlation_type!r})"


# SQLAlchemy model
class ArticleFinancialLinkDB(Base):
    """SQLAlchemy model for the article_financial_links table."""
    __tablename__ = 'article_financial_links'
    
    id = Column(String(36), primary_key=True)
    article_id = Column(String(36), ForeignKey('articles.id'), nullable=False)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'))
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    
    # Correlation metadata
    correlation_score = Column(Float, default=0.0)
    correlation_type = Column(String(20), default=CorrelationType.MENTION.value)
    time_diff_hours = Column(Float)
    direction = Column(String(20), default=Direction.SAME_TIME.value)
    
    # Keyword matching (new)
    matched_keywords = Column(JSON, default=[])
    matched_sector = Column(String(100))
    
    # Sentiment analysis
    article_sentiment = Column(Float)
    financial_sentiment = Column(Float)
    
    # Analysis
    is_significant = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="article_links")
    exchange = relationship("ExchangeDB")
    
    # Indexes
    __table_args__ = (
        Index('idx_link_article', 'article_id'),
        Index('idx_link_instrument', 'instrument_id'),
        Index('idx_link_correlation_type', 'correlation_type'),
        Index('idx_link_score', 'correlation_score'),
        Index('idx_link_article_instrument', 'article_id', 'instrument_id'),
    )
    
    def to_dataclass(self) -> ArticleFinancialLink:
        """Convert SQLAlchemy model to dataclass."""
        return ArticleFinancialLink(
            id=self.id,
            article_id=self.article_id,
            instrument_id=self.instrument_id,
            exchange_id=self.exchange_id,
            correlation_score=self.correlation_score,
            correlation_type=self.correlation_type,
            time_diff_hours=self.time_diff_hours,
            direction=self.direction,
            matched_keywords=self.matched_keywords or [],
            matched_sector=self.matched_sector,
            article_sentiment=self.article_sentiment,
            financial_sentiment=self.financial_sentiment,
            is_significant=self.is_significant,
            confidence=self.confidence,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
    
    @classmethod
    def from_dataclass(cls, link: ArticleFinancialLink) -> "ArticleFinancialLinkDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=link.id,
            article_id=link.article_id,
            instrument_id=link.instrument_id,
            exchange_id=link.exchange_id,
            correlation_score=link.correlation_score,
            correlation_type=link.correlation_type,
            time_diff_hours=link.time_diff_hours,
            direction=link.direction,
            matched_keywords=link.matched_keywords,
            matched_sector=link.matched_sector,
            article_sentiment=link.article_sentiment,
            financial_sentiment=link.financial_sentiment,
            is_significant=link.is_significant,
            confidence=link.confidence,
            created_at=link.created_at,
            updated_at=link.updated_at,
        )
