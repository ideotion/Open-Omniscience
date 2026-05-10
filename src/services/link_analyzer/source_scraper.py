"""
Source Scraper Service for Open Omniscience

This module provides functionality for scraping external source articles
to extract metadata, content, and publication information.

Author: Open Omniscience Team
"""

import re
import time
import hashlib
from urllib.parse import urlparse, urljoin
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timezone
import logging
import requests
from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)


class SourceScraper:
    """
    Service for scraping external source articles.
    
    This class provides methods to:
    - Scrape article content from external sources
    - Extract article metadata (title, author, date, etc.)
    - Calculate content hashes for duplicate detection
    - Handle rate limiting and retries
    - Respect robots.txt and crawl delays
    """
    
    def __init__(self, user_agent: str = None, timeout: int = 15, max_retries: int = 3):
        """
        Initialize the SourceScraper.
        
        Args:
            user_agent: User agent string for requests
            timeout: Timeout for HTTP requests in seconds
            max_retries: Maximum number of retries for failed requests
        """
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; Open Omniscience Source Scraper/1.0; +https://github.com/open-omniscience)"
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        
        # Configure session headers
        self.session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1.0  # Minimum seconds between requests
        
        # Track visited URLs to avoid duplicates
        self.visited_urls = set()
    
    def scrape_source_article(self, url: str, source_info: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Scrape an article from an external source.
        
        Args:
            url: URL of the article to scrape
            source_info: Optional information about the source (for rate limiting, etc.)
            
        Returns:
            Dictionary containing scraped article information, or None if scraping failed
        """
        if not url:
            logger.error("URL is required for scraping")
            return None
        
        # Normalize URL
        url = self._normalize_url(url)
        
        # Check if we've already visited this URL
        if url in self.visited_urls:
            logger.info(f"URL already visited: {url}")
            return None
        
        # Apply rate limiting
        self._apply_rate_limiting(source_info)
        
        try:
            # Fetch the article
            response = self._fetch_url(url)
            if not response or response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: HTTP {response.status_code if response else 'N/A'}")
                return None
            
            # Parse HTML
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract article information
            article_info = self._extract_article_info(soup, url)
            
            if not article_info:
                logger.warning(f"No article information extracted from {url}")
                return None
            
            # Add source information
            article_info['source_url'] = url
            if source_info:
                article_info['source_info'] = source_info
            
            # Mark as visited
            self.visited_urls.add(url)
            
            return article_info
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None
    
    def scrape_multiple_articles(self, urls: List[str], source_info: Optional[Dict[str, Any]] = None, 
                                max_articles: int = 10) -> List[Dict[str, Any]]:
        """
        Scrape multiple articles from external sources.
        
        Args:
            urls: List of URLs to scrape
            source_info: Optional information about the source
            max_articles: Maximum number of articles to scrape
            
        Returns:
            List of scraped article information dictionaries
        """
        scraped_articles = []
        
        for i, url in enumerate(urls[:max_articles]):
            if i >= max_articles:
                break
                
            article = self.scrape_source_article(url, source_info)
            if article:
                scraped_articles.append(article)
            
            # Small delay between requests
            time.sleep(0.5)
        
        return scraped_articles
    
    def _fetch_url(self, url: str) -> Optional[requests.Response]:
        """
        Fetch a URL with retries and error handling.
        
        Args:
            url: URL to fetch
            
        Returns:
            Response object, or None if request failed
        """
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout)
                
                # Check for rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited. Retrying after {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                
                # Check for redirects
                if response.history:
                    # Followed redirects, use the final URL
                    final_url = response.url
                    logger.info(f"Redirected from {url} to {final_url}")
                
                return response
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return None
        
        return None
    
    def _apply_rate_limiting(self, source_info: Optional[Dict[str, Any]] = None):
        """
        Apply rate limiting based on source information.
        
        Args:
            source_info: Information about the source (may contain rate_limit_ms)
        """
        # Calculate time since last request
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # Get rate limit from source info or use default
        rate_limit = 0.001  # Default: 1ms (effectively no limit)
        if source_info and 'rate_limit_ms' in source_info:
            rate_limit = source_info['rate_limit_ms'] / 1000.0  # Convert to seconds
        
        # Apply rate limiting
        wait_time = max(0, rate_limit - time_since_last)
        if wait_time > 0:
            time.sleep(wait_time)
        
        # Update last request time
        self.last_request_time = time.time()
    
    def _normalize_url(self, url: str) -> str:
        """
        Normalize a URL for consistent storage and comparison.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        if not url:
            return ""
        
        try:
            parsed = urlparse(url)
            
            # Remove default ports
            if parsed.port and ((parsed.scheme == 'http' and parsed.port == 80) or 
                               (parsed.scheme == 'https' and parsed.port == 443)):
                netloc = parsed.netloc.replace(f":{parsed.port}", "")
            else:
                netloc = parsed.netloc
            
            # Lowercase scheme and netloc
            scheme = parsed.scheme.lower()
            netloc = netloc.lower()
            
            # Remove www. prefix
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            
            # Remove empty path
            path = parsed.path or '/'
            
            # Remove fragment
            fragment = ""
            
            # Reconstruct URL
            normalized = f"{scheme}://{netloc}{path}"
            
            # Remove trailing slash from path (except for root)
            if len(normalized) > 1 and normalized.endswith('/') and not normalized.endswith('://'):
                normalized = normalized[:-1]
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Error normalizing URL {url}: {e}")
            return url.lower() if url else ""
    
    def _extract_article_info(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Extract article information from BeautifulSoup object.
        
        Args:
            soup: BeautifulSoup object
            url: Original URL
            
        Returns:
            Dictionary containing extracted article information
        """
        article_info = {}
        
        # Extract title
        title = self._extract_title(soup)
        if title:
            article_info['title'] = title
        
        # Extract author
        author = self._extract_author(soup)
        if author:
            article_info['author'] = author
        
        # Extract publication date
        published_at = self._extract_published_date(soup)
        if published_at:
            article_info['published_at'] = published_at
        
        # Extract main content
        content = self._extract_content(soup)
        if content:
            article_info['content'] = content
            article_info['word_count'] = len(content.split())
            
            # Calculate content hash
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            article_info['content_hash'] = content_hash
        
        # Extract summary/description
        summary = self._extract_summary(soup)
        if summary:
            article_info['summary'] = summary
        
        # Extract language
        language = self._extract_language(soup)
        if language:
            article_info['language'] = language
        
        # Extract sentiment (basic analysis)
        sentiment = self._analyze_sentiment(content if content else "")
        article_info['sentiment_score'] = sentiment
        
        # Extract metadata
        metadata = self._extract_metadata(soup)
        article_info.update(metadata)
        
        # Set timestamps
        article_info['scraped_at'] = datetime.now(timezone.utc).isoformat()
        article_info['last_accessed_at'] = datetime.now(timezone.utc).isoformat()
        
        return article_info
    
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article title from HTML."""
        # Try different methods to find the title
        
        # 1. Check for OpenGraph title
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        if og_title and og_title.get('content'):
            return og_title.get('content').strip()
        
        # 2. Check for Twitter card title
        twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
        if twitter_title and twitter_title.get('content'):
            return twitter_title.get('content').strip()
        
        # 3. Check for h1 tag
        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()
        
        # 4. Check for title tag
        title_tag = soup.title
        if title_tag:
            title = title_tag.get_text().strip()
            # Remove site name if present
            if '|' in title:
                title = title.split('|')[0].strip()
            elif '-' in title:
                title = title.split('-')[0].strip()
            return title
        
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author from HTML."""
        # Try different methods to find the author
        
        # 1. Check for OpenGraph author
        og_author = soup.find('meta', attrs={'property': 'og:author'})
        if og_author and og_author.get('content'):
            return og_author.get('content').strip()
        
        # 2. Check for Twitter card author
        twitter_author = soup.find('meta', attrs={'name': 'twitter:creator'})
        if twitter_author and twitter_author.get('content'):
            return twitter_author.get('content').strip()
        
        # 3. Check for author meta tag
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            return author_meta.get('content').strip()
        
        # 4. Check for common author class names
        author_selectors = [
            '.author', '.byline', '.post-author', '.entry-author',
            '.article-author', '.writer', '.contributor'
        ]
        for selector in author_selectors:
            author_element = soup.select_one(selector)
            if author_element:
                return author_element.get_text().strip()
        
        return None
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from HTML."""
        # Try different methods to find the publication date
        
        # 1. Check for OpenGraph published time
        og_published = soup.find('meta', attrs={'property': 'article:published_time'})
        if og_published and og_published.get('content'):
            return og_published.get('content').strip()
        
        # 2. Check for OpenGraph published
        og_published = soup.find('meta', attrs={'property': 'og:published'})
        if og_published and og_published.get('content'):
            return og_published.get('content').strip()
        
        # 3. Check for Twitter card published
        twitter_published = soup.find('meta', attrs={'name': 'twitter:published'})
        if twitter_published and twitter_published.get('content'):
            return twitter_published.get('content').strip()
        
        # 4. Check for datetime in meta tags
        datetime_meta = soup.find('meta', attrs={'name': 'date'})
        if datetime_meta and datetime_meta.get('content'):
            return datetime_meta.get('content').strip()
        
        # 5. Check for time tags
        time_tag = soup.find('time')
        if time_tag and time_tag.get('datetime'):
            return time_tag.get('datetime').strip()
        
        # 6. Check for common date class names
        date_selectors = [
            '.date', '.published', '.post-date', '.entry-date',
            '.article-date', '.timestamp', '.byline-date'
        ]
        for selector in date_selectors:
            date_element = soup.select_one(selector)
            if date_element:
                date_text = date_element.get_text().strip()
                if date_text:
                    return date_text
        
        return None
    
    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract main article content from HTML."""
        # Try different methods to find the main content
        
        # 1. Check for article tag
        article_tag = soup.find('article')
        if article_tag:
            return self._clean_content(article_tag.get_text())
        
        # 2. Check for main tag
        main_tag = soup.find('main')
        if main_tag:
            return self._clean_content(main_tag.get_text())
        
        # 3. Check for common content class names
        content_selectors = [
            '.content', '.article-content', '.post-content', '.entry-content',
            '.main-content', '.body-content', '.article-body', '.story-content'
        ]
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                return self._clean_content(content_element.get_text())
        
        # 4. Check for div with specific IDs
        id_selectors = [
            '#content', '#article', '#main', '#body',
            '#post-content', '#entry-content', '#article-body'
        ]
        for selector in id_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                return self._clean_content(content_element.get_text())
        
        # 5. Fallback: get all paragraphs
        paragraphs = soup.find_all('p')
        if paragraphs:
            content = '\n\n'.join(p.get_text().strip() for p in paragraphs)
            return self._clean_content(content)
        
        # 6. Last resort: get all text
        body = soup.find('body')
        if body:
            return self._clean_content(body.get_text())
        
        return None
    
    def _extract_summary(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article summary/description from HTML."""
        # Try different methods to find the summary
        
        # 1. Check for OpenGraph description
        og_description = soup.find('meta', attrs={'property': 'og:description'})
        if og_description and og_description.get('content'):
            return og_description.get('content').strip()
        
        # 2. Check for Twitter card description
        twitter_description = soup.find('meta', attrs={'name': 'twitter:description'})
        if twitter_description and twitter_description.get('content'):
            return twitter_description.get('content').strip()
        
        # 3. Check for description meta tag
        description_meta = soup.find('meta', attrs={'name': 'description'})
        if description_meta and description_meta.get('content'):
            return description_meta.get('content').strip()
        
        # 4. Check for excerpt class
        excerpt_selectors = [
            '.excerpt', '.summary', '.description', '.intro',
            '.lead', '.standfirst', '.subheading'
        ]
        for selector in excerpt_selectors:
            excerpt_element = soup.select_one(selector)
            if excerpt_element:
                return excerpt_element.get_text().strip()
        
        return None
    
    def _extract_language(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract language from HTML."""
        # Check for lang attribute on html tag
        html_tag = soup.find('html')
        if html_tag and html_tag.get('lang'):
            return html_tag.get('lang').strip()
        
        # Check for OpenGraph locale
        og_locale = soup.find('meta', attrs={'property': 'og:locale'})
        if og_locale and og_locale.get('content'):
            locale = og_locale.get('content').strip()
            # Extract language code (e.g., 'en_US' -> 'en')
            if '_' in locale:
                return locale.split('_')[0]
            return locale
        
        return None
    
    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract additional metadata from HTML."""
        metadata = {}
        
        # Extract OpenGraph type
        og_type = soup.find('meta', attrs={'property': 'og:type'})
        if og_type and og_type.get('content'):
            metadata['og_type'] = og_type.get('content').strip()
        
        # Extract OpenGraph site name
        og_site_name = soup.find('meta', attrs={'property': 'og:site_name'})
        if og_site_name and og_site_name.get('content'):
            metadata['og_site_name'] = og_site_name.get('content').strip()
        
        # Extract OpenGraph URL
        og_url = soup.find('meta', attrs={'property': 'og:url'})
        if og_url and og_url.get('content'):
            metadata['og_url'] = og_url.get('content').strip()
        
        # Extract canonical URL
        canonical = soup.find('link', attrs={'rel': 'canonical'})
        if canonical and canonical.get('href'):
            metadata['canonical_url'] = canonical.get('href').strip()
        
        # Extract favicon
        favicon = soup.find('link', attrs={'rel': 'icon'}) or \
                soup.find('link', attrs={'rel': 'shortcut icon'})
        if favicon and favicon.get('href'):
            metadata['favicon_url'] = favicon.get('href').strip()
        
        return metadata
    
    def _clean_content(self, text: str) -> str:
        """Clean extracted content by removing unwanted elements."""
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove navigation text
        navigation_patterns = [
            r'\[?Home[\|\-]?\]?', r'\[?About[\|\-]?\]?', r'\[?Contact[\|\-]?\]?',
            r'\bClick here\b', r'\bRead more\b', r'\bContinue reading\b',
            r'\bPrevious[\|\-]?Next\b', r'\bPage \d+ of \d+\b'
        ]
        for pattern in navigation_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove advertising text
        ad_patterns = [
            r'\bAdvertisement\b', r'\bSponsored\b', r'\bPromoted\b',
            r'\bAd\b', r'\bAds by\b', r'\bPowered by\b'
        ]
        for pattern in ad_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove social media prompts
        social_patterns = [
            r'\bShare on\b', r'\bFollow us on\b', r'\bLike us on\b',
            r'\bTweet\b', r'\bShare\b', r'\bPin it\b'
        ]
        for pattern in social_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove copyright notices
        copyright_patterns = [
            r'\bCopyright\b', r'\bAll rights reserved\b', r'\b\d{4} [\w ]+\b'
        ]
        for pattern in copyright_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Trim and clean
        text = text.strip()
        
        return text
    
    def _analyze_sentiment(self, text: str) -> float:
        """
        Perform basic sentiment analysis on text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Sentiment score (-1.0 to 1.0, where negative = negative, positive = positive)
        """
        if not text:
            return 0.0
        
        # Basic sentiment analysis using word lists
        positive_words = {
            'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic',
            'best', 'positive', 'happy', 'joy', 'love', 'success', 'win',
            'beautiful', 'perfect', 'outstanding', 'superb', 'brilliant'
        }
        
        negative_words = {
            'bad', 'terrible', 'awful', 'horrible', 'worst', 'negative',
            'hate', 'sad', 'angry', 'fail', 'loss', 'disaster', 'tragedy',
            'ugly', 'poor', 'weak', 'broken', 'damage'
        }
        
        words = re.findall(r'\b\w+\b', text.lower())
        
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        # Calculate sentiment score
        sentiment = (positive_count - negative_count) / total
        
        return sentiment
    
    def check_url_accessibility(self, url: str) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Check if a URL is accessible.
        
        Args:
            url: URL to check
            
        Returns:
            Tuple of (is_accessible, http_status, redirect_url)
        """
        try:
            response = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            is_accessible = response.status_code < 400
            return is_accessible, response.status_code, response.url
        except requests.exceptions.RequestException:
            return False, None, None
    
    def get_robots_txt(self, domain: str) -> Optional[str]:
        """
        Fetch robots.txt for a domain.
        
        Args:
            domain: Domain to fetch robots.txt from
            
        Returns:
            robots.txt content, or None if not accessible
        """
        if not domain:
            return None
        
        # Normalize domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Construct robots.txt URL
        robots_url = f"https://{domain}/robots.txt"
        
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.status_code == 200:
                return response.text
        except requests.exceptions.RequestException:
            pass
        
        return None
    
    def parse_robots_txt(self, robots_txt: str) -> Dict[str, Any]:
        """
        Parse robots.txt content.
        
        Args:
            robots_txt: robots.txt content
            
        Returns:
            Dictionary containing parsed robots.txt information
        """
        if not robots_txt:
            return {'allowed': True, 'crawl_delay': None}
        
        result = {'allowed': True, 'crawl_delay': None, 'disallowed': [], 'allowed_paths': []}
        
        for line in robots_txt.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split(':')
            if len(parts) < 2:
                continue
            
            key = parts[0].strip().lower()
            value = parts[1].strip()
            
            if key == 'user-agent':
                # Check if this applies to our user agent
                if '*' in value or 'Open Omniscience' in value or 'bot' in value.lower():
                    result['user_agent'] = value
            elif key == 'disallow':
                if value:
                    result['disallowed'].append(value)
            elif key == 'allow':
                if value:
                    result['allowed_paths'].append(value)
            elif key == 'crawl-delay':
                try:
                    result['crawl_delay'] = int(value)
                except ValueError:
                    pass
        
        # Check if we're allowed
        if 'disallowed' in result and '/' in result['disallowed']:
            result['allowed'] = False
        
        return result