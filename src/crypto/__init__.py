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

Provides the SHA-256 Merkle tree primitive used by the app's real, live
provenance/chain-of-custody mechanism.

Components:
- merkle_tree: SHA-256 Merkle tree implementation, imported and called by
  src/reporting/evidence.py (Ed25519 + Merkle) and src/backup/artifact.py.

Note: this package previously also re-exported a `ProvenanceLedger` (a
plaintext-sqlite provenance ledger) and a `GPGSigner` stub. Neither was ever
wired into any live code path, imported nowhere outside this package's own
files, and both were removed as orphaned dead code (their docstrings claimed
"legal admissibility" which they never delivered for the live app). The
app's actual, live legal-admissibility / chain-of-custody mechanism is
`src/custody/log.py`'s `CustodyLog` (hash-chained, Ed25519-signed, optional
post-quantum ML-DSA), reachable through the `/api/custody/*` routes.
"""

from .merkle_tree import MerkleNode, MerkleTree

__all__ = ["MerkleTree", "MerkleNode"]
