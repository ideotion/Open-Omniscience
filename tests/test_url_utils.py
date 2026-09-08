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

Tests for canonicalize_url and generate_content_hash functions.

Author: Ideotion
"""

from src.utils.url_utils import DOMAIN_ALIASES, canonicalize_url, generate_content_hash, is_equivalent_domain


def test_canonicalize_url():
    """Test URL canonicalization."""
    # Test stripping tracking parameters
    assert (
        canonicalize_url("https://example.com/page?utm_source=test&id=123")
        == "https://example.com/page?id=123"
    )
    assert (
        canonicalize_url("https://example.com/page?gclid=abc&param=value")
        == "https://example.com/page?param=value"
    )

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


def test_is_equivalent_domain_same_domain():
    """A domain is always equivalent to itself, via the equality short-circuit --
    independent of whatever DOMAIN_ALIASES happens to contain (or not) for it."""
    assert is_equivalent_domain("washingtonpost.com", "washingtonpost.com") is True
    assert is_equivalent_domain("www.washingtonpost.com", "washingtonpost.com") is True
    assert is_equivalent_domain("example.com", "example.com") is True


def test_is_equivalent_domain_known_aliases():
    """Real (non-self-referential) alias pairs from DOMAIN_ALIASES resolve as
    equivalent in both directions."""
    assert is_equivalent_domain("bbc.com", "bbc.co.uk") is True
    assert is_equivalent_domain("bbc.co.uk", "bbc.com") is True
    assert is_equivalent_domain("nytimes.com", "nyt.com") is True


def test_domain_aliases_has_no_self_referential_entries():
    """DOMAIN_ALIASES must never map a domain to itself -- such an entry is dead
    weight, since is_equivalent_domain() already returns True on domain1 ==
    domain2 before the alias table is consulted (regression test for a
    washingtonpost.com -> ["washingtonpost.com"] no-op entry)."""
    for domain, aliases in DOMAIN_ALIASES.items():
        assert domain not in aliases, f"{domain!r} is listed as its own alias"


if __name__ == "__main__":
    # Run tests manually
    test_canonicalize_url()
    test_generate_content_hash()
    test_is_equivalent_domain_same_domain()
    test_is_equivalent_domain_known_aliases()
    test_domain_aliases_has_no_self_referential_entries()
    print("All tests passed!")
