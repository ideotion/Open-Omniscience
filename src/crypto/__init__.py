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
Cryptographic Module for Open-Omniscience Pillar 4

Provides cryptographic provenance and digital signature functionality
for ensuring legal admissibility of data.

Components:
- merkle_tree: SHA-256 Merkle tree implementation
- provenance: SQLite-based cryptographic ledger
- signatures: GPG signing and verification (Phase 4.2)
"""

from .merkle_tree import MerkleNode, MerkleTree
from .provenance import DataProvenance, ProvenanceLedger

try:
    from .signatures import GPGNotAvailableError, GPGSigner, SignatureResult
    HAS_SIGNATURES = True
except Exception:
    HAS_SIGNATURES = False

__all__ = ["MerkleTree", "MerkleNode", "ProvenanceLedger", "DataProvenance"]
if HAS_SIGNATURES:
    __all__.extend(["GPGSigner", "SignatureResult", "GPGNotAvailableError"])
