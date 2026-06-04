"""
Base Scraper Module

Provides the foundation for ethical web scraping with:
- Rate limiting (configurable per domain)
- Caching (24-hour cache by default)
- User-agent identification
- robots.txt respect
- Retry logic with exponential backoff
"""

import time
import hashlib
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import yaml


@dataclass
class ScraperConfig:
    """Configuration for ethical scraping."""
    user_agent: str = "OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)"
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 2.0
    rate_limit_enabled: bool = True
    default_rate_limit: float = 2.0  # seconds between requests to same domain
    domain_rate_limits: Dict[str, float] = field(default_factory=dict)
    cache_enabled: bool = True
    cache_directory: str = "data/cache"
    cache_expiration: int = 86400  # 24 hours in seconds
    max_cache_size_mb: int = 1000
    respect_robots_txt: bool = True
    
    @classmethod
    def from_yaml(cls, config_path: str) -> "ScraperConfig":
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        return cls(
            user_agent=config_data.get('user_agent', cls.user_agent),
            request_timeout=config_data.get('request_timeout', cls.request_timeout),
            max_retries=config_data.get('max_retries', cls.max_retries),
            retry_delay=config_data.get('retry_delay', cls.retry_delay),
            rate_limit_enabled=config_data.get('rate_limit', {}).get('enabled', True),
            default_rate_limit=config_data.get('rate_limit', {}).get('default_delay', 2.0),
            domain_rate_limits=config_data.get('rate_limit', {}).get('domain_delays', {}),
            cache_enabled=config_data.get('cache', {}).get('enabled', True),
            cache_directory=config_data.get('cache', {}).get('directory', 'data/cache'),
            cache_expiration=config_data.get('cache', {}).get('expiration', 86400),
            max_cache_size_mb=config_data.get('cache', {}).get('max_size_mb', 1000),
            respect_robots_txt=config_data.get('respect_robots_txt', True),
        )


class RateLimiter:
    """
    Rate limiter to respect website policies.
    Tracks last request time per domain and enforces minimum delay.
    """
    
    def __init__(self, default_delay: float = 2.0, domain_delays: Optional[Dict[str, float]] = None):
        """
        Initialize rate limiter.
        
        Args:
            default_delay: Default delay in seconds between requests to the same domain
            domain_delays: Dictionary of domain-specific delays
        """
        self.default_delay = default_delay
        self.domain_delays = domain_delays or {}
        self.last_request_times: Dict[str, float] = {}
        self.request_counts: Dict[str, int] = {}
    
    def get_delay(self, domain: str) -> float:
        """Get the delay for a specific domain."""
        return self.domain_delays.get(domain, self.default_delay)
    
    def wait(self, domain: str) -> None:
        """
        Wait if necessary before making a request to the domain.
        
        Args:
            domain: The domain to request (e.g., 'yahoo.com')
        """
        now = time.time()
        delay = self.get_delay(domain)
        
        if domain in self.last_request_times:
            elapsed = now - self.last_request_times[domain]
            if elapsed < delay:
                time_to_wait = delay - elapsed
                time.sleep(time_to_wait)
        
        # Update last request time
        self.last_request_times[domain] = time.time()
        self.request_counts[domain] = self.request_counts.get(domain, 0) + 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        return {
            "domains": list(self.last_request_times.keys()),
            "request_counts": self.request_counts,
            "last_request_times": self.last_request_times,
        }


class CacheManager:
    """
    Cache manager for scraped content.
    Stores responses in files with expiration.
    """
    
    def __init__(self, cache_dir: str = "data/cache", expiration: int = 86400, max_size_mb: int = 1000):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory to store cached responses
            expiration: Cache expiration time in seconds
            max_size_mb: Maximum cache size in MB
        """
        self.cache_dir = Path(cache_dir)
        self.expiration = expiration
        self.max_size_mb = max_size_mb
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired()
    
    def _get_cache_path(self, url: str) -> Path:
        """Get the cache file path for a URL."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"{url_hash}.cache"
    
    def get(self, url: str) -> Optional[str]:
        """
        Get cached content for a URL.
        
        Args:
            url: The URL to get cached content for
            
        Returns:
            Cached HTML content or None if not cached or expired
        """
        cache_path = self._get_cache_path(url)
        
        if not cache_path.exists():
            return None
        
        # Check expiration
        file_mtime = cache_path.stat().st_mtime
        if time.time() - file_mtime > self.expiration:
            cache_path.unlink()
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'expires_at' in data and datetime.fromisoformat(data['expires_at']) < datetime.now():
                    cache_path.unlink()
                    return None
                return data.get('content')
        except (json.JSONDecodeError, KeyError):
            cache_path.unlink()
            return None
    
    def set(self, url: str, content: str) -> None:
        """
        Cache content for a URL.
        
        Args:
            url: The URL to cache
            content: The HTML content to cache
        """
        cache_path = self._get_cache_path(url)
        
        # Check cache size limit
        self._check_cache_size()
        
        data = {
            'url': url,
            'content': content,
            'cached_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(seconds=self.expiration)).isoformat(),
        }
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    
    def _check_cache_size(self) -> None:
        """Check and enforce cache size limit."""
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob('*.cache') if f.is_file())
        total_size_mb = total_size / (1024 * 1024)
        
        if total_size_mb > self.max_size_mb:
            # Delete oldest files
            files = sorted(self.cache_dir.glob('*.cache'), key=lambda f: f.stat().st_mtime)
            for file in files:
                if total_size_mb <= self.max_size_mb:
                    break
                file.unlink()
                total_size_mb -= file.stat().st_size / (1024 * 1024)
    
    def _cleanup_expired(self) -> int:
        """
        Clean up expired cache entries.
        
        Returns:
            Number of entries cleaned up
        """
        cleaned = 0
        for cache_file in self.cache_dir.glob('*.cache'):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'expires_at' in data:
                        expires_at = datetime.fromisoformat(data['expires_at'])
                        if expires_at < datetime.now():
                            cache_file.unlink()
                            cleaned += 1
            except (json.JSONDecodeError, KeyError):
                cache_file.unlink()
                cleaned += 1
        
        return cleaned
    
    def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns:
            Number of entries cleared
        """
        count = 0
        for cache_file in self.cache_dir.glob('*.cache'):
            cache_file.unlink()
            count += 1
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        files = list(self.cache_dir.glob('*.cache'))
        total_size = sum(f.stat().st_size for f in files)
        
        return {
            "entries": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "max_size_mb": self.max_size_mb,
            "expiration_seconds": self.expiration,
        }


class EthicalScraper:
    """
    Base class for ethical web scraping.
    Implements rate limiting, caching, and respectful scraping practices.
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """
        Initialize ethical scraper.
        
        Args:
            config: Scraper configuration (defaults to ethical settings)
        """
        if config is None:
            # Try to load from config file
            config_path = Path(__file__).parent.parent.parent / "configs" / "scraping.yaml"
            if config_path.exists():
                config = ScraperConfig.from_yaml(config_path)
            else:
                config = ScraperConfig()
        
        self.config = config
        self.rate_limiter = RateLimiter(
            default_delay=config.default_rate_limit,
            domain_delays=config.domain_rate_limits
        )
        self.cache = CacheManager(
            cache_dir=config.cache_directory,
            expiration=config.cache_expiration,
            max_size_mb=config.max_cache_size_mb
        )
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
        })
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    
    def _check_robots_txt(self, domain: str) -> bool:
        """
        Check if scraping is allowed by robots.txt.
        
        Args:
            domain: The domain to check
            
        Returns:
            True if scraping is allowed, False otherwise
        """
        if not self.config.respect_robots_txt:
            return True
        
        try:
            robots_url = f"https://{domain}/robots.txt"
            response = self.session.get(robots_url, timeout=10)
            
            if response.status_code == 200:
                robots_content = response.text
                # Simple check - in production, use a proper robots.txt parser
                if 'Disallow: /' in robots_content:
                    return False
            
            return True
        except Exception:
            # If we can't check robots.txt, assume scraping is allowed
            return True
    
    def fetch(self, url: str, use_cache: bool = True, force_refresh: bool = False) -> Optional[str]:
        """
        Fetch a URL with ethical scraping practices.
        
        Args:
            url: The URL to fetch
            use_cache: Whether to use cached content if available
            force_refresh: Whether to ignore cache and fetch fresh
            
        Returns:
            HTML content or None if request fails
        """
        domain = self._get_domain(url)
        
        # Check cache first
        if use_cache and not force_refresh:
            cached = self.cache.get(url)
            if cached is not None:
                return cached
        
        # Check robots.txt
        if not self._check_robots_txt(domain):
            return None
        
        # Rate limiting
        self.rate_limiter.wait(domain)
        
        # Make request with retries
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.get(url, timeout=self.config.request_timeout)
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Cache the response
                    if use_cache:
                        self.cache.set(url, content)
                    
                    return content
                elif response.status_code == 429:  # Too Many Requests
                    # Wait longer and retry
                    delay = self.rate_limiter.get_delay(domain) * (attempt + 1)
                    time.sleep(delay)
                elif response.status_code >= 400:
                    # Other errors - don't retry
                    break
                    
            except requests.exceptions.RequestException as e:
                if attempt == self.config.max_retries - 1:
                    # Last attempt failed
                    break
                time.sleep(self.config.retry_delay * (attempt + 1))
        
        return None
    
    def get_soup(self, url: str, use_cache: bool = True) -> Optional[BeautifulSoup]:
        """
        Get BeautifulSoup object for a URL.
        
        Args:
            url: The URL to fetch
            use_cache: Whether to use cached content
            
        Returns:
            BeautifulSoup object or None if request fails
        """
        html = self.fetch(url, use_cache=use_cache)
        if html:
            return BeautifulSoup(html, 'html.parser')
        return None
    
    def get_json(self, url: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Fetch JSON data from a URL.
        
        Args:
            url: The URL to fetch
            use_cache: Whether to use cached content
            
        Returns:
            Parsed JSON data or None if request fails
        """
        content = self.fetch(url, use_cache=use_cache)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
        return None
    
    def close(self):
        """Close the scraper session."""
        self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
