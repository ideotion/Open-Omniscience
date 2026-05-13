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
Compliance Module for Open-Omniscience Pillar 4

Provides automated compliance checking functionality
for ensuring legal admissibility of data.

Components:
- gdpr: Anonymize PII locally, right to erasure (Phase 4.4)
- copyright: Check robots.txt and ToS locally, rate limits (Phase 4.4)
"""

from .gdpr import GDPRCompliance, anonymize_pii
from .copyright import CopyrightCompliance, check_robots_txt

__all__ = ["GDPRCompliance", "anonymize_pii", "CopyrightCompliance", "check_robots_txt"]
