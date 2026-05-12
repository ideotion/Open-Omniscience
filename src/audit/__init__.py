"""
Audit Module for Open-Omniscience Pillar 4

Provides chain of custody tracking and audit functionality
for ensuring legal admissibility of data.

Components:
- chain_of_custody: Log every data interaction (Phase 4.3)
"""

from .chain_of_custody import ChainOfCustody

__all__ = ["ChainOfCustody"]
