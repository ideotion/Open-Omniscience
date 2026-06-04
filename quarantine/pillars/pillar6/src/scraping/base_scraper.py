"""
Pillar 6 Base Scraper

Base class for all rare earth market scrapers.
Provides common functionality including rate limiting, retry logic,
user agent rotation, and robots.txt compliance.
"""

import asyncio
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from urllib.parse import urlparse, urljoin
import logging
import hashlib

import requests
import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from src.utils.rate_limiter import RateLimiter
from src.utils.retry import retry_with_backoff

# Configure logging
logger = logging.getLogger(__name__)


class ScraperConfig:
    """
    Configuration for web scrapers.
    
    Attributes:
        request_timeout: Timeout for HTTP requests in seconds
        max_retries: Maximum number of retry attempts
        retry_delay: Base delay between retries in seconds
        max_retry_delay: Maximum delay between retries
        rate_limit: Requests per second limit
        user_agents: List of user agents to rotate through
        respect_robots_txt: Whether to respect robots.txt
        delay_between_requests: Minimum delay between requests to same domain
        cache_enabled: Whether to cache responses
        cache_dir: Directory for cache storage
    """
    
    def __init__(
        self,
        request_timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_retry_delay: float = 30.0,
        rate_limit: float = 1.0,
        respect_robots_txt: bool = True,
        delay_between_requests: float = 1.0,
        cache_enabled: bool = False,
        cache_dir: str = ".scraper_cache",
    ):
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_retry_delay = max_retry_delay
        self.rate_limit = rate_limit
        self.respect_robots_txt = respect_robots_txt
        self.delay_between_requests = delay_between_requests
        self.cache_enabled = cache_enabled
        self.cache_dir = cache_dir
        
        # Initialize user agent rotator
        self.ua = UserAgent()
        self.user_agents = [
            self.ua.chrome,
            self.ua.firefox,
            self.ua.safari,
            self.ua.edge,
            self.ua.opera,
        ]
    
    def get_random_user_agent(self) -> str:
        """Get a random user agent."""
        return random.choice(self.user_agents)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "max_retry_delay": self.max_retry_delay,
            "rate_limit": self.rate_limit,
            "respect_robots_txt": self.respect_robots_txt,
            "delay_between_requests": self.delay_between_requests,
            "cache_enabled": self.cache_enabled,
            "cache_dir": self.cache_dir,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScraperConfig':
        """Create configuration from dictionary."""
        return cls(
            request_timeout=data.get("request_timeout", 30),
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
            max_retry_delay=data.get("max_retry_delay", 30.0),
            rate_limit=data.get("rate_limit", 1.0),
            respect_robots_txt=data.get("respect_robots_txt", True),
            delay_between_requests=data.get("delay_between_requests", 1.0),
            cache_enabled=data.get("cache_enabled", False),
            cache_dir=data.get("cache_dir", ".scraper_cache"),
        )


# Default configuration
DEFAULT_CONFIG = ScraperConfig(
    request_timeout=30,
    max_retries=3,
    retry_delay=1.0,
    max_retry_delay=30.0,
    rate_limit=1.0,
    respect_robots_txt=True,
    delay_between_requests=1.0,
    cache_enabled=False,
)


class RobotsTxtCache:
    """
    Cache for robots.txt rules.
    
    Stores parsed robots.txt rules to avoid repeated fetching.
    """
    
    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.last_fetched: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(hours=24)
    
    def get_rules(self, domain: str) -> Dict[str, Any]:
        """Get cached robots.txt rules for a domain."""
        return self.cache.get(domain, {})
    
    def set_rules(self, domain: str, rules: Dict[str, Any]) -> None:
        """Set robots.txt rules for a domain."""
        self.cache[domain] = rules
        self.last_fetched[domain] = datetime.now()
    
    def is_cached(self, domain: str) -> bool:
        """Check if rules are cached and still valid."""
        if domain not in self.last_fetched:
            return False
        return datetime.now() - self.last_fetched[domain] < self.cache_ttl
    
    def clear_expired(self) -> None:
        """Clear expired cache entries."""
        now = datetime.now()
        expired = [
            domain for domain, timestamp in self.last_fetched.items()
            if now - timestamp > self.cache_ttl
        ]
        for domain in expired:
            del self.cache[domain]
            del self.last_fetched[domain]


class ResponseCache:
    """
    Simple response cache for scraped content.
    
    Uses URL hashing for cache keys.
    """
    
    def __init__(self, cache_dir: str = ".scraper_cache"):
        import os
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_dir = cache_dir
        self.cache: Dict[str, Any] = {}
    
    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key from URL."""
        return hashlib.sha256(url.encode()).hexdigest()
    
    def get(self, url: str) -> Optional[str]:
        """Get cached response content."""
        key = self._get_cache_key(url)
        return self.cache.get(key)
    
    def set(self, url: str, content: str) -> None:
        """Cache response content."""
        key = self._get_cache_key(url)
        self.cache[key] = content
    
    def clear(self) -> None:
        """Clear all cached responses."""
        self.cache.clear()


class RareEarthScraper(ABC):
    """
    Base class for rare earth market scrapers.
    
    Provides common functionality for all scrapers including:
    - Rate limiting
    - Retry logic with exponential backoff
    - User agent rotation
    - robots.txt compliance
    - Response caching
    - Error handling
    - Logging
    
    Subclasses should implement the specific scraping logic.
    """
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        name: str = "BaseScraper",
    ):
        """
        Initialize the scraper.
        
        Args:
            config: Scraper configuration
            name: Name of the scraper (for logging)
        """
        self.config = config or DEFAULT_CONFIG
        self.name = name
        self.robots_cache = RobotsTxtCache()
        self.response_cache = ResponseCache(self.config.cache_dir) if self.config.cache_enabled else None
        self.rate_limiter = RateLimiter(self.config.rate_limit)
        self.domain_last_request: Dict[str, datetime] = {}
        
        # Initialize session
        self.session = None
        self.async_session = None
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc
    
    def _get_user_agent(self) -> str:
        """Get a user agent for requests."""
        return self.config.get_random_user_agent()
    
    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for requests."""
        return {
            "User-Agent": self._get_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
        }
    
    def _check_robots_txt(self, url: str) -> bool:
        """
        Check if scraping is allowed by robots.txt.
        
        Args:
            url: URL to check
            
        Returns:
            True if scraping is allowed, False otherwise
        """
        if not self.config.respect_robots_txt:
            return True
        
        domain = self._get_domain(url)
        
        # Check cache first
        if self.robots_cache.is_cached(domain):
            rules = self.robots_cache.get_rules(domain)
            return rules.get("can_scrape", True)
        
        # Fetch robots.txt
        robots_url = f"https://{domain}/robots.txt"
        try:
            response = requests.get(
                robots_url,
                headers=self._get_headers(),
                timeout=self.config.request_timeout,
            )
            
            if response.status_code == 200:
                rules = self._parse_robots_txt(response.text, url)
                self.robots_cache.set_rules(domain, rules)
                return rules.get("can_scrape", True)
            else:
                # If robots.txt is not found, assume scraping is allowed
                self.robots_cache.set_rules(domain, {"can_scrape": True})
                return True
                
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt for {domain}: {e}")
            # On error, assume scraping is allowed
            self.robots_cache.set_rules(domain, {"can_scrape": True})
            return True
    
    def _parse_robots_txt(self, content: str, url: str) -> Dict[str, Any]:
        """
        Parse robots.txt content.
        
        Args:
            content: robots.txt content
            url: URL being scraped
            
        Returns:
            Dictionary with parsing results
        """
        from urllib.robotparser import RobotFileParser
        
        rp = RobotFileParser()
        rp.parse(content.splitlines())
        
        user_agent = "*"
        path = urlparse(url).path
        
        can_scrape = rp.can_fetch(user_agent, url)
        crawl_delay = rp.crawl_delay(user_agent)
        
        return {
            "can_scrape": can_scrape,
            "crawl_delay": crawl_delay,
        }
    
    def _enforce_rate_limit(self, domain: str) -> None:
        """
        Enforce rate limiting for a domain.
        
        Args:
            domain: Domain being requested
        """
        if domain in self.domain_last_request:
            last_request = self.domain_last_request[domain]
            elapsed = (datetime.now() - last_request).total_seconds()
            
            if elapsed < self.config.delay_between_requests:
                time.sleep(self.config.delay_between_requests - elapsed)
        
        self.domain_last_request[domain] = datetime.now()
    
    def _make_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[requests.Response]:
        """
        Make an HTTP request with retry logic.
        
        Args:
            url: URL to request
            method: HTTP method
            headers: Request headers
            params: Query parameters
            data: Request body
            timeout: Request timeout
            
        Returns:
            Response object or None on failure
        """
        # Check robots.txt
        if not self._check_robots_txt(url):
            logger.warning(f"Scraping blocked by robots.txt: {url}")
            return None
        
        # Check cache
        if self.response_cache and self.response_cache.get(url):
            logger.debug(f"Using cached response for: {url}")
            # For now, return None to indicate cache hit
            # In practice, you'd need to create a mock response
            return None
        
        # Enforce rate limiting
        domain = self._get_domain(url)
        self._enforce_rate_limit(domain)
        
        # Use global rate limiter
        self.rate_limiter.wait()
        
        # Prepare request
        headers = headers or self._get_headers()
        timeout = timeout or self.config.request_timeout
        
        @retry_with_backoff(
            max_retries=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.max_retry_delay,
            exceptions=(requests.RequestException, ConnectionError, TimeoutError),
        )
        def _request():
            if method.upper() == "GET":
                return requests.get(url, headers=headers, params=params, timeout=timeout)
            elif method.upper() == "POST":
                return requests.post(url, headers=headers, data=data, timeout=timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        
        try:
            response = _request()
            
            # Check for rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                time.sleep(retry_after)
                response = _request()
            
            # Cache response if enabled
            if self.response_cache and response.status_code == 200:
                self.response_cache.set(url, response.text)
            
            return response
            
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            return None
    
    def get(self, url: str, **kwargs) -> Optional[str]:
        """
        Make a GET request and return the text content.
        
        Args:
            url: URL to GET
            **kwargs: Additional arguments for _make_request
            
        Returns:
            Response text or None on failure
        """
        response = self._make_request(url, "GET", **kwargs)
        if response and response.status_code == 200:
            return response.text
        return None
    
    def get_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """
        Make a GET request and return a BeautifulSoup object.
        
        Args:
            url: URL to GET
            **kwargs: Additional arguments for _make_request
            
        Returns:
            BeautifulSoup object or None on failure
        """
        html = self.get(url, **kwargs)
        if html:
            return BeautifulSoup(html, "html.parser")
        return None
    
    async def async_get(self, url: str, **kwargs) -> Optional[str]:
        """
        Make an async GET request and return the text content.
        
        Args:
            url: URL to GET
            **kwargs: Additional arguments
            
        Returns:
            Response text or None on failure
        """
        if not self.async_session:
            self.async_session = aiohttp.ClientSession(
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
            )
        
        try:
            async with self.async_session.get(url, **kwargs) as response:
                if response.status == 200:
                    return await response.text()
                return None
        except Exception as e:
            logger.error(f"Async request failed for {url}: {e}")
            return None
    
    async def async_get_soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        """
        Make an async GET request and return a BeautifulSoup object.
        
        Args:
            url: URL to GET
            **kwargs: Additional arguments
            
        Returns:
            BeautifulSoup object or None on failure
        """
        html = await self.async_get(url, **kwargs)
        if html:
            return BeautifulSoup(html, "html.parser")
        return None
    
    def close(self):
        """Close the scraper and clean up resources."""
        if self.async_session:
            asyncio.run(self.async_session.close())
        if self.response_cache:
            self.response_cache.clear()
    
    @abstractmethod
    def scrape(self, **kwargs) -> Any:
        """
        Main scraping method to be implemented by subclasses.
        
        Args:
            **kwargs: Scraper-specific arguments
            
        Returns:
            Scraped data (structure depends on implementation)
        """
        pass
    
    @abstractmethod
    def get_data_sources(self) -> List[str]:
        """
        Get the list of data sources for this scraper.
        
        Returns:
            List of URLs or identifiers
        """
        pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"


class ScraperFactory:
    """
    Factory for creating scrapers with consistent configuration.
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize the factory."""
        self.config = config or DEFAULT_CONFIG
    
    def create_scraper(self, scraper_class, name: str = None, **kwargs) -> RareEarthScraper:
        """
        Create a scraper instance.
        
        Args:
            scraper_class: Scraper class to instantiate
            name: Name for the scraper
            **kwargs: Additional arguments for the scraper
            
        Returns:
            Configured scraper instance
        """
        return scraper_class(
            config=self.config,
            name=name or scraper_class.__name__,
            **kwargs
        )


# Export everything
__all__ = [
    "ScraperConfig",
    "DEFAULT_CONFIG",
    "RobotsTxtCache",
    "ResponseCache",
    "RareEarthScraper",
    "ScraperFactory",
]
