"""
Financial Analysis Model

Represents analysis results for financial data.
Includes both dataclass and SQLAlchemy model.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from sqlalchemy import Column, String, DateTime, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


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
        instrument_id: Reference to the instrument (replaces company_id)
        exchange_id: Reference to the exchange (optional)
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
    instrument_id: str  # Updated from company_id
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
        if not self.instrument_id:
            raise ValueError("Instrument ID cannot be empty")
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
            "instrument_id": self.instrument_id,
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
            instrument_id=data.get("instrument_id") or data.get("company_id"),  # Backward compatibility
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
        return f"FinancialAnalysis(id={self.id!r}, instrument_id={self.instrument_id!r}, type={self.analysis_type!r})"


# SQLAlchemy model
class FinancialAnalysisDB(Base):
    """SQLAlchemy model for the financial_analyses table."""
    __tablename__ = 'financial_analyses'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'))
    exchange_id = Column(String(10), ForeignKey('financial_exchanges.id'))
    analysis_type = Column(String(20), nullable=False)
    analysis_date = Column(DateTime, default=datetime.utcnow)
    time_period = Column(String(10), default="1D")
    
    # Results (JSON)
    results = Column(JSON)
    
    # Metadata
    confidence = Column(Float, default=0.0)
    severity = Column(String(20), default=Severity.MEDIUM.value)
    related_articles = Column(JSON, default=[])
    related_events = Column(JSON, default=[])
    
    # Type-specific fields
    price_change_pct = Column(Float)
    volume_change_pct = Column(Float)
    volatility = Column(Float)
    pattern_type = Column(String(50))
    pattern_strength = Column(Float)
    correlation_score = Column(Float)
    correlated_article_ids = Column(JSON, default=[])
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="analyses")
    exchange = relationship("ExchangeDB")
    
    # Indexes
    __table_args__ = (
        Index('idx_analysis_instrument', 'instrument_id'),
        Index('idx_analysis_type', 'analysis_type'),
        Index('idx_analysis_date', 'analysis_date'),
        Index('idx_analysis_instrument_type', 'instrument_id', 'analysis_type'),
    )
    
    def to_dataclass(self) -> FinancialAnalysis:
        """Convert SQLAlchemy model to dataclass."""
        return FinancialAnalysis(
            id=self.id,
            instrument_id=self.instrument_id,
            exchange_id=self.exchange_id,
            analysis_type=self.analysis_type,
            analysis_date=self.analysis_date,
            time_period=self.time_period,
            results=self.results or {},
            confidence=self.confidence,
            severity=self.severity,
            related_articles=self.related_articles or [],
            related_events=self.related_events or [],
            price_change_pct=self.price_change_pct,
            volume_change_pct=self.volume_change_pct,
            volatility=self.volatility,
            pattern_type=self.pattern_type,
            pattern_strength=self.pattern_strength,
            correlation_score=self.correlation_score,
            correlated_article_ids=self.correlated_article_ids or [],
            created_at=self.created_at,
        )
    
    @classmethod
    def from_dataclass(cls, analysis: FinancialAnalysis) -> "FinancialAnalysisDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=analysis.id,
            instrument_id=analysis.instrument_id,
            exchange_id=analysis.exchange_id,
            analysis_type=analysis.analysis_type,
            analysis_date=analysis.analysis_date,
            time_period=analysis.time_period,
            results=analysis.results,
            confidence=analysis.confidence,
            severity=analysis.severity,
            related_articles=analysis.related_articles,
            related_events=analysis.related_events,
            price_change_pct=analysis.price_change_pct,
            volume_change_pct=analysis.volume_change_pct,
            volatility=analysis.volatility,
            pattern_type=analysis.pattern_type,
            pattern_strength=analysis.pattern_strength,
            correlation_score=analysis.correlation_score,
            correlated_article_ids=analysis.correlated_article_ids,
            created_at=analysis.created_at,
        )
