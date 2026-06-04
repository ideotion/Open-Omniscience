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
Pillar 4: Tests for Threat Intelligence
"""

import pytest
import time
import json
import tempfile
import os
from src.analysis.threat_intel import (
    ThreatIntel, 
    IndicatorOfCompromise, 
    ThreatIntelMatch,
    ThreatType,
    ThreatSeverity,
)


class TestThreatIntel:
    """Tests for the ThreatIntel class."""

    def test_initialization(self):
        """Test ThreatIntel initialization."""
        ti = ThreatIntel()
        assert len(ti.ioc_database) == 0
        assert len(ti.sources) == 0

    def test_load_ioc_database(self):
        """Test loading IOC database from file."""
        # Create a temporary IOC database file
        ioc_data = [
            {
                "value": "192.168.1.1",
                "type": "ip",
                "threat_type": "MALWARE",
                "severity": "HIGH",
                "description": "Known malware C2 server",
                "first_seen": time.time() - 86400,
                "last_seen": time.time(),
                "source": "test",
                "confidence": 0.95,
                "tags": ["malware", "c2"],
            },
            {
                "value": "evil.com",
                "type": "domain",
                "threat_type": "PHISHING",
                "severity": "MEDIUM",
                "description": "Phishing domain",
                "first_seen": time.time() - 3600,
                "last_seen": time.time(),
                "source": "test",
                "confidence": 0.85,
                "tags": ["phishing"],
            },
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(ioc_data, f)
            temp_path = f.name
        
        try:
            ti = ThreatIntel()
            ti.load_ioc_database(temp_path)
            
            # Database has 4 keys: 192.168.1.1, ip:192.168.1.1, evil.com, domain:evil.com
            assert len(ti.ioc_database) == 4
            assert "192.168.1.1" in ti.ioc_database
            assert "evil.com" in ti.ioc_database
            assert "domain:evil.com" in ti.ioc_database
            assert "ip:192.168.1.1" in ti.ioc_database
        finally:
            os.unlink(temp_path)

    def test_add_ioc(self):
        """Test adding a single IOC."""
        ti = ThreatIntel()
        
        ioc = IndicatorOfCompromise(
            value="10.0.0.1",
            type="ip",
            threat_type=ThreatType.MALWARE,
            severity=ThreatSeverity.HIGH,
            description="Test IOC",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.9,
        )
        
        ti.add_ioc(ioc)
        
        assert "10.0.0.1" in ti.ioc_database
        assert "ip:10.0.0.1" in ti.ioc_database

    def test_check_ip(self):
        """Test checking an IP address."""
        ti = ThreatIntel()
        
        ioc = IndicatorOfCompromise(
            value="192.168.1.100",
            type="ip",
            threat_type=ThreatType.MALWARE,
            severity=ThreatSeverity.CRITICAL,
            description="Malicious IP",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.99,
        )
        ti.add_ioc(ioc)
        
        matches = ti.check_ip("192.168.1.100")
        assert len(matches) == 1
        assert matches[0].indicator.value == "192.168.1.100"
        assert matches[0].matched_value == "192.168.1.100"

    def test_check_ip_no_match(self):
        """Test checking an IP with no match."""
        ti = ThreatIntel()
        matches = ti.check_ip("1.2.3.4")
        assert len(matches) == 0

    def test_check_domain(self):
        """Test checking a domain."""
        ti = ThreatIntel()
        
        ioc = IndicatorOfCompromise(
            value="malicious.example.com",
            type="domain",
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            description="Phishing domain",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.9,
        )
        ti.add_ioc(ioc)
        
        matches = ti.check_domain("malicious.example.com")
        assert len(matches) == 1
        
        # Also check with protocol
        matches = ti.check_domain("https://malicious.example.com")
        assert len(matches) == 1

    def test_check_domain_no_match(self):
        """Test checking a domain with no match."""
        ti = ThreatIntel()
        matches = ti.check_domain("example.com")
        assert len(matches) == 0

    def test_check_url(self):
        """Test checking a URL."""
        ti = ThreatIntel()
        
        # Add domain IOC
        ioc = IndicatorOfCompromise(
            value="bad-site.com",
            type="domain",
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            description="Bad site",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.9,
        )
        ti.add_ioc(ioc)
        
        # Check URL
        matches = ti.check_url("https://bad-site.com/path")
        assert len(matches) == 1

    def test_check_url_exact_match(self):
        """Test checking URL with exact match."""
        ti = ThreatIntel()
        
        # Add URL IOC
        ioc = IndicatorOfCompromise(
            value="https://exact-match.com/path",
            type="url",
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            description="Exact match URL",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.95,
        )
        ti.add_ioc(ioc)
        
        matches = ti.check_url("https://exact-match.com/path")
        assert len(matches) == 1

    def test_check_hash(self):
        """Test checking a file hash."""
        ti = ThreatIntel()
        
        ioc = IndicatorOfCompromise(
            value="a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
            type="hash",
            threat_type=ThreatType.MALWARE,
            severity=ThreatSeverity.CRITICAL,
            description="Malicious file hash",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.99,
        )
        ti.add_ioc(ioc)
        
        matches = ti.check_hash("a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef")
        assert len(matches) == 1

    def test_check_hash_no_match(self):
        """Test checking a hash with no match."""
        ti = ThreatIntel()
        matches = ti.check_hash("0" * 64)
        assert len(matches) == 0

    def test_check_text(self):
        """Test checking text for malicious keywords."""
        ti = ThreatIntel()
        
        text = "This is a malicious payload that exploits a vulnerability"
        matches = ti.check_text(text)
        
        # Should find keywords like "malicious", "payload", "exploits", "vulnerability"
        assert len(matches) > 0
        assert any("malicious" in m.indicator.value.lower() or 
                   "payload" in m.indicator.value.lower() or
                   "exploit" in m.indicator.value.lower() or
                   "vulnerability" in m.indicator.value.lower()
                   for m in matches)

    def test_check_text_no_matches(self):
        """Test checking clean text."""
        ti = ThreatIntel()
        text = "This is a completely clean and safe text with no malicious content"
        matches = ti.check_text(text)
        assert len(matches) == 0

    def test_calculate_file_hash_sha256(self):
        """Test calculating SHA-256 hash of a file."""
        ti = ThreatIntel()
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            # Calculate expected hash
            import hashlib
            expected_hash = hashlib.sha256(b"test content").hexdigest()
            
            # Calculate with ThreatIntel
            actual_hash = ti.calculate_file_hash(temp_path, "sha256")
            
            assert actual_hash == expected_hash
        finally:
            os.unlink(temp_path)

    def test_calculate_file_hash_md5(self):
        """Test calculating MD5 hash of a file."""
        ti = ThreatIntel()
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            import hashlib
            expected_hash = hashlib.md5(b"test content").hexdigest()
            actual_hash = ti.calculate_file_hash(temp_path, "md5")
            assert actual_hash == expected_hash
        finally:
            os.unlink(temp_path)

    def test_get_stats(self):
        """Test getting statistics."""
        ti = ThreatIntel()
        
        # Add some IOCs
        for i in range(5):
            ioc = IndicatorOfCompromise(
                value=f"test{i}.com",
                type="domain",
                threat_type=ThreatType.PHISHING,
                severity=ThreatSeverity.MEDIUM,
                description=f"Test domain {i}",
                first_seen=time.time(),
                last_seen=time.time(),
                source="test",
                confidence=0.8,
            )
            ti.add_ioc(ioc)
        
        stats = ti.get_stats()
        assert stats["total_iocs"] == 5
        assert "test" in stats["sources"]

    def test_export_ioc_database(self):
        """Test exporting IOC database."""
        ti = ThreatIntel()
        
        # Add IOCs
        for i in range(3):
            ioc = IndicatorOfCompromise(
                value=f"export{i}.com",
                type="domain",
                threat_type=ThreatType.MALWARE,
                severity=ThreatSeverity.HIGH,
                description=f"Export test {i}",
                first_seen=time.time(),
                last_seen=time.time(),
                source="export_test",
                confidence=0.9,
            )
            ti.add_ioc(ioc)
        
        # Export to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            ti.export_ioc_database(temp_path)
            
            # Verify export
            with open(temp_path, 'r') as f:
                data = json.load(f)
            
            assert len(data) == 3
        finally:
            os.unlink(temp_path)


class TestIndicatorOfCompromise:
    """Tests for the IndicatorOfCompromise dataclass."""

    def test_ioc_creation(self):
        """Test creating an IOC."""
        ioc = IndicatorOfCompromise(
            value="test.com",
            type="domain",
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            description="Test IOC",
            first_seen=time.time() - 86400,
            last_seen=time.time(),
            source="test",
            confidence=0.95,
            tags=["test", "ioc"],
            metadata={"custom": "value"},
        )
        
        assert ioc.value == "test.com"
        assert ioc.type == "domain"
        assert ioc.threat_type == ThreatType.PHISHING
        assert ioc.severity == ThreatSeverity.HIGH

    def test_ioc_to_dict(self):
        """Test converting IOC to dictionary."""
        ioc = IndicatorOfCompromise(
            value="192.168.1.1",
            type="ip",
            threat_type=ThreatType.MALWARE,
            severity=ThreatSeverity.CRITICAL,
            description="Malicious IP",
            first_seen=time.time() - 3600,
            last_seen=time.time(),
            source="test_source",
            confidence=0.99,
            tags=["malware", "c2"],
            metadata={"campaign": "test_campaign"},
        )
        
        d = ioc.to_dict()
        assert d["value"] == "192.168.1.1"
        assert d["type"] == "ip"
        assert d["threat_type"] == "malware"
        assert d["severity"] == "critical"
        assert d["source"] == "test_source"
        assert d["tags"] == ["malware", "c2"]


class TestThreatIntelMatch:
    """Tests for the ThreatIntelMatch dataclass."""

    def test_match_creation(self):
        """Test creating a threat intelligence match."""
        ioc = IndicatorOfCompromise(
            value="matched.com",
            type="domain",
            threat_type=ThreatType.PHISHING,
            severity=ThreatSeverity.HIGH,
            description="Matched domain",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.9,
        )
        
        match = ThreatIntelMatch(
            indicator=ioc,
            matched_value="matched.com",
            context={"type": "domain"},
            timestamp=time.time(),
        )
        
        assert match.indicator.value == "matched.com"
        assert match.matched_value == "matched.com"
        assert match.context["type"] == "domain"

    def test_match_to_dict(self):
        """Test converting match to dictionary."""
        ioc = IndicatorOfCompromise(
            value="test.com",
            type="domain",
            threat_type=ThreatType.SPAM,
            severity=ThreatSeverity.MEDIUM,
            description="Test",
            first_seen=time.time(),
            last_seen=time.time(),
            source="test",
            confidence=0.8,
        )
        
        match = ThreatIntelMatch(
            indicator=ioc,
            matched_value="test.com",
            context={"check": "domain"},
            timestamp=time.time(),
        )
        
        d = match.to_dict()
        assert "indicator" in d
        assert "matched_value" in d
        assert "context" in d
        assert "timestamp" in d
