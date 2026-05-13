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
# Legal Report Module for Open-Omniscience Pillar 4
# Generate tamper-proof reports in Markdown/PDF format

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


class LegalReportGenerator:
    def __init__(self):
        pass

    def generate_markdown_report(self, data, title="Legal Report"):
        timestamp = datetime.now(timezone.utc).isoformat()
        data_hash = self._compute_data_hash(data)
        
        report = "# " + title + "\n\n"
        report += "**Generated:** " + timestamp + "\n\n"
        report += "**Data Hash (SHA-256):** " + data_hash + "\n\n"
        report += "---\n\n"
        report += "## Data Summary\n\n"
        report += json.dumps(data, indent=2) + "\n\n"
        report += "---\n\n"
        report += "**Report Hash (SHA-256):** " + self._compute_data_hash(report) + "\n"
        
        return report

    def _compute_data_hash(self, data):
        if isinstance(data, str):
            data_bytes = data.encode("utf-8")
        else:
            data_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(data_bytes).hexdigest()

def create_legal_report(data, title="Legal Report"):
    generator = LegalReportGenerator()
    return generator.generate_markdown_report(data, title)
