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
