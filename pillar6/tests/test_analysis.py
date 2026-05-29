"""
Pillar 6 Analysis Tests

Tests for analysis functionality.
"""

import pytest
import sys
import os
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.base_analyzer import (
    RareEarthAnalyzer,
    AnalyzerConfig,
    AnalyzerFactory,
)
from src.analysis.price_analyzer import PriceAnalyzer
from src.analysis.correlation_analyzer import CorrelationAnalyzer
from src.analysis.normalization_analyzer import NormalizationAnalyzer
from src.models.element import RareEarthElement, get_element_by_symbol
from src.models.price import RareEarthPrice
from src.models.production import RareEarthProduction
from src.models.analysis import (
    RareEarthAnalysis,
    PriceFluctuationAnalysis,
    TrendAnalysis,
    AnomalyDetection,
    NormalizationAnalysis,
)
from src.models.correlation import ArticleRareEarthLink


class TestAnalyzerConfig:
    """Tests for AnalyzerConfig class."""
    
    def test_default_config(self):
        """Test default analyzer configuration."""
        config = AnalyzerConfig()
        
        assert config.window_size == 30
        assert config.min_data_points == 5
        assert config.confidence_threshold == 0.7
        assert config.anomaly_threshold == 3.0
        assert config.trend_threshold == 0.1
        assert config.normalization_method == "zscore"
        assert config.log_level == "INFO"
    
    def test_custom_config(self):
        """Test custom analyzer configuration."""
        config = AnalyzerConfig(
            window_size=60,
            min_data_points=10,
            confidence_threshold=0.8,
            anomaly_threshold=2.5,
            trend_threshold=0.2,
            normalization_method="minmax",
            log_level="DEBUG",
        )
        
        assert config.window_size == 60
        assert config.min_data_points == 10
        assert config.confidence_threshold == 0.8
        assert config.anomaly_threshold == 2.5
        assert config.trend_threshold == 0.2
        assert config.normalization_method == "minmax"
    
    def test_config_to_dict(self):
        """Test converting config to dictionary."""
        config = AnalyzerConfig()
        config_dict = config.to_dict()
        
        assert "window_size" in config_dict
        assert "min_data_points" in config_dict
        assert "anomaly_threshold" in config_dict
        assert config_dict["window_size"] == 30
    
    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        config_data = {
            "window_size": 45,
            "min_data_points": 8,
            "anomaly_threshold": 2.8,
        }
        
        config = AnalyzerConfig.from_dict(config_data)
        
        assert config.window_size == 45
        assert config.min_data_points == 8
        assert config.anomaly_threshold == 2.8


class TestRareEarthAnalyzer:
    """Tests for RareEarthAnalyzer base class."""
    
    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        assert analyzer.config is not None
        assert analyzer.logger is not None
    
    def test_analyzer_with_custom_config(self):
        """Test analyzer with custom config."""
        config = AnalyzerConfig(
            window_size=60,
            anomaly_threshold=2.5,
        )
        analyzer = RareEarthAnalyzer(config)
        
        assert analyzer.config.window_size == 60
        assert analyzer.config.anomaly_threshold == 2.5
    
    def test_calculate_statistics(self):
        """Test calculating basic statistics."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        stats = analyzer.calculate_statistics(data)
        
        assert stats["count"] == 5
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["mean"] == 30.0
        assert stats["median"] == 30.0
        assert "std" in stats
    
    def test_calculate_trend(self):
        """Test calculating trend."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        # Upward trend
        data = [10, 20, 30, 40, 50]
        trend = analyzer.calculate_trend(data)
        
        assert trend["slope"] > 0
        assert trend["direction"] == "up"
        
        # Downward trend
        data = [50, 40, 30, 20, 10]
        trend = analyzer.calculate_trend(data)
        
        assert trend["slope"] < 0
        assert trend["direction"] == "down"
        
        # No trend
        data = [30, 30, 30, 30, 30]
        trend = analyzer.calculate_trend(data)
        
        assert trend["slope"] == 0
        assert trend["direction"] == "stable"
    
    def test_detect_anomalies(self):
        """Test detecting anomalies."""
        config = AnalyzerConfig(anomaly_threshold=2.0)
        analyzer = RareEarthAnalyzer(config)
        
        # Data with an anomaly
        data = [10, 11, 12, 13, 14, 100, 15, 16]
        anomalies = analyzer.detect_anomalies(data)
        
        assert len(anomalies) > 0
        assert 100 in anomalies["values"]
    
    def test_normalize_data(self):
        """Test normalizing data."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        
        # Z-score normalization
        normalized = analyzer.normalize_data(data, method="zscore")
        assert len(normalized) == len(data)
        
        # Min-max normalization
        normalized = analyzer.normalize_data(data, method="minmax")
        assert len(normalized) == len(data)
        assert min(normalized) >= 0
        assert max(normalized) <= 1
        
        # Percent change normalization
        normalized = analyzer.normalize_data(data, method="percent")
        assert len(normalized) == len(data)
    
    def test_calculate_correlation(self):
        """Test calculating correlation."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        # Positively correlated data
        data1 = [1, 2, 3, 4, 5]
        data2 = [2, 4, 6, 8, 10]
        correlation = analyzer.calculate_correlation(data1, data2)
        
        assert correlation > 0.9
        
        # Negatively correlated data
        data1 = [1, 2, 3, 4, 5]
        data2 = [10, 8, 6, 4, 2]
        correlation = analyzer.calculate_correlation(data1, data2)
        
        assert correlation < -0.9
    
    def test_calculate_moving_average(self):
        """Test calculating moving average."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        moving_avg = analyzer.calculate_moving_average(data, window=3)
        
        assert len(moving_avg) == len(data)
        assert moving_avg[0] is None or np.isnan(moving_avg[0])  # First value
        assert moving_avg[2] == 20.0  # Average of first 3 values
    
    def test_calculate_volatility(self):
        """Test calculating volatility."""
        config = AnalyzerConfig()
        analyzer = RareEarthAnalyzer(config)
        
        # Low volatility data
        data = [10, 10.1, 10.2, 10.1, 10.0]
        volatility = analyzer.calculate_volatility(data)
        assert volatility < 0.1
        
        # High volatility data
        data = [10, 50, 20, 80, 30]
        volatility = analyzer.calculate_volatility(data)
        assert volatility > 0.5


class TestPriceAnalyzer:
    """Tests for PriceAnalyzer class."""
    
    def test_price_analyzer_initialization(self):
        """Test price analyzer initialization."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        assert analyzer.config is not None
        assert analyzer.element_map is not None
    
    def test_analyze_price_fluctuation(self):
        """Test analyzing price fluctuation."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(30):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 100),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analysis = analyzer.analyze_price_fluctuation(prices)
        
        assert analysis is not None
        assert isinstance(analysis, PriceFluctuationAnalysis)
        assert analysis.analysis_type == "price_fluctuation"
        assert "change_pct" in analysis.results
        assert "volatility" in analysis.results
    
    def test_analyze_trend(self):
        """Test analyzing price trend."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        # Create test price data with upward trend
        prices = []
        for i in range(30):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 200),  # Upward trend
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analysis = analyzer.analyze_trend(prices)
        
        assert analysis is not None
        assert isinstance(analysis, TrendAnalysis)
        assert analysis.analysis_type == "trend"
        assert analysis.trend_direction == "up"
    
    def test_detect_anomalies(self):
        """Test detecting price anomalies."""
        config = AnalyzerConfig(anomaly_threshold=2.0)
        analyzer = PriceAnalyzer(config)
        
        # Create test price data with an anomaly
        prices = []
        for i in range(30):
            if i == 15:
                price_value = 100000.0  # Anomaly
            else:
                price_value = 50000.0 + (i * 100)
            
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=price_value,
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analysis = analyzer.detect_anomalies(prices)
        
        assert analysis is not None
        assert isinstance(analysis, AnomalyDetection)
        assert analysis.analysis_type == "anomaly_detection"
        assert analysis.is_anomaly is True
    
    def test_normalize_prices(self):
        """Test normalizing prices."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(10):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analysis = analyzer.normalize_prices(prices)
        
        assert analysis is not None
        assert isinstance(analysis, NormalizationAnalysis)
        assert analysis.analysis_type == "normalization"
        assert analysis.normalization_method == "zscore"
    
    def test_analyze_price_history(self):
        """Test analyzing complete price history."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(30):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 100),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analyses = analyzer.analyze_price_history(prices)
        
        assert len(analyses) > 0
        assert all(isinstance(a, RareEarthAnalysis) for a in analyses)
    
    def test_compare_elements(self):
        """Test comparing prices across elements."""
        config = AnalyzerConfig()
        analyzer = PriceAnalyzer(config)
        
        # Create test price data for multiple elements
        element1_prices = []
        element2_prices = []
        
        for i in range(10):
            price1 = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 100),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            element1_prices.append(price1)
            
            price2 = RareEarthPrice(
                element_id=2,
                market_id=1,
                price=60000.0 + (i * 150),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            element2_prices.append(price2)
        
        analysis = analyzer.compare_elements(
            {"Nd": element1_prices, "Dy": element2_prices}
        )
        
        assert analysis is not None
        assert isinstance(analysis, RareEarthAnalysis)


class TestCorrelationAnalyzer:
    """Tests for CorrelationAnalyzer class."""
    
    def test_correlation_analyzer_initialization(self):
        """Test correlation analyzer initialization."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        assert analyzer.config is not None
        assert analyzer.sentiment_analyzer is not None
    
    def test_analyze_sentiment(self):
        """Test analyzing sentiment of text."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        # Positive text
        sentiment = analyzer.analyze_sentiment("Price increased significantly due to high demand")
        assert sentiment["sentiment"] == "positive"
        assert sentiment["score"] > 0
        
        # Negative text
        sentiment = analyzer.analyze_sentiment("Price crashed due to oversupply")
        assert sentiment["sentiment"] == "negative"
        assert sentiment["score"] < 0
        
        # Neutral text
        sentiment = analyzer.analyze_sentiment("Price remained stable")
        assert sentiment["sentiment"] == "neutral"
    
    def test_calculate_correlation_score(self):
        """Test calculating correlation score."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(10):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        # Create a correlation with price data
        correlation = analyzer.calculate_correlation_score(
            article_text="Neodymium prices are rising",
            prices=prices,
            time_lag_days=2,
        )
        
        assert correlation is not None
        assert isinstance(correlation, ArticleRareEarthLink)
        assert correlation.correlation_score >= 0
    
    def test_analyze_correlation(self):
        """Test analyzing correlation between article and price data."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(10):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        correlation = analyzer.analyze_correlation(
            article_id=1,
            element_id=1,
            article_text="Neodymium prices are rising due to increased demand",
            article_date=date(2024, 1, 5),
            prices=prices,
        )
        
        assert correlation is not None
        assert isinstance(correlation, ArticleRareEarthLink)
        assert correlation.article_id == 1
        assert correlation.element_id == 1
        assert correlation.correlation_type == "price_news"
    
    def test_find_correlations(self):
        """Test finding correlations for multiple articles."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(10):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        # Create test articles
        articles = [
            {
                "id": 1,
                "text": "Neodymium prices are rising",
                "date": date(2024, 1, 5),
            },
            {
                "id": 2,
                "text": "Dysprosium production increased",
                "date": date(2024, 1, 6),
            },
        ]
        
        correlations = analyzer.find_correlations(
            articles=articles,
            element_id=1,
            prices=prices,
        )
        
        assert len(correlations) > 0
        assert all(isinstance(c, ArticleRareEarthLink) for c in correlations)
    
    def test_analyze_correlation_strength(self):
        """Test analyzing correlation strength."""
        config = AnalyzerConfig()
        analyzer = CorrelationAnalyzer(config)
        
        # Strong correlation
        strength = analyzer.analyze_correlation_strength(0.95)
        assert strength == "very_strong"
        
        # Moderate correlation
        strength = analyzer.analyze_correlation_strength(0.5)
        assert strength == "moderate"
        
        # Weak correlation
        strength = analyzer.analyze_correlation_strength(0.2)
        assert strength == "weak"


class TestNormalizationAnalyzer:
    """Tests for NormalizationAnalyzer class."""
    
    def test_normalization_analyzer_initialization(self):
        """Test normalization analyzer initialization."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        assert analyzer.config is not None
    
    def test_normalize_zscore(self):
        """Test z-score normalization."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        normalized = analyzer.normalize_zscore(data)
        
        assert len(normalized) == len(data)
        # Mean should be approximately 0
        assert abs(sum(normalized) / len(normalized)) < 0.001
    
    def test_normalize_minmax(self):
        """Test min-max normalization."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        normalized = analyzer.normalize_minmax(data)
        
        assert len(normalized) == len(data)
        assert min(normalized) >= 0
        assert max(normalized) <= 1
    
    def test_normalize_percent(self):
        """Test percent change normalization."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        normalized = analyzer.normalize_percent(data)
        
        assert len(normalized) == len(data)
        # First value should be 0 (no change from first value)
        assert normalized[0] == 0
    
    def test_analyze_normalization(self):
        """Test analyzing normalization of data."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        # Create test price data
        prices = []
        for i in range(10):
            price = RareEarthPrice(
                element_id=1,
                market_id=1,
                price=50000.0 + (i * 1000),
                currency="USD",
                date=date(2024, 1, 1) + timedelta(days=i),
            )
            prices.append(price)
        
        analysis = analyzer.analyze_normalization(prices)
        
        assert analysis is not None
        assert isinstance(analysis, NormalizationAnalysis)
        assert analysis.analysis_type == "normalization"
    
    def test_compare_normalization_methods(self):
        """Test comparing different normalization methods."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        data = [10, 20, 30, 40, 50]
        comparison = analyzer.compare_normalization_methods(data)
        
        assert comparison is not None
        assert "zscore" in comparison
        assert "minmax" in comparison
        assert "percent" in comparison
    
    def test_normalize_multiple_elements(self):
        """Test normalizing data for multiple elements."""
        config = AnalyzerConfig()
        analyzer = NormalizationAnalyzer(config)
        
        # Create test price data for multiple elements
        element_data = {
            "Nd": [50000.0, 51000.0, 52000.0],
            "Dy": [60000.0, 61000.0, 62000.0],
        }
        
        normalized = analyzer.normalize_multiple_elements(element_data)
        
        assert normalized is not None
        assert "Nd" in normalized
        assert "Dy" in normalized


class TestAnalyzerFactory:
    """Tests for AnalyzerFactory class."""
    
    def test_create_price_analyzer(self):
        """Test creating a price analyzer."""
        config = AnalyzerConfig()
        analyzer = AnalyzerFactory.create_analyzer("price", config)
        
        assert isinstance(analyzer, PriceAnalyzer)
    
    def test_create_correlation_analyzer(self):
        """Test creating a correlation analyzer."""
        config = AnalyzerConfig()
        analyzer = AnalyzerFactory.create_analyzer("correlation", config)
        
        assert isinstance(analyzer, CorrelationAnalyzer)
    
    def test_create_normalization_analyzer(self):
        """Test creating a normalization analyzer."""
        config = AnalyzerConfig()
        analyzer = AnalyzerFactory.create_analyzer("normalization", config)
        
        assert isinstance(analyzer, NormalizationAnalyzer)
    
    def test_create_unknown_analyzer(self):
        """Test creating an unknown analyzer type."""
        config = AnalyzerConfig()
        
        with pytest.raises(ValueError):
            AnalyzerFactory.create_analyzer("unknown", config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
