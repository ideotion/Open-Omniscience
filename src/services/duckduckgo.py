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
DuckDuckGo Search Module for Open Omniscience

This module provides functionality for searching the web using DuckDuckGo
to discover new sources and identify RSS feeds. It includes:
- Web search capabilities
- RSS feed detection
- Source discovery and validation
- Rate limiting and caching

Author: Ideotion
"""

import re
import time
from urllib.parse import urljoin, urlparse

import requests

from src.utils.logging_config import setup_logging

logger = setup_logging("duckduckgo")


class DuckDuckGoSearch:
    """
    A class for performing web searches using DuckDuckGo.
    
    DuckDuckGo provides a free, privacy-focused search API that can be used
    for source discovery. This class handles:
    - Search queries
    - Result parsing
    - RSS feed detection
    - Rate limiting
    
    Note: DuckDuckGo's official API is rate-limited. This implementation
    uses the HTML interface with proper User-Agent and delays.
    """
    
    BASE_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = "Mozilla/5.0 (compatible; OpenOmniscience/1.0; +https://github.com/ideotion/Open-Omniscience)"
    
    # Rate limiting
    MIN_DELAY_SECONDS = 2.0  # Minimum delay between requests
    last_request_time = 0
    
    # Common RSS feed patterns
    RSS_PATTERNS = [
        r'\.rss\b',
        r'\.xml\b',
        r'\.atom\b',
        r'/rss\b',
        r'/feed\b',
        r'/feeds\b',
        r'feed\.xml',
        r'rss\.xml',
        r'atom\.xml',
        r'/rss\.php',
        r'/feed\.php',
        r'\.rdf\b',
        r'/news/rss',
        r'/rss/news',
    ]
    
    # Common RSS link text patterns
    RSS_LINK_PATTERNS = [
        r'RSS',
        r'Feed',
        r'Subscribe',
        r'News Feed',
        r'XML Feed',
        r'Atom',
        r'RDF',
    ]
    
    @classmethod
    def _enforce_rate_limit(cls):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - cls.last_request_time
        if elapsed < cls.MIN_DELAY_SECONDS:
            time.sleep(cls.MIN_DELAY_SECONDS - elapsed)
        cls.last_request_time = time.time()
    
    @classmethod
    def search(cls, query: str, max_results: int = 10, region: str = "wt-wt", 
               safe_search: str = "1", time_range: str | None = None) -> list[dict]:
        """
        Perform a web search using DuckDuckGo.
        
        Args:
            query: The search query string
            max_results: Maximum number of results to return (default: 10)
            region: Region code (e.g., "wt-wt" for worldwide, "us-en" for US English)
            safe_search: Safe search level (0=off, 1=moderate, 2=strict)
            time_range: Time range filter (e.g., "d" for day, "w" for week, "m" for month, "y" for year)
        
        Returns:
            List of search result dictionaries, each containing:
            - title: The title of the result
            - url: The URL of the result
            - snippet: The description snippet
            - domain: The domain of the result
        
        Raises:
            Exception: If the search fails
        """
        cls._enforce_rate_limit()
        
        params = {
            'q': query,
            'kl': region,
            'p': safe_search,
        }
        
        if time_range:
            params['df'] = time_range
        
        headers = {
            'User-Agent': cls.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        try:
            logger.info(f"Searching DuckDuckGo for: {query}")
            response = requests.post(cls.BASE_URL, data=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            results = cls._parse_results(response.text, max_results)
            logger.info(f"Found {len(results)} results for query: {query}")
            return results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            raise Exception(f"DuckDuckGo search failed: {e}")
    
    @classmethod
    def _parse_results(cls, html: str, max_results: int) -> list[dict]:
        """
        Parse search results from DuckDuckGo HTML.
        
        Args:
            html: The HTML content from DuckDuckGo
            max_results: Maximum number of results to parse
        
        Returns:
            List of parsed result dictionaries
        """
        results = []
        
        # DuckDuckGo result pattern
        # Results are in <div class="result"> elements
        result_pattern = re.compile(
            r'<div class="result">.*?<a class="result__url" href="(.*?)".*?'
            r'<a class="result__a" href="(.*?)">(.*?)</a>.*?'
            r'<a class="result__snippet-link"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        
        # Alternative pattern for DuckDuckGo results
        # Try to find all result links
        link_pattern = re.compile(
            r'<a class="result__a" href="(.*?)">(.*?)</a>',
            re.DOTALL
        )
        
        # Find all result links
        matches = link_pattern.findall(html)
        
        for i, (url, title) in enumerate(matches[:max_results]):
            # Clean up the URL
            url = cls._clean_url(url)
            if not url:
                continue
            
            # Extract domain
            domain = cls._extract_domain(url)
            
            # Try to find snippet - look for text after the title link
            snippet = ""
            
            # Create result
            result = {
                'title': cls._clean_text(title),
                'url': url,
                'snippet': snippet,
                'domain': domain
            }
            results.append(result)
        
        return results
    
    @classmethod
    def _clean_url(cls, url: str) -> str | None:
        """Clean and validate a URL from search results."""
        if not url:
            return None
        
        # Remove tracking parameters
        url = re.sub(r'\/\*[^*]+\*\/', '/', url)
        url = re.sub(r'\?.*$', '', url)  # Remove query string for now
        
        # Decode URL encoding
        try:
            url = url.replace('&amp;', '&')
            from urllib.parse import unquote
            url = unquote(url)
        except Exception:
            pass
        
        # Validate URL
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return None
            return url
        except Exception:
            return None
    
    @classmethod
    def _extract_domain(cls, url: str) -> str:
        """Extract the domain from a URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
    
    @classmethod
    def _clean_text(cls, text: str) -> str:
        """Clean text by removing HTML tags and entities."""
        if not text:
            return ""
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode HTML entities
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @classmethod
    def discover_rss_feeds(cls, url: str, timeout: int = 10, fetcher=None) -> list[str]:
        """
        Discover RSS feeds for a given URL.

        This method:
        1. Fetches the HTML content of the URL
        2. Looks for <link> tags with RSS/Atom types
        3. Looks for common RSS feed URL patterns
        4. Validates found feeds

        All HTTP fetches go through the shared :class:`~src.ingest.EthicalFetcher`
        (finding ETH-01), so robots.txt is honoured fail-closed, internal/SSRF
        targets are refused, and per-host rate limiting applies -- discovery is
        held to the same ethical-scraping contract as ingestion. A refusal
        (robots disallow, blocked target, fetch failure) yields no feeds rather
        than a raw fallback.

        Args:
            url: The URL to search for RSS feeds
            timeout: Request timeout in seconds (informational; the fetcher owns
                the real timeout)
            fetcher: Optional EthicalFetcher (dependency-injected for tests);
                one is built from the current safety settings if omitted.

        Returns:
            List of discovered RSS feed URLs
        """
        from src.ingest import FetchError

        if fetcher is None:
            from src.safety.fetcher import make_fetcher

            fetcher = make_fetcher()

        feeds = []

        try:
            # Fetch the page through the ethical fetch path (robots/SSRF/rate-limit).
            try:
                html = fetcher.fetch(url, require_html=True).content
            except FetchError as e:
                logger.info(f"Ethical fetch refused or failed for {url}: {e}")
                return []

            # Method 1: Look for <link> tags with RSS/Atom types
            link_pattern = re.compile(
                r'<link[^>]+(?:type=["\'](?:application\/(?:rss\+xml|atom\+xml)|text\/xml)["\']|' +
                r'rel=["\'](?:alternate|rss|atom)["\'])[^>]+href=["\']([^"\']+)["\']',
                re.IGNORECASE
            )
            
            for match in link_pattern.finditer(html):
                feed_url = match.group(1)
                feed_url = cls._resolve_url(feed_url, url)
                if feed_url and feed_url not in feeds:
                    feeds.append(feed_url)
            
            # Method 2: Look for common RSS feed URL patterns in the HTML
            for pattern in cls.RSS_PATTERNS:
                url_matches = re.findall(pattern, html, re.IGNORECASE)
                for match in url_matches:
                    # Try to extract full URL
                    if 'http' in match:
                        feed_url = match.strip()
                        feed_url = cls._resolve_url(feed_url, url)
                        if feed_url and feed_url not in feeds:
                            feeds.append(feed_url)
            
            # Method 3: Try common RSS feed paths
            common_paths = [
                '/rss', '/rss.xml', '/rss2.xml', '/rss2.0.xml',
                '/feed', '/feed.xml', '/atom.xml', '/rdf.xml',
                '/news/rss', '/rss/news', '/rss/feed', '/feed/rss',
                '/index.rss', '/index.xml', '/index.atom',
                '/blog/rss', '/blog/feed', '/posts/rss', '/articles/rss',
            ]
            
            for path in common_paths:
                feed_url = cls._resolve_url(path, url)
                if feed_url and feed_url not in feeds:
                    # Probe the candidate path through the same ethical fetcher
                    # (require_html=False since feeds are XML). A refusal/miss is
                    # swallowed -- this is opportunistic discovery.
                    try:
                        probe = fetcher.fetch(feed_url, require_html=False)
                        ct = probe.content_type.lower()
                        if 'xml' in ct or 'rss' in ct or 'atom' in ct or cls._is_xml_content(probe.content[:1024]):
                            feeds.append(feed_url)
                    except FetchError:
                        pass

            logger.info(f"Discovered {len(feeds)} potential RSS feeds for {url}")

            # Validate feeds
            valid_feeds = []
            for feed_url in feeds:
                if cls._validate_rss_feed(feed_url, fetcher=fetcher):
                    valid_feeds.append(feed_url)
                    logger.info(f"Valid RSS feed found: {feed_url}")

            return valid_feeds

        except Exception as e:
            logger.error(f"Error discovering RSS feeds for {url}: {e}")
            return []
    
    @classmethod
    def _resolve_url(cls, path: str, base_url: str) -> str | None:
        """Resolve a relative URL path against a base URL."""
        try:
            if path.startswith('http://') or path.startswith('https://'):
                return path
            
            # Ensure base_url ends with / for proper joining
            if not base_url.endswith('/'):
                base_url += '/'
            
            parsed_base = urlparse(base_url)
            resolved = urljoin(f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_base.path}", path)
            return resolved
        except Exception:
            return None
    
    @classmethod
    def _validate_rss_feed(cls, url: str, timeout: int = 5, fetcher=None) -> bool:
        """
        Validate if a URL points to a valid RSS/Atom feed.

        Fetches through the EthicalFetcher (ETH-01) with ``require_html=False``
        since feeds are XML. A refusal or failure means "not a usable feed".

        Args:
            url: The URL to validate
            timeout: Request timeout in seconds (informational; fetcher owns it)
            fetcher: Optional EthicalFetcher (built from safety settings if None)

        Returns:
            True if the URL is a valid RSS/Atom feed, False otherwise
        """
        from src.ingest import FetchError

        if fetcher is None:
            from src.safety.fetcher import make_fetcher

            fetcher = make_fetcher()

        try:
            result = fetcher.fetch(url, require_html=False)
            content_type = result.content_type
            if 'xml' not in content_type.lower() and 'rss' not in content_type.lower() and 'atom' not in content_type.lower():
                if not cls._is_xml_content(result.content[:1024]):
                    return False
            return True
        except FetchError as e:
            logger.debug(f"RSS feed validation refused/failed for {url}: {e}")
            return False
        except Exception as e:
            logger.debug(f"RSS feed validation error for {url}: {e}")
            return False
    
    @classmethod
    def _is_xml_content(cls, content: str) -> bool:
        """Check if content appears to be XML."""
        # Look for XML declaration or RSS/Atom tags
        xml_patterns = [
            r'<\?xml',  # XML declaration ('?' must be escaped; '<?' made '<' optional)
            r'<rss\s',
            r'<rss>',
            r'<feed\s',
            r'<feed>',
            r'<rdf\s',
            r'<rdf>',
            r'xmlns=',
        ]
        
        for pattern in xml_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False
    
    @classmethod
    def discover_sources_by_topic(cls, topic: str, max_sources: int = 20, 
                                  region: str = "wt-wt") -> list[dict]:
        """
        Discover news sources for a specific topic.
        
        Args:
            topic: The topic to search for (e.g., "technology news", "financial markets")
            max_sources: Maximum number of sources to return
            region: Region code for localized results
        
        Returns:
            List of discovered source dictionaries, each containing:
            - name: Source name (extracted from domain or title)
            - domain: The domain of the source
            - url: The homepage URL
            - rss_urls: List of discovered RSS feed URLs
            - relevance: Relevance score (0-1)
        """
        sources = []
        seen_domains = set()
        
        # Build search query
        query = f"{topic} site:news OR site:media OR site:journal"
        
        try:
            # Perform search
            results = cls.search(query, max_results=50, region=region)
            
            for result in results:
                domain = result.get('domain', '')
                if not domain or domain in seen_domains:
                    continue
                
                seen_domains.add(domain)
                
                # Discover RSS feeds
                rss_urls = cls.discover_rss_feeds(result.get('url', ''))
                
                # Create source info
                source_info = {
                    'name': result.get('title', domain.replace('.', ' ').title()),
                    'domain': domain,
                    'url': result.get('url', ''),
                    'rss_urls': rss_urls,
                    'relevance': 1.0 - (len(sources) / max_sources) if max_sources > 0 else 1.0
                }
                
                sources.append(source_info)
                
                if len(sources) >= max_sources:
                    break
            
            logger.info(f"Discovered {len(sources)} sources for topic: {topic}")
            return sources
            
        except Exception as e:
            logger.error(f"Failed to discover sources for topic {topic}: {e}")
            return []
    
    @classmethod
    def find_missing_rss_feeds(cls, sources: list[dict], timeout: int = 10, fetcher=None) -> list[dict]:
        """
        Find missing RSS feeds for a list of sources.

        A single EthicalFetcher is shared across the batch so per-host rate
        limiting and the robots cache carry over between sources (ETH-01).

        Args:
            sources: List of source dictionaries with 'domain' and optionally 'url' keys
            timeout: Request timeout in seconds
            fetcher: Optional shared EthicalFetcher (built once if omitted)

        Returns:
            List of sources with discovered RSS feeds added
        """
        if fetcher is None:
            from src.safety.fetcher import make_fetcher

            fetcher = make_fetcher()

        results = []

        for source in sources:
            domain = source.get('domain', '')
            url = source.get('url', f"https://{domain}")

            if not domain:
                results.append(source)
                continue

            # Check if source already has RSS URL
            if source.get('rss_url'):
                results.append(source)
                continue

            # Try to discover RSS feeds (shared fetcher = shared rate-limit state)
            rss_urls = cls.discover_rss_feeds(url, timeout=timeout, fetcher=fetcher)
            
            # Update source
            updated_source = source.copy()
            if rss_urls:
                updated_source['rss_url'] = rss_urls[0]
                updated_source['rss_urls'] = rss_urls
            
            results.append(updated_source)
            
            if rss_urls:
                logger.info(f"Found RSS feed for {domain}: {rss_urls[0]}")
            else:
                logger.warning(f"No RSS feed found for {domain}")
        
        return results


# Convenience functions for module-level usage
def search(query: str, max_results: int = 10, **kwargs) -> list[dict]:
    """Perform a DuckDuckGo web search."""
    return DuckDuckGoSearch.search(query, max_results, **kwargs)


def discover_rss_feeds(url: str, **kwargs) -> list[str]:
    """Discover RSS feeds for a URL."""
    return DuckDuckGoSearch.discover_rss_feeds(url, **kwargs)


def discover_sources_by_topic(topic: str, **kwargs) -> list[dict]:
    """Discover sources for a topic."""
    return DuckDuckGoSearch.discover_sources_by_topic(topic, **kwargs)


def find_missing_rss_feeds(sources: list[dict], **kwargs) -> list[dict]:
    """Find missing RSS feeds for sources."""
    return DuckDuckGoSearch.find_missing_rss_feeds(sources, **kwargs)


if __name__ == "__main__":
    # Example usage
    print("Testing DuckDuckGo search...")
    
    # Test search
    try:
        results = search("technology news", max_results=5)
        print("\nSearch results for 'technology news':")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result.get('title', 'No title')} - {result.get('url', 'No URL')}")
        
        # Test RSS discovery
        if results:
            print("\nDiscovering RSS feeds for first result...")
            feeds = discover_rss_feeds(results[0]['url'])
            print(f"Found {len(feeds)} RSS feeds:")
            for feed in feeds:
                print(f"  - {feed}")
        
        # Test source discovery
        print("\nDiscovering sources for 'financial news'...")
        sources = discover_sources_by_topic("financial news", max_sources=5)
        print(f"Found {len(sources)} sources:")
        for source in sources:
            print(f"  - {source.get('name', 'Unknown')} ({source.get('domain', 'No domain')})")
            if source.get('rss_urls'):
                print(f"    RSS: {source['rss_urls'][0]}")
        
    except Exception as e:
        print(f"Error: {e}")
