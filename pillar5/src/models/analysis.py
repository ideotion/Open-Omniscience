"""
Financial Analysis Model

Represents analysis results for financial data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


class AnalysisType(Enum):
    """Types of financial analysis."""
    FLUCTUATION = "fluctuation"
    PATTERN = "pattern"
    ANOMALY = "anomaly"
    CORRELATION = "correlation"
    TREND = "trend"
    VOLATILITY = "volatility"


class Severity(Enum):
    """Severity levels for analysis results."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FinancialAnalysis:
    """
    Represents analysis results for financial data.
    
    Attributes:
        id: UUID for this analysis
        company_id: Reference to the company
        exchange_id: Reference to the exchange
        analysis_type: Type of analysis performed
        analysis_date: When the analysis was performed
        time_period: Time period for the analysis (e.g., "1D", "5D", "1M")
        
        # Results (flexible JSON field)
        results: Analysis-specific results
        
        # Metadata
        confidence: Confidence score (0-1)
        severity: Severity level
        related_articles: IDs of related articles
        related_events: IDs of related financial events
        
        # Type-specific fields
        price_change_pct: Percentage price change
        volume_change_pct: Percentage volume change
        volatility: Volatility score
        pattern_type: Detected pattern type
        pattern_strength: Pattern confidence score
        correlation_score: Correlation score with news
        correlated_article_ids: List of correlated article IDs
        
        created_at: When this analysis was created
    """
    id: str
    company_id: str
    exchange_id: Optional[str] = None
    analysis_type: str = AnalysisType.FLUCTUATION.value
    analysis_date: datetime = field(default_factory=datetime.utcnow)
    time_period: str = "1D"
    
    # Results
    results: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    confidence: float = 0.0
    severity: str = Severity.MEDIUM.value
    related_articles: List[str] = field(default_factory=list)
    related_events: List[str] = field(default_factory=list)
    
    # Type-specific fields
    price_change_pct: Optional[float] = None
    volume_change_pct: Optional[float] = None
    volatility: Optional[float] = None
    pattern_type: Optional[str] = None
    pattern_strength: Optional[float] = None
    correlation_score: Optional[float] = None
    correlated_article_ids: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate analysis data."""
        if not self.id:
            raise ValueError("Analysis ID cannot be empty")
        if not self.company_id:
            raise ValueError("Company ID cannot be empty")
        if not self.analysis_type:
            raise ValueError("Analysis type cannot be empty")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
    
    @property
    def is_significant(self) -> bool:
        """Check if analysis is significant."""
        return self.confidence >= 0.7 and self.severity in [Severity.HIGH.value, Severity.CRITICAL.value]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert analysis to dictionary."""
        return {
            "id": self.id,
            "company_id": self.company_id,
            "exchange_id": self.exchange_id,
            "analysis_type": self.analysis_type,
            "analysis_date": self.analysis_date.isoformat(),
            "time_period": self.time_period,
            "results": self.results,
            "confidence": self.confidence,
            "severity": self.severity,
            "related_articles": self.related_articles,
            "related_events": self.related_events,
            "price_change_pct": self.price_change_pct,
            "volume_change_pct": self.volume_change_pct,
            "volatility": self.volatility,
            "pattern_type": self.pattern_type,
            "pattern_strength": self.pattern_strength,
            "correlation_score": self.correlation_score,
            "correlated_article_ids": self.correlated_article_ids,
            "is_significant": self.is_significant,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinancialAnalysis":
        """Create analysis from dictionary."""
        return cls(
            id=data.get("id"),
            company_id=data.get("company_id"),
            exchange_id=data.get("exchange_id"),
            analysis_type=data.get("analysis_type", AnalysisType.FLUCTUATION.value),
            analysis_date=datetime.fromisoformat(data["analysis_date"]) if data.get("analysis_date") else datetime.utcnow(),
            time_period=data.get("time_period", "1D"),
            results=data.get("results", {}),
            confidence=data.get("confidence", 0.0),
            severity=data.get("severity", Severity.MEDIUM.value),
            related_articles=data.get("related_articles", []),
            related_events=data.get("related_events", []),
            price_change_pct=data.get("price_change_pct"),
            volume_change_pct=data.get("volume_change_pct"),
            volatility=data.get("volatility"),
            pattern_type=data.get("pattern_type"),
            pattern_strength=data.get("pattern_strength"),
            correlation_score=data.get("correlation_score"),
            correlated_article_ids=data.get("correlated_article_ids", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"FinancialAnalysis(id={self.id!r}, company_id={self.company_id!r}, type={self.analysis_type!r})"
