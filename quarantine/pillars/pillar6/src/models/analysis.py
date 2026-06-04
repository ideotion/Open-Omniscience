"""
Rare Earth Analysis Model

Defines the RareEarthAnalysis dataclass for representing analysis results.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Dict, Any
import hashlib
import json


class AnalysisType(Enum):
    """Type of analysis performed."""
    PRICE_FLUCTUATION = "price_fluctuation"
    TREND_ANALYSIS = "trend_analysis"
    ANOMALY_DETECTION = "anomaly_detection"
    CORRELATION = "correlation"
    FORECASTING = "forecasting"
    NORMALIZATION = "normalization"
    COMPARATIVE = "comparative"
    PATTERN_RECOGNITION = "pattern_recognition"


class Severity(Enum):
    """Severity level of analysis findings."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Direction(Enum):
    """Direction of price movement or trend."""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"
    VOLATILE = "volatile"


@dataclass
class RareEarthAnalysis:
    """
    Represents analysis results for rare earth market data.
    
    Attributes:
        element_symbol: Chemical symbol of the element
        analysis_type: Type of analysis performed
        start_date: Start date of analysis period
        end_date: End date of analysis period
        results: Analysis results (structure depends on analysis type)
        severity: Severity level of findings
        confidence: Confidence score (0-1)
        direction: Direction of movement/trend
        magnitude: Magnitude of change/fluctuation
        insights: Human-readable insights
        recommendations: Actionable recommendations
        related_articles: List of related article IDs
        related_markets: List of related market IDs
        metadata: Additional metadata
        created_at: Creation timestamp
    """
    element_symbol: str
    analysis_type: AnalysisType
    start_date: date
    end_date: date
    results: Dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.MEDIUM
    confidence: float = 1.0
    direction: Direction = Direction.STABLE
    magnitude: float = 0.0
    insights: str = ""
    recommendations: List[str] = field(default_factory=list)
    related_articles: List[str] = field(default_factory=list)
    related_markets: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate analysis data after initialization."""
        if not self.element_symbol or len(self.element_symbol) > 3:
            raise ValueError(f"Invalid element symbol: {self.element_symbol}")
        if self.start_date > self.end_date:
            raise ValueError("Start date cannot be after end date")
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1: {self.confidence}")
        
    @property
    def analysis_id(self) -> str:
        """Generate a unique identifier for the analysis."""
        return f"{self.element_symbol}-{self.analysis_type.value}-{self.start_date.isoformat()}-{self.end_date.isoformat()}"
    
    @property
    def hash(self) -> str:
        """Generate a hash for the analysis."""
        data = f"{self.element_symbol}{self.analysis_type.value}{self.start_date.isoformat()}{self.end_date.isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()
    
    @property
    def period_days(self) -> int:
        """Get the number of days in the analysis period."""
        return (self.end_date - self.start_date).days
    
    @property
    def significance(self) -> float:
        """Calculate significance score (0-100)."""
        severity_weight = {
            Severity.LOW: 1,
            Severity.MEDIUM: 2,
            Severity.HIGH: 3,
            Severity.CRITICAL: 4,
        }
        severity_score = severity_weight.get(self.severity, 1) * 25
        confidence_score = self.confidence * 100
        magnitude_score = min(self.magnitude * 10, 100)
        
        # Weighted average
        significance = (severity_score * 0.4) + (confidence_score * 0.3) + (magnitude_score * 0.3)
        return min(significance, 100)
    
    @property
    def summary(self) -> str:
        """Get a brief summary of the analysis."""
        direction_map = {
            Direction.UP: "↑",
            Direction.DOWN: "↓",
            Direction.STABLE: "→",
            Direction.VOLATILE: "↕",
        }
        direction_symbol = direction_map.get(self.direction, "")
        return f"{self.element_symbol} {self.analysis_type.value}: {direction_symbol}{self.magnitude:.2%} ({self.severity.value})"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "element_symbol": self.element_symbol,
            "analysis_type": self.analysis_type.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "results": self.results,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "direction": self.direction.value,
            "magnitude": self.magnitude,
            "insights": self.insights,
            "recommendations": self.recommendations,
            "related_articles": self.related_articles,
            "related_markets": self.related_markets,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "analysis_id": self.analysis_id,
            "period_days": self.period_days,
            "significance": self.significance,
            "summary": self.summary,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RareEarthAnalysis':
        """Create from dictionary."""
        return cls(
            element_symbol=data.get("element_symbol"),
            analysis_type=AnalysisType(data.get("analysis_type", "price_fluctuation")),
            start_date=date.fromisoformat(data.get("start_date")) if data.get("start_date") else date.today(),
            end_date=date.fromisoformat(data.get("end_date")) if data.get("end_date") else date.today(),
            results=data.get("results", {}),
            severity=Severity(data.get("severity", "medium")),
            confidence=data.get("confidence", 1.0),
            direction=Direction(data.get("direction", "stable")),
            magnitude=data.get("magnitude", 0.0),
            insights=data.get("insights", ""),
            recommendations=data.get("recommendations", []),
            related_articles=data.get("related_articles", []),
            related_markets=data.get("related_markets", []),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else datetime.utcnow(),
        )
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'RareEarthAnalysis':
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on analysis_id."""
        if not isinstance(other, RareEarthAnalysis):
            return False
        return self.analysis_id == other.analysis_id
    
    def __hash__(self) -> int:
        """Hash based on analysis_id."""
        return hash(self.analysis_id)
    
    def __lt__(self, other: 'RareEarthAnalysis') -> bool:
        """Compare by created_at."""
        return self.created_at < other.created_at


@dataclass
class PriceFluctuationAnalysis(RareEarthAnalysis):
    """
    Specialized analysis for price fluctuations.
    """
    price_change_pct: float = 0.0
    volatility: float = 0.0
    price_range: tuple = (0.0, 0.0)
    average_price: float = 0.0
    
    def __post_init__(self):
        """Initialize price fluctuation analysis."""
        super().__post_init__()
        self.analysis_type = AnalysisType.PRICE_FLUCTUATION
        self.results = {
            "price_change_pct": self.price_change_pct,
            "volatility": self.volatility,
            "price_range": self.price_range,
            "average_price": self.average_price,
        }


@dataclass
class TrendAnalysis(RareEarthAnalysis):
    """
    Specialized analysis for trend detection.
    """
    trend_strength: float = 0.0
    trend_direction: Direction = Direction.STABLE
    trend_duration_days: int = 0
    is_significant: bool = False
    
    def __post_init__(self):
        """Initialize trend analysis."""
        super().__post_init__()
        self.analysis_type = AnalysisType.TREND_ANALYSIS
        self.direction = self.trend_direction
        self.results = {
            "trend_strength": self.trend_strength,
            "trend_direction": self.trend_direction.value,
            "trend_duration_days": self.trend_duration_days,
            "is_significant": self.is_significant,
        }


@dataclass
class AnomalyAnalysis(RareEarthAnalysis):
    """
    Specialized analysis for anomaly detection.
    """
    anomaly_score: float = 0.0
    is_anomaly: bool = False
    anomaly_type: str = ""
    expected_value: float = 0.0
    actual_value: float = 0.0
    deviation: float = 0.0
    
    def __post_init__(self):
        """Initialize anomaly analysis."""
        super().__post_init__()
        self.analysis_type = AnalysisType.ANOMALY_DETECTION
        self.results = {
            "anomaly_score": self.anomaly_score,
            "is_anomaly": self.is_anomaly,
            "anomaly_type": self.anomaly_type,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "deviation": self.deviation,
        }


@dataclass
class NormalizationAnalysis(RareEarthAnalysis):
    """
    Specialized analysis for data normalization.
    """
    normalized_value: float = 0.0
    normalization_method: str = ""
    baseline_value: float = 0.0
    baseline_period: str = ""
    
    def __post_init__(self):
        """Initialize normalization analysis."""
        super().__post_init__()
        self.analysis_type = AnalysisType.NORMALIZATION
        self.results = {
            "normalized_value": self.normalized_value,
            "normalization_method": self.normalization_method,
            "baseline_value": self.baseline_value,
            "baseline_period": self.baseline_period,
        }
