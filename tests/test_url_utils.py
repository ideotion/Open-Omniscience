"""
Unit Tests for Open Omniscience URL Utilities

Tests for canonicalize_url, resolve_redirects, and generate_content_hash functions.

Author: Ideotion
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.ingestor.url_utils import canonicalize_url, generate_content_hash


def test_canonicalize_url():
    """Test URL canonicalization."""
    # Test stripping tracking parameters
    assert canonicalize_url("https://example.com/page?utm_source=test&id=123") == "https://example.com/page?id=123"
    assert canonicalize_url("https://example.com/page?gclid=abc&param=value") == "https://example.com/page?param=value"
    
    # Test scheme normalization
    assert canonicalize_url("http://example.com") == "https://example.com"
    assert canonicalize_url("HTTP://EXAMPLE.COM") == "https://example.com"
    
    # Test fragment removal
    assert canonicalize_url("https://example.com/page#section") == "https://example.com/page"
    
    # Test domain lowercasing
    assert canonicalize_url("https://EXAMPLE.COM") == "https://example.com"
    
    # Test empty input
    assert canonicalize_url("") == ""
    assert canonicalize_url(None) is None


def test_generate_content_hash():
    """Test content hashing."""
    # Test same content produces same hash
    content = "This is a test article.   It has extra spaces."
    content_cleaned = "This is a test article. It has extra spaces."
    hash1 = generate_content_hash(content)
    hash2 = generate_content_hash(content_cleaned)
    assert hash1 == hash2, "Same content should produce same hash"
    
    # Test different content produces different hash
    different_content = "This is a different article."
    hash3 = generate_content_hash(different_content)
    assert hash1 != hash3, "Different content should produce different hash"
    
    # Test empty content
    assert generate_content_hash("") == ""
    assert generate_content_hash(None) == ""
    
    # Test hash length (SHA-256 produces 64-character hex string)
    assert len(hash1) == 64


if __name__ == "__main__":
    # Run tests manually
    test_canonicalize_url()
    test_generate_content_hash()
    print("All tests passed!")