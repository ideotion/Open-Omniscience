"""
Web Scraper for Open-Omniscience
Scrapes article content from URLs with caching
"""

import os
import hashlib
import json
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
import time

import requests
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse


class WebScraper:
    """
    Scrapes web pages and extracts article content.
    Supports caching to avoid repeated requests.
    """
    
    def __init__(self, cache_dir: str = '/workspace/open-omniscience/data/scraped_content',
                 user_agent: str = None, delay: float = 1.0, timeout: int = 30):
        """
        Initialize the web scraper.
        
        Args:
            cache_dir: Directory for caching scraped content
            user_agent: Custom user agent (default: random desktop user agent)
            delay: Delay between requests in seconds (default: 1.0)
            timeout: Request timeout in seconds (default: 30)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.timeout = timeout
        
        # User agents
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        ]
        
        self.user_agent = user_agent or self.user_agents[0]
        self._last_request_time = 0
        
        # Create cloudscraper instance for bypassing anti-scraping
        self.scraper = cloudscraper.create_scraper()
    
    def _get_cache_path(self, url: str) -> Path:
        """Get cache file path for a URL."""
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f'{url_hash}.json'
    
    def _get_user_agent(self) -> str:
        """Get a user agent, rotating if needed."""
        return self.user_agent
    
    def _enforce_delay(self) -> None:
        """Enforce delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()
    
    def scrape_url(self, url: str, use_cache: bool = True, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Scrape a URL and extract article content.
        
        Args:
            url: URL to scrape
            use_cache: Whether to use cached content (default: True)
            force_refresh: Force refresh from web (default: False)
            
        Returns:
            Dictionary with scraped content or None if failed
        """
        if not url:
            return None
        
        # Check cache first
        if use_cache and not force_refresh:
            cached = self._load_from_cache(url)
            if cached:
                return cached
        
        # Scrape from web
        result = self._scrape_from_web(url)
        
        if result and use_cache:
            self._save_to_cache(url, result)
        
        return result
    
    def _load_from_cache(self, url: str) -> Optional[Dict[str, Any]]:
        """Load scraped content from cache."""
        cache_path = self._get_cache_path(url)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Check if cache is expired (older than 7 days)
                cache_time = datetime.fromisoformat(data.get('cached_at', '1970-01-01'))
                if (datetime.now() - cache_time).days > 7:
                    return None
                return data
        except Exception:
            return None
    
    def _save_to_cache(self, url: str, data: Dict[str, Any]) -> None:
        """Save scraped content to cache."""
        cache_path = self._get_cache_path(url)
        data['cached_at'] = datetime.now().isoformat()
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def _scrape_from_web(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape content from the web."""
        self._enforce_delay()
        
        try:
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.google.com/',
            }
            
            response = self.scraper.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            html = response.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract article content
            result = self._extract_article_content(soup, url)
            
            return result
        except Exception as e:
            return {
                'url': url,
                'error': str(e),
                'success': False
            }
    
    def _extract_article_content(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract article content from BeautifulSoup object."""
        result = {
            'url': url,
            'success': True,
            'title': '',
            'content': '',
            'author': '',
            'published_date': '',
            'modified_date': '',
            'description': '',
            'keywords': [],
            'canonical_url': '',
            'language': '',
            'word_count': 0,
            'links': [],
            'domain': urlparse(url).netloc,
        }
        
        try:
            # Try to find title
            title_tag = soup.find('title')
            if title_tag:
                result['title'] = title_tag.get_text().strip()
            
            # Try to find canonical URL
            canonical = soup.find('link', {'rel': 'canonical'})
            if canonical and canonical.get('href'):
                result['canonical_url'] = canonical['href']
            
            # Try to find description
            desc_tag = soup.find('meta', attrs={'name': 'description'})
            if desc_tag and desc_tag.get('content'):
                result['description'] = desc_tag['content'].strip()
            
            # Try to find keywords
            keywords_tag = soup.find('meta', attrs={'name': 'keywords'})
            if keywords_tag and keywords_tag.get('content'):
                result['keywords'] = [k.strip() for k in keywords_tag['content'].split(',')]
            
            # Try to find author
            author_tag = soup.find('meta', attrs={'name': 'author'})
            if author_tag and author_tag.get('content'):
                result['author'] = author_tag['content'].strip()
            
            # Try to find published date
            published_tag = soup.find('meta', attrs={'property': 'article:published_time'})
            if published_tag and published_tag.get('content'):
                result['published_date'] = published_tag['content']
            else:
                # Try other date formats
                date_tag = soup.find('time')
                if date_tag and date_tag.get('datetime'):
                    result['published_date'] = date_tag['datetime']
            
            # Try to find language
            lang_tag = soup.find('html', attrs={'lang': True})
            if lang_tag and lang_tag.get('lang'):
                result['language'] = lang_tag['lang']
            
            # Extract main content
            content = self._extract_main_content(soup)
            result['content'] = content
            result['word_count'] = len(content.split())
            
            # Extract links
            result['links'] = self._extract_links(soup, url)
            
        except Exception as e:
            result['error'] = f'Content extraction error: {str(e)}'
        
        return result
    
    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """Extract main article content from page."""
        # Try different strategies
        
        # 1. Look for article tag
        article = soup.find('article')
        if article:
            return self._clean_text(article.get_text())
        
        # 2. Look for common content classes
        common_selectors = [
            '.article-body',
            '.post-content',
            '.entry-content',
            '.main-content',
            '.content__article-body',
            '[itemprop="articleBody"]',
        ]
        
        for selector in common_selectors:
            element = soup.select_one(selector)
            if element:
                return self._clean_text(element.get_text())
        
        # 3. Look for largest text block
        paragraphs = soup.find_all('p')
        if paragraphs:
            content = '\n\n'.join([self._clean_text(p.get_text()) for p in paragraphs])
            return content
        
        # 4. Fallback to body
        body = soup.find('body')
        if body:
            return self._clean_text(body.get_text())
        
        return ''
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all links from page."""
        links = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # Skip empty, javascript, and mailto links
            if not href or href.startswith(('javascript:', 'mailto:', '#')):
                continue
            
            # Make absolute URL
            try:
                absolute_url = urljoin(base_url, href)
                links.append(absolute_url)
            except Exception:
                pass
        
        return links
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ''
        
        # Remove excessive whitespace
        text = ' '.join(text.split())
        
        # Remove common boilerplate
        boilerplate = [
            'cookie policy',
            'privacy policy',
            'terms of service',
            'all rights reserved',
            'subscribe to our newsletter',
        ]
        
        for bp in boilerplate:
            text = text.replace(bp, '')
        
        return text.strip()
    
    def batch_scrape(self, urls: list, use_cache: bool = True) -> list:
        """
        Scrape multiple URLs in batch.
        
        Args:
            urls: List of URLs to scrape
            use_cache: Whether to use cached content (default: True)
            
        Returns:
            List of results
        """
        results = []
        for url in urls:
            result = self.scrape_url(url, use_cache=use_cache)
            results.append(result)
            # Small delay between batches
            time.sleep(0.1)
        return results


# Global instance
web_scraper = WebScraper()
