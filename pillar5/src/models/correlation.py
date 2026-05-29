"""
Article-Financial Link Model

Represents a correlation between an article and financial data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


class CorrelationType(Enum):
    """Types of correlation between articles and financial data."""
    MENTION = "mention"           # Article mentions the company/exchange
    EVENT = "event"               # Article about a specific financial event
    SENTIMENT = "sentiment"       # Sentiment correlation
    TEMPORAL = "temporal"         # Temporal proximity
    STATISTICAL = "statistical"   # Statistical correlation


class Direction(Enum):
    """Direction of correlation (temporal)."""
    BEFORE = "before"            # Article published before financial event
    AFTER = "after"              # Article published after financial event
    SAME_TIME = "same_time"      # Article and event at the same time


@dataclass
class ArticleFinancialLink:
    """
    Represents a correlation between an article and financial data.
    
    Attributes:
        id: UUID for this correlation link
        article_id: Reference to the article
        company_id: Reference to the company
        exchange_id: Reference to the exchange
        
        # Correlation metadata
        correlation_score: Strength of correlation (0-1)
        correlation_type: Type of correlation
        time_diff_hours: Hours between article and financial event
        direction: Temporal direction
        
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
    company_id: Optional[str] = None
    exchange_id: Optional[str] = None
    
    # Correlation metadata
    correlation_score: float = 0.0
    correlation_type: str = CorrelationType.MENTION.value
    time_diff_hours: Optional[float] = None
    direction: str = Direction.SAME_TIME.value
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert correlation link to dictionary."""
        return {
            "id": self.id,
            "article_id": self.article_id,
            "company_id": self.company_id,
            "exchange_id": self.exchange_id,
            "correlation_score": self.correlation_score,
            "correlation_type": self.correlation_type,
            "time_diff_hours": self.time_diff_hours,
            "direction": self.direction,
            "article_sentiment": self.article_sentiment,
            "financial_sentiment": self.financial_sentiment,
            "is_significant": self.is_significant,
            "confidence": self.confidence,
            "sentiment_match": self.sentiment_match,
            "strength": self.strength,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArticleFinancialLink":
        """Create correlation link from dictionary."""
        return cls(
            id=data.get("id"),
            article_id=data.get("article_id"),
            company_id=data.get("company_id"),
            exchange_id=data.get("exchange_id"),
            correlation_score=data.get("correlation_score", 0.0),
            correlation_type=data.get("correlation_type", CorrelationType.MENTION.value),
            time_diff_hours=data.get("time_diff_hours"),
            direction=data.get("direction", Direction.SAME_TIME.value),
            article_sentiment=data.get("article_sentiment"),
            financial_sentiment=data.get("financial_sentiment"),
            is_significant=data.get("is_significant", False),
            confidence=data.get("confidence", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"ArticleFinancialLink(id={self.id!r}, article_id={self.article_id!r}, score={self.correlation_score!r})"
