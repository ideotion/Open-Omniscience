"""
URL Utilities for Open Omniscience

This module provides functions for:
- Canonicalizing URLs (removing tracking parameters, normalizing schemes)
- Resolving redirects to final URLs
- Generating content hashes for duplicate detection

Author: Ideotion
"""

from urllib.parse import urlparse, urlunparse, parse_qs
import requests
import hashlib
import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../../audit/url_utils.log"),
        logging.StreamHandler()
    ]
)


def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL by:
    1. Stripping tracking parameters (e.g., utm_*, gclid)
    2. Normalizing the scheme (http:// → https://)
    3. Removing fragments (#)
    4. Lowercasing the domain
    
    Args:
        url: The URL to canonicalize.
        
    Returns:
        The canonicalized URL.
    """
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        
        # Normalize scheme
        scheme = parsed.scheme if parsed.scheme else "https"
        
        # Normalize domain (lowercase)
        netloc = parsed.netloc.lower()
        
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
        "https://example.com/page?gclid=abc&param=value"
    ]
    
    for url in test_urls:
        canonical = canonicalize_url(url)
        print(f"Original: {url}")
        print(f"Canonical: {canonical}")
        print("---")
    
    # Test resolve_redirects (commented out as it requires network)
    # print(resolve_redirects("http://example.com"))
    
    # Test generate_content_hash
    content1 = "This is a test article.   It has extra spaces."
    content2 = "This is a test article. It has extra spaces."
    print(f"Hash 1: {generate_content_hash(content1)}")
    print(f"Hash 2: {generate_content_hash(content2)}")  # Should match Hash 1
