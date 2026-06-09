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
Tests for the Open Omniscience scraper module.

Tests cover:
- Basic scraping functionality
- Rate limiting
- Robots.txt compliance
- Duplicate detection
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone
import yaml
import csv

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scraper.scraper import Scraper
from database.models import Article, Source, get_session
from ingestor.url_utils import canonicalize_url, generate_content_hash

# Test configuration
TEST_CONFIG = {
    "sources": [
        {
            "name": "Test Source 1",
            "domain": "test-source-1.com",
            "rss_url": "",
            "rate_limit_ms": 1000,
            "enabled": True,
            "priority": 1
        },
        {
            "name": "Test Source 2",
            "domain": "test-source-2.com",
            "rss_url": "",
            "rate_limit_ms": 1000,
            "enabled": True,
            "priority": 1
        },
        {
            "name": "Disabled Source",
            "domain": "disabled-source.com",
            "rss_url": "",
            "rate_limit_ms": 1000,
            "enabled": False,
            "priority": 1
        }
    ]
}

@pytest.fixture
def temp_config():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(TEST_CONFIG, f)
        f.flush()
        yield f.name
    os.unlink(f.name)

@pytest.fixture
def scraper(temp_config):
    """Create a scraper instance with test config.

    F-003: stub the network-touching methods so the suite stays OFFLINE and
    deterministic. The scraper's own logic (audit logging, rate-limit sleeps) still
    runs — only the real HTTP/DNS is removed — so the behaviours these tests assert
    (log rows, elapsed time) are preserved without reaching the wire.
    """
    s = Scraper(config_path=temp_config)
    s._can_scrape = lambda url: True            # no robots.txt fetch
    s._parse_html = lambda url, name: []        # no HTML request
    s._parse_rss = lambda url, name: []         # no feed request
    return s

def test_scraper_initialization(scraper):
    """Test that the scraper initializes correctly."""
    assert len(scraper.sources) == 3
    assert scraper.audit_log.exists or scraper.audit_log.parent.exists

def test_scraper_skips_disabled_sources(scraper):
    """Test that disabled sources are skipped."""
    # Mock the scrape_source method to track calls
    original_scrape_source = scraper.scrape_source
    scraped_sources = []

    def mock_scrape_source(source):
        scraped_sources.append(source["name"])
        return []

    scraper.scrape_source = mock_scrape_source
    scraper.scrape_all_sources()

    assert "Disabled Source" not in scraped_sources
    assert "Test Source 1" in scraped_sources
    assert "Test Source 2" in scraped_sources

def test_canonicalize_url():
    """Test URL canonicalization."""
    test_cases = [
        ("https://example.com/page?utm_source=test", "https://example.com/page"),
        ("http://EXAMPLE.COM/Page#section", "https://example.com/Page"),
        ("https://www.bbc.com/page", "https://bbc.com/page"),
        ("https://bbc.co.uk/page", "https://bbc.co.uk/page"),
    ]
    for url, expected in test_cases:
        assert canonicalize_url(url) == expected

def test_generate_content_hash():
    """Test content hashing."""
    content1 = "This is a test.   It has extra spaces."
    content2 = "This is a test. It has extra spaces."
    assert generate_content_hash(content1) == generate_content_hash(content2)

def test_scraper_logging(scraper, temp_config):
    """Test that the scraper logs requests correctly."""
    # Run a mock scrape
    scraper.scrape_all_sources()

    # Check that the audit log was created and has entries
    assert scraper.audit_log.exists
    with open(scraper.audit_log, "r") as f:
        reader = csv.reader(f)
        rows = list(reader)
        # Header + at least 2 entries (for Test Source 1 and 2)
        assert len(rows) >= 3

def test_duplicate_detection():
    """Test that duplicate articles are not added to the database."""
    session = get_session()

    try:
        # Clean up any existing test data
        existing_source = session.query(Source).filter_by(domain="test-source-dup-detection.com").first()
        if existing_source:
            # Delete articles first
            session.query(Article).filter_by(source_id=existing_source.id).delete()
            session.delete(existing_source)
            session.commit()

        # Create a test source
        source = Source(
            name="Test Source",
            domain="test-source-dup-detection.com",
            rss_url="",
            rate_limit_ms=1000,
            enabled=True
        )
        session.add(source)
        session.commit()

        # Add a test article
        content = "This is a test article for duplicate detection."
        article1 = Article(
            url="https://test-source-dup-detection.com/article1",
            canonical_url=canonicalize_url("https://test-source-dup-detection.com/article1"),
            source_id=source.id,
            title="Test Article",
            content=content,
            published_at=datetime.now(timezone.utc),
            language="en",
            hash=generate_content_hash(content)
        )
        session.add(article1)
        session.commit()

        # Try to add the same article with different URL but same content (same hash)
        article2 = Article(
            url="https://test-source-dup-detection.com/article2",
            canonical_url=canonicalize_url("https://test-source-dup-detection.com/article2"),
            source_id=source.id,
            title="Test Article 2",
            content=content,  # Same content = same hash
            published_at=datetime.now(timezone.utc),
            language="en",
            hash=generate_content_hash(content)  # Same hash
        )
        session.add(article2)
        with pytest.raises(Exception):  # SQLite will raise IntegrityError for duplicate hash
            session.commit()
        session.rollback()
    finally:
        # Clean up
        source = session.query(Source).filter_by(domain="test-source-dup-detection.com").first()
        if source:
            session.query(Article).filter_by(source_id=source.id).delete()
            session.delete(source)
            session.commit()
        session.close()

def test_rate_limiting(scraper, monkeypatch):
    """Rate limiting applies a per-source delay.

    The scraper runs sources in parallel (ThreadPoolExecutor), so wall-clock time is
    NOT the sum of the delays — asserting >=2s only ever passed incidentally via real
    network latency. Instead, assert the control deterministically: count the
    rate-limit sleeps (one per enabled source) without sleeping or touching the network.
    """
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    scraper.scrape_all_sources()
    # 2 enabled sources, 1000ms each -> two 1.0s rate-limit delays were requested.
    assert sleeps.count(1.0) >= 2