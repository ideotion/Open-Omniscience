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
Audit Module for Open-Omniscience Pillar 4

Provides chain of custody tracking and audit functionality
for ensuring legal admissibility of data.

Components:
- chain_of_custody: Log every data interaction (Phase 4.3)
"""

from .chain_of_custody import ChainOfCustody

__all__ = ["ChainOfCustody"]
