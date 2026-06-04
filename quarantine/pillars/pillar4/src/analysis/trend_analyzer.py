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
Pillar 4: Real-Time Monitoring & Alerting System - Trend Analyzer

Identifies trends in real-time data streams using time series analysis.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from collections import deque


class TrendDirection(Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class TrendStrength(Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


@dataclass
class Trend:
    """Represents a detected trend."""
    direction: TrendDirection
    strength: TrendStrength
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    start_time: float
    end_time: float
    slope: float
    r_squared: float
    data_points: List[Tuple[float, float]]  # (timestamp, value)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction.value,
            "strength": self.strength.value,
            "score": self.score,
            "confidence": self.confidence,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "slope": self.slope,
            "r_squared": self.r_squared,
            "data_points": [(t, v) for t, v in self.data_points],
            "metadata": self.metadata,
        }


class TrendAnalyzer:
    """
    Analyzes trends in time series data using:
    - Linear regression for trend direction
    - Moving averages for smoothing
    - Volatility measures
    """

    def __init__(
        self,
        window_size: int = 100,
        min_trend_length: int = 10,
        volatility_threshold: float = 0.2,
    ):
        """
        Initialize the trend analyzer.

        Args:
            window_size: Size of the sliding window for analysis.
            min_trend_length: Minimum number of points to consider a trend.
            volatility_threshold: Threshold for volatility detection.
        """
        self.window_size = window_size
        self.min_trend_length = min_trend_length
        self.volatility_threshold = volatility_threshold

        # Data storage
        self.data: deque = deque(maxlen=window_size)
        self.timestamps: deque = deque(maxlen=window_size)

    def add_data_point(self, value: float, timestamp: Optional[float] = None) -> None:
        """Add a new data point to the analyzer."""
        if timestamp is None:
            timestamp = time.time()
        self.data.append(value)
        self.timestamps.append(timestamp)

    def detect_trends(self) -> List[Trend]:
        """
        Detect trends in the current data window.

        Returns:
            List of detected trends.
        """
        trends = []
        if len(self.data) < self.min_trend_length:
            return trends

        # Convert to numpy arrays
        values = np.array(self.data)
        times = np.array(self.timestamps)

        # Normalize time to 0..1 range for analysis
        if len(times) > 1:
            normalized_times = (times - times[0]) / (times[-1] - times[0])
        else:
            normalized_times = np.zeros_like(times)

        # Simple linear regression to detect trend
        if len(values) >= 2:
            # Calculate slope and intercept
            n = len(values)
            sum_x = np.sum(normalized_times)
            sum_y = np.sum(values)
            sum_xy = np.sum(normalized_times * values)
            sum_x2 = np.sum(normalized_times**2)

            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
            intercept = (sum_y - slope * sum_x) / n

            # Calculate R-squared
            y_pred = slope * normalized_times + intercept
            ss_res = np.sum((values - y_pred) ** 2)
            ss_tot = np.sum((values - np.mean(values)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            # Determine trend direction
            if slope > 0.1:
                direction = TrendDirection.INCREASING
            elif slope < -0.1:
                direction = TrendDirection.DECREASING
            else:
                direction = TrendDirection.STABLE

            # Determine trend strength
            if abs(slope) > 0.5:
                strength = TrendStrength.STRONG
            elif abs(slope) > 0.2:
                strength = TrendStrength.MODERATE
            else:
                strength = TrendStrength.WEAK

            # Calculate volatility
            volatility = np.std(np.diff(values)) / (np.mean(values) + 1e-6)

            # Create trend object
            trend = Trend(
                direction=direction,
                strength=strength,
                score=min(1.0, abs(slope) * 2),
                confidence=min(1.0, r_squared * 1.5),
                start_time=float(times[0]),
                end_time=float(times[-1]),
                slope=float(slope),
                r_squared=float(r_squared),
                data_points=list(zip(times, values)),
                metadata={
                    "volatility": float(volatility),
                    "n_points": n,
                },
            )

            # Check for volatility
            if volatility > self.volatility_threshold:
                trend.direction = TrendDirection.VOLATILE
                trend.strength = TrendStrength.STRONG
                trend.score = min(1.0, volatility * 2)

            trends.append(trend)

        return trends

    def detect_emerging_trends(self, new_window_size: int = 20) -> List[Trend]:
        """
        Detect emerging trends in the most recent data.

        Args:
            new_window_size: Size of the window to consider for emerging trends.

        Returns:
            List of emerging trends.
        """
        if len(self.data) < new_window_size:
            return []

        # Get the most recent data
        recent_values = np.array(self.data)[-new_window_size:]
        recent_times = np.array(self.timestamps)[-new_window_size:]

        # Temporarily replace data with recent window
        old_data = self.data
        old_times = self.timestamps
        self.data = deque(recent_values, maxlen=self.window_size)
        self.timestamps = deque(recent_times, maxlen=self.window_size)

        trends = self.detect_trends()

        # Restore original data
        self.data = old_data
        self.timestamps = old_times

        return trends

    def get_current_trend(self) -> Optional[Trend]:
        """Get the current dominant trend."""
        trends = self.detect_trends()
        if not trends:
            return None
        # Return the trend with highest score
        return max(trends, key=lambda t: t.score)

    def reset(self) -> None:
        """Reset the analyzer's state."""
        self.data.clear()
        self.timestamps.clear()

    def get_stats(self) -> Dict[str, float]:
        """Get current statistics."""
        if not self.data:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        data = np.array(self.data)
        return {
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "count": len(data),
        }
