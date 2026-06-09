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
Source Monitor for Open Omniscience

This module provides health checks and local caching for news sources.
It monitors source availability, response times, and caches responses locally
to avoid redundant external calls.

Author: Ideotion
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import feedparser
import requests
from bs4 import BeautifulSoup

# Configure logging
from src.utils.logging_config import setup_logging

logger = setup_logging("source_monitor")


class SourceStatus(Enum):
    """Status of a source health check."""
    HEALTHY = "healthy"
    SLOW = "slow"
    UNREACHABLE = "unreachable"
    INVALID_CONTENT = "invalid_content"
    BLOCKED = "blocked"


@dataclass
class SourceHealth:
    """Health information for a source."""
    domain: str
    status: SourceStatus
    response_time_ms: float = 0.0
    last_checked: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_success: datetime | None = None
    consecutive_failures: int = 0
    error_message: str | None = None
    content_type: str | None = None
    content_length: int = 0
    
    def is_healthy(self) -> bool:
        """Check if source is healthy."""
        return self.status == SourceStatus.HEALTHY
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "status": self.status.value,
            "response_time_ms": self.response_time_ms,
            "last_checked": self.last_checked.isoformat(),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "consecutive_failures": self.consecutive_failures,
            "error_message": self.error_message,
            "content_type": self.content_type,
            "content_length": self.content_length
        }


@dataclass
class CachedResponse:
    """Cached response from a source."""
    url: str
    content: bytes
    content_type: str
    timestamp: datetime
    expires: datetime
    hash: str
    
    def is_expired(self) -> bool:
        """Check if cache has expired."""
        return datetime.now(UTC) > self.expires
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "content": self.content.decode('utf-8', errors='ignore'),
            "content_type": self.content_type,
            "timestamp": self.timestamp.isoformat(),
            "expires": self.expires.isoformat(),
            "hash": self.hash
        }


class SourceMonitor:
    """
    Monitors source health and provides local caching.
    
    Features:
    - Health checks for all configured sources
    - Local caching of responses
    - Rate limiting and retry logic
    - Persistent health history
    """
    
    DEFAULT_CACHE_DIR = "cache/sources"
    DEFAULT_HEALTH_HISTORY_FILE = "audit/source_health.json"
    DEFAULT_CACHE_TTL = 3600  # 1 hour in seconds
    MAX_CACHE_SIZE = 1000  # Maximum number of cached responses
    HEALTH_CHECK_TIMEOUT = 10  # seconds
    SLOW_THRESHOLD_MS = 5000  # 5 seconds
    
    def __init__(self, config_path: str | None = None, cache_dir: str | None = None):
        """
        Initialize the source monitor.
        
        Args:
            config_path: Path to sources.yml configuration file.
            cache_dir: Directory for caching responses.
        """
        # Get repository root
        self.repo_root = Path(__file__).parent.parent.parent.resolve()
        
        # Load sources configuration
        if config_path is None:
            config_path = self.repo_root / "configs" / "sources.yml"
        
        self.config_path = Path(config_path)
        self.sources = self._load_sources()
        
        # Setup cache directory
        if cache_dir is None:
            cache_dir = self.repo_root / self.DEFAULT_CACHE_DIR
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup health history file
        self.health_history_path = self.repo_root / self.DEFAULT_HEALTH_HISTORY_FILE
        self.health_history_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize caches
        self._response_cache: dict[str, CachedResponse] = {}
        self._health_cache: dict[str, SourceHealth] = {}
        self._health_history: list[dict] = []
        
        # Load persistent data
        self._load_health_history()
        self._load_cache()
        
        # Session for HTTP requests
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OpenOmniscience/1.0 SourceMonitor (+https://github.com/ideotion/Open-Omniscience)"
        })
        
        logger.info(f"SourceMonitor initialized with {len(self.sources)} sources")
    
    def _load_sources(self) -> list[dict]:
        """Load sources from configuration file."""
        import yaml
        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
                return config.get("sources", [])
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_path}")
            return []
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in config file: {e}")
            return []
    
    def _load_cache(self):
        """Load cached responses from disk."""
        cache_file = self.cache_dir / "response_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    self._response_cache = json.load(f)
                    logger.info(f"Loaded {len(self._response_cache)} cached responses")
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Error loading cache: {e}")
    
    def _save_cache(self):
        """Save cached responses to disk."""
        cache_file = self.cache_dir / "response_cache.json"
        try:
            with open(cache_file, "w") as f:
                json.dump(self._response_cache, f)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
    
    def _load_health_history(self):
        """Load health history from disk."""
        if self.health_history_path.exists():
            try:
                import json
                with open(self.health_history_path) as f:
                    self._health_history = json.load(f)
                logger.info(f"Loaded {len(self._health_history)} health history entries")
            except Exception as e:
                logger.error(f"Error loading health history: {e}")
    
    def _save_health_history(self):
        """Save health history to disk."""
        try:
            import json
            with open(self.health_history_path, "w") as f:
                json.dump(self._health_history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving health history: {e}")
    
    def _generate_hash(self, content: bytes) -> str:
        """Generate SHA-256 hash of content."""
        return hashlib.sha256(content).hexdigest()
    
    def check_source_health(self, source: dict) -> SourceHealth:
        """
        Check the health of a single source.
        
        Args:
            source: Source configuration dictionary.
            
        Returns:
            SourceHealth object with health information.
        """
        domain = source.get("domain", "")
        rss_url = source.get("rss_url", "")
        url = rss_url if rss_url else f"https://{domain}"
        
        if not domain:
            return SourceHealth(
                domain=domain,
                status=SourceStatus.INVALID_CONTENT,
                error_message="No domain specified"
            )
        
        start_time = time.time()
        
        try:
            # Check if source is enabled
            if not source.get("enabled", True):
                return SourceHealth(
                    domain=domain,
                    status=SourceStatus.HEALTHY,
                    error_message="Source disabled"
                )
            
            # Try to fetch the URL
            response = self.session.get(url, timeout=self.HEALTH_CHECK_TIMEOUT)
            response_time_ms = (time.time() - start_time) * 1000
            
            if response.status_code >= 400:
                return SourceHealth(
                    domain=domain,
                    status=SourceStatus.UNREACHABLE,
                    response_time_ms=response_time_ms,
                    error_message=f"HTTP {response.status_code}"
                )
            
            # Check content type
            content_type = response.headers.get("Content-Type", "")
            content_length = len(response.content)
            
            # Validate content based on source type
            if rss_url:
                # For RSS feeds, check if it's valid XML
                try:
                    feedparser.parse(response.content)
                except Exception as e:
                    return SourceHealth(
                        domain=domain,
                        status=SourceStatus.INVALID_CONTENT,
                        response_time_ms=response_time_ms,
                        content_type=content_type,
                        content_length=content_length,
                        error_message=f"Invalid RSS feed: {e}"
                    )
            else:
                # For HTML, check if it's valid
                try:
                    soup = BeautifulSoup(response.content, "html.parser")
                    if not soup.html:
                        return SourceHealth(
                            domain=domain,
                            status=SourceStatus.INVALID_CONTENT,
                            response_time_ms=response_time_ms,
                            content_type=content_type,
                            content_length=content_length,
                            error_message="No valid HTML content"
                        )
                except Exception as e:
                    return SourceHealth(
                        domain=domain,
                        status=SourceStatus.INVALID_CONTENT,
                        response_time_ms=response_time_ms,
                        content_type=content_type,
                        content_length=content_length,
                        error_message=f"Invalid HTML: {e}"
                    )
            
            # Check response time
            if response_time_ms > self.SLOW_THRESHOLD_MS:
                return SourceHealth(
                    domain=domain,
                    status=SourceStatus.SLOW,
                    response_time_ms=response_time_ms,
                    content_type=content_type,
                    content_length=content_length
                )
            
            return SourceHealth(
                domain=domain,
                status=SourceStatus.HEALTHY,
                response_time_ms=response_time_ms,
                content_type=content_type,
                content_length=content_length,
                last_success=datetime.now(UTC)
            )
            
        except requests.exceptions.Timeout:
            return SourceHealth(
                domain=domain,
                status=SourceStatus.UNREACHABLE,
                response_time_ms=self.HEALTH_CHECK_TIMEOUT * 1000,
                error_message="Request timeout"
            )
        except requests.exceptions.RequestException as e:
            return SourceHealth(
                domain=domain,
                status=SourceStatus.UNREACHABLE,
                error_message=str(e)
            )
        except Exception as e:
            return SourceHealth(
                domain=domain,
                status=SourceStatus.INVALID_CONTENT,
                error_message=str(e)
            )
    
    def check_all_sources(self) -> dict[str, SourceHealth]:
        """
        Check health of all configured sources.
        
        Returns:
            Dictionary mapping domain to SourceHealth.
        """
        health_results = {}
        
        for source in self.sources:
            domain = source.get("domain", "")
            if not domain:
                continue
            
            health = self.check_source_health(source)
            health_results[domain] = health
            
            # Update health history
            self._health_history.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "domain": domain,
                "status": health.status.value,
                "response_time_ms": health.response_time_ms,
                "error_message": health.error_message
            })
            
            # Keep history manageable
            if len(self._health_history) > 10000:
                self._health_history = self._health_history[-5000:]
            
            # Update cache
            self._health_cache[domain] = health
            
            # Log status
            if health.is_healthy():
                logger.info(f"✓ {domain}: {health.status.value} ({health.response_time_ms:.2f}ms)")
            else:
                logger.warning(f"✗ {domain}: {health.status.value} - {health.error_message}")
            
            # Rate limiting
            time.sleep(source.get("rate_limit_ms", 2000) / 1000)
        
        # Save persistent data
        self._save_health_history()
        
        return health_results
    
    def get_source_health(self, domain: str) -> SourceHealth | None:
        """
        Get the current health status of a source.
        
        Args:
            domain: Domain of the source.
            
        Returns:
            SourceHealth if available, None otherwise.
        """
        return self._health_cache.get(domain)
    
    def get_healthy_sources(self) -> list[str]:
        """
        Get list of domains for healthy sources.
        
        Returns:
            List of domain names.
        """
        return [domain for domain, health in self._health_cache.items() if health.is_healthy()]
    
    def get_unhealthy_sources(self) -> list[str]:
        """
        Get list of domains for unhealthy sources.
        
        Returns:
            List of domain names.
        """
        return [domain for domain, health in self._health_cache.items() if not health.is_healthy()]
    
    def cache_response(self, url: str, content: bytes, content_type: str, ttl: int = None) -> CachedResponse:
        """
        Cache a response locally.
        
        Args:
            url: URL of the response.
            content: Response content as bytes.
            content_type: Content type header.
            ttl: Time to live in seconds (default: DEFAULT_CACHE_TTL).
            
        Returns:
            CachedResponse object.
        """
        if ttl is None:
            ttl = self.DEFAULT_CACHE_TTL
        
        cached = CachedResponse(
            url=url,
            content=content,
            content_type=content_type,
            timestamp=datetime.now(UTC),
            expires=datetime.now(UTC) + timedelta(seconds=ttl),
            hash=self._generate_hash(content)
        )
        
        # Store in memory cache
        self._response_cache[url] = cached
        
        # Save to disk
        self._save_cache()
        
        # Clean up old cache entries
        self._cleanup_cache()
        
        return cached
    
    def get_cached_response(self, url: str) -> CachedResponse | None:
        """
        Get a cached response if available and not expired.
        
        Args:
            url: URL to look up.
            
        Returns:
            CachedResponse if available and valid, None otherwise.
        """
        cached = self._response_cache.get(url)
        if cached and not cached.is_expired():
            return cached
        return None
    
    def _cleanup_cache(self):
        """Remove expired and excess cache entries."""
        now = datetime.now(UTC)
        
        # Remove expired entries
        expired_urls = [
            url for url, cached in self._response_cache.items()
            if cached.is_expired()
        ]
        for url in expired_urls:
            del self._response_cache[url]
        
        # Enforce max cache size
        if len(self._response_cache) > self.MAX_CACHE_SIZE:
            # Remove oldest entries
            sorted_entries = sorted(
                self._response_cache.items(),
                key=lambda x: x[1].timestamp
            )
            for url, _ in sorted_entries[:len(self._response_cache) - self.MAX_CACHE_SIZE]:
                del self._response_cache[url]
        
        # Save after cleanup
        self._save_cache()
    
    def clear_cache(self):
        """Clear all cached responses."""
        self._response_cache.clear()
        self._save_cache()
        logger.info("Cache cleared")
    
    def get_cache_stats(self) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics.
        """
        now = datetime.now(UTC)
        valid_count = sum(1 for c in self._response_cache.values() if not c.is_expired())
        expired_count = sum(1 for c in self._response_cache.values() if c.is_expired())
        
        return {
            "total_entries": len(self._response_cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "max_size": self.MAX_CACHE_SIZE,
            "cache_dir": str(self.cache_dir)
        }
    
    def get_health_stats(self) -> dict:
        """
        Get health monitoring statistics.
        
        Returns:
            Dictionary with health statistics.
        """
        total = len(self._health_cache)
        healthy = sum(1 for h in self._health_cache.values() if h.is_healthy())
        unhealthy = total - healthy
        
        avg_response_time = sum(
            h.response_time_ms for h in self._health_cache.values()
        ) / total if total > 0 else 0
        
        return {
            "total_sources": total,
            "healthy_sources": healthy,
            "unhealthy_sources": unhealthy,
            "average_response_time_ms": avg_response_time,
            "last_check": datetime.now(UTC).isoformat()
        }
    
    def get_source_info(self, domain: str) -> dict | None:
        """
        Get information about a specific source from configuration.
        
        Args:
            domain: Domain of the source.
            
        Returns:
            Source configuration dictionary or None.
        """
        for source in self.sources:
            if source.get("domain") == domain:
                return source
        return None
    
    def close(self):
        """Clean up resources."""
        self.session.close()
        self._save_cache()
        self._save_health_history()
        logger.info("SourceMonitor closed")


if __name__ == "__main__":
    monitor = SourceMonitor()
    try:
        # Check all sources
        print("Checking source health...")
        results = monitor.check_all_sources()
        
        # Print summary
        stats = monitor.get_health_stats()
        print(f"\nHealth Check Summary:")
        print(f"  Total sources: {stats['total_sources']}")
        print(f"  Healthy: {stats['healthy_sources']}")
        print(f"  Unhealthy: {stats['unhealthy_sources']}")
        print(f"  Avg response time: {stats['average_response_time_ms']:.2f}ms")
        
        # Print unhealthy sources
        unhealthy = monitor.get_unhealthy_sources()
        if unhealthy:
            print(f"\nUnhealthy sources:")
            for domain in unhealthy:
                health = monitor.get_source_health(domain)
                print(f"  - {domain}: {health.status.value} - {health.error_message}")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        monitor.close()
