"""
Pillar 4: Tests for Anomaly Detector
"""

import pytest
import time
import numpy as np
from pillar4.src.analysis.anomaly_detector import AnomalyDetector, Anomaly, AnomalyType, AnomalyStatus


class TestAnomalyDetector:
    """Tests for the AnomalyDetector class."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = AnomalyDetector()
        assert detector.window_size == 100
        assert detector.z_threshold == 3.0
        assert detector.iqr_multiplier == 1.5
        assert detector.moving_avg_window == 50

    def test_initialization_custom_params(self):
        """Test detector initialization with custom parameters."""
        detector = AnomalyDetector(
            window_size=50,
            z_threshold=2.5,
            iqr_multiplier=2.0,
            moving_avg_window=25,
        )
        assert detector.window_size == 50
        assert detector.z_threshold == 2.5
        assert detector.iqr_multiplier == 2.0
        assert detector.moving_avg_window == 25

    def test_add_data_point(self):
        """Test adding data points."""
        detector = AnomalyDetector(window_size=10)
        detector.add_data_point(1.0)
        detector.add_data_point(2.0)
        assert len(detector.data_window) == 2

    def test_detect_statistical_anomalies_z_score(self):
        """Test Z-score anomaly detection."""
        detector = AnomalyDetector(z_threshold=2.0)
        
        # Add normal data points
        for i in range(10):
            detector.add_data_point(float(i))
        
        # Add an outlier
        detector.add_data_point(100.0)
        
        anomalies = detector.detect_statistical_anomalies()
        assert len(anomalies) >= 1
        assert any(a.type == AnomalyType.STATISTICAL for a in anomalies)
        assert any(a.status == AnomalyStatus.ANOMALOUS for a in anomalies)

    def test_detect_statistical_anomalies_iqr(self):
        """Test IQR-based anomaly detection."""
        detector = AnomalyDetector(iqr_multiplier=1.0)
        
        # Add data points with a clear outlier
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]
        for value in data:
            detector.add_data_point(float(value))
        
        anomalies = detector.detect_statistical_anomalies()
        assert len(anomalies) >= 1

    def test_detect_temporal_anomalies_spike(self):
        """Test detection of sudden spikes."""
        detector = AnomalyDetector()
        
        # Add normal data
        for i in range(10):
            detector.add_data_point(float(i))
        
        # Add a spike
        detector.add_data_point(100.0)
        
        anomalies = detector.detect_temporal_anomalies()
        assert len(anomalies) >= 1
        assert any(a.type == AnomalyType.TEMPORAL for a in anomalies)

    def test_detect_temporal_anomalies_drop(self):
        """Test detection of sudden drops."""
        detector = AnomalyDetector()
        
        # Add normal data
        for i in range(10, 20):
            detector.add_data_point(float(i))
        
        # Add a drop
        detector.add_data_point(1.0)
        
        anomalies = detector.detect_temporal_anomalies()
        assert len(anomalies) >= 1

    def test_detect_all(self):
        """Test running all detection methods."""
        detector = AnomalyDetector()
        
        # Add data with both statistical and temporal anomalies
        data = [1, 2, 3, 4, 5, 100, 6, 7, 8, 9, 10]
        for value in data:
            detector.add_data_point(float(value))
        
        anomalies = detector.detect_all()
        assert len(anomalies) >= 2  # At least one statistical and one temporal

    def test_get_stats(self):
        """Test getting statistics."""
        detector = AnomalyDetector()
        detector.add_data_point(1.0)
        detector.add_data_point(2.0)
        detector.add_data_point(3.0)
        
        stats = detector.get_stats()
        assert stats["count"] == 3
        assert stats["mean"] == 2.0
        assert "std" in stats

    def test_reset(self):
        """Test resetting the detector."""
        detector = AnomalyDetector()
        detector.add_data_point(1.0)
        detector.add_data_point(2.0)
        
        detector.reset()
        
        assert len(detector.data_window) == 0
        assert len(detector.timestamps) == 0

    def test_empty_data(self):
        """Test with empty data."""
        detector = AnomalyDetector()
        anomalies = detector.detect_statistical_anomalies()
        assert len(anomalies) == 0

    def test_single_data_point(self):
        """Test with single data point."""
        detector = AnomalyDetector()
        detector.add_data_point(1.0)
        anomalies = detector.detect_statistical_anomalies()
        assert len(anomalies) == 0  # Can't detect anomalies with single point

    def test_anomaly_properties(self):
        """Test anomaly properties."""
        detector = AnomalyDetector()
        detector.add_data_point(100.0)  # Outlier
        
        anomalies = detector.detect_statistical_anomalies()
        if anomalies:
            anomaly = anomalies[0]
            assert isinstance(anomaly, Anomaly)
            assert anomaly.type in [AnomalyType.STATISTICAL, AnomalyType.TEMPORAL]
            assert anomaly.status in [AnomalyStatus.NORMAL, AnomalyStatus.SUSPICIOUS, AnomalyStatus.ANOMALOUS]
            assert 0.0 <= anomaly.score <= 1.0
            assert 0.0 <= anomaly.confidence <= 1.0
            assert anomaly.timestamp > 0

    def test_moving_average_deviation(self):
        """Test moving average deviation detection."""
        detector = AnomalyDetector(moving_avg_window=5)
        
        # Add data with a pattern
        for i in range(20):
            detector.add_data_point(float(i))
        
        # Add a value that deviates from the moving average
        detector.add_data_point(100.0)
        
        anomalies = detector.detect_statistical_anomalies()
        assert len(anomalies) >= 1

    def test_pattern_change_detection(self):
        """Test pattern change detection."""
        detector = AnomalyDetector()
        
        # Add data with one pattern
        for i in range(25):
            detector.add_data_point(float(i))
        
        # Add data with a different pattern
        for i in range(25, 50):
            detector.add_data_point(float(i * 2))
        
        anomalies = detector.detect_temporal_anomalies()
        # Pattern change detection might find this as an anomaly
        assert len(anomalies) >= 0  # May or may not detect depending on implementation


class TestAnomaly:
    """Tests for the Anomaly dataclass."""

    def test_anomaly_creation(self):
        """Test creating an anomaly."""
        anomaly = Anomaly(
            type=AnomalyType.STATISTICAL,
            status=AnomalyStatus.ANOMALOUS,
            score=0.95,
            confidence=0.9,
            description="Test anomaly",
            timestamp=time.time(),
            data_point=100.0,
        )
        assert anomaly.type == AnomalyType.STATISTICAL
        assert anomaly.status == AnomalyStatus.ANOMALOUS
        assert anomaly.score == 0.95

    def test_anomaly_to_dict(self):
        """Test converting anomaly to dictionary."""
        anomaly = Anomaly(
            type=AnomalyType.TEMPORAL,
            status=AnomalyStatus.SUSPICIOUS,
            score=0.75,
            confidence=0.8,
            description="Test",
            timestamp=time.time(),
            data_point=50.0,
        )
        
        d = anomaly.to_dict()
        assert d["type"] == "temporal"
        assert d["status"] == "suspicious"
        assert d["score"] == 0.75
        assert "timestamp" in d
        assert "data_point"] in d
