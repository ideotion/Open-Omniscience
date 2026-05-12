"""
Pillar 4: Legal Admissibility - Crypto Module

Provides cryptographic provenance, Merkle trees, and digital signatures for legal compliance.
"""
from .provenance import DataLineageTracker, ReproducibilityCalculator
from .merkle_tree import MerkleTree
from .signatures import GPGSigner

__all__ = ["DataLineageTracker", "ReproducibilityCalculator", "MerkleTree", "GPGSigner"]
