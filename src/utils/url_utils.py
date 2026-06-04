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

This module provides centralized functions for:
- Canonicalizing URLs (removing tracking parameters, normalizing schemes)
- Resolving redirects to final URLs
- Generating content hashes for duplicate detection
- Normalizing domains (e.g., stripping www., lowercase)
- Deduplicating URLs (e.g., bbc.com = bbc.co.uk)

Author: Ideotion
"""

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse, urlunparse

import requests

# Configure logging
logger = logging.getLogger(__name__)

# Known domain aliases for equivalent domain checking
DOMAIN_ALIASES: dict[str, list[str]] = {
    "bbc.com": ["bbc.co.uk"],
    "theguardian.com": ["guardian.co.uk"],
    "independent.co.uk": ["independent.com"],
    "nytimes.com": ["nyt.com"],
    "washingtonpost.com": ["washingtonpost.com"],
}


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain by:
    1. Lowercasing
    2. Stripping www. prefix
    3. Stripping trailing slashes
    4. Removing default ports (80, 443)

    Args:
        domain: The domain to normalize.

    Returns:
        The normalized domain.
    """
    if not domain:
        return domain

    domain = domain.lower().strip()
    
    # Remove default ports
    if domain.endswith(":80"):
        domain = domain[:-3]
    elif domain.endswith(":443"):
        domain = domain[:-4]
    
    # Strip www. prefix
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

    # Check if domain1 is an alias of domain2 or vice versa
    if domain1 in DOMAIN_ALIASES and domain2 in DOMAIN_ALIASES[domain1]:
        return True
    if domain2 in DOMAIN_ALIASES and domain1 in DOMAIN_ALIASES[domain2]:
        return True

    return False


def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL by:
    1. Stripping tracking parameters (e.g., utm_*, gclid)
    2. Normalizing the scheme (http:// → https://)
    3. Removing fragments (#)
    4. Lowercasing the domain
    5. Normalizing the domain (strip www., remove default ports)
    6. Removing empty path (set to /)
    7. Removing trailing slash from path (except root)

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

        # Normalize domain (lowercase, strip www., remove default ports)
        netloc = normalize_domain(parsed.netloc)

        # Remove tracking parameters
        query = parse_qs(parsed.query, keep_blank_values=True)
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'gclid', 'fbclid', 'mc_cid', 'mc_eid', 'dclid', 'msclkid'
        }
        filtered_query = {k: v for k, v in query.items() if k.lower() not in tracking_params}
        
        # Sort remaining query parameters for consistency, preserving ALL values of
        # multi-valued params (a=1&a=2 must not collapse to a=1 -- that changes
        # semantics and dedup).
        sorted_query = dict(sorted(filtered_query.items()))
        clean_query = "&".join(
            f"{k}={val}" for k, vals in sorted_query.items() for val in vals
        )

        # Normalize path
        path = parsed.path
        if not path:
            path = '/'
        elif len(path) > 1 and path.endswith('/'):
            path = path.rstrip('/')

        # Rebuild URL
        canonical_url = urlunparse((
            scheme,
            netloc,
            path,
            parsed.params,
            clean_query,
            ""  # Remove fragment
        ))

        return canonical_url

    except Exception as e:
        logger.error(f"Error canonicalizing URL {url}: {e}")
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
        logger.warning(f"Too many redirects for URL: {url}")
        return url
    except requests.exceptions.RequestException as e:
        logger.error(f"Error resolving redirects for {url}: {e}")
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


def get_domain_from_url(url: str) -> str | None:
    """
    Extract the domain from a URL.

    Args:
        url: The URL to extract domain from.

    Returns:
        The domain (netloc) or None if URL is invalid.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc:
            return normalize_domain(parsed.netloc)
        return None
    except Exception as e:
        logger.error(f"Error extracting domain from {url}: {e}")
        return None


def get_base_url(url: str) -> str | None:
    """
    Get the base URL (scheme + netloc) from a URL.

    Args:
        url: The URL to get base URL from.

    Returns:
        The base URL or None if URL is invalid.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{normalize_domain(parsed.netloc)}"
        return None
    except Exception as e:
        logger.error(f"Error getting base URL from {url}: {e}")
        return None
