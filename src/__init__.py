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

# Open-Omniscience - Pillar 4: Legal Admissibility
# This package provides cryptographic provenance, digital signatures,
# chain of custody tracking, and compliance checking for legal admissibility.
# All components work offline without cloud dependencies.

__version__ = "0.0.8"  # keep in sync with pyproject.toml [project].version
__author__ = "Open-Omniscience Team"
__license__ = "GPLv3"

# Cryptographic provenance (Merkle proofs, signatures) -- used by the evidence
# reporting path. The other former "Pillar 4: Legal Admissibility" siblings
# (audit, compliance, reports) were superseded by src/custody + src/reporting
# and moved to quarantine/dead_src/ in the v0.0.7 audit (finding MAINT-01).
from . import crypto

__all__ = ["crypto"]
