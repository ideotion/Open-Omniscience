"""
Pillar 5: Services Module

This module provides core services for financial data processing.
Includes:
- Metric calculation
- Correlation engine
- Analysis services
"""

from pillar5.src.services.metric_calculator import MetricCalculator, MetricDefinition, MetricGroup
from pillar5.src.services.correlation_engine import (
    HybridCorrelationEngine,
    CorrelationResult,
    CorrelationMethod,
)

__all__ = [
    "MetricCalculator",
    "MetricDefinition",
    "MetricGroup",
    "HybridCorrelationEngine",
    "CorrelationResult",
    "CorrelationMethod",
]
