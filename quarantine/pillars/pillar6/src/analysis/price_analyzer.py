"""
Pillar 6 Price Analyzer

Analyzes rare earth price data for fluctuations, trends, and patterns.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import logging
import numpy as np

from .base_analyzer import RareEarthAnalyzer, AnalyzerConfig, DEFAULT_ANALYZER_CONFIG
from ..models import (
    RareEarthPrice,
    RareEarthAnalysis,
    PriceFluctuationAnalysis,
    TrendAnalysis,
    AnalysisType,
    Severity,
    Direction,
)
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class PriceAnalyzer(RareEarthAnalyzer):
    """
    Analyzer for rare earth price data.
    
    Performs various types of price analysis including:
    - Price fluctuation analysis
    - Trend analysis
    - Volatility analysis
    - Price comparison
    """
    
    def __init__(
        self,
        config: Optional[AnalyzerConfig] = None,
        name: str = "PriceAnalyzer",
    ):
        """
        Initialize the price analyzer.
        
        Args:
            config: Analyzer configuration
            name: Name of the analyzer
        """
        super().__init__(config, name)
    
    def get_analysis_type(self) -> AnalysisType:
        """Get the type of analysis performed."""
        return AnalysisType.PRICE_FLUCTUATION
    
    def analyze(
        self,
        element_symbol: str,
        **kwargs
    ) -> Optional[RareEarthAnalysis]:
        """
        Perform comprehensive price analysis.
        
        Args:
            element_symbol: Element symbol to analyze
            **kwargs: Additional parameters
                - market_id: Specific market to analyze
                - days: Number of days of history (default: 30)
                - analysis_type: Specific analysis type to perform
                
        Returns:
            Price analysis results or None on failure
        """
        market_id = kwargs.get("market_id", None)
        days = kwargs.get("days", 30)
        specific_analysis = kwargs.get("analysis_type", None)
        
        # Get price data
        prices = self.get_price_data(element_symbol, market_id, days)
        
        if not self._check_min_data(prices):
            logger.warning(f"Insufficient price data for {element_symbol}")
            return None
        
        # Determine dates
        start_date = prices[-1].date if prices else date.today()
        end_date = prices[0].date if prices else date.today()
        
        # Perform the requested analysis
        if specific_analysis == AnalysisType.TREND_ANALYSIS:
            return self.analyze_trend(element_symbol, prices, start_date, end_date)
        elif specific_analysis == AnalysisType.ANOMALY_DETECTION:
            return self.analyze_anomalies(element_symbol, prices, start_date, end_date)
        elif specific_analysis == AnalysisType.NORMALIZATION:
            return self.analyze_normalization(element_symbol, prices, start_date, end_date)
        else:
            # Default: comprehensive analysis
            return self.analyze_fluctuation(element_symbol, prices, start_date, end_date)
    
    def analyze_fluctuation(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        start_date: date,
        end_date: date,
    ) -> Optional[RareEarthAnalysis]:
        """
        Analyze price fluctuations.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            start_date: Start date of analysis period
            end_date: End date of analysis period
            
        Returns:
            Price fluctuation analysis results
        """
        # Extract price values (normalized to per kg)
        price_values = [p.price_per_kg for p in prices]
        
        if len(price_values) < 2:
            return None
        
        # Calculate statistics
        stats = self._calculate_statistics(price_values)
        
        # Calculate price change
        latest_price = price_values[0]
        oldest_price = price_values[-1]
        price_change = latest_price - oldest_price
        price_change_pct = (price_change / oldest_price * 100) if oldest_price != 0 else 0
        
        # Calculate volatility
        volatility = stats["std"]
        
        # Determine direction
        if price_change_pct > 5:
            direction = Direction.UP
        elif price_change_pct < -5:
            direction = Direction.DOWN
        elif volatility > stats["mean"] * 0.1:
            direction = Direction.VOLATILE
        else:
            direction = Direction.STABLE
        
        # Determine severity based on price change and volatility
        magnitude = abs(price_change_pct) / 100
        severity_score = min(magnitude + (volatility / stats["mean"] if stats["mean"] != 0 else 0), 1.0)
        severity = self.config.get_severity(severity_score)
        
        # Generate insights
        insights = self._generate_fluctuation_insights(
            element_symbol, price_change_pct, volatility, direction
        )
        
        # Generate recommendations
        recommendations = self._generate_fluctuation_recommendations(
            element_symbol, price_change_pct, volatility, direction
        )
        
        # Create results
        results = {
            "price_change_pct": price_change_pct,
            "price_change_abs": price_change,
            "volatility": volatility,
            "price_range": (stats["min"], stats["max"]),
            "average_price": stats["mean"],
            "median_price": stats["median"],
            "std_dev": stats["std"],
            "min_price": stats["min"],
            "max_price": stats["max"],
            "data_points": len(price_values),
        }
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=element_symbol,
            analysis_type=AnalysisType.PRICE_FLUCTUATION,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=severity,
            confidence=0.9,
            direction=direction,
            magnitude=magnitude,
            insights=insights,
            recommendations=recommendations,
        )
        
        return analysis
    
    def analyze_trend(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        start_date: date,
        end_date: date,
    ) -> Optional[RareEarthAnalysis]:
        """
        Analyze price trends.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            start_date: Start date of analysis period
            end_date: End date of analysis period
            
        Returns:
            Trend analysis results
        """
        # Extract price values
        price_values = [p.price_per_kg for p in prices]
        
        if len(price_values) < self.config.trend_min_points:
            logger.warning(f"Insufficient data for trend analysis: {len(price_values)} points")
            return None
        
        # Calculate trend
        trend = self._calculate_trend(price_values)
        
        # Calculate additional statistics
        stats = self._calculate_statistics(price_values)
        
        # Determine severity based on trend strength and R-squared
        severity_score = min(trend["strength"] * 10 + trend["r_squared"], 1.0)
        severity = self.config.get_severity(severity_score)
        
        # Generate insights
        insights = self._generate_trend_insights(
            element_symbol, trend, stats
        )
        
        # Generate recommendations
        recommendations = self._generate_trend_recommendations(
            element_symbol, trend, stats
        )
        
        # Create results
        results = {
            "trend_direction": trend["direction"].value,
            "trend_strength": trend["strength"],
            "slope": trend["slope"],
            "r_squared": trend["r_squared"],
            "is_significant": trend["is_significant"],
            "trend_duration_days": len(price_values),
            "average_price": stats["mean"],
            "price_range": (stats["min"], stats["max"]),
        }
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=element_symbol,
            analysis_type=AnalysisType.TREND_ANALYSIS,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=severity,
            confidence=0.85,
            direction=trend["direction"],
            magnitude=trend["strength"],
            insights=insights,
            recommendations=recommendations,
        )
        
        return analysis
    
    def analyze_anomalies(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        start_date: date,
        end_date: date,
    ) -> Optional[RareEarthAnalysis]:
        """
        Detect price anomalies.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            start_date: Start date of analysis period
            end_date: End date of analysis period
            
        Returns:
            Anomaly detection analysis results
        """
        # Extract price values
        price_values = [p.price_per_kg for p in prices]
        
        if len(price_values) < 3:
            return None
        
        # Detect anomalies
        anomalies = self._detect_anomalies(price_values)
        
        if not anomalies:
            # No anomalies found
            return self._create_analysis(
                element_symbol=element_symbol,
                analysis_type=AnalysisType.ANOMALY_DETECTION,
                start_date=start_date,
                end_date=end_date,
                results={"anomalies_found": 0, "is_anomaly": False},
                severity=Severity.LOW,
                confidence=0.9,
                direction=Direction.STABLE,
                magnitude=0.0,
                insights=f"No price anomalies detected for {element_symbol} in the analysis period.",
                recommendations=[],
            )
        
        # Calculate statistics
        stats = self._calculate_statistics(price_values)
        
        # Calculate severity based on number and magnitude of anomalies
        anomaly_score = sum(a["z_score"] for a in anomalies) / len(anomalies)
        severity_score = min(anomaly_score / self.config.anomaly_z_score, 1.0)
        severity = self.config.get_severity(severity_score)
        
        # Generate insights
        insights = self._generate_anomaly_insights(
            element_symbol, anomalies, stats
        )
        
        # Generate recommendations
        recommendations = self._generate_anomaly_recommendations(
            element_symbol, anomalies, stats
        )
        
        # Create results
        results = {
            "anomalies_found": len(anomalies),
            "is_anomaly": True,
            "anomaly_indices": [a["index"] for a in anomalies],
            "anomaly_values": [a["value"] for a in anomalies],
            "anomaly_z_scores": [a["z_score"] for a in anomalies],
            "average_z_score": anomaly_score,
            "max_z_score": max(a["z_score"] for a in anomalies),
            "average_price": stats["mean"],
            "std_dev": stats["std"],
        }
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=element_symbol,
            analysis_type=AnalysisType.ANOMALY_DETECTION,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=severity,
            confidence=0.8,
            direction=Direction.VOLATILE,
            magnitude=severity_score,
            insights=insights,
            recommendations=recommendations,
        )
        
        return analysis
    
    def analyze_normalization(
        self,
        element_symbol: str,
        prices: List[RareEarthPrice],
        start_date: date,
        end_date: date,
        method: str = "zscore",
    ) -> Optional[RareEarthAnalysis]:
        """
        Normalize price data for comparison.
        
        Args:
            element_symbol: Element symbol
            prices: List of price data points
            start_date: Start date of analysis period
            end_date: End date of analysis period
            method: Normalization method
            
        Returns:
            Normalization analysis results
        """
        # Extract price values
        price_values = [p.price_per_kg for p in prices]
        
        if len(price_values) < 2:
            return None
        
        # Normalize values
        normalized_values = self._normalize_values(price_values, method)
        
        # Calculate statistics
        stats = self._calculate_statistics(price_values)
        normalized_stats = self._calculate_statistics(normalized_values)
        
        # Generate insights
        insights = self._generate_normalization_insights(
            element_symbol, method, stats, normalized_stats
        )
        
        # Create results
        results = {
            "normalization_method": method,
            "original_stats": stats,
            "normalized_stats": normalized_stats,
            "normalized_values": normalized_values,
            "baseline_value": price_values[0] if method == "percent" else stats["mean"],
            "baseline_period": start_date.isoformat(),
        }
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=element_symbol,
            analysis_type=AnalysisType.NORMALIZATION,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=Severity.LOW,
            confidence=0.95,
            direction=Direction.STABLE,
            magnitude=0.0,
            insights=insights,
            recommendations=[],
        )
        
        return analysis
    
    def _generate_fluctuation_insights(
        self,
        element_symbol: str,
        price_change_pct: float,
        volatility: float,
        direction: Direction,
    ) -> str:
        """Generate insights for price fluctuation analysis."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        direction_map = {
            Direction.UP: "increased",
            Direction.DOWN: "decreased",
            Direction.STABLE: "remained stable",
            Direction.VOLATILE: "experienced high volatility",
        }
        
        direction_text = direction_map.get(direction, "changed")
        
        insights = []
        insights.append(f"{element_name} prices have {direction_text} by {abs(price_change_pct):.2f}% over the analysis period.")
        
        if volatility > 0:
            insights.append(f"Price volatility is {volatility:.2f}, indicating {'high' if volatility > 10 else 'moderate' if volatility > 5 else 'low'} price fluctuations.")
        
        if price_change_pct > 10:
            insights.append("This represents a significant price increase that may indicate supply constraints or increased demand.")
        elif price_change_pct < -10:
            insights.append("This represents a significant price decrease that may indicate oversupply or reduced demand.")
        
        return " ".join(insights)
    
    def _generate_fluctuation_recommendations(
        self,
        element_symbol: str,
        price_change_pct: float,
        volatility: float,
        direction: Direction,
    ) -> List[str]:
        """Generate recommendations for price fluctuation analysis."""
        recommendations = []
        
        if price_change_pct > 10:
            recommendations.append(f"Monitor {element_symbol} supply chain for potential disruptions.")
            recommendations.append(f"Consider securing long-term contracts for {element_symbol} to lock in current prices.")
        elif price_change_pct < -10:
            recommendations.append(f"Investigate {element_symbol} market for oversupply conditions.")
            recommendations.append(f"Consider purchasing {element_symbol} at current lower prices for future use.")
        
        if volatility > 10:
            recommendations.append(f"Implement hedging strategies for {element_symbol} due to high price volatility.")
            recommendations.append(f"Monitor {element_symbol} price movements closely for trading opportunities.")
        
        return recommendations
    
    def _generate_trend_insights(
        self,
        element_symbol: str,
        trend: Dict[str, Any],
        stats: Dict[str, float],
    ) -> str:
        """Generate insights for trend analysis."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        direction_map = {
            Direction.UP: "upward",
            Direction.DOWN: "downward",
            Direction.STABLE: "stable",
            Direction.VOLATILE: "volatile",
        }
        
        direction_text = direction_map.get(trend["direction"], "unknown")
        
        insights = []
        insights.append(f"{element_name} prices show a {direction_text} trend over the analysis period.")
        
        if trend["is_significant"]:
            insights.append(f"The trend is statistically significant with R-squared of {trend['r_squared']:.3f}.")
        else:
            insights.append(f"The trend has low statistical significance (R-squared: {trend['r_squared']:.3f}).")
        
        insights.append(f"The average price is {stats['mean']:.2f} with a range of {stats['min']:.2f} to {stats['max']:.2f}.")
        
        return " ".join(insights)
    
    def _generate_trend_recommendations(
        self,
        element_symbol: str,
        trend: Dict[str, Any],
        stats: Dict[str, float],
    ) -> List[str]:
        """Generate recommendations for trend analysis."""
        recommendations = []
        
        if trend["direction"] == Direction.UP and trend["is_significant"]:
            recommendations.append(f"Consider investing in {element_symbol} production capacity given the upward trend.")
            recommendations.append(f"Monitor {element_symbol} demand drivers to understand the trend.")
        elif trend["direction"] == Direction.DOWN and trend["is_significant"]:
            recommendations.append(f"Investigate causes of downward trend in {element_symbol} prices.")
            recommendations.append(f"Consider purchasing {element_symbol} at current lower prices.")
        
        return recommendations
    
    def _generate_anomaly_insights(
        self,
        element_symbol: str,
        anomalies: List[Dict[str, Any]],
        stats: Dict[str, float],
    ) -> str:
        """Generate insights for anomaly detection."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        insights = []
        insights.append(f"Detected {len(anomalies)} price anomalies for {element_name} in the analysis period.")
        
        if anomalies:
            max_z = max(a["z_score"] for a in anomalies)
            avg_z = sum(a["z_score"] for a in anomalies) / len(anomalies)
            insights.append(f"Anomalies have Z-scores ranging from {min(a['z_score'] for a in anomalies):.2f} to {max_z:.2f} (average: {avg_z:.2f}).")
            
            if max_z > self.config.anomaly_z_score * 2:
                insights.append("Some anomalies are extreme outliers that warrant immediate investigation.")
        
        return " ".join(insights)
    
    def _generate_anomaly_recommendations(
        self,
        element_symbol: str,
        anomalies: List[Dict[str, Any]],
        stats: Dict[str, float],
    ) -> List[str]:
        """Generate recommendations for anomaly detection."""
        recommendations = []
        
        if anomalies:
            recommendations.append(f"Investigate the causes of price anomalies for {element_symbol}.")
            recommendations.append(f"Review news and market events during anomaly periods for {element_symbol}.")
            
            if len(anomalies) > 1:
                recommendations.append(f"Analyze patterns in {element_symbol} price anomalies to identify common causes.")
        
        return recommendations
    
    def _generate_normalization_insights(
        self,
        element_symbol: str,
        method: str,
        original_stats: Dict[str, float],
        normalized_stats: Dict[str, float],
    ) -> str:
        """Generate insights for normalization analysis."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        method_map = {
            "zscore": "Z-score normalization",
            "minmax": "Min-Max normalization",
            "percent": "Percentage change normalization",
        }
        
        method_text = method_map.get(method, method)
        
        insights = []
        insights.append(f"Applied {method_text} to {element_name} price data for comparison.")
        insights.append(f"Original price range: {original_stats['min']:.2f} to {original_stats['max']:.2f}.")
        insights.append(f"Normalized range: {normalized_stats['min']:.3f} to {normalized_stats['max']:.3f}.")
        
        return " ".join(insights)


class PriceFluctuationAnalyzer(PriceAnalyzer):
    """Specialized analyzer for price fluctuation analysis."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "PriceFluctuationAnalyzer")
    
    def get_analysis_type(self) -> AnalysisType:
        return AnalysisType.PRICE_FLUCTUATION
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform price fluctuation analysis."""
        return super().analyze(element_symbol, **kwargs)


class TrendAnalyzer(PriceAnalyzer):
    """Specialized analyzer for trend analysis."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "TrendAnalyzer")
    
    def get_analysis_type(self) -> AnalysisType:
        return AnalysisType.TREND_ANALYSIS
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform trend analysis."""
        kwargs["analysis_type"] = AnalysisType.TREND_ANALYSIS
        return super().analyze(element_symbol, **kwargs)


class AnomalyAnalyzer(PriceAnalyzer):
    """Specialized analyzer for anomaly detection."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "AnomalyAnalyzer")
    
    def get_analysis_type(self) -> AnalysisType:
        return AnalysisType.ANOMALY_DETECTION
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform anomaly detection."""
        kwargs["analysis_type"] = AnalysisType.ANOMALY_DETECTION
        return super().analyze(element_symbol, **kwargs)


# Export everything
__all__ = [
    "PriceAnalyzer",
    "PriceFluctuationAnalyzer",
    "TrendAnalyzer",
    "AnomalyAnalyzer",
]
