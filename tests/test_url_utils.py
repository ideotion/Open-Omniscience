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
Unit Tests for Open Omniscience URL Utilities

Tests for canonicalize_url, resolve_redirects, and generate_content_hash functions.

Author: Ideotion
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent / "src"))

from ingestor.url_utils import canonicalize_url, generate_content_hash


def test_canonicalize_url():
    """Test URL canonicalization."""
    # Test stripping tracking parameters
    assert canonicalize_url("https://example.com/page?utm_source=test&id=123") == "https://example.com/page?id=123"
    assert canonicalize_url("https://example.com/page?gclid=abc&param=value") == "https://example.com/page?param=value"
    
    # Test scheme normalization
    # Note: empty path is normalized to "/" to ensure canonical form
    assert canonicalize_url("http://example.com") == "https://example.com/"
    assert canonicalize_url("HTTP://EXAMPLE.COM") == "https://example.com/"
    
    # Test fragment removal
    assert canonicalize_url("https://example.com/page#section") == "https://example.com/page"
    
    # Test domain lowercasing
    # Note: empty path is normalized to "/" to ensure canonical form
    assert canonicalize_url("https://EXAMPLE.COM") == "https://example.com/"
    
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