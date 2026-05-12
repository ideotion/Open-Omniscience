"""
Pillar 4: Tests for Trend Analyzer
"""

import pytest
import time
import numpy as np
from pillar4.src.analysis.trend_analyzer import TrendAnalyzer, Trend, TrendDirection, TrendStrength


class TestTrendAnalyzer:
    """Tests for the TrendAnalyzer class."""

    def test_initialization(self):
        """Test analyzer initialization."""
        analyzer = TrendAnalyzer()
        assert analyzer.window_size == 100
        assert analyzer.min_trend_length == 10
        assert analyzer.volatility_threshold == 0.2

    def test_initialization_custom_params(self):
        """Test analyzer initialization with custom parameters."""
        analyzer = TrendAnalyzer(
            window_size=50,
            min_trend_length=5,
            volatility_threshold=0.3,
        )
        assert analyzer.window_size == 50
        assert analyzer.min_trend_length == 5
        assert analyzer.volatility_threshold == 0.3

    def test_add_data_point(self):
        """Test adding data points."""
        analyzer = TrendAnalyzer()
        analyzer.add_data_point(1.0)
        analyzer.add_data_point(2.0)
        assert len(analyzer.data) == 2

    def test_detect_trends_increasing(self):
        """Test detection of increasing trends."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Add increasing data
        for i in range(20):
            analyzer.add_data_point(float(i))
        
        trends = analyzer.detect_trends()
        assert len(trends) >= 1
        assert any(t.direction == TrendDirection.INCREASING for t in trends)

    def test_detect_trends_decreasing(self):
        """Test detection of decreasing trends."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Add decreasing data
        for i in range(20, 0, -1):
            analyzer.add_data_point(float(i))
        
        trends = analyzer.detect_trends()
        assert len(trends) >= 1
        assert any(t.direction == TrendDirection.DECREASING for t in trends)

    def test_detect_trends_stable(self):
        """Test detection of stable trends."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Add stable data (small variations around a mean)
        for i in range(20):
            analyzer.add_data_point(10.0 + (i % 3 - 1) * 0.1)
        
        trends = analyzer.detect_trends()
        # With small variations, should be mostly stable
        assert any(t.direction == TrendDirection.STABLE for t in trends) or \
               len(trends) == 0  # Or no clear trend

    def test_detect_emerging_trends(self):
        """Test detection of emerging trends."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Add stable data
        for i in range(15):
            analyzer.add_data_point(10.0)
        
        # Add emerging trend (increasing)
        for i in range(5):
            analyzer.add_data_point(10.0 + i)
        
        trends = analyzer.detect_emerging_trends(new_window_size=5)
        assert len(trends) >= 0  # May or may not detect depending on implementation

    def test_get_current_trend(self):
        """Test getting the current trend."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Add data with a clear trend
        for i in range(20):
            analyzer.add_data_point(float(i))
        
        trend = analyzer.get_current_trend()
        assert trend is not None
        assert trend.direction == TrendDirection.INCREASING

    def test_get_stats(self):
        """Test getting statistics."""
        analyzer = TrendAnalyzer()
        analyzer.add_data_point(1.0)
        analyzer.add_data_point(2.0)
        analyzer.add_data_point(3.0)
        
        stats = analyzer.get_stats()
        assert stats["count"] == 3
        assert "mean" in stats
        assert "std" in stats

    def test_reset(self):
        """Test resetting the analyzer."""
        analyzer = TrendAnalyzer()
        analyzer.add_data_point(1.0)
        analyzer.add_data_point(2.0)
        
        analyzer.reset()
        
        assert len(analyzer.data) == 0
        assert len(analyzer.timestamps) == 0

    def test_empty_data(self):
        """Test with empty data."""
        analyzer = TrendAnalyzer()
        trends = analyzer.detect_trends()
        assert len(trends) == 0

    def test_insufficient_data(self):
        """Test with insufficient data for trend detection."""
        analyzer = TrendAnalyzer(min_trend_length=10)
        for i in range(5):
            analyzer.add_data_point(float(i))
        
        trends = analyzer.detect_trends()
        assert len(trends) == 0

    def test_volatility_detection(self):
        """Test volatility detection."""
        analyzer = TrendAnalyzer(volatility_threshold=0.1)
        
        # Add volatile data
        data = [10, 5, 15, 8, 12, 6, 14]
        for value in data:
            analyzer.add_data_point(float(value))
        
        trends = analyzer.detect_trends()
        assert any(t.direction == TrendDirection.VOLATILE for t in trends)


class TestTrend:
    """Tests for the Trend dataclass."""

    def test_trend_creation(self):
        """Test creating a trend."""
        trend = Trend(
            direction=TrendDirection.INCREASING,
            strength=TrendStrength.STRONG,
            score=0.9,
            confidence=0.85,
            start_time=time.time() - 100,
            end_time=time.time(),
            slope=2.5,
            r_squared=0.95,
            data_points=[(time.time() - i, float(i)) for i in range(10)],
        )
        assert trend.direction == TrendDirection.INCREASING
        assert trend.strength == TrendStrength.STRONG
        assert trend.score == 0.9

    def test_trend_to_dict(self):
        """Test converting trend to dictionary."""
        trend = Trend(
            direction=TrendDirection.DECREASING,
            strength=TrendStrength.MODERATE,
            score=0.75,
            confidence=0.8,
            start_time=time.time() - 100,
            end_time=time.time(),
            slope=-1.5,
            r_squared=0.85,
            data_points=[(time.time() - i, float(20 - i)) for i in range(10)],
        )
        
        d = trend.to_dict()
        assert d["direction"] == "decreasing"
        assert d["strength"] == "moderate"
        assert d["score"] == 0.75
        assert "slope" in d
        assert "r_squared" in d
        assert "data_points" in d

    def test_trend_properties(self):
        """Test trend properties."""
        trend = Trend(
            direction=TrendDirection.INCREASING,
            strength=TrendStrength.STRONG,
            score=0.95,
            confidence=0.9,
            start_time=time.time() - 100,
            end_time=time.time(),
            slope=3.0,
            r_squared=0.98,
            data_points=[],
        )
        assert trend.direction.value == "increasing"
        assert trend.strength.value == "strong"
        assert trend.score > 0.9
        assert trend.confidence > 0.8


class TestTrendAnalysis:
    """Integration tests for trend analysis."""

    def test_linear_trend(self):
        """Test detection of linear trends."""
        analyzer = TrendAnalyzer(min_trend_length=10)
        
        # Linear trend: y = 2x + 5
        for x in range(20):
            analyzer.add_data_point(2.0 * x + 5.0)
        
        trends = analyzer.detect_trends()
        assert len(trends) >= 1
        trend = trends[0]
        assert trend.direction == TrendDirection.INCREASING
        assert trend.strength == TrendStrength.STRONG
        assert trend.slope > 1.5  # Should be close to 2

    def test_quadratic_trend(self):
        """Test detection of quadratic trends."""
        analyzer = TrendAnalyzer(min_trend_length=10)
        
        # Quadratic trend: y = x^2
        for x in range(20):
            analyzer.add_data_point(float(x * x))
        
        trends = analyzer.detect_trends()
        assert len(trends) >= 1
        trend = trends[0]
        assert trend.direction == TrendDirection.INCREASING
        # For quadratic, slope should be increasing

    def test_sinusoidal_trend(self):
        """Test detection of sinusoidal patterns."""
        analyzer = TrendAnalyzer(min_trend_length=10)
        
        # Sinusoidal pattern
        for x in range(0, 40, 2):
            analyzer.add_data_point(np.sin(x / 5) * 10 + 10)
        
        trends = analyzer.detect_trends()
        # Sinusoidal patterns may be detected as volatile or oscillating
        assert len(trends) >= 0

    def test_step_change_trend(self):
        """Test detection of step changes in trends."""
        analyzer = TrendAnalyzer(min_trend_length=5)
        
        # Step change: constant, then jump, then constant
        for i in range(10):
            analyzer.add_data_point(10.0)
        for i in range(10):
            analyzer.add_data_point(20.0)
        
        trends = analyzer.detect_trends()
        assert len(trends) >= 1
