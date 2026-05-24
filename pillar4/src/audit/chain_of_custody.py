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
Chain of Custody Module for Open-Omniscience Pillar 4

This module provides chain of custody tracking for legal admissibility.
For Pillar 4 Qubes OS compatibility, we use DataLineageTracker from crypto.provenance.
"""

# Import DataLineageTracker from crypto.provenance
from pillar4.src.crypto.provenance import DataLineageTracker

# Re-export for compatibility
__all__ = ["DataLineageTracker"]
