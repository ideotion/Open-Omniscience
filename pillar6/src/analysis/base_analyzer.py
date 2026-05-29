"""
Pillar 6 Base Analyzer

Base class for all rare earth market analyzers.
"""

from abc import ABC, abstractmethod
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Union
import logging
import numpy as np
import pandas as pd

from ..models import (
    RareEarthPrice,
    RareEarthProduction,
    RareEarthInventory,
    RareEarthAnalysis,
    PriceFluctuationAnalysis,
    TrendAnalysis,
    AnomalyAnalysis,
    NormalizationAnalysis,
    AnalysisType,
    Severity,
    Direction,
)
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class AnalyzerConfig:
    """
    Configuration for analyzers.
    
    Attributes:
        window_size: Number of data points to use for analysis
        min_data_points: Minimum number of data points required
        confidence_threshold: Minimum confidence for analysis results
        severity_thresholds: Thresholds for severity levels
        trend_min_points: Minimum points for trend detection
        anomaly_z_score: Z-score threshold for anomaly detection
    """
    
    def __init__(
        self,
        window_size: int = 30,
        min_data_points: int = 5,
        confidence_threshold: float = 0.7,
        trend_min_points: int = 10,
        anomaly_z_score: float = 3.0,
    ):
        self.window_size = window_size
        self.min_data_points = min_data_points
        self.confidence_threshold = confidence_threshold
        self.trend_min_points = trend_min_points
        self.anomaly_z_score = anomaly_z_score
        
        # Severity thresholds (0-1 scale)
        self.severity_thresholds = {
            Severity.LOW: 0.25,
            Severity.MEDIUM: 0.5,
            Severity.HIGH: 0.75,
            Severity.CRITICAL: 0.9,
        }
    
    def get_severity(self, score: float) -> Severity:
        """Get severity level from a score (0-1)."""
        for severity, threshold in self.severity_thresholds.items():
            if score >= threshold:
                return severity
        return Severity.LOW
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "window_size": self.window_size,
            "min_data_points": self.min_data_points,
            "confidence_threshold": self.confidence_threshold,
            "trend_min_points": self.trend_min_points,
            "anomaly_z_score": self.anomaly_z_score,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalyzerConfig':
        """Create configuration from dictionary."""
        return cls(
            window_size=data.get("window_size", 30),
            min_data_points=data.get("min_data_points", 5),
            confidence_threshold=data.get("confidence_threshold", 0.7),
            trend_min_points=data.get("trend_min_points", 10),
            anomaly_z_score=data.get("anomaly_z_score", 3.0),
        )


# Default configuration
DEFAULT_ANALYZER_CONFIG = AnalyzerConfig()


class RareEarthAnalyzer(ABC):
    """
    Base class for rare earth market analyzers.
    
    Provides common functionality for all analyzers including:
    - Data retrieval from storage
    - Statistical calculations
    - Result formatting
    - Error handling
    - Logging
    
    Subclasses should implement specific analysis logic.
    """
    
    def __init__(
        self,
        config: Optional[AnalyzerConfig] = None,
        name: str = "BaseAnalyzer",
    ):
        """
        Initialize the analyzer.
        
        Args:
            config: Analyzer configuration
            name: Name of the analyzer (for logging)
        """
        self.config = config or DEFAULT_ANALYZER_CONFIG
        self.name = name
    
    def get_price_data(
        self,
        element_symbol: str,
        market_id: Optional[str] = None,
        days: int = 30,
    ) -> List[RareEarthPrice]:
        """
        Get price data for analysis.
        
        Args:
            element_symbol: Element symbol
            market_id: Optional market ID
            days: Number of days of history
            
        Returns:
            List of RareEarthPrice objects
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        return storage.get_prices_in_date_range(
            element_symbol, start_date, end_date, market_id
        )
    
    def get_production_data(
        self,
        element_symbol: str,
        country: Optional[str] = None,
        years: Optional[int] = None,
    ) -> List[RareEarthProduction]:
        """
        Get production data for analysis.
        
        Args:
            element_symbol: Element symbol
            country: Optional country filter
            years: Optional number of years of history
            
        Returns:
            List of RareEarthProduction objects
        """
        productions = storage.get_productions_by_element(element_symbol)
        
        if country:
            productions = [p for p in productions if p.country == country]
        
        if years:
            current_year = datetime.now().year
            productions = [p for p in productions if p.year >= current_year - years]
        
        return productions
    
    def get_inventory_data(
        self,
        element_symbol: str,
        country: Optional[str] = None,
        years: Optional[int] = None,
    ) -> List[RareEarthInventory]:
        """
        Get inventory data for analysis.
        
        Args:
            element_symbol: Element symbol
            country: Optional country filter
            years: Optional number of years of history
            
        Returns:
            List of RareEarthInventory objects
        """
        inventories = storage.get_inventories_by_element(element_symbol)
        
        if country:
            inventories = [i for i in inventories if i.country == country]
        
        if years:
            current_year = datetime.now().year
            inventories = [i for i in inventories if i.year >= current_year - years]
        
        return inventories
    
    def _check_min_data(self, data: List[Any]) -> bool:
        """Check if there's enough data for analysis."""
        return len(data) >= self.config.min_data_points
    
    def _get_dataframe(self, data: List[Any], date_field: str = "date") -> Optional[pd.DataFrame]:
        """Convert data list to pandas DataFrame."""
        if not data:
            return None
        
        # Convert to dicts
        records = [d.to_dict() for d in data]
        df = pd.DataFrame(records)
        
        # Convert date fields
        if date_field in df.columns:
            df[date_field] = pd.to_datetime(df[date_field])
            df = df.sort_values(date_field)
        
        return df
    
    def _calculate_statistics(self, values: List[float]) -> Dict[str, float]:
        """Calculate basic statistics for a list of values."""
        if not values or len(values) < 2:
            return {
                "mean": 0,
                "median": 0,
                "std": 0,
                "min": 0,
                "max": 0,
                "range": 0,
                "count": 0,
            }
        
        return {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": float(np.std(values)),
            "min": float(min(values)),
            "max": float(max(values)),
            "range": float(max(values) - min(values)),
            "count": len(values),
        }
    
    def _calculate_trend(self, values: List[float]) -> Dict[str, Any]:
        """
        Calculate trend for a series of values.
        
        Uses linear regression to determine trend direction and strength.
        """
        if len(values) < self.config.trend_min_points:
            return {
                "direction": Direction.STABLE,
                "strength": 0.0,
                "slope": 0.0,
                "r_squared": 0.0,
                "is_significant": False,
            }
        
        # Create x values (indices)
        x = np.arange(len(values))
        y = np.array(values)
        
        # Calculate linear regression
        A = np.vstack([x, np.ones(len(x))]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        
        # Calculate R-squared
        y_pred = m * x + c
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Determine direction
        if m > 0.01:
            direction = Direction.UP
        elif m < -0.01:
            direction = Direction.DOWN
        else:
            direction = Direction.STABLE
        
        return {
            "direction": direction,
            "strength": abs(m),
            "slope": float(m),
            "r_squared": float(r_squared),
            "is_significant": r_squared > 0.7,
        }
    
    def _detect_anomalies(self, values: List[float]) -> List[Dict[str, Any]]:
        """
        Detect anomalies in a series of values.
        
        Uses Z-score method for anomaly detection.
        """
        if len(values) < 3:
            return []
        
        mean = np.mean(values)
        std = np.std(values)
        
        if std == 0:
            return []
        
        anomalies = []
        for i, value in enumerate(values):
            z_score = abs((value - mean) / std)
            
            if z_score > self.config.anomaly_z_score:
                anomalies.append({
                    "index": i,
                    "value": value,
                    "z_score": z_score,
                    "is_anomaly": True,
                    "anomaly_type": "outlier",
                })
        
        return anomalies
    
    def _normalize_values(
        self, 
        values: List[float], 
        method: str = "zscore"
    ) -> List[float]:
        """
        Normalize a list of values.
        
        Args:
            values: List of values to normalize
            method: Normalization method ('zscore', 'minmax', 'percent')
            
        Returns:
            List of normalized values
        """
        if not values:
            return []
        
        arr = np.array(values)
        
        if method == "zscore":
            mean = np.mean(arr)
            std = np.std(arr)
            if std == 0:
                return [0.0] * len(arr)
            return [(x - mean) / std for x in arr]
        
        elif method == "minmax":
            min_val = np.min(arr)
            max_val = np.max(arr)
            if max_val == min_val:
                return [0.5] * len(arr)
            return [(x - min_val) / (max_val - min_val) for x in arr]
        
        elif method == "percent":
            base = arr[0] if len(arr) > 0 else 1
            if base == 0:
                return [0.0] * len(arr)
            return [(x / base - 1) * 100 for x in arr]
        
        else:
            return values
    
    def _create_analysis(
        self,
        element_symbol: str,
        analysis_type: AnalysisType,
        start_date: date,
        end_date: date,
        results: Dict[str, Any],
        severity: Severity = Severity.MEDIUM,
        confidence: float = 1.0,
        direction: Direction = Direction.STABLE,
        magnitude: float = 0.0,
        insights: str = "",
        recommendations: List[str] = None,
        related_articles: List[str] = None,
        related_markets: List[str] = None,
        metadata: Dict[str, Any] = None,
    ) -> RareEarthAnalysis:
        """
        Create an analysis object.
        
        Args:
            element_symbol: Element symbol
            analysis_type: Type of analysis
            start_date: Start date of analysis period
            end_date: End date of analysis period
            results: Analysis results
            severity: Severity level
            confidence: Confidence score
            direction: Direction of movement
            magnitude: Magnitude of change
            insights: Human-readable insights
            recommendations: Actionable recommendations
            related_articles: Related article IDs
            related_markets: Related market IDs
            metadata: Additional metadata
            
        Returns:
            RareEarthAnalysis object
        """
        return RareEarthAnalysis(
            element_symbol=element_symbol,
            analysis_type=analysis_type,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=severity,
            confidence=confidence,
            direction=direction,
            magnitude=magnitude,
            insights=insights,
            recommendations=recommendations or [],
            related_articles=related_articles or [],
            related_markets=related_markets or [],
            metadata=metadata or {},
        )
    
    def store_analysis(self, analysis: RareEarthAnalysis) -> Optional[Any]:
        """
        Store an analysis in the database.
        
        Args:
            analysis: Analysis to store
            
        Returns:
            Stored analysis object or None on failure
        """
        try:
            # Convert to dict for storage
            analysis_data = analysis.to_dict()
            # Remove computed fields
            analysis_data.pop("analysis_id", None)
            analysis_data.pop("hash", None)
            analysis_data.pop("period_days", None)
            analysis_data.pop("significance", None)
            analysis_data.pop("summary", None)
            
            # Get element ID
            element = storage.get_element_by_symbol(analysis.element_symbol)
            if element:
                analysis_data["element_id"] = element.id
                return storage.create_analysis(analysis_data)
            
        except Exception as e:
            logger.error(f"Failed to store analysis: {e}")
        
        return None
    
    @abstractmethod
    def analyze(
        self, 
        element_symbol: str, 
        **kwargs
    ) -> Optional[RareEarthAnalysis]:
        """
        Perform analysis on rare earth data.
        
        Args:
            element_symbol: Element symbol to analyze
            **kwargs: Additional analysis parameters
            
        Returns:
            Analysis results or None on failure
        """
        pass
    
    @abstractmethod
    def get_analysis_type(self) -> AnalysisType:
        """Get the type of analysis performed."""
        pass
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"


class AnalyzerFactory:
    """
    Factory for creating analyzers with consistent configuration.
    """
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        """Initialize the factory."""
        self.config = config or DEFAULT_ANALYZER_CONFIG
    
    def create_analyzer(self, analyzer_class, name: str = None, **kwargs) -> RareEarthAnalyzer:
        """
        Create an analyzer instance.
        
        Args:
            analyzer_class: Analyzer class to instantiate
            name: Name for the analyzer
            **kwargs: Additional arguments for the analyzer
            
        Returns:
            Configured analyzer instance
        """
        return analyzer_class(
            config=self.config,
            name=name or analyzer_class.__name__,
            **kwargs
        )


# Export everything
__all__ = [
    "AnalyzerConfig",
    "DEFAULT_ANALYZER_CONFIG",
    "RareEarthAnalyzer",
    "AnalyzerFactory",
]
