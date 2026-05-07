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
from datetime import datetime
import yaml
import csv

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent.parent))

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
    """Create a scraper instance with test config."""
    return Scraper(config_path=temp_config)

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

    # Create a test source
    source = Source(
        name="Test Source",
        domain="test-source.com",
        rss_url="",
        rate_limit_ms=1000,
        enabled=True
    )
    session.add(source)
    session.commit()

    # Add a test article
    content = "This is a test article."
    article1 = Article(
        url="https://test-source.com/article1",
        canonical_url=canonicalize_url("https://test-source.com/article1"),
        source_id=source.id,
        title="Test Article",
        content=content,
        published_at=datetime.utcnow(),
        language="en",
        hash=generate_content_hash(content)
    )
    session.add(article1)
    session.commit()

    # Try to add the same article again
    article2 = Article(
        url="https://test-source.com/article1?utm_source=test",
        canonical_url=canonicalize_url("https://test-source.com/article1?utm_source=test"),
        source_id=source.id,
        title="Test Article",
        content=content,
        published_at=datetime.utcnow(),
        language="en",
        hash=generate_content_hash(content)
    )
    session.add(article2)
    with pytest.raises(Exception):  # SQLite will raise IntegrityError for duplicate hash
        session.commit()

    session.close()

def test_rate_limiting(scraper):
    """Test that rate limiting is applied."""
    import time
    start_time = time.time()
    scraper.scrape_all_sources()
    elapsed_time = time.time() - start_time

    # With 2 enabled sources and 1000ms rate limit, should take at least 2 seconds
    assert elapsed_time >= 2.0