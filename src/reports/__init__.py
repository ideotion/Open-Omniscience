"""
Reports Module for Open-Omniscience Pillar 4

Provides tamper-proof reporting functionality
for ensuring legal admissibility of data.

Components:
- legal_report: Tamper-proof reports in Markdown/PDF (Phase 4.3)
"""

from .legal_report import LegalReportGenerator, create_legal_report

__all__ = ["LegalReportGenerator", "create_legal_report"]
