"""
Rare Earth Correlation Model

Defines the ArticleRareEarthLink dataclass for representing correlations
between articles and rare earth market data.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Dict, Any
import hashlib
import json


class CorrelationType(Enum):
    """Type of correlation."""
    PRICE_NEWS = "price_news"
    PRODUCTION_NEWS = "production_news"
    INVENTORY_NEWS = "inventory_news"
    MARKET_EVENT = "market_event"
    POLICY_IMPACT = "policy_impact"
    TECHNOLOGY_IMPACT = "technology_impact"
    SUPPLY_CHAIN = "supply_chain"


class CorrelationStrength(Enum):
    """Strength of correlation."""
    NONE = "none"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class Sentiment(Enum):
    """Sentiment of the article or correlation."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


@dataclass
class ArticleRareEarthLink:
    """
    Represents a correlation between an article and rare earth market data.
    
    Attributes:
        article_id: ID of the related article
        element_symbol: Chemical symbol of the element
        correlation_type: Type of correlation
        correlation_score: Strength of correlation (0-1)
        correlation_strength: Categorical strength level
        sentiment: Sentiment of the article
        sentiment_score: Sentiment score (-1 to 1)
        date: Date of the correlation
        time_lag_days: Days between article and market event
        price_change_pct: Percentage price change (if applicable)
        volume_change_pct: Percentage volume change (if applicable)
        keywords: List of relevant keywords
        entities: List of relevant entities (companies, countries, etc.)
        confidence: Confidence score (0-1)
        insights: Human-readable insights
        is_significant: Whether the correlation is statistically significant
        p_value: P-value for statistical significance
        metadata: Additional metadata
        created_at: Creation timestamp
    """
    article_id: str
    element_symbol: str
    correlation_type: CorrelationType
    correlation_score: float = 0.0
    correlation_strength: CorrelationStrength = CorrelationStrength.NONE
    sentiment: Sentiment = Sentiment.NEUTRAL
    sentiment_score: float = 0.0
    date: date = field(default_factory=date.today)
    time_lag_days: int = 0
    price_change_pct: Optional[float] = None
    volume_change_pct: Optional[float] = None
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    confidence: float = 1.0
    insights: str = ""
    is_significant: bool = False
    p_value: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate correlation data after initialization."""
        if not self.article_id:
            raise ValueError("Article ID cannot be empty")
        if not self.element_symbol or len(self.element_symbol) > 3:
            raise ValueError(f"Invalid element symbol: {self.element_symbol}")
        if not 0 <= self.correlation_score <= 1:
            raise ValueError(f"Correlation score must be between 0 and 1: {self.correlation_score}")
        if not -1 <= self.sentiment_score <= 1:
            raise ValueError(f"Sentiment score must be between -1 and 1: {self.sentiment_score}")
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1: {self.confidence}")
        
    @property
    def link_id(self) -> str:
        """Generate a unique identifier for the correlation link."""
        return f"{self.article_id}-{self.element_symbol}-{self.correlation_type.value}"
    
    @property
    def hash(self) -> str:
        """Generate a hash for the correlation link."""
        data = f"{self.article_id}{self.element_symbol}{self.correlation_type.value}{self.date.isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @property
    def strength_level(self) -> int:
        """Get numerical strength level (0-4)."""
        strength_map = {
            CorrelationStrength.NONE: 0,
            CorrelationStrength.WEAK: 1,
            CorrelationStrength.MODERATE: 2,
            CorrelationStrength.STRONG: 3,
            CorrelationStrength.VERY_STRONG: 4,
        }
        return strength_map.get(self.correlation_strength, 0)
    
    @property
    def sentiment_label(self) -> str:
        """Get sentiment label with score."""
        sentiment_map = {
            Sentiment.POSITIVE: "+",
            Sentiment.NEGATIVE: "-",
            Sentiment.NEUTRAL: "=",
            Sentiment.MIXED: "±",
        }
        symbol = sentiment_map.get(self.sentiment, "")
        return f"{symbol} {self.sentiment_score:.2f}"
    
    @property
    def significance_score(self) -> float:
        """Calculate overall significance score (0-100)."""
        # Weight components
        correlation_score = self.correlation_score * 100
        confidence_score = self.confidence * 100
        strength_score = self.strength_level * 25
        significance_score = (1 - self.p_value) * 100 if self.p_value else 0
        
        # Weighted average
        significance = (
            correlation_score * 0.4 +
            confidence_score * 0.2 +
            strength_score * 0.2 +
            significance_score * 0.2
        )
        return min(significance, 100)
    
    @property
    def summary(self) -> str:
        """Get a brief summary of the correlation."""
        sentiment_map = {
            Sentiment.POSITIVE: "positive",
            Sentiment.NEGATIVE: "negative",
            Sentiment.NEUTRAL: "neutral",
            Sentiment.MIXED: "mixed",
        }
        sentiment_str = sentiment_map.get(self.sentiment, "neutral")
        
        price_str = ""
        if self.price_change_pct is not None:
            price_str = f" (price: {self.price_change_pct:+.2f}%)"
        
        return f"{self.element_symbol} ↔ Article: {self.correlation_strength.value} {sentiment_str}{price_str}"
    
    def matches_keywords(self, keywords: List[str]) -> bool:
        """Check if any of the given keywords match."""
        keywords_lower = [k.lower() for k in keywords]
        link_keywords_lower = [k.lower() for k in self.keywords]
        return any(k in link_keywords_lower for k in keywords_lower)
    
    def matches_entities(self, entities: List[str]) -> bool:
        """Check if any of the given entities match."""
        entities_lower = [e.lower() for e in entities]
        link_entities_lower = [e.lower() for e in self.entities]
        return any(e in link_entities_lower for e in entities_lower)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "article_id": self.article_id,
            "element_symbol": self.element_symbol,
            "correlation_type": self.correlation_type.value,
            "correlation_score": self.correlation_score,
            "correlation_strength": self.correlation_strength.value,
            "sentiment": self.sentiment.value,
            "sentiment_score": self.sentiment_score,
            "date": self.date.isoformat(),
            "time_lag_days": self.time_lag_days,
            "price_change_pct": self.price_change_pct,
            "volume_change_pct": self.volume_change_pct,
            "keywords": self.keywords,
            "entities": self.entities,
            "confidence": self.confidence,
            "insights": self.insights,
            "is_significant": self.is_significant,
            "p_value": self.p_value,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "link_id": self.link_id,
            "strength_level": self.strength_level,
            "sentiment_label": self.sentiment_label,
            "significance_score": self.significance_score,
            "summary": self.summary,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ArticleRareEarthLink':
        """Create from dictionary."""
        return cls(
            article_id=data.get("article_id"),
            element_symbol=data.get("element_symbol"),
            correlation_type=CorrelationType(data.get("correlation_type", "price_news")),
            correlation_score=data.get("correlation_score", 0.0),
            correlation_strength=CorrelationStrength(data.get("correlation_strength", "none")),
            sentiment=Sentiment(data.get("sentiment", "neutral")),
            sentiment_score=data.get("sentiment_score", 0.0),
            date=date.fromisoformat(data.get("date")) if data.get("date") else date.today(),
            time_lag_days=data.get("time_lag_days", 0),
            price_change_pct=data.get("price_change_pct"),
            volume_change_pct=data.get("volume_change_pct"),
            keywords=data.get("keywords", []),
            entities=data.get("entities", []),
            confidence=data.get("confidence", 1.0),
            insights=data.get("insights", ""),
            is_significant=data.get("is_significant", False),
            p_value=data.get("p_value"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else datetime.utcnow(),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ArticleRareEarthLink':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on link_id."""
        if not isinstance(other, ArticleRareEarthLink):
            return False
        return self.link_id == other.link_id
    
    def __hash__(self) -> int:
        """Hash based on link_id."""
        return hash(self.link_id)
    
    def __lt__(self, other: 'ArticleRareEarthLink') -> bool:
        """Compare by correlation_score, then date."""
        if self.correlation_score != other.correlation_score:
            return self.correlation_score > other.correlation_score
        return self.date < other.date


@dataclass
class CorrelationAnalysis:
    """
    Represents a collection of correlations for analysis.
    """
    element_symbol: str
    start_date: date
    end_date: date
    correlations: List[ArticleRareEarthLink] = field(default_factory=list)
    
    @property
    def total_correlations(self) -> int:
        """Get total number of correlations."""
        return len(self.correlations)
    
    @property
    def significant_correlations(self) -> List[ArticleRareEarthLink]:
        """Get only significant correlations."""
        return [c for c in self.correlations if c.is_significant]
    
    @property
    def strong_correlations(self) -> List[ArticleRareEarthLink]:
        """Get only strong correlations."""
        return [c for c in self.correlations if c.strength_level >= 3]
    
    @property
    def average_correlation_score(self) -> float:
        """Get average correlation score."""
        if not self.correlations:
            return 0.0
        return sum(c.correlation_score for c in self.correlations) / len(self.correlations)
    
    @property
    def average_significance_score(self) -> float:
        """Get average significance score."""
        if not self.correlations:
            return 0.0
        return sum(c.significance_score for c in self.correlations) / len(self.correlations)
    
    def add_correlation(self, correlation: ArticleRareEarthLink) -> None:
        """Add a correlation to the analysis."""
        self.correlations.append(correlation)
        # Sort by significance score
        self.correlations.sort(key=lambda c: c.significance_score, reverse=True)
    
    def get_correlations_by_type(self, correlation_type: CorrelationType) -> List[ArticleRareEarthLink]:
        """Get correlations by type."""
        return [c for c in self.correlations if c.correlation_type == correlation_type]
    
    def get_correlations_by_sentiment(self, sentiment: Sentiment) -> List[ArticleRareEarthLink]:
        """Get correlations by sentiment."""
        return [c for c in self.correlations if c.sentiment == sentiment]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_correlations": self.total_correlations,
            "significant_correlations": len(self.significant_correlations),
            "strong_correlations": len(self.strong_correlations),
            "average_correlation_score": self.average_correlation_score,
            "average_significance_score": self.average_significance_score,
            "correlations": [c.to_dict() for c in self.correlations],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CorrelationAnalysis':
        """Create from dictionary."""
        correlations = [ArticleRareEarthLink.from_dict(c) for c in data.get("correlations", [])]
        return cls(
            element_symbol=data.get("element_symbol"),
            start_date=date.fromisoformat(data.get("start_date")) if data.get("start_date") else date.today(),
            end_date=date.fromisoformat(data.get("end_date")) if data.get("end_date") else date.today(),
            correlations=correlations,
        )
