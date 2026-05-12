"""
Cryptographic Module for Open-Omniscience Pillar 4

Provides cryptographic provenance and digital signature functionality
for ensuring legal admissibility of data.

Components:
- merkle_tree: SHA-256 Merkle tree implementation
- provenance: SQLite-based cryptographic ledger
- signatures: GPG signing and verification (Phase 4.2)
"""

from .merkle_tree import MerkleTree, MerkleNode
from .provenance import ProvenanceLedger, DataProvenance

try:
    from .signatures import GPGSigner, SignatureResult, GPGNotAvailableError
    HAS_SIGNATURES = True
except Exception:
    HAS_SIGNATURES = False

__all__ = ["MerkleTree", "MerkleNode", "ProvenanceLedger", "DataProvenance"]
if HAS_SIGNATURES:
    __all__.extend(["GPGSigner", "SignatureResult", "GPGNotAvailableError"])
