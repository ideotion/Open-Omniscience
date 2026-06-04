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
Pillar 4: Real-Time Monitoring & Alerting System - Threat Intelligence

Integrates with open-source threat intelligence feeds for contextual enrichment.
"""

import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum
from urllib.parse import urlparse
import hashlib


class ThreatType(Enum):
    MALWARE = "malware"
    PHISHING = "phishing"
    BOTNET = "botnet"
    SPAM = "spam"
    SCANNING = "scanning"
    EXPLOIT = "exploit"
    DISINFORMATION = "disinformation"
    UNKNOWN = "unknown"


class ThreatSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class IndicatorOfCompromise:
    """Represents an indicator of compromise (IOC)."""
    value: str
    type: str  # ip, domain, url, hash, etc.
    threat_type: ThreatType
    severity: ThreatSeverity
    description: str
    first_seen: float
    last_seen: float
    source: str
    confidence: float
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "type": self.type,
            "threat_type": self.threat_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "source": self.source,
            "confidence": self.confidence,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class ThreatIntelMatch:
    """Represents a match against threat intelligence."""
    indicator: IndicatorOfCompromise
    matched_value: str
    context: Dict[str, Any]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "indicator": self.indicator.to_dict(),
            "matched_value": self.matched_value,
            "context": self.context,
            "timestamp": self.timestamp,
        }


class ThreatIntel:
    """
    Threat intelligence integration for contextual enrichment of detected anomalies.

    Supports:
    - Local IOC databases
    - Open-source threat feeds (MISP, STIX/TAXII)
    - Custom threat lists
    """

    def __init__(self, ioc_database_path: Optional[str] = None):
        """
        Initialize the threat intelligence module.

        Args:
            ioc_database_path: Path to a JSON file containing IOCs.
        """
        self.ioc_database: Dict[str, IndicatorOfCompromise] = {}
        self.sources: Set[str] = set()
        self.last_updated: float = 0.0

        if ioc_database_path:
            self.load_ioc_database(ioc_database_path)

    def load_ioc_database(self, path: str) -> None:
        """Load IOC database from a JSON file."""
        try:
            with open(path, "r") as f:
                data = json.load(f)

            for ioc_data in data:
                ioc = IndicatorOfCompromise(
                    value=ioc_data.get("value", ""),
                    type=ioc_data.get("type", "unknown"),
                    threat_type=ThreatType(ioc_data.get("threat_type", "unknown").lower()),
                    severity=ThreatSeverity(ioc_data.get("severity", "medium").lower()),
                    description=ioc_data.get("description", ""),
                    first_seen=ioc_data.get("first_seen", time.time()),
                    last_seen=ioc_data.get("last_seen", time.time()),
                    source=ioc_data.get("source", "local"),
                    confidence=ioc_data.get("confidence", 0.8),
                    tags=ioc_data.get("tags", []),
                    metadata=ioc_data.get("metadata", {}),
                )
                # Create keys for fast lookup
                self.ioc_database[ioc.value.lower()] = ioc
                if ioc.type == "domain":
                    self.ioc_database[f"domain:{ioc.value.lower()}"] = ioc
                elif ioc.type == "ip":
                    self.ioc_database[f"ip:{ioc.value.lower()}"] = ioc
                elif ioc.type == "url":
                    parsed = urlparse(ioc.value.lower())
                    if parsed.netloc:
                        self.ioc_database[f"domain:{parsed.netloc}"] = ioc
                    self.ioc_database[f"url:{ioc.value.lower()}"] = ioc
                elif ioc.type == "hash":
                    self.ioc_database[f"hash:{ioc.value.lower()}"] = ioc

                self.sources.add(ioc.source)

            self.last_updated = time.time()
        except Exception as e:
            print(f"Error loading IOC database: {e}")

    def add_ioc(self, ioc: IndicatorOfCompromise) -> None:
        """Add a single IOC to the database."""
        self.ioc_database[ioc.value.lower()] = ioc
        if ioc.type == "domain":
            self.ioc_database[f"domain:{ioc.value.lower()}"] = ioc
        elif ioc.type == "ip":
            self.ioc_database[f"ip:{ioc.value.lower()}"] = ioc
        elif ioc.type == "url":
            parsed = urlparse(ioc.value.lower())
            if parsed.netloc:
                self.ioc_database[f"domain:{parsed.netloc}"] = ioc
            self.ioc_database[f"url:{ioc.value.lower()}"] = ioc
        elif ioc.type == "hash":
            self.ioc_database[f"hash:{ioc.value.lower()}"] = ioc
        self.sources.add(ioc.source)

    def check_ip(self, ip: str) -> List[ThreatIntelMatch]:
        """Check an IP address against the IOC database."""
        matches = []
        ip_lower = ip.lower().strip()
        seen_iocs = set()

        # Check exact match
        if ip_lower in self.ioc_database:
            ioc = self.ioc_database[ip_lower]
            if id(ioc) not in seen_iocs:
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=ip,
                        context={"type": "ip"},
                        timestamp=time.time(),
                    )
                )
                seen_iocs.add(id(ioc))

        # Check IP-based keys
        if f"ip:{ip_lower}" in self.ioc_database:
            ioc = self.ioc_database[f"ip:{ip_lower}"]
            if id(ioc) not in seen_iocs:
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=ip,
                        context={"type": "ip"},
                        timestamp=time.time(),
                    )
                )
                seen_iocs.add(id(ioc))

        return matches

    def check_domain(self, domain: str) -> List[ThreatIntelMatch]:
        """Check a domain against the IOC database."""
        matches = []
        domain_lower = domain.lower().strip()
        seen_iocs = set()

        # Remove protocol and path if present
        if domain_lower.startswith("http://") or domain_lower.startswith("https://"):
            domain_lower = domain_lower.split("://")[1].split("/")[0]

        # Check exact match
        if domain_lower in self.ioc_database:
            ioc = self.ioc_database[domain_lower]
            if id(ioc) not in seen_iocs:
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=domain,
                        context={"type": "domain"},
                        timestamp=time.time(),
                    )
                )
                seen_iocs.add(id(ioc))

        # Check domain-based keys
        if f"domain:{domain_lower}" in self.ioc_database:
            ioc = self.ioc_database[f"domain:{domain_lower}"]
            if id(ioc) not in seen_iocs:
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=domain,
                        context={"type": "domain"},
                        timestamp=time.time(),
                    )
                )
                seen_iocs.add(id(ioc))

        return matches

    def check_url(self, url: str) -> List[ThreatIntelMatch]:
        """Check a URL against the IOC database."""
        matches = []
        url_lower = url.lower().strip()
        seen_iocs = set()

        # Check exact URL match
        if f"url:{url_lower}" in self.ioc_database:
            ioc = self.ioc_database[f"url:{url_lower}"]
            if id(ioc) not in seen_iocs:
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=url,
                        context={"type": "url"},
                        timestamp=time.time(),
                    )
                )
                seen_iocs.add(id(ioc))

        # Check domain from URL
        parsed = urlparse(url_lower)
        if parsed.netloc:
            domain_matches = self.check_domain(parsed.netloc)
            for match in domain_matches:
                if id(match.indicator) not in seen_iocs:
                    matches.append(match)
                    seen_iocs.add(id(match.indicator))

        return matches

    def check_hash(self, hash_value: str, hash_type: str = "sha256") -> List[ThreatIntelMatch]:
        """Check a file hash against the IOC database."""
        matches = []
        hash_lower = hash_value.lower().strip()

        # Check hash-based keys
        if f"hash:{hash_lower}" in self.ioc_database:
            ioc = self.ioc_database[f"hash:{hash_lower}"]
            matches.append(
                ThreatIntelMatch(
                    indicator=ioc,
                    matched_value=hash_value,
                    context={"type": "hash", "hash_type": hash_type},
                    timestamp=time.time(),
                )
            )

        return matches

    def check_text(self, text: str) -> List[ThreatIntelMatch]:
        """
        Check text for known malicious patterns or keywords.

        Args:
            text: Text to check.

        Returns:
            List of threat intelligence matches.
        """
        matches = []

        # Simple keyword check (can be extended)
        malicious_keywords = [
            "exploit", "payload", "malware", "virus", "trojan",
            "phishing", "botnet", "ransomware", "backdoor",
            "zero-day", "vulnerability", "cve-",
        ]

        text_lower = text.lower()
        for keyword in malicious_keywords:
            if keyword in text_lower:
                # This is a simple check; in production, use more sophisticated methods
                ioc = IndicatorOfCompromise(
                    value=keyword,
                    type="keyword",
                    threat_type=ThreatType.UNKNOWN,
                    severity=ThreatSeverity.LOW,
                    description=f"Potentially malicious keyword: {keyword}",
                    first_seen=time.time(),
                    last_seen=time.time(),
                    source="keyword_analysis",
                    confidence=0.3,
                )
                matches.append(
                    ThreatIntelMatch(
                        indicator=ioc,
                        matched_value=keyword,
                        context={"type": "keyword", "text": text[:100] + "..."},
                        timestamp=time.time(),
                    )
                )

        return matches

    def calculate_file_hash(self, file_path: str, hash_type: str = "sha256") -> str:
        """Calculate the hash of a file."""
        if hash_type == "sha256":
            hasher = hashlib.sha256()
        elif hash_type == "md5":
            hasher = hashlib.md5()
        elif hash_type == "sha1":
            hasher = hashlib.sha1()
        else:
            raise ValueError(f"Unsupported hash type: {hash_type}")

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                hasher.update(chunk)

        return hasher.hexdigest()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the threat intelligence database."""
        # Count unique IOCs by using a set of IOC ids
        unique_iocs = set(id(ioc) for ioc in self.ioc_database.values())
        return {
            "total_iocs": len(unique_iocs),
            "sources": list(self.sources),
            "last_updated": self.last_updated,
            "ioc_types": {
                "ip": sum(1 for ioc in self.ioc_database.values() if ioc.type == "ip"),
                "domain": sum(1 for ioc in self.ioc_database.values() if ioc.type == "domain"),
                "url": sum(1 for ioc in self.ioc_database.values() if ioc.type == "url"),
                "hash": sum(1 for ioc in self.ioc_database.values() if ioc.type == "hash"),
                "other": sum(1 for ioc in self.ioc_database.values() if ioc.type not in ["ip", "domain", "url", "hash"]),
            },
        }

    def export_ioc_database(self, path: str) -> None:
        """Export the IOC database to a JSON file."""
        # Export unique IOCs only
        seen_iocs = set()
        data = []
        for ioc in self.ioc_database.values():
            if id(ioc) not in seen_iocs:
                data.append(ioc.to_dict())
                seen_iocs.add(id(ioc))
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
