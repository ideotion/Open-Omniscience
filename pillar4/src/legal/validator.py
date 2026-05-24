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
Pillar 4: Legal Admissibility - Legal Validator

Validates data and processes for legal compliance and admissibility.
"""

import time
import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set
from enum import Enum
import logging


class LegalStatus(Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    CONDITIONALLY_COMPLIANT = "conditionally_compliant"
    PENDING_REVIEW = "pending_review"


class ComplianceType(Enum):
    ROBOTS_TXT = "robots_txt"
    COPYRIGHT = "copyright"
    GDPR = "gdpr"
    DATA_PROVENANCE = "data_provenance"
    CHAIN_OF_CUSTODY = "chain_of_custody"
    ETHICAL_SCRAPING = "ethical_scraping"


@dataclass
class ComplianceIssue:
    """Represents a compliance issue."""
    type: ComplianceType
    severity: str  # low, medium, high, critical
    description: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "severity": self.severity,
            "description": self.description,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class LegalValidationResult:
    """Result of a legal validation."""
    status: LegalStatus
    compliant: bool
    issues: List[ComplianceIssue] = field(default_factory=list)
    warnings: List[ComplianceIssue] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "compliant": self.compliant,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [w.to_dict() for w in self.warnings],
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class LegalValidator:
    """
    Validates data and processes for legal compliance and admissibility.

    Checks for:
    - robots.txt compliance
    - Copyright compliance
    - GDPR compliance
    - Data provenance
    - Chain of custody
    - Ethical scraping practices
    """

    def __init__(self):
        """Initialize the legal validator."""
        self.logger = logging.getLogger("LegalValidator")
        self.robots_cache: Dict[str, Dict[str, Any]] = {}
        self.copyright_keywords: Set[str] = {
            "copyright", "©", "all rights reserved", "intellectual property",
            "trademark", "™", "®", "patent", "licensed", "terms of use",
            "privacy policy", "do not reproduce", "confidential",
        }
        self.gdpr_keywords: Set[str] = {
            "personal data", "personally identifiable", "PII", "sensitive data",
            "consent", "data subject", "data controller", "data processor",
            "right to erasure", "right to access", "data portability",
            "privacy", "GDPR", "EU", "data protection",
        }

    def validate_all(
        self,
        data: Dict[str, Any],
        source_url: Optional[str] = None,
        ingestion_metadata: Optional[Dict[str, Any]] = None,
    ) -> LegalValidationResult:
        """
        Perform all legal validations on data.

        Args:
            data: Data to validate.
            source_url: URL where the data was ingested from.
            ingestion_metadata: Metadata about the ingestion process.

        Returns:
            LegalValidationResult with all validation outcomes.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"source_url": source_url},
        )

        # Run all validations
        if source_url:
            robots_result = self.validate_robots_txt(source_url)
            result.issues.extend(robots_result.issues)
            result.warnings.extend(robots_result.warnings)

        copyright_result = self.validate_copyright(data)
        result.issues.extend(copyright_result.issues)
        result.warnings.extend(copyright_result.warnings)

        gdpr_result = self.validate_gdpr(data)
        result.issues.extend(gdpr_result.issues)
        result.warnings.extend(gdpr_result.warnings)

        if ingestion_metadata:
            provenance_result = self.validate_provenance(ingestion_metadata)
            result.issues.extend(provenance_result.issues)
            result.warnings.extend(provenance_result.warnings)

            custody_result = self.validate_chain_of_custody(ingestion_metadata)
            result.issues.extend(custody_result.issues)
            result.warnings.extend(custody_result.warnings)

        if source_url and ingestion_metadata:
            ethical_result = self.validate_ethical_scraping(source_url, ingestion_metadata)
            result.issues.extend(ethical_result.issues)
            result.warnings.extend(ethical_result.warnings)

        # Determine overall status
        if result.issues:
            result.compliant = False
            result.status = LegalStatus.NON_COMPLIANT
        elif result.warnings:
            result.compliant = True
            result.status = LegalStatus.CONDITIONALLY_COMPLIANT
        else:
            result.compliant = True
            result.status = LegalStatus.COMPLIANT

        return result

    def validate_robots_txt(self, url: str) -> LegalValidationResult:
        """
        Validate that the URL complies with robots.txt.

        Args:
            url: URL to check.

        Returns:
            LegalValidationResult for robots.txt compliance.
        """
        from urllib.parse import urlparse
        import requests

        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"url": url, "check": "robots_txt"},
        )

        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

            # Check cache
            if robots_url in self.robots_cache:
                robots_data = self.robots_cache[robots_url]
            else:
                # Fetch robots.txt
                response = requests.get(robots_url, timeout=5)
                if response.status_code == 200:
                    robots_data = self._parse_robots_txt(response.text)
                    self.robots_cache[robots_url] = robots_data
                else:
                    # If robots.txt doesn't exist, we assume scraping is allowed
                    return result

            # Check if our user agent is allowed
            user_agent = "OpenOmniscience/1.0"
            path = parsed.path

            for rule in robots_data.get("rules", []):
                if rule["user_agent"] == "*" or rule["user_agent"] == user_agent:
                    if rule["disallow"] == path or path.startswith(rule["disallow"] + "/"):
                        result.issues.append(ComplianceIssue(
                            type=ComplianceType.ROBOTS_TXT,
                            severity="high",
                            description=f"URL {url} is disallowed by robots.txt",
                            details={"robots_url": robots_url, "disallowed_path": rule["disallow"]},
                        ))
                        result.compliant = False
                        result.status = LegalStatus.NON_COMPLIANT
                        break

        except Exception as e:
            result.warnings.append(ComplianceIssue(
                type=ComplianceType.ROBOTS_TXT,
                severity="medium",
                description=f"Could not validate robots.txt for {url}: {e}",
                details={"error": str(e)},
            ))

        return result

    def _parse_robots_txt(self, content: str) -> Dict[str, Any]:
        """Parse robots.txt content."""
        rules = []
        lines = content.split('\n')

        current_user_agent = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.lower().startswith("user-agent:"):
                current_user_agent = line.split(":", 1)[1].strip()
            elif line.lower().startswith("disallow:") and current_user_agent:
                path = line.split(":", 1)[1].strip()
                rules.append({
                    "user_agent": current_user_agent,
                    "disallow": path,
                })

        return {"rules": rules}

    def validate_copyright(self, data: Dict[str, Any]) -> LegalValidationResult:
        """
        Validate data for copyright compliance.

        Args:
            data: Data to validate.

        Returns:
            LegalValidationResult for copyright compliance.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"check": "copyright"},
        )

        # Check for copyright notices in text content
        text_content = self._extract_text(data)
        if text_content:
            for keyword in self.copyright_keywords:
                if keyword.lower() in text_content.lower():
                    result.warnings.append(ComplianceIssue(
                        type=ComplianceType.COPYRIGHT,
                        severity="medium",
                        description=f"Potential copyright notice detected: '{keyword}'",
                        details={"keyword": keyword},
                    ))

        # Check for copyrighted images or media
        if "images" in data:
            for image in data["images"]:
                if self._is_likely_copyrighted(image):
                    result.warnings.append(ComplianceIssue(
                        type=ComplianceType.COPYRIGHT,
                        severity="medium",
                        description="Potential copyrighted image detected",
                        details={"image": image},
                    ))

        # Check for copyrighted content from known sources
        if "source" in data and self._is_known_copyright_source(data["source"]):
            result.issues.append(ComplianceIssue(
                type=ComplianceType.COPYRIGHT,
                severity="high",
                description=f"Content from known copyright source: {data['source']}",
                details={"source": data["source"]},
            ))
            result.compliant = False
            result.status = LegalStatus.NON_COMPLIANT

        return result

    def _extract_text(self, data: Dict[str, Any]) -> str:
        """Extract text content from data."""
        text_parts = []

        if "content" in data:
            text_parts.append(str(data["content"]))
        if "text" in data:
            text_parts.append(str(data["text"]))
        if "title" in data:
            text_parts.append(str(data["title"]))
        if "description" in data:
            text_parts.append(str(data["description"]))

        return " ".join(text_parts)

    def _is_likely_copyrighted(self, image_data: Dict[str, Any]) -> bool:
        """Check if an image is likely copyrighted."""
        # Simple heuristics - in production, use image analysis
        if "url" in image_data:
            url = image_data["url"].lower()
            copyright_indicators = [
                "copyright", "stock", "getty", "shutterstock",
                "istock", "adobe", "ap", "reuters", "afp",
            ]
            return any(indicator in url for indicator in copyright_indicators)
        return False

    def _is_known_copyright_source(self, source: str) -> bool:
        """Check if a source is known to have strict copyright."""
        known_sources = [
            "nytimes.com", "washingtonpost.com", "theguardian.com",
            "bbc.com", "cnn.com", "foxnews.com", "reuters.com",
            "apnews.com", "bloomberg.com", "wsj.com", "ft.com",
            "gettyimages.com", "shutterstock.com", "istockphoto.com",
            "adobe.com", "apimages.com", "reuters.com",
        ]
        return any(src in source.lower() for src in known_sources)

    def validate_gdpr(self, data: Dict[str, Any]) -> LegalValidationResult:
        """
        Validate data for GDPR compliance.

        Args:
            data: Data to validate.

        Returns:
            LegalValidationResult for GDPR compliance.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"check": "gdpr"},
        )

        # Check for personal data
        text_content = self._extract_text(data)
        if text_content:
            # Check for PII (Personally Identifiable Information)
            pii_found = self._detect_pii(text_content)
            if pii_found:
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.GDPR,
                    severity="high",
                    description="Potential PII (Personally Identifiable Information) detected",
                    details={"pii_types": list(pii_found.keys())},
                ))
                result.compliant = False
                result.status = LegalStatus.NON_COMPLIANT

            # Check for GDPR-related keywords
            for keyword in self.gdpr_keywords:
                if keyword.lower() in text_content.lower():
                    result.warnings.append(ComplianceIssue(
                        type=ComplianceType.GDPR,
                        severity="low",
                        description=f"GDPR-related keyword detected: '{keyword}'",
                        details={"keyword": keyword},
                    ))

        # Check for data subject rights
        if "data_subject" in data or "personal_data" in data:
            if not data.get("consent_obtained", False):
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.GDPR,
                    severity="high",
                    description="Personal data processing without consent",
                    details={"data_type": "personal_data"},
                ))
                result.compliant = False
                result.status = LegalStatus.NON_COMPLIANT

        return result

    def _detect_pii(self, text: str) -> Dict[str, List[str]]:
        """
        Detect PII (Personally Identifiable Information) in text.

        Args:
            text: Text to analyze.

        Returns:
            Dictionary mapping PII types to lists of found values.
        """
        import re

        pii = {}

        # Email addresses
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if emails:
            pii["email"] = emails

        # Phone numbers (simple pattern)
        phones = re.findall(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', text)
        if phones:
            pii["phone"] = phones

        # Social security numbers (US)
        ssns = re.findall(r'\b\d{3}-\d{2}-\d{4}\b', text)
        if ssns:
            pii["ssn"] = ssns

        # IP addresses
        ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', text)
        if ips:
            pii["ip_address"] = [ip for ip in ips if self._is_valid_ip(ip)]

        # Credit card numbers (simple pattern)
        credit_cards = re.findall(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', text)
        if credit_cards:
            pii["credit_card"] = credit_cards

        # Names (simple pattern - this will have false positives)
        # This is a placeholder - in production, use NLP or a proper name detector
        name_pattern = r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b'
        names = re.findall(name_pattern, text)
        if len(names) > 5:  # Only flag if there are many names (likely a list)
            pii["name"] = names[:10]  # Limit to first 10

        return pii

    def _is_valid_ip(self, ip: str) -> bool:
        """Check if an IP address is valid."""
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        return all(0 <= int(part) <= 255 for part in parts)

    def validate_provenance(self, metadata: Dict[str, Any]) -> LegalValidationResult:
        """
        Validate data provenance for legal compliance.

        Args:
            metadata: Ingestion metadata containing provenance information.

        Returns:
            LegalValidationResult for provenance compliance.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"check": "data_provenance"},
        )

        # Check for required provenance fields
        required_fields = ["source_url", "ingestion_time", "data_hash"]
        missing_fields = [f for f in required_fields if f not in metadata]

        if missing_fields:
            result.issues.append(ComplianceIssue(
                type=ComplianceType.DATA_PROVENANCE,
                severity="high",
                description="Missing required provenance fields",
                details={"missing_fields": missing_fields},
            ))
            result.compliant = False
            result.status = LegalStatus.NON_COMPLIANT

        # Check for data hash
        if "data_hash" in metadata:
            if not self._is_valid_hash(metadata["data_hash"]):
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.DATA_PROVENANCE,
                    severity="high",
                    description="Invalid data hash format",
                    details={"hash": metadata["data_hash"]},
                ))
                result.compliant = False
                result.status = LegalStatus.NON_COMPLIANT

        # Check for source URL
        if "source_url" in metadata:
            if not self._is_valid_url(metadata["source_url"]):
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.DATA_PROVENANCE,
                    severity="medium",
                    description="Invalid source URL format",
                    details={"url": metadata["source_url"]},
                ))

        return result

    def _is_valid_hash(self, hash_value: str) -> bool:
        """Check if a hash is valid (SHA-256 format)."""
        return len(hash_value) == 64 and all(c in '0123456789abcdef' for c in hash_value.lower())

    def _is_valid_url(self, url: str) -> bool:
        """Check if a URL is valid."""
        from urllib.parse import urlparse
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except (ValueError, AttributeError):
            return False

    def validate_chain_of_custody(self, metadata: Dict[str, Any]) -> LegalValidationResult:
        """
        Validate chain of custody for legal compliance.

        Args:
            metadata: Ingestion metadata containing chain of custody information.

        Returns:
            LegalValidationResult for chain of custody compliance.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"check": "chain_of_custody"},
        )

        # Check for chain of custody records
        if "custody_records" not in metadata or not metadata["custody_records"]:
            result.warnings.append(ComplianceIssue(
                type=ComplianceType.CHAIN_OF_CUSTODY,
                severity="medium",
                description="No chain of custody records found",
                details={},
            ))
            return result

        records = metadata["custody_records"]

        # Check for required fields in each record
        required_fields = ["timestamp", "action", "user_id", "data_hash"]
        for i, record in enumerate(records):
            missing = [f for f in required_fields if f not in record]
            if missing:
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.CHAIN_OF_CUSTODY,
                    severity="high",
                    description=f"Missing fields in custody record {i}",
                    details={"record_index": i, "missing_fields": missing},
                ))
                result.compliant = False
                result.status = LegalStatus.NON_COMPLIANT

        # Check for sequential timestamps
        timestamps = [r.get("timestamp", 0) for r in records]
        if timestamps != sorted(timestamps):
            result.issues.append(ComplianceIssue(
                type=ComplianceType.CHAIN_OF_CUSTODY,
                severity="high",
                description="Custody records are not in chronological order",
                details={"timestamps": timestamps},
            ))
            result.compliant = False
            result.status = LegalStatus.NON_COMPLIANT

        # Check for data hash consistency
        data_hashes = [r.get("data_hash", "") for r in records]
        if len(set(data_hashes)) > 1:
            result.warnings.append(ComplianceIssue(
                type=ComplianceType.CHAIN_OF_CUSTODY,
                severity="low",
                description="Multiple data hashes in custody records",
                details={"hashes": data_hashes},
            ))

        return result

    def validate_ethical_scraping(
        self,
        url: str,
        metadata: Dict[str, Any],
    ) -> LegalValidationResult:
        """
        Validate that scraping was done ethically.

        Args:
            url: URL that was scraped.
            metadata: Ingestion metadata.

        Returns:
            LegalValidationResult for ethical scraping compliance.
        """
        result = LegalValidationResult(
            status=LegalStatus.COMPLIANT,
            compliant=True,
            metadata={"check": "ethical_scraping", "url": url},
        )

        # Check rate limiting
        if "requests_per_minute" in metadata:
            if metadata["requests_per_minute"] > 10:
                result.issues.append(ComplianceIssue(
                    type=ComplianceType.ETHICAL_SCRAPING,
                    severity="high",
                    description="Excessive request rate",
                    details={"rate": metadata["requests_per_minute"]},
                ))
                result.compliant = False
                result.status = LegalStatus.NON_COMPLIANT

        # Check for user agent
        if "user_agent" not in metadata or not metadata["user_agent"]:
            result.warnings.append(ComplianceIssue(
                type=ComplianceType.ETHICAL_SCRAPING,
                severity="medium",
                description="No user agent specified",
                details={},
            ))

        # Check for robots.txt compliance (already checked separately)
        # This is just a cross-reference
        if "robots_txt_checked" in metadata and not metadata["robots_txt_checked"]:
            result.issues.append(ComplianceIssue(
                type=ComplianceType.ETHICAL_SCRAPING,
                severity="high",
                description="robots.txt was not checked before scraping",
                details={},
            ))
            result.compliant = False
            result.status = LegalStatus.NON_COMPLIANT

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get validator statistics."""
        return {
            "robots_cache_size": len(self.robots_cache),
            "copyright_keywords": len(self.copyright_keywords),
            "gdpr_keywords": len(self.gdpr_keywords),
        }
