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
# Digital Signatures Module for Open-Omniscience Pillar 4
# GPG signing and verification functionality

from datetime import UTC


class GPGNotAvailableError(Exception):
    pass

class SignatureResult:
    def __init__(self, success, signature=None, message=None, fingerprint=None, key_id=None):
        self.success = success
        self.signature = signature
        self.message = message
        self.fingerprint = fingerprint
        self.key_id = key_id
        from datetime import datetime, timezone
        self.timestamp = datetime.now(UTC).isoformat()

class GPGSigner:
    """Placeholder GPG signer -- NOT implemented.

    The previous stubs returned None from sign/verify, i.e. a "signer" that
    silently produced no signature and a "verifier" that silently passed. That is
    a dangerous no-op for anything relying on it. Real, working signing lives in
    ``src/reporting/evidence.py`` (Ed25519 + Merkle). These methods now raise so a
    caller can never mistake a no-op for a valid signature.
    """

    def __init__(self, gpg_path="gpg"):
        self.gpg_path = gpg_path

    def sign_data(self, data, key_id=None):
        raise NotImplementedError(
            "GPG signing is not implemented; use src.reporting.evidence (Ed25519)."
        )

    def verify_signature(self, data, signature):
        raise NotImplementedError(
            "GPG verification is not implemented; use src.reporting.evidence.verify_bundle."
        )
