"""
Financial Metric Model

Represents a pre-computed metric for a financial instrument.
Stored separately with full audit trails (source, calculation method, parameters, timestamp).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship

from pillar5.src.models.base import Base


@dataclass
class FinancialMetric:
    """
    Pre-computed metric for a financial instrument.
    
    Attributes:
        id: UUID
        instrument_id: Reference to instrument
        metric_name: Name of the metric (e.g., "sma_20", "rsi_14")
        metric_group: Theme/group (e.g., "Trend", "Momentum", "Volatility")
        metric_value: Computed value
        timeframe: Timeframe for calculation (e.g., "1D", "1W", "1M")
        timestamp: Timestamp of the data point this metric is for
        calculation_method: Formula/method used (e.g., "Simple Moving Average")
        parameters: Parameters used (e.g., {"period": 20} for SMA(20))
        source: Source of the underlying data (e.g., "yahoo_finance")
        is_real_time: Whether this is a real-time or historical metric
        confidence: Confidence score (0-1) for the calculation
        created_at: When this metric was computed
        updated_at: When this metric was last updated
    """
    id: str
    instrument_id: str
    metric_name: str  # e.g., "sma_20", "rsi_14"
    metric_group: str  # e.g., "Trend", "Momentum", "Volatility", "Volume", "Fundamental"
    metric_value: float
    timestamp: datetime
    calculation_method: str  # e.g., "Simple Moving Average"
    timeframe: str = "1D"  # 1D, 1W, 1M, 3M, 1Y, etc.
    parameters: Dict[str, Any] = field(default_factory=dict)  # e.g., {"period": 20}
    source: Optional[str] = None
    is_real_time: bool = False
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate financial metric data."""
        if not self.id:
            raise ValueError("Metric ID cannot be empty")
        if not self.instrument_id:
            raise ValueError("Instrument ID cannot be empty")
        if not self.metric_name:
            raise ValueError("Metric name cannot be empty")
        if not self.metric_group:
            raise ValueError("Metric group cannot be empty")
        if self.metric_value is None:
            raise ValueError("Metric value cannot be None")
        if not self.timestamp:
            raise ValueError("Timestamp cannot be empty")
        if not self.calculation_method:
            raise ValueError("Calculation method cannot be empty")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
    
    @property
    def display_name(self) -> str:
        """Get display name with parameters (e.g., 'SMA(20)')."""
        if self.parameters:
            params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
            return f"{self.metric_name}({params})"
        return self.metric_name
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "metric_name": self.metric_name,
            "metric_group": self.metric_group,
            "metric_value": self.metric_value,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "calculation_method": self.calculation_method,
            "parameters": self.parameters,
            "source": self.source,
            "is_real_time": self.is_real_time,
            "confidence": self.confidence,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinancialMetric":
        """Create metric from dictionary."""
        return cls(
            id=data.get("id"),
            instrument_id=data.get("instrument_id"),
            metric_name=data.get("metric_name"),
            metric_group=data.get("metric_group"),
            metric_value=data.get("metric_value"),
            timeframe=data.get("timeframe", "1D"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.utcnow(),
            calculation_method=data.get("calculation_method"),
            parameters=data.get("parameters", {}),
            source=data.get("source"),
            is_real_time=data.get("is_real_time", False),
            confidence=data.get("confidence", 1.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.utcnow(),
        )
    
    def __repr__(self) -> str:
        return f"FinancialMetric(id={self.id!r}, instrument_id={self.instrument_id!r}, metric_name={self.metric_name!r}, metric_group={self.metric_group!r}, value={self.metric_value!r})"


# SQLAlchemy model
class FinancialMetricDB(Base):
    """SQLAlchemy model for the financial_metrics table."""
    __tablename__ = 'financial_metrics'
    
    id = Column(String(36), primary_key=True)
    instrument_id = Column(String(50), ForeignKey('financial_instruments.id'), nullable=False)
    metric_name = Column(String(100), nullable=False)
    metric_group = Column(String(50), nullable=False)  # Trend, Momentum, Volatility, Volume, Fundamental, Statistical, Pattern, Custom
    metric_value = Column(Float, nullable=False)
    timeframe = Column(String(10), default="1D")  # 1D, 1W, 1M, 3M, 1Y, etc.
    timestamp = Column(DateTime, nullable=False)
    calculation_method = Column(String(255), nullable=False)
    parameters = Column(JSON, default={})  # e.g., {"period": 20}
    source = Column(String(100))
    is_real_time = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    instrument = relationship("FinancialInstrumentDB", back_populates="metrics")
    
    # Indexes
    __table_args__ = (
        Index('idx_metric_instrument', 'instrument_id'),
        Index('idx_metric_name', 'metric_name'),
        Index('idx_metric_group', 'metric_group'),
        Index('idx_metric_timestamp', 'timestamp'),
        Index('idx_metric_instrument_timestamp', 'instrument_id', 'timestamp'),
        Index('idx_metric_instrument_group', 'instrument_id', 'metric_group'),
    )
    
    def to_dataclass(self) -> FinancialMetric:
        """Convert SQLAlchemy model to dataclass."""
        return FinancialMetric(
            id=self.id,
            instrument_id=self.instrument_id,
            metric_name=self.metric_name,
            metric_group=self.metric_group,
            metric_value=self.metric_value,
            timeframe=self.timeframe,
            timestamp=self.timestamp,
            calculation_method=self.calculation_method,
            parameters=self.parameters or {},
            source=self.source,
            is_real_time=self.is_real_time,
            confidence=self.confidence,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
    
    @classmethod
    def from_dataclass(cls, metric: FinancialMetric) -> "FinancialMetricDB":
        """Create SQLAlchemy model from dataclass."""
        return cls(
            id=metric.id,
            instrument_id=metric.instrument_id,
            metric_name=metric.metric_name,
            metric_group=metric.metric_group,
            metric_value=metric.metric_value,
            timeframe=metric.timeframe,
            timestamp=metric.timestamp,
            calculation_method=metric.calculation_method,
            parameters=metric.parameters,
            source=metric.source,
            is_real_time=metric.is_real_time,
            confidence=metric.confidence,
            created_at=metric.created_at,
            updated_at=metric.updated_at,
        )
