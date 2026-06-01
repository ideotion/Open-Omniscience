"""
GUI Components for Pillar 5 - Financial Intelligence

This module provides JavaScript-based GUI components that integrate with
Open-Omniscience's existing frontend architecture.

Components:
- MetricExplorer: Browse and visualize pre-computed financial metrics
- CorrelationView: View hybrid correlation results between articles and instruments
- InstrumentBrowser: Browse and filter financial instruments
- FinancialDashboard: Main dashboard integrating all components

Usage:
    These components are designed to work with the existing Open-Omniscience
    frontend (vanilla JavaScript) and consume the Pillar 5 API endpoints.
"""

from pillar5.src.gui.metric_explorer import MetricExplorer
from pillar5.src.gui.correlation_view import CorrelationView
from pillar5.src.gui.instrument_browser import InstrumentBrowser
from pillar5.src.gui.financial_dashboard import FinancialDashboard

__all__ = [
    'MetricExplorer',
    'CorrelationView',
    'InstrumentBrowser',
    'FinancialDashboard',
]
