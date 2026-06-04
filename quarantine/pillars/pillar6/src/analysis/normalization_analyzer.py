"""
Pillar 6 Normalization Analyzer

Normalizes rare earth data for comparison and visualization.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import logging
import numpy as np
import pandas as pd

from .base_analyzer import RareEarthAnalyzer, AnalyzerConfig, DEFAULT_ANALYZER_CONFIG
from ..models import (
    RareEarthPrice,
    RareEarthProduction,
    RareEarthInventory,
    RareEarthAnalysis,
    NormalizationAnalysis,
    AnalysisType,
    Severity,
    Direction,
)
from ..storage import storage

# Configure logging
logger = logging.getLogger(__name__)


class NormalizationAnalyzer(RareEarthAnalyzer):
    """
    Analyzer for normalizing rare earth data.
    
    Provides various normalization methods for comparing
    rare earth elements across different scales and units.
    """
    
    # Normalization methods
    NORMALIZATION_METHODS = {
        "zscore": {
            "name": "Z-Score Normalization",
            "description": "Standardizes data to have mean=0 and std=1",
            "use_case": "Statistical analysis, outlier detection",
        },
        "minmax": {
            "name": "Min-Max Normalization",
            "description": "Scales data to a fixed range (typically 0-1)",
            "use_case": "Machine learning, neural networks",
        },
        "percent": {
            "name": "Percentage Change",
            "description": "Normalizes to percentage change from baseline",
            "use_case": "Financial analysis, time series comparison",
        },
        "decimal": {
            "name": "Decimal Scaling",
            "description": "Scales data by dividing by 10^n",
            "use_case": "Data with large values",
        },
        "log": {
            "name": "Logarithmic Scaling",
            "description": "Applies log transformation to compress scale",
            "use_case": "Data with exponential growth",
        },
        "rank": {
            "name": "Rank Normalization",
            "description": "Replaces values with their rank",
            "use_case": "Non-parametric analysis",
        },
    }
    
    def __init__(
        self,
        config: Optional[AnalyzerConfig] = None,
        name: str = "NormalizationAnalyzer",
    ):
        """
        Initialize the normalization analyzer.
        
        Args:
            config: Analyzer configuration
            name: Name of the analyzer
        """
        super().__init__(config, name)
    
    def get_analysis_type(self) -> AnalysisType:
        """Get the type of analysis performed."""
        return AnalysisType.NORMALIZATION
    
    def analyze(
        self,
        element_symbol: str,
        **kwargs
    ) -> Optional[RareEarthAnalysis]:
        """
        Normalize rare earth data for comparison.
        
        Args:
            element_symbol: Element symbol to normalize
            **kwargs: Additional parameters
                - method: Normalization method (default: 'zscore')
                - data_type: Type of data to normalize ('price', 'production', 'inventory')
                - days: Number of days of history (for time series)
                - baseline_date: Baseline date for percentage normalization
                - compare_elements: List of elements to compare
                
        Returns:
            Normalization analysis results or None on failure
        """
        method = kwargs.get("method", "zscore")
        data_type = kwargs.get("data_type", "price")
        days = kwargs.get("days", 30)
        baseline_date = kwargs.get("baseline_date", None)
        compare_elements = kwargs.get("compare_elements", None)
        
        # Get data based on type
        if data_type == "price":
            data = self.get_price_data(element_symbol, days=days)
        elif data_type == "production":
            data = self.get_production_data(element_symbol)
        elif data_type == "inventory":
            data = self.get_inventory_data(element_symbol)
        else:
            data = self.get_price_data(element_symbol, days=days)
        
        if not self._check_min_data(data):
            logger.warning(f"Insufficient data for normalization: {element_symbol}")
            return None
        
        # Determine dates
        if data_type == "price":
            start_date = data[-1].date if data else date.today()
            end_date = data[0].date if data else date.today()
        else:
            start_date = date(min(d.year for d in data)) if data else date.today()
            end_date = date(max(d.year for d in data)) if data else date.today()
        
        # Perform normalization
        if compare_elements:
            # Compare multiple elements
            return self.analyze_multi_element_normalization(
                compare_elements, method, data_type, start_date, end_date
            )
        else:
            # Normalize single element
            return self.analyze_single_element_normalization(
                element_symbol, data, method, data_type, start_date, end_date, baseline_date
            )
    
    def analyze_single_element_normalization(
        self,
        element_symbol: str,
        data: List[Any],
        method: str,
        data_type: str,
        start_date: date,
        end_date: date,
        baseline_date: Optional[date] = None,
    ) -> Optional[RareEarthAnalysis]:
        """
        Normalize data for a single element.
        
        Args:
            element_symbol: Element symbol
            data: List of data points
            method: Normalization method
            data_type: Type of data
            start_date: Start date
            end_date: End date
            baseline_date: Optional baseline date
            
        Returns:
            Normalization analysis results
        """
        # Extract values based on data type
        if data_type == "price":
            values = [d.price_per_kg for d in data]
            value_field = "price_per_kg"
        elif data_type == "production":
            values = [d.tonnes for d in data]
            value_field = "tonnes"
        elif data_type == "inventory":
            values = [d.tonnes for d in data]
            value_field = "tonnes"
        else:
            values = [d.price_per_kg for d in data]
            value_field = "price_per_kg"
        
        # Normalize values
        normalized_values = self._normalize_values(values, method)
        
        # Calculate statistics
        original_stats = self._calculate_statistics(values)
        normalized_stats = self._calculate_statistics(normalized_values)
        
        # Determine baseline
        if baseline_date:
            baseline_value = self._get_value_at_date(data, baseline_date, value_field)
        else:
            baseline_value = values[0] if values else 0
        
        baseline_period = baseline_date.isoformat() if baseline_date else start_date.isoformat()
        
        # Generate insights
        insights = self._generate_normalization_insights(
            element_symbol, method, data_type, original_stats, normalized_stats, baseline_value
        )
        
        # Create results
        results = {
            "normalization_method": method,
            "data_type": data_type,
            "original_values": values,
            "normalized_values": normalized_values,
            "original_stats": original_stats,
            "normalized_stats": normalized_stats,
            "baseline_value": baseline_value,
            "baseline_period": baseline_period,
            "data_points": len(values),
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
    
    def analyze_multi_element_normalization(
        self,
        element_symbols: List[str],
        method: str,
        data_type: str,
        start_date: date,
        end_date: date,
    ) -> Optional[RareEarthAnalysis]:
        """
        Normalize and compare multiple elements.
        
        Args:
            element_symbols: List of element symbols
            method: Normalization method
            data_type: Type of data
            start_date: Start date
            end_date: End date
            
        Returns:
            Normalization analysis results
        """
        # Get data for all elements
        all_data = {}
        for symbol in element_symbols:
            if data_type == "price":
                data = self.get_price_data(symbol, days=(end_date - start_date).days)
            elif data_type == "production":
                data = self.get_production_data(symbol)
            elif data_type == "inventory":
                data = self.get_inventory_data(symbol)
            else:
                data = self.get_price_data(symbol, days=(end_date - start_date).days)
            
            if data:
                all_data[symbol] = data
        
        if not all_data:
            return None
        
        # Extract and normalize values for each element
        element_values = {}
        normalized_element_values = {}
        
        for symbol, data in all_data.items():
            if data_type == "price":
                values = [d.price_per_kg for d in data]
            elif data_type == "production":
                values = [d.tonnes for d in data]
            elif data_type == "inventory":
                values = [d.tonnes for d in data]
            else:
                values = [d.price_per_kg for d in data]
            
            element_values[symbol] = values
            normalized_element_values[symbol] = self._normalize_values(values, method)
        
        # Calculate comparative statistics
        comparative_stats = self._calculate_comparative_stats(
            element_values, normalized_element_values, method
        )
        
        # Generate insights
        insights = self._generate_comparative_insights(
            element_symbols, method, data_type, comparative_stats
        )
        
        # Create results
        results = {
            "normalization_method": method,
            "data_type": data_type,
            "elements": element_symbols,
            "element_values": element_values,
            "normalized_element_values": normalized_element_values,
            "comparative_stats": comparative_stats,
        }
        
        # Use first element for analysis metadata
        first_symbol = element_symbols[0]
        
        # Create analysis
        analysis = self._create_analysis(
            element_symbol=first_symbol,
            analysis_type=AnalysisType.NORMALIZATION,
            start_date=start_date,
            end_date=end_date,
            results=results,
            severity=Severity.LOW,
            confidence=0.9,
            direction=Direction.STABLE,
            magnitude=0.0,
            insights=insights,
            recommendations=[],
            metadata={"comparison_elements": element_symbols[1:]},
        )
        
        return analysis
    
    def _get_value_at_date(
        self,
        data: List[Any],
        target_date: date,
        value_field: str,
    ) -> float:
        """Get the value at or closest to a target date."""
        if not data:
            return 0.0
        
        # Find closest date
        closest_data = min(
            data,
            key=lambda d: abs((getattr(d, "date", getattr(d, "year", 0)) - target_date).days)
        )
        
        return getattr(closest_data, value_field, 0.0)
    
    def _calculate_comparative_stats(
        self,
        element_values: Dict[str, List[float]],
        normalized_values: Dict[str, List[float]],
        method: str,
    ) -> Dict[str, Any]:
        """Calculate statistics for comparing multiple elements."""
        stats = {
            "elements": list(element_values.keys()),
            "original_means": {},
            "normalized_means": {},
            "original_stds": {},
            "normalized_stds": {},
            "value_ranges": {},
            "normalized_ranges": {},
            "correlation_matrix": None,
        }
        
        # Calculate statistics for each element
        for symbol, values in element_values.items():
            if values:
                stats["original_means"][symbol] = float(np.mean(values))
                stats["original_stds"][symbol] = float(np.std(values))
                stats["value_ranges"][symbol] = (float(min(values)), float(max(values)))
            
            if symbol in normalized_values and normalized_values[symbol]:
                norm_vals = normalized_values[symbol]
                stats["normalized_means"][symbol] = float(np.mean(norm_vals))
                stats["normalized_stds"][symbol] = float(np.std(norm_vals))
                stats["normalized_ranges"][symbol] = (float(min(norm_vals)), float(max(norm_vals)))
        
        # Calculate correlation matrix for normalized values
        if len(element_values) > 1:
            # Create DataFrame for correlation
            df = pd.DataFrame(normalized_values)
            corr_matrix = df.corr().to_dict()
            stats["correlation_matrix"] = corr_matrix
        
        return stats
    
    def _generate_normalization_insights(
        self,
        element_symbol: str,
        method: str,
        data_type: str,
        original_stats: Dict[str, float],
        normalized_stats: Dict[str, float],
        baseline_value: float,
    ) -> str:
        """Generate insights for normalization analysis."""
        element = storage.get_element_by_symbol(element_symbol)
        element_name = element.name if element else element_symbol
        
        method_info = self.NORMALIZATION_METHODS.get(method, {})
        method_name = method_info.get("name", method)
        
        insights = []
        insights.append(f"Applied {method_name} to {element_name} {data_type} data.")
        insights.append(f"Original range: {original_stats['min']:.2f} to {original_stats['max']:.2f}.")
        insights.append(f"Normalized range: {normalized_stats['min']:.3f} to {normalized_stats['max']:.3f}.")
        insights.append(f"Baseline value: {baseline_value:.2f}.")
        
        if method == "zscore":
            insights.append(f"Mean: {normalized_stats['mean']:.3f}, Std Dev: {normalized_stats['std']:.3f}.")
        elif method == "minmax":
            insights.append("Values scaled to 0-1 range.")
        elif method == "percent":
            insights.append("Values represent percentage change from baseline.")
        
        return " ".join(insights)
    
    def _generate_comparative_insights(
        self,
        element_symbols: List[str],
        method: str,
        data_type: str,
        comparative_stats: Dict[str, Any],
    ) -> str:
        """Generate insights for comparative normalization analysis."""
        method_info = self.NORMALIZATION_METHODS.get(method, {})
        method_name = method_info.get("name", method)
        
        insights = []
        insights.append(f"Compared {len(element_symbols)} rare earth elements using {method_name} normalization.")
        
        # Add original value comparison
        means = comparative_stats.get("original_means", {})
        if means:
            sorted_elements = sorted(means.items(), key=lambda x: x[1], reverse=True)
            insights.append(f"Original value ranking: {', '.join([f'{e[0]} ({e[1]:.2f})' for e in sorted_elements[:3]])}.")
        
        # Add normalized value comparison
        norm_means = comparative_stats.get("normalized_means", {})
        if norm_means:
            sorted_norm = sorted(norm_means.items(), key=lambda x: x[1], reverse=True)
            insights.append(f"Normalized value ranking: {', '.join([f'{e[0]} ({e[1]:.3f})' for e in sorted_norm[:3]])}.")
        
        # Add correlation insights
        corr_matrix = comparative_stats.get("correlation_matrix", {})
        if corr_matrix:
            high_corr = []
            for symbol1, correlations in corr_matrix.items():
                for symbol2, corr in correlations.items():
                    if symbol1 != symbol2 and corr > 0.7:
                        high_corr.append(f"{symbol1}-{symbol2} ({corr:.2f})")
            
            if high_corr:
                insights.append(f"High correlations found: {', '.join(high_corr[:3])}.")
        
        return " ".join(insights)
    
    def normalize_for_comparison(
        self,
        element_symbols: List[str],
        data_type: str = "price",
        method: str = "zscore",
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        Normalize data for multiple elements for comparison.
        
        Args:
            element_symbols: List of element symbols
            data_type: Type of data to normalize
            method: Normalization method
            days: Number of days of history
            
        Returns:
            Dictionary with normalized data for all elements
        """
        normalized_data = {}
        
        for symbol in element_symbols:
            if data_type == "price":
                data = self.get_price_data(symbol, days=days)
            elif data_type == "production":
                data = self.get_production_data(symbol)
            elif data_type == "inventory":
                data = self.get_inventory_data(symbol)
            else:
                data = self.get_price_data(symbol, days=days)
            
            if data:
                if data_type == "price":
                    values = [d.price_per_kg for d in data]
                elif data_type == "production":
                    values = [d.tonnes for d in data]
                elif data_type == "inventory":
                    values = [d.tonnes for d in data]
                else:
                    values = [d.price_per_kg for d in data]
                
                normalized_values = self._normalize_values(values, method)
                normalized_data[symbol] = {
                    "original": values,
                    "normalized": normalized_values,
                    "dates": [d.date for d in data] if hasattr(data[0], "date") else None,
                }
        
        return normalized_data


class ZScoreNormalizer(NormalizationAnalyzer):
    """Specialized analyzer for Z-score normalization."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "ZScoreNormalizer")
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform Z-score normalization."""
        kwargs["method"] = "zscore"
        return super().analyze(element_symbol, **kwargs)


class MinMaxNormalizer(NormalizationAnalyzer):
    """Specialized analyzer for Min-Max normalization."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "MinMaxNormalizer")
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform Min-Max normalization."""
        kwargs["method"] = "minmax"
        return super().analyze(element_symbol, **kwargs)


class PercentNormalizer(NormalizationAnalyzer):
    """Specialized analyzer for percentage normalization."""
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        super().__init__(config, "PercentNormalizer")
    
    def analyze(self, element_symbol: str, **kwargs) -> Optional[RareEarthAnalysis]:
        """Perform percentage normalization."""
        kwargs["method"] = "percent"
        return super().analyze(element_symbol, **kwargs)


# Export everything
__all__ = [
    "NormalizationAnalyzer",
    "ZScoreNormalizer",
    "MinMaxNormalizer",
    "PercentNormalizer",
]
