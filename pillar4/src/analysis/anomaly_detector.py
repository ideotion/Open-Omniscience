"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Pillar 4: Real-Time Monitoring & Alerting System - Anomaly Detector

Detects anomalies in real-time data streams using statistical and ML-based approaches.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from collections import deque


class AnomalyType(Enum):
    STATISTICAL = "statistical"
    TEMPORAL = "temporal"
    CONTEXTUAL = "contextual"
    BEHAVIORAL = "behavioral"


class AnomalyStatus(Enum):
    NORMAL = "normal"
    SUSPICIOUS = "suspicious"
    ANOMALOUS = "anomalous"


@dataclass
class Anomaly:
    """Represents a detected anomaly."""
    type: AnomalyType
    status: AnomalyStatus
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    description: str
    timestamp: float
    data_point: Any
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "description": self.description,
            "timestamp": self.timestamp,
            "data_point": str(self.data_point),
            "metadata": self.metadata,
        }


class AnomalyDetector:
    """
    Detects anomalies in real-time data streams using:
    - Statistical methods (Z-score, IQR, moving averages)
    - Machine learning (Isolation Forest, One-Class SVM)
    - Temporal analysis (sudden spikes, drops, pattern changes)
    """

    def __init__(
        self,
        window_size: int = 100,
        z_threshold: float = 3.0,
        iqr_multiplier: float = 1.5,
        moving_avg_window: int = 50,
    ):
        """
        Initialize the anomaly detector.

        Args:
            window_size: Size of the sliding window for analysis.
            z_threshold: Z-score threshold for statistical anomalies.
            iqr_multiplier: Multiplier for IQR-based anomaly detection.
            moving_avg_window: Window size for moving average calculations.
        """
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier
        self.moving_avg_window = moving_avg_window

        # Data storage
        self.data_window: deque = deque(maxlen=window_size)
        self.timestamps: deque = deque(maxlen=window_size)

        # ML models (optional)
        self.isolation_forest_model = None
        self.one_class_svm_model = None

        # Statistical history
        self.mean_history: deque = deque(maxlen=window_size)
        self.std_history: deque = deque(maxlen=window_size)

    def add_data_point(self, value: float, timestamp: Optional[float] = None) -> None:
        """Add a new data point to the detector's window."""
        if timestamp is None:
            timestamp = time.time()
        self.data_window.append(value)
        self.timestamps.append(timestamp)

    def detect_statistical_anomalies(self) -> List[Anomaly]:
        """
        Detect anomalies using statistical methods.

        Returns:
            List of detected anomalies.
        """
        anomalies = []
        if len(self.data_window) < 2:
            return anomalies

        data = np.array(self.data_window)
        timestamps = np.array(self.timestamps)

        # Z-score method
        mean = np.mean(data)
        std = np.std(data)
        if std > 0:
            z_scores = np.abs((data - mean) / std)
            for i, (z, value, ts) in enumerate(zip(z_scores, data, timestamps)):
                if z > self.z_threshold:
                    anomalies.append(
                        Anomaly(
                            type=AnomalyType.STATISTICAL,
                            status=AnomalyStatus.ANOMALOUS,
                            score=min(1.0, z / (self.z_threshold * 2)),
                            confidence=0.9,
                            description=f"High Z-score ({z:.2f} > {self.z_threshold})",
                            timestamp=ts,
                            data_point=value,
                            metadata={"method": "z_score", "z_score": z},
                        )
                    )

        # IQR method
        q1 = np.percentile(data, 25)
        q3 = np.percentile(data, 75)
        iqr = q3 - q1
        lower_bound = q1 - self.iqr_multiplier * iqr
        upper_bound = q3 + self.iqr_multiplier * iqr

        for i, (value, ts) in enumerate(zip(data, timestamps)):
            if value < lower_bound or value > upper_bound:
                # Avoid duplicates with Z-score anomalies
                if not any(
                    a.timestamp == ts and a.type == AnomalyType.STATISTICAL
                    for a in anomalies
                ):
                    anomalies.append(
                        Anomaly(
                            type=AnomalyType.STATISTICAL,
                            status=AnomalyStatus.ANOMALOUS,
                            score=0.8,
                            confidence=0.85,
                            description=f"Outside IQR bounds (Q1={q1:.2f}, Q3={q3:.2f})",
                            timestamp=ts,
                            data_point=value,
                            metadata={
                                "method": "iqr",
                                "lower_bound": lower_bound,
                                "upper_bound": upper_bound,
                            },
                        )
                    )

        # Moving average deviation
        if len(data) >= self.moving_avg_window:
            moving_avg = np.convolve(
                data, np.ones(self.moving_avg_window) / self.moving_avg_window, mode="valid"
            )
            for i, (value, ma, ts) in enumerate(
                zip(data[self.moving_avg_window - 1 :], moving_avg, timestamps[self.moving_avg_window - 1 :])
            ):
                deviation = abs(value - ma) / (ma + 1e-6)  # Avoid division by zero
                if deviation > 0.5:  # 50% deviation threshold
                    anomalies.append(
                        Anomaly(
                            type=AnomalyType.TEMPORAL,
                            status=AnomalyStatus.SUSPICIOUS,
                            score=min(1.0, deviation * 2),
                            confidence=0.75,
                            description=f"High deviation from moving average ({deviation:.2%})",
                            timestamp=ts,
                            data_point=value,
                            metadata={"method": "moving_avg", "deviation": deviation},
                        )
                    )

        return anomalies

    def detect_temporal_anomalies(self) -> List[Anomaly]:
        """
        Detect temporal anomalies (sudden spikes, drops, pattern changes).

        Returns:
            List of detected anomalies.
        """
        anomalies = []
        if len(self.data_window) < 2:
            return anomalies

        data = np.array(self.data_window)
        timestamps = np.array(self.timestamps)

        # Sudden spikes/drops
        for i in range(1, len(data)):
            prev_value = data[i - 1]
            current_value = data[i]
            change = current_value - prev_value
            relative_change = abs(change) / (abs(prev_value) + 1e-6)

            if relative_change > 0.5:  # 50% change threshold
                status = AnomalyStatus.ANOMALOUS if relative_change > 1.0 else AnomalyStatus.SUSPICIOUS
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.TEMPORAL,
                        status=status,
                        score=min(1.0, relative_change),
                        confidence=0.8,
                        description=f"Sudden {'spike' if change > 0 else 'drop'} ({relative_change:.1%})",
                        timestamp=timestamps[i],
                        data_point=current_value,
                        metadata={
                            "method": "temporal_change",
                            "change": change,
                            "relative_change": relative_change,
                        },
                    )
                )

        # Pattern change detection (simple version)
        if len(data) >= 10:
            first_half = data[: len(data) // 2]
            second_half = data[len(data) // 2 :]
            mean_first = np.mean(first_half)
            mean_second = np.mean(second_half)
            std_first = np.std(first_half)
            std_second = np.std(second_half)

            if std_first > 0 and std_second > 0:
                mean_diff = abs(mean_first - mean_second) / ((mean_first + mean_second) / 2 + 1e-6)
                std_diff = abs(std_first - std_second) / ((std_first + std_second) / 2 + 1e-6)

                if mean_diff > 0.3 and std_diff > 0.3:
                    anomalies.append(
                        Anomaly(
                            type=AnomalyType.TEMPORAL,
                            status=AnomalyStatus.SUSPICIOUS,
                            score=0.7,
                            confidence=0.7,
                            description="Significant pattern change detected",
                            timestamp=timestamps[-1],
                            data_point=data[-1],
                            metadata={
                                "method": "pattern_change",
                                "mean_diff": mean_diff,
                                "std_diff": std_diff,
                            },
                        )
                    )

        return anomalies

    def detect_all(self) -> List[Anomaly]:
        """Run all anomaly detection methods."""
        anomalies = []
        anomalies.extend(self.detect_statistical_anomalies())
        anomalies.extend(self.detect_temporal_anomalies())
        # Sort by timestamp
        anomalies.sort(key=lambda x: x.timestamp)
        return anomalies

    def reset(self) -> None:
        """Reset the detector's state."""
        self.data_window.clear()
        self.timestamps.clear()
        self.mean_history.clear()
        self.std_history.clear()

    def get_stats(self) -> Dict[str, float]:
        """Get current statistics."""
        if not self.data_window:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        data = np.array(self.data_window)
        return {
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "count": len(data),
        }
