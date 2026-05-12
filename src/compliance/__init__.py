"""
Compliance Module for Open-Omniscience Pillar 4

Provides automated compliance checking functionality
for ensuring legal admissibility of data.

Components:
- gdpr: Anonymize PII locally, right to erasure (Phase 4.4)
- copyright: Check robots.txt and ToS locally, rate limits (Phase 4.4)
"""

from .gdpr import GDPRCompliance, anonymize_pii
from .copyright import CopyrightCompliance, check_robots_txt

__all__ = ["GDPRCompliance", "anonymize_pii", "CopyrightCompliance", "check_robots_txt"]
