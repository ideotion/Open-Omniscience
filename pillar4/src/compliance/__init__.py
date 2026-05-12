"""
Pillar 4: Legal Admissibility - Compliance Module

Provides GDPR, copyright, and ethical compliance checking.
"""
from .gdpr import GDPRComplianceChecker
from .copyright import CopyrightComplianceChecker

__all__ = ["GDPRComplianceChecker", "CopyrightComplianceChecker"]
