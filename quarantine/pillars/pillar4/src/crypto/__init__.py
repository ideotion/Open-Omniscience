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
Pillar 4: Legal Admissibility - Crypto Module

Provides cryptographic provenance, Merkle trees, and digital signatures for legal compliance.
"""
from .provenance import DataLineageTracker
from .merkle_tree import MerkleTree, MerkleNode

try:
    from .signatures import GPGSigner, SignatureResult, GPGNotAvailableError
    HAS_SIGNATURES = True
except Exception:
    HAS_SIGNATURES = False

__all__ = ["DataLineageTracker", "MerkleTree", "MerkleNode"]
if HAS_SIGNATURES:
    __all__.extend(["GPGSigner", "SignatureResult", "GPGNotAvailableError"])
