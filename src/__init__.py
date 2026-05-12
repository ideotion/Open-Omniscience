"""
Open-Omniscience - Pillar 4: Legal Admissibility

This package provides cryptographic provenance, digital signatures,
chain of custody tracking, and compliance checking for legal admissibility.

All components work offline without cloud dependencies.
"""

__version__ = "0.1.0"
__author__ = "Open-Omniscience Team"
__license__ = "MIT"

# Pillar 4 modules
from . import crypto
from . import audit
from . import compliance
from . import reports

__all__ = ['crypto', 'audit', 'compliance', 'reports']

# Version info
__version__ = "0.1.0"
__author__ = "Open-Omniscience Team"
__license__ = "MIT"