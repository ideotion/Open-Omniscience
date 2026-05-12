"""
Open-Omniscience - Ethical Scraper

Provides ethical web scraping with:
- robots.txt compliance
- Rate limiting
- User agent identification
- Respect for website terms of service
- Duplicate detection
"""

import time
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Set, Tuple, Callable
from urllib.parse import urlparse, urljoin
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import hashlib
import socket


class ScraperStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ScraperConfig:
    """Configuration for the ethical scraper."""
    user_agent: str = "OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.5"
    
    # Rate limiting
    requests_per_minute: int = 10
    delay_between_requests: float = 6.0  # 60 seconds / 10 requests
    
    # Timeout
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    total_timeout: float = 60.0
    
    # Retry
    max_retries: int = 3
    retry_delay: float = 5.0
    backoff_factor: float = 2.0
    
    # robots.txt
    respect_robots_txt: bool = True
    robots_cache_ttl: float = 3600.0  # 1 hour
    
    # Depth
    max_depth: int = 3
    
    # Domain limits
    max_pages_per_domain: int = 100
    
    # Headers
    headers: Dict[str, str] = field(default_factory=dict)
    
    # Proxies
    proxies: Optional[Dict[str, str]] = None
    
    # SSL verification
    verify_ssl: bool = True


@dataclass
class ScrapedPage:
    """Represents a scraped web page."""
    url: str
    content: str
    status_code: int
    headers: Dict[str, str]
    timestamp: float = field(default_factory=time.time)
    depth: int = 0
    parent_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def domain(self) -> str:
        """Get the domain of the URL."""
        return urlparse(self.url).netloc
    
    @property
    def is_html(self) -> bool:
        """Check if the content is HTML."""
        content_type = self.headers.get('Content-Type', '').lower()
        return 'text/html' in content_type
    
    @property
    def content_hash(self) -> str:
        """Get a hash of the content."""
        return hashlib.sha256(self.content.encode('utf-8', errors='ignore')).hexdigest()


@dataclass
class RobotsTxt:
    """Represents a parsed robots.txt file."""
    url: str
    rules: List[Dict[str, Any]]
    crawl_delay: Optional[float] = None
    sitemap: Optional[str] = None
    last_fetched: float = field(default_factory=time.time)
    expires: float = field(default_factory=lambda: time.time() + 3600.0)
    
    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if a URL is allowed by robots.txt."""
        path = urlparse(url).path
        
        for rule in self.rules:
            if rule.get('user_agent') == user_agent or rule.get('user_agent') == "*":
                disallow = rule.get('disallow', '')
                allow = rule.get('allow', '')
                
                # Check allow rules first
                if allow and path.startswith(allow):
                    return True
                
                # Check disallow rules
                if disallow and path.startswith(disallow):
                    return False
        
        # Default to allowed if no matching rules
        return True
    
    def get_crawl_delay(self, user_agent: str = "*") -> Optional[float]:
        """Get the crawl delay for a user agent."""
        if self.crawl_delay:
            return self.crawl_delay
        return None


class EthicalScraper:
    """
    Ethical web scraper with compliance features.
    
    Features:
    - robots.txt compliance
    - Rate limiting
    - User agent identification
    - Respect for website terms
    - Duplicate detection
    - Error handling
    """

    def __init__(self, config: Optional[ScraperConfig] = None):
        """
        Initialize the ethical scraper.
        
        Args:
            config: Scraper configuration.
        """
        self.config = config if config else ScraperConfig()
        self.logger = logging.getLogger("EthicalScraper")
        
        # State
        self.status = ScraperStatus.IDLE
        self.running = False
        
        # Rate limiting
        self.last_request_time: float = 0.0
        self.request_count: int = 0
        self.domain_requests: Dict[str, List[float]] = {}
        
        # robots.txt cache
        self.robots_cache: Dict[str, RobotsTxt] = {}
        
        # Visited URLs (for duplicate detection)
        self.visited_urls: Set[str] = set()
        self.domain_page_counts: Dict[str, int] = {}
        
        # Session
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set default headers
        session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": self.config.accept,
            "Accept-Language": self.config.accept_language,
        })
        
        # Update with custom headers
        session.headers.update(self.config.headers)
        
        return session

    def start(self) -> None:
        """Start the scraper."""
        if self.running:
            return
        
        self.running = True
        self.status = ScraperStatus.RUNNING
        self.logger.info("Ethical scraper started")

    def stop(self) -> None:
        """Stop the scraper."""
        self.running = False
        self.status = ScraperStatus.IDLE
        self.logger.info("Ethical scraper stopped")

    def pause(self) -> None:
        """Pause the scraper."""
        self.status = ScraperStatus.PAUSED
        self.logger.info("Ethical scraper paused")

    def resume(self) -> None:
        """Resume the scraper."""
        if self.status == ScraperStatus.PAUSED:
            self.status = ScraperStatus.RUNNING
            self.logger.info("Ethical scraper resumed")

    def scrape_url(self, url: str, depth: int = 0, parent_url: Optional[str] = None) -> Optional[ScrapedPage]:
        """
        Scrape a single URL ethically.
        
        Args:
            url: URL to scrape.
            depth: Current crawl depth.
            parent_url: Parent URL (for tracking).
        
        Returns:
            ScrapedPage if successful, None otherwise.
        """
        if not self.running:
            self.logger.warning(f"Scraper not running, cannot scrape: {url}")
            return None
        
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.logger.warning(f"Invalid URL: {url}")
            return None
        
        # Check depth
        if depth > self.config.max_depth:
            self.logger.debug(f"Max depth exceeded for: {url}")
            return None
        
        # Check domain page limit
        domain = parsed.netloc
        if domain in self.domain_page_counts and self.domain_page_counts[domain] >= self.config.max_pages_per_domain:
            self.logger.debug(f"Max pages per domain exceeded for: {domain}")
            return None
        
        # Check if already visited
        if url in self.visited_urls:
            self.logger.debug(f"Already visited: {url}")
            return None
        
        # Check robots.txt
        if self.config.respect_robots_txt:
            if not self._check_robots_txt(url):
                self.logger.debug(f"Disallowed by robots.txt: {url}")
                return None
        
        # Check rate limiting
        if not self._check_rate_limit(domain):
            self.logger.debug(f"Rate limited for domain: {domain}")
            return None
        
        try:
            # Fetch the page
            response = self._fetch_page(url)
            
            if response is None:
                return None
            
            # Create scraped page
            page = ScrapedPage(
                url=url,
                content=response.text,
                status_code=response.status_code,
                headers=dict(response.headers),
                depth=depth,
                parent_url=parent_url,
                metadata={
                    "content_type": response.headers.get('Content-Type', ''),
                    "content_length": len(response.content),
                },
            )
            
            # Mark as visited
            self.visited_urls.add(url)
            self.domain_page_counts[domain] = self.domain_page_counts.get(domain, 0) + 1
            
            # Record request
            self._record_request(domain)
            
            return page
            
        except Exception as e:
            self.logger.error(f"Error scraping {url}: {e}")
            return None

    def scrape_site(self, start_url: str, max_pages: Optional[int] = None) -> List[ScrapedPage]:
        """
        Scrape an entire site starting from a URL.
        
        Args:
            start_url: Starting URL.
            max_pages: Maximum number of pages to scrape (defaults to config).
        
        Returns:
            List of scraped pages.
        """
        if max_pages is None:
            max_pages = self.config.max_pages_per_domain
        
        pages: List[ScrapedPage] = []
        queue: List[Tuple[str, int]] = [(start_url, 0)]  # (url, depth)
        visited: Set[str] = set()
        
        while queue and len(pages) < max_pages:
            url, depth = queue.pop(0)
            
            if url in visited:
                continue
            
            page = self.scrape_url(url, depth)
            if page:
                pages.append(page)
                visited.add(url)
                
                # Extract links and add to queue
                if page.is_html:
                    links = self._extract_links(page)
                    for link in links:
                        if link not in visited and link not in [q[0] for q in queue]:
                            queue.append((link, depth + 1))
        
        return pages

    def _check_robots_txt(self, url: str) -> bool:
        """Check if a URL is allowed by robots.txt."""
        parsed = urlparse(url)
        domain = parsed.netloc
        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        
        # Check cache
        if robots_url in self.robots_cache:
            robots = self.robots_cache[robots_url]
            if time.time() < robots.expires:
                return robots.is_allowed(url, self.config.user_agent)
        
        # Fetch robots.txt
        try:
            response = self.session.get(
                robots_url,
                timeout=self.config.connect_timeout,
                allow_redirects=False,
            )
            
            if response.status_code == 200:
                robots = self._parse_robots_txt(response.text, robots_url)
                self.robots_cache[robots_url] = robots
                return robots.is_allowed(url, self.config.user_agent)
            elif response.status_code == 404:
                # No robots.txt, assume allowed
                return True
            else:
                # Error fetching robots.txt, assume allowed
                return True
                
        except Exception as e:
            self.logger.warning(f"Error fetching robots.txt for {domain}: {e}")
            # Assume allowed on error
            return True

    def _parse_robots_txt(self, content: str, url: str) -> RobotsTxt:
        """Parse robots.txt content."""
        rules = []
        crawl_delay = None
        sitemap = None
        
        lines = content.split('\n')
        current_user_agent = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if line.lower().startswith("user-agent:"):
                current_user_agent = line.split(':', 1)[1].strip()
            elif line.lower().startswith("disallow:") and current_user_agent:
                path = line.split(':', 1)[1].strip()
                rules.append({
                    'user_agent': current_user_agent,
                    'disallow': path,
                })
            elif line.lower().startswith("allow:") and current_user_agent:
                path = line.split(':', 1)[1].strip()
                rules.append({
                    'user_agent': current_user_agent,
                    'allow': path,
                })
            elif line.lower().startswith("crawl-delay:"):
                if current_user_agent == "*" or current_user_agent == self.config.user_agent:
                    try:
                        crawl_delay = float(line.split(':', 1)[1].strip())
                    except ValueError:
                        pass
            elif line.lower().startswith("sitemap:"):
                sitemap = line.split(':', 1)[1].strip()
        
        return RobotsTxt(
            url=url,
            rules=rules,
            crawl_delay=crawl_delay,
            sitemap=sitemap,
        )

    def _check_rate_limit(self, domain: str) -> bool:
        """Check if we're rate limited for a domain."""
        now = time.time()
        
        # Global rate limiting
        if now - self.last_request_time < self.config.delay_between_requests:
            return False
        
        # Per-domain rate limiting
        if domain in self.domain_requests:
            # Remove old requests (older than 1 minute)
            self.domain_requests[domain] = [
                t for t in self.domain_requests[domain]
                if now - t < 60.0
            ]
            
            if len(self.domain_requests[domain]) >= self.config.requests_per_minute:
                return False
        
        return True

    def _record_request(self, domain: str) -> None:
        """Record a request for rate limiting."""
        now = time.time()
        self.last_request_time = now
        
        if domain not in self.domain_requests:
            self.domain_requests[domain] = []
        
        self.domain_requests[domain].append(now)

    def _fetch_page(self, url: str) -> Optional[requests.Response]:
        """Fetch a web page."""
        try:
            # Check for custom domain delay
            domain = urlparse(url).netloc
            robots = self.robots_cache.get(f"https://{domain}/robots.txt") or \
                    self.robots_cache.get(f"http://{domain}/robots.txt")
            
            if robots and robots.crawl_delay:
                time.sleep(robots.crawl_delay)
            
            response = self.session.get(
                url,
                timeout=(
                    self.config.connect_timeout,
                    self.config.read_timeout,
                ),
                verify=self.config.verify_ssl,
                proxies=self.config.proxies,
            )
            
            # Check status code
            if response.status_code >= 400:
                self.logger.warning(f"HTTP {response.status_code} for: {url}")
                return None
            
            return response
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request error for {url}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def _extract_links(self, page: ScrapedPage) -> List[str]:
        """Extract all links from a page."""
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(page.content, 'html.parser')
            links = set()
            
            for tag in soup.find_all(['a', 'link']):
                href = tag.get('href')
                if href:
                    # Skip mailto, tel, javascript, etc.
                    if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                        continue
                    
                    # Make absolute URL
                    absolute_url = urljoin(page.url, href)
                    
                    # Normalize URL
                    normalized = self._normalize_url(absolute_url)
                    if normalized:
                        links.add(normalized)
            
            return list(links)
            
        except Exception as e:
            self.logger.error(f"Error extracting links from {page.url}: {e}")
            return []

    def _normalize_url(self, url: str) -> Optional[str]:
        """Normalize a URL."""
        try:
            parsed = urlparse(url)
            
            # Remove fragment
            parsed = parsed._replace(fragment='')
            
            # Remove trailing slash
            path = parsed.path.rstrip('/')
            parsed = parsed._replace(path=path)
            
            # Reconstruct URL
            return parsed.geturl()
            
        except Exception:
            return None

    def get_robots_txt(self, url: str) -> Optional[RobotsTxt]:
        """Get robots.txt for a domain."""
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        # Check cache
        if robots_url in self.robots_cache:
            robots = self.robots_cache[robots_url]
            if time.time() < robots.expires:
                return robots
        
        # Fetch fresh
        self._check_robots_txt(url)
        return self.robots_cache.get(robots_url)

    def clear_cache(self) -> None:
        """Clear all caches."""
        self.robots_cache.clear()
        self.visited_urls.clear()
        self.domain_page_counts.clear()
        self.domain_requests.clear()
        self.logger.info("Ethical scraper cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get scraper statistics."""
        return {
            "status": self.status.value,
            "pages_scraped": len(self.visited_urls),
            "domains_visited": len(self.domain_page_counts),
            "robots_cache_size": len(self.robots_cache),
            "config": {
                "user_agent": self.config.user_agent,
                "requests_per_minute": self.config.requests_per_minute,
                "max_depth": self.config.max_depth,
                "max_pages_per_domain": self.config.max_pages_per_domain,
                "respect_robots_txt": self.config.respect_robots_txt,
            },
        }


# Convenience function for simple ethical scraping
def scrape_ethically(
    url: str,
    user_agent: str = "OpenOmniscience/1.0",
    respect_robots_txt: bool = True,
    max_depth: int = 1,
) -> Optional[ScrapedPage]:
    """
    Simple function to scrape a URL ethically.
    
    Args:
        url: URL to scrape.
        user_agent: User agent string.
        respect_robots_txt: Whether to respect robots.txt.
        max_depth: Maximum crawl depth.
    
    Returns:
        ScrapedPage if successful, None otherwise.
    """
    config = ScraperConfig(
        user_agent=user_agent,
        respect_robots_txt=respect_robots_txt,
        max_depth=max_depth,
    )
    
    scraper = EthicalScraper(config)
    scraper.start()
    
    try:
        return scraper.scrape_url(url)
    finally:
        scraper.stop()
