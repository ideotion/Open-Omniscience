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
URL Utilities for Open Omniscience

This module provides functions for:
- Canonicalizing URLs (removing tracking parameters, normalizing schemes)
- Resolving redirects to final URLs
- Generating content hashes for duplicate detection
- Normalizing domains (e.g., stripping www., lowercase)
- Deduplicating URLs (e.g., bbc.com = bbc.co.uk)

Author: Ideotion
"""

from urllib.parse import urlparse, urlunparse, parse_qs
import requests
import hashlib
import logging
from typing import Optional

# Configure logging
from pathlib import Path

# Get the absolute path to the repository root
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
AUDIT_DIR = REPO_ROOT / "audit"
AUDIT_DIR.mkdir(exist_ok=True, parents=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(AUDIT_DIR / "url_utils.log")),
        logging.StreamHandler()
    ]
)

def normalize_domain(domain: str) -> str:
    """
    Normalize a domain by:
    1. Lowercasing
    2. Stripping www. prefix
    3. Stripping trailing slashes

    Args:
        domain: The domain to normalize.

    Returns:
        The normalized domain.
    """
    if not domain:
        return domain

    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip("/")

def is_equivalent_domain(domain1: str, domain2: str) -> bool:
    """
    Check if two domains are equivalent after normalization.
    Also handles known aliases (e.g., bbc.com = bbc.co.uk).

    Args:
        domain1: First domain.
        domain2: Second domain.

    Returns:
        True if domains are equivalent, False otherwise.
    """
    domain1 = normalize_domain(domain1)
    domain2 = normalize_domain(domain2)

    if domain1 == domain2:
        return True

    # Known domain aliases
    aliases = {
        "bbc.com": ["bbc.co.uk"],
        "theguardian.com": ["guardian.co.uk"],
        "independent.co.uk": ["independent.com"],
        "nytimes.com": ["nyt.com"],
        "washingtonpost.com": ["washingtonpost.com"],
    }

    # Check if domain1 is an alias of domain2 or vice versa
    if domain1 in aliases and domain2 in aliases[domain1]:
        return True
    if domain2 in aliases and domain1 in aliases[domain2]:
        return True

    return False

def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL by:
    1. Stripping tracking parameters (e.g., utm_*, gclid)
    2. Normalizing the scheme (http:// → https://)
    3. Removing fragments (#)
    4. Lowercasing the domain
    5. Normalizing the domain (strip www.)

    Args:
        url: The URL to canonicalize.

    Returns:
        The canonicalized URL.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Normalize scheme (force https)
        scheme = "https"

        # Normalize domain (lowercase, strip www.)
        netloc = normalize_domain(parsed.netloc)

        # Remove tracking parameters
        query = parse_qs(parsed.query, keep_blank_values=True)
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'gclid', 'fbclid', 'mc_cid', 'mc_eid', 'dclid', 'msclkid'
        }
        filtered_query = {k: v for k, v in query.items() if k.lower() not in tracking_params}
        clean_query = "&".join(f"{k}={v[0]}" for k, v in filtered_query.items()) if filtered_query else ""

        # Rebuild URL
        canonical_url = urlunparse((
            scheme,
            netloc,
            parsed.path,
            parsed.params,
            clean_query,
            ""  # Remove fragment
        ))

        return canonical_url

    except Exception as e:
        logging.error(f"Error canonicalizing URL {url}: {e}")
        return url

def resolve_redirects(url: str, max_redirects: int = 5) -> str:
    """
    Resolve all redirects for a URL to get the final destination.

    Args:
        url: The URL to resolve.
        max_redirects: Maximum number of redirects to follow.

    Returns:
        The final URL after all redirects.
    """
    if not url:
        return url

    try:
        # Ensure URL starts with http:// or https://
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"

        headers = {"User-Agent": "OpenOmniscience/1.0"}
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=10,
            headers=headers,
            max_redirects=max_redirects
        )
        return response.url

    except requests.exceptions.TooManyRedirects:
        logging.warning(f"Too many redirects for URL: {url}")
        return url
    except requests.exceptions.RequestException as e:
        logging.error(f"Error resolving redirects for {url}: {e}")
        return url

def generate_content_hash(content: str) -> str:
    """
    Generate a SHA-256 hash of the content for duplicate detection.

    Args:
        content: The text content to hash.

    Returns:
        The SHA-256 hash as a hexadecimal string.
    """
    if not content:
        return ""

    # Clean content: remove extra whitespace and normalize
    cleaned_content = " ".join(content.split())
    return hashlib.sha256(cleaned_content.encode("utf-8")).hexdigest()


# Example usage
if __name__ == "__main__":
    # Test canonicalize_url
    test_urls = [
        "https://example.com/page?utm_source=test&id=123",
        "http://EXAMPLE.COM/Page#section",
        "https://www.bbc.com/page?gclid=abc&param=value",
        "https://bbc.co.uk/page"
    ]
    
    for url in test_urls:
        canonical = canonicalize_url(url)
        print(f"Original: {url}")
        print(f"Canonical: {canonical}")
        print("---")

    # Test domain equivalence
    print(f"bbc.com == bbc.co.uk: {is_equivalent_domain('bbc.com', 'bbc.co.uk')}")
    print(f"bbc.com == cnn.com: {is_equivalent_domain('bbc.com', 'cnn.com')}")

    # Test generate_content_hash
    content1 = "This is a test article.   It has extra spaces."
    content2 = "This is a test article. It has extra spaces."
    print(f"Hash 1: {generate_content_hash(content1)}")
    print(f"Hash 2: {generate_content_hash(content2)}")  # Should match Hash 1