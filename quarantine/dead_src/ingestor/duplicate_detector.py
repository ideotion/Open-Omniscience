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
Open-Omniscience - Duplicate Detector

Detects duplicate content using URL canonicalization, hashing, and TTL-based caching.
"""

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse


@dataclass
class DuplicateCheckResult:
    """Result of a duplicate check."""
    is_duplicate: bool
    original_url: str | None = None
    original_hash: str | None = None
    similarity_score: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class DuplicateDetector:
    """
    Detects duplicate content using multiple methods:
    - URL canonicalization
    - Content hashing (SHA-256)
    - Text similarity (for near-duplicates)
    - Time-to-live (TTL) for cache expiration
    """

    def __init__(
        self,
        ttl_hours: float = 24.0,
        similarity_threshold: float = 0.95,
        max_cache_size: int = 10000,
    ):
        """
        Initialize the duplicate detector.
        
        Args:
            ttl_hours: Time-to-live for cached entries in hours.
            similarity_threshold: Threshold for considering content similar (0.0 to 1.0).
            max_cache_size: Maximum number of entries to keep in cache.
        """
        self.ttl_seconds = ttl_hours * 3600.0
        self.similarity_threshold = similarity_threshold
        self.max_cache_size = max_cache_size
        
        # URL cache: canonical_url -> (timestamp, original_url)
        self.url_cache: dict[str, tuple[float, str]] = {}
        
        # Content hash cache: hash -> (timestamp, original_url)
        self.hash_cache: dict[str, tuple[float, str]] = {}
        
        # Text content cache for similarity: hash -> (timestamp, text)
        self.text_cache: dict[str, tuple[float, str]] = {}
        
        # Statistics
        self.stats = {
            "total_checks": 0,
            "duplicates_found": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        
        self.logger = logging.getLogger("DuplicateDetector")

    def check_url(self, url: str) -> DuplicateCheckResult:
        """
        Check if a URL is a duplicate.
        
        Args:
            url: URL to check.
        
        Returns:
            DuplicateCheckResult with the check outcome.
        """
        self.stats["total_checks"] += 1
        
        # Canonicalize URL
        canonical = self.canonicalize_url(url)
        if not canonical:
            return DuplicateCheckResult(
                is_duplicate=False,
                metadata={"error": "Invalid URL"},
            )
        
        # Check URL cache
        if canonical in self.url_cache:
            timestamp, original_url = self.url_cache[canonical]
            
            # Check TTL
            if time.time() - timestamp <= self.ttl_seconds:
                self.stats["duplicates_found"] += 1
                self.stats["cache_hits"] += 1
                return DuplicateCheckResult(
                    is_duplicate=True,
                    original_url=original_url,
                    metadata={"method": "url_canonicalization"},
                )
        
        self.stats["cache_misses"] += 1
        return DuplicateCheckResult(
            is_duplicate=False,
            metadata={"method": "url_canonicalization"},
        )

    def check_content(self, content: str, url: str | None = None) -> DuplicateCheckResult:
        """
        Check if content is a duplicate.
        
        Args:
            content: Content to check.
            url: Optional URL associated with the content.
        
        Returns:
            DuplicateCheckResult with the check outcome.
        """
        self.stats["total_checks"] += 1
        
        # Generate hash
        content_hash = self.hash_content(content)
        
        # Check hash cache
        if content_hash in self.hash_cache:
            timestamp, original_url = self.hash_cache[content_hash]
            
            # Check TTL
            if time.time() - timestamp <= self.ttl_seconds:
                self.stats["duplicates_found"] += 1
                self.stats["cache_hits"] += 1
                return DuplicateCheckResult(
                    is_duplicate=True,
                    original_url=original_url,
                    original_hash=content_hash,
                    metadata={"method": "content_hash"},
                )
        
        # Check for similar content (near-duplicates)
        if self.similarity_threshold > 0:
            similar_result = self._check_similar_content(content, content_hash)
            if similar_result.is_duplicate:
                self.stats["duplicates_found"] += 1
                self.stats["cache_hits"] += 1
                return similar_result
        
        self.stats["cache_misses"] += 1
        return DuplicateCheckResult(
            is_duplicate=False,
            metadata={"method": "content_hash"},
        )

    def check(self, content: str, url: str) -> DuplicateCheckResult:
        """
        Check both URL and content for duplicates.
        
        Args:
            content: Content to check.
            url: URL of the content.
        
        Returns:
            DuplicateCheckResult with the check outcome.
        """
        # First check URL
        url_result = self.check_url(url)
        if url_result.is_duplicate:
            return url_result
        
        # Then check content
        content_result = self.check_content(content, url)
        if content_result.is_duplicate:
            return content_result
        
        return DuplicateCheckResult(
            is_duplicate=False,
            metadata={"url_check": url_result.to_dict(), "content_check": content_result.to_dict()},
        )

    def record(self, content: str, url: str) -> None:
        """
        Record content and URL for future duplicate checks.
        
        Args:
            content: Content to record.
            url: URL of the content.
        """
        # Canonicalize and cache URL
        canonical = self.canonicalize_url(url)
        if canonical:
            self.url_cache[canonical] = (time.time(), url)
        
        # Hash and cache content
        content_hash = self.hash_content(content)
        self.hash_cache[content_hash] = (time.time(), url)
        
        # Cache text for similarity checking
        if self.similarity_threshold > 0:
            self.text_cache[content_hash] = (time.time(), content)
        
        # Clean up old entries
        self._cleanup_cache()

    def canonicalize_url(self, url: str) -> str | None:
        """
        Canonicalize a URL for duplicate detection.
        
        Args:
            url: URL to canonicalize.
        
        Returns:
            Canonicalized URL, or None if invalid.
        """
        try:
            parsed = urlparse(url)
            
            # Remove fragment
            parsed = parsed._replace(fragment='')
            
            # Remove default port
            if (parsed.scheme == 'http' and parsed.port == 80) or \
               (parsed.scheme == 'https' and parsed.port == 443):
                parsed = parsed._replace(netloc=parsed.netloc.replace(f":{parsed.port}", ""))
            
            # Lowercase scheme and netloc
            parsed = parsed._replace(
                scheme=parsed.scheme.lower(),
                netloc=parsed.netloc.lower(),
            )
            
            # Sort query parameters
            if parsed.query:
                query_parts = parsed.query.split('&')
                query_parts = [p for p in query_parts if p]  # Remove empty
                query_parts.sort()
                parsed = parsed._replace(query='&'.join(query_parts))
            
            # Remove trailing slash from path
            path = parsed.path.rstrip('/')
            parsed = parsed._replace(path=path)
            
            # Reconstruct URL
            return urlunparse(parsed)
            
        except Exception as e:
            self.logger.warning(f"Error canonicalizing URL {url}: {e}")
            return None

    def hash_content(self, content: str) -> str:
        """
        Generate a SHA-256 hash of content.
        
        Args:
            content: Content to hash.
        
        Returns:
            SHA-256 hash as hex string.
        """
        # Normalize content (remove extra whitespace, etc.)
        normalized = self._normalize_content(content)
        return hashlib.sha256(normalized.encode('utf-8', errors='ignore')).hexdigest()

    def _normalize_content(self, content: str) -> str:
        """
        Normalize content for hashing.
        
        Args:
            content: Content to normalize.
        
        Returns:
            Normalized content.
        """
        # Remove HTML tags if present
        content = re.sub(r'<[^>]+>', ' ', content)
        
        # Remove extra whitespace
        content = re.sub(r'\s+', ' ', content)
        
        # Remove leading/trailing whitespace
        content = content.strip()
        
        # Convert to lowercase (optional, for case-insensitive comparison)
        # content = content.lower()
        
        return content

    def _check_similar_content(self, content: str, content_hash: str) -> DuplicateCheckResult:
        """
        Check for similar content using text similarity.
        
        Args:
            content: Content to check.
            content_hash: Hash of the content.
        
        Returns:
            DuplicateCheckResult if similar content is found.
        """
        # Extract text features
        normalized_content = self._normalize_content(content)
        
        # Compare with cached content
        for cached_hash, (timestamp, cached_content) in self.text_cache.items():
            # Skip if expired
            if time.time() - timestamp > self.ttl_seconds:
                continue
            
            # Skip same hash (exact duplicate already handled)
            if cached_hash == content_hash:
                continue
            
            # Calculate similarity
            similarity = self._text_similarity(normalized_content, cached_content)
            
            if similarity >= self.similarity_threshold:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    original_hash=cached_hash,
                    similarity_score=similarity,
                    metadata={"method": "text_similarity", "similarity": similarity},
                )
        
        return DuplicateCheckResult(
            is_duplicate=False,
            metadata={"method": "text_similarity"},
        )

    def _text_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts using Jaccard similarity on words.
        
        Args:
            text1: First text.
            text2: Second text.
        
        Returns:
            Similarity score between 0.0 and 1.0.
        """
        # Tokenize into words
        words1 = set(re.findall(r'\b\w+\b', text1.lower()))
        words2 = set(re.findall(r'\b\w+\b', text2.lower()))
        
        if not words1 or not words2:
            return 0.0
        
        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0

    def _cleanup_cache(self) -> None:
        """Clean up old cache entries."""
        now = time.time()
        
        # Clean URL cache
        self.url_cache = {
            url: (ts, orig) for url, (ts, orig) in self.url_cache.items()
            if now - ts <= self.ttl_seconds
        }
        
        # Clean hash cache
        self.hash_cache = {
            h: (ts, orig) for h, (ts, orig) in self.hash_cache.items()
            if now - ts <= self.ttl_seconds
        }
        
        # Clean text cache
        self.text_cache = {
            h: (ts, text) for h, (ts, text) in self.text_cache.items()
            if now - ts <= self.ttl_seconds
        }
        
        # Enforce max cache size
        if len(self.url_cache) > self.max_cache_size:
            # Remove oldest entries
            sorted_urls = sorted(self.url_cache.items(), key=lambda x: x[1][0])
            self.url_cache = dict(sorted_urls[-self.max_cache_size:])
        
        if len(self.hash_cache) > self.max_cache_size:
            sorted_hashes = sorted(self.hash_cache.items(), key=lambda x: x[1][0])
            self.hash_cache = dict(sorted_hashes[-self.max_cache_size:])

    def clear_cache(self) -> None:
        """Clear all caches."""
        self.url_cache.clear()
        self.hash_cache.clear()
        self.text_cache.clear()
        self.logger.info("Duplicate detector cache cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get duplicate detector statistics."""
        return {
            "total_checks": self.stats["total_checks"],
            "duplicates_found": self.stats["duplicates_found"],
            "cache_hits": self.stats["cache_hits"],
            "cache_misses": self.stats["cache_misses"],
            "url_cache_size": len(self.url_cache),
            "hash_cache_size": len(self.hash_cache),
            "text_cache_size": len(self.text_cache),
            "ttl_seconds": self.ttl_seconds,
            "similarity_threshold": self.similarity_threshold,
            "max_cache_size": self.max_cache_size,
        }

    def set_ttl(self, ttl_hours: float) -> None:
        """Set the TTL for cache entries."""
        self.ttl_seconds = ttl_hours * 3600.0
        self.logger.info(f"TTL set to {ttl_hours} hours")

    def set_similarity_threshold(self, threshold: float) -> None:
        """Set the similarity threshold."""
        self.similarity_threshold = threshold
        self.logger.info(f"Similarity threshold set to {threshold}")


# Global duplicate detector instance (optional)
_default_detector = None


def get_duplicate_detector(
    ttl_hours: float = 24.0,
    similarity_threshold: float = 0.95,
    max_cache_size: int = 10000,
) -> DuplicateDetector:
    """
    Get or create the default duplicate detector.
    
    Args:
        ttl_hours: Time-to-live for cached entries in hours.
        similarity_threshold: Threshold for considering content similar.
        max_cache_size: Maximum number of entries to keep in cache.
    
    Returns:
        DuplicateDetector instance.
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = DuplicateDetector(ttl_hours, similarity_threshold, max_cache_size)
    return _default_detector
