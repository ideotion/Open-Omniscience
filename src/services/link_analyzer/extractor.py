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
Link Extractor Service for Open Omniscience

This module provides functionality for extracting links from HTML content,
including URL normalization, link text extraction, and position tracking.

Author: Open Omniscience Team
"""

import hashlib
import logging
import re
from datetime import UTC, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)


class LinkExtractor:
    """
    Service for extracting links from HTML content.
    
    This class provides methods to:
    - Extract all links from HTML content
    - Normalize URLs for duplicate detection
    - Extract link text and context
    - Track link positions
    - Filter links by type
    """
    
    def __init__(self):
        """Initialize the LinkExtractor."""
        # Patterns for identifying different types of links
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp', '.ico'}
        self.script_extensions = {'.js', '.javascript'}
        self.stylesheet_extensions = {'.css'}
        self.document_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}
        self.media_extensions = {'.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.mpeg'}
        
        # Patterns for social media URLs
        self.social_media_domains = {
            'facebook.com', 'fb.com', 'twitter.com', 'x.com', 'linkedin.com',
            'instagram.com', 'youtube.com', 'youtu.be', 'tiktok.com', 'reddit.com',
            'pinterest.com', 'tumblr.com', 'snapchat.com', 'whatsapp.com', 'telegram.org'
        }
        
        # Patterns for ad networks
        self.ad_network_domains = {
            'googleads.g.doubleclick.net', 'pagead2.googlesyndication.com',
            'adservice.google.com', 'adsystem.com', 'adserver.com',
            'openx.net', 'rubiconproject.com', 'pubmatic.com', 'indexww.com',
            'adnxs.com', 'casalemedia.com', 'media.net', 'revcontent.com'
        }
        
        # Patterns for tracking/analytics
        self.tracking_domains = {
            'google-analytics.com', 'googlesyndication.com', 'doubleclick.net',
            'scorecardresearch.com', 'comscore.com', 'nielsen.com',
            'quantserve.com', 'chartbeat.com', 'newrelic.com'
        }
    
    def extract_links(self, html_content: str, base_url: str | None = None, 
                     article_id: int | None = None) -> list[dict[str, Any]]:
        """
        Extract all links from HTML content.
        
        Args:
            html_content: HTML content to extract links from
            base_url: Base URL for resolving relative links
            article_id: ID of the article (for reference)
            
        Returns:
            List of dictionaries containing link information:
            - url: Original URL
            - normalized_url: Normalized URL
            - link_text: Link text (anchor text)
            - position: Character position in HTML
            - link_type: Type of link (internal, external, image, script, stylesheet, etc.)
            - html_tag: HTML tag that contained the link (a, img, script, link, etc.)
            - html_attributes: Dictionary of HTML attributes
            - domain: Domain of the URL
            - path: Path of the URL
            - query: Query string of the URL
            - fragment: Fragment identifier of the URL
            - is_absolute: Whether the URL is absolute
            - is_relative: Whether the URL is relative
            - article_id: ID of the article
            - created_at: Timestamp when the link was extracted
        """
        if not html_content or not html_content.strip():
            logger.warning("Empty HTML content provided for link extraction")
            return []
        
        extracted_links = []
        
        try:
            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find all elements that can contain links
            link_elements = soup.find_all(['a', 'img', 'script', 'link', 'iframe', 'source', 'video', 'audio'])
            
            current_position = 0
            
            for element in link_elements:
                # Get the position of the element in the HTML
                element_start = html_content.find(str(element), current_position)
                if element_start == -1:
                    continue
                
                current_position = element_start
                
                # Extract link information based on element type
                link_info = self._extract_link_from_element(element, base_url, article_id, current_position)
                
                if link_info:
                    extracted_links.append(link_info)
                    
        except Exception as e:
            logger.error(f"Error extracting links from HTML: {e}")
            # Fallback to regex-based extraction
            extracted_links = self._extract_links_with_regex(html_content, base_url, article_id)
        
        return extracted_links
    
    def _extract_link_from_element(self, element, base_url: str | None, 
                                  article_id: int | None, position: int) -> dict[str, Any] | None:
        """
        Extract link information from a BeautifulSoup element.
        
        Args:
            element: BeautifulSoup element
            base_url: Base URL for resolving relative links
            article_id: ID of the article
            position: Character position in HTML
            
        Returns:
            Dictionary containing link information, or None if no valid link
        """
        tag_name = element.name
        link_url = None
        link_text = ""
        
        # Extract URL based on element type
        if tag_name == 'a':
            link_url = element.get('href')
            link_text = element.get_text(strip=True) or ""
        elif tag_name == 'img':
            link_url = element.get('src')
            link_text = element.get('alt', '') or ""
        elif tag_name == 'script':
            link_url = element.get('src')
            link_text = ""
        elif tag_name == 'link':
            link_url = element.get('href')
            link_text = ""
        elif tag_name == 'iframe':
            link_url = element.get('src')
            link_text = element.get('title', '') or ""
        elif tag_name in ['source', 'video', 'audio']:
            link_url = element.get('src')
            link_text = ""
        
        if not link_url:
            return None
        
        # Resolve relative URLs
        if base_url and not link_url.startswith(('http://', 'https://', 'ftp://', 'mailto:', 'tel:', 'javascript:', '#')):
            try:
                link_url = urljoin(base_url, link_url)
            except Exception as e:
                logger.warning(f"Error resolving relative URL {link_url} with base {base_url}: {e}")
        
        # Normalize URL
        normalized_url = self.normalize_url(link_url)
        
        # Parse URL components
        parsed_url = urlparse(link_url)
        
        # Determine link type
        link_type = self._determine_link_type(link_url, parsed_url, tag_name)
        
        # Extract HTML attributes
        html_attributes = dict(element.attrs)
        
        return {
            'url': link_url,
            'normalized_url': normalized_url,
            'link_text': link_text.strip() if link_text else "",
            'position': position,
            'link_type': link_type,
            'html_tag': tag_name,
            'html_attributes': html_attributes,
            'domain': parsed_url.netloc.lower() if parsed_url.netloc else "",
            'path': parsed_url.path,
            'query': parsed_url.query,
            'fragment': parsed_url.fragment,
            'is_absolute': bool(parsed_url.scheme and parsed_url.netloc),
            'is_relative': not bool(parsed_url.scheme and parsed_url.netloc),
            'article_id': article_id,
            'created_at': datetime.now(UTC).isoformat()
        }
    
    def _extract_links_with_regex(self, html_content: str, base_url: str | None, 
                                 article_id: int | None) -> list[dict[str, Any]]:
        """
        Fallback method to extract links using regex when BeautifulSoup fails.
        
        Args:
            html_content: HTML content
            base_url: Base URL for resolving relative links
            article_id: ID of the article
            
        Returns:
            List of dictionaries containing link information
        """
        # Regex patterns for different types of links
        patterns = {
            'a_href': r'<a\s+[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            'img_src': r'<img\s+[^>]*src=["\']([^"\']*)["\'][^>]*>',
            'script_src': r'<script\s+[^>]*src=["\']([^"\']*)["\'][^>]*>',
            'link_href': r'<link\s+[^>]*href=["\']([^"\']*)["\'][^>]*>',
            'iframe_src': r'<iframe\s+[^>]*src=["\']([^"\']*)["\'][^>]*>',
        }
        
        extracted_links = []
        
        for tag, pattern in patterns.items():
            matches = re.finditer(pattern, html_content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                url = match.group(1)
                link_text = match.group(2) if len(match.groups()) > 1 else ""
                
                if url and not url.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                    # Resolve relative URLs
                    if base_url and not url.startswith(('http://', 'https://', 'ftp://')):
                        try:
                            url = urljoin(base_url, url)
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Failed to resolve relative URL: {e}")
                    
                    normalized_url = self.normalize_url(url)
                    parsed_url = urlparse(url)
                    
                    link_info = {
                        'url': url,
                        'normalized_url': normalized_url,
                        'link_text': link_text.strip() if link_text else "",
                        'position': match.start(),
                        'link_type': self._determine_link_type(url, parsed_url, tag.split('_')[0]),
                        'html_tag': tag.split('_')[0],
                        'html_attributes': {},
                        'domain': parsed_url.netloc.lower() if parsed_url.netloc else "",
                        'path': parsed_url.path,
                        'query': parsed_url.query,
                        'fragment': parsed_url.fragment,
                        'is_absolute': bool(parsed_url.scheme and parsed_url.netloc),
                        'is_relative': not bool(parsed_url.scheme and parsed_url.netloc),
                        'article_id': article_id,
                        'created_at': datetime.now(UTC).isoformat()
                    }
                    extracted_links.append(link_info)
        
        return extracted_links
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize a URL for duplicate detection.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        if not url:
            return ""
        
        try:
            # Parse the URL
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
            normalized = urlunparse((scheme, netloc, path, parsed.params, parsed.query, fragment))
            
            # Remove trailing slash from path (except for root)
            if len(normalized) > 1 and normalized.endswith('/') and not normalized.endswith('://'):
                normalized = normalized[:-1]
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Error normalizing URL {url}: {e}")
            return url.lower() if url else ""
    
    def _determine_link_type(self, url: str, parsed_url, tag_name: str) -> str:
        """
        Determine the type of a link based on URL and tag.
        
        Args:
            url: The URL
            parsed_url: Parsed URL components
            tag_name: HTML tag name
            
        Returns:
            Link type string
        """
        # Check by tag first
        if tag_name == 'img':
            return 'image'
        elif tag_name == 'script':
            return 'script'
        elif tag_name == 'link':
            rel = getattr(parsed_url, 'rel', '') if hasattr(parsed_url, 'rel') else ''
            if 'stylesheet' in rel.lower():
                return 'stylesheet'
            return 'external'
        elif tag_name == 'iframe':
            return 'iframe'
        elif tag_name in ['video', 'audio', 'source']:
            return 'media'
        
        # Check by URL pattern
        domain = parsed_url.netloc.lower() if parsed_url.netloc else ""
        path = parsed_url.path.lower()
        
        # Check for social media
        for social_domain in self.social_media_domains:
            if social_domain in domain:
                return 'social'
        
        # Check for ad networks
        for ad_domain in self.ad_network_domains:
            if ad_domain in domain:
                return 'ad'
        
        # Check for tracking
        for tracking_domain in self.tracking_domains:
            if tracking_domain in domain:
                return 'tracking'
        
        # Check by file extension
        path_parts = path.split('/')
        if path_parts:
            filename = path_parts[-1]
            if '.' in filename:
                extension = '.' + filename.split('.')[-1].lower()
                if extension in self.image_extensions:
                    return 'image'
                elif extension in self.script_extensions:
                    return 'script'
                elif extension in self.stylesheet_extensions:
                    return 'stylesheet'
                elif extension in self.document_extensions:
                    return 'document'
                elif extension in self.media_extensions:
                    return 'media'
        
        # Default to external for absolute URLs, internal for relative
        if parsed_url.scheme and parsed_url.netloc:
            return 'external'
        else:
            return 'internal'
    
    def filter_links(self, links: list[dict[str, Any]], link_types: list[str] | None = None,
                    domains: list[str] | None = None, 
                    classifications: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Filter links based on various criteria.
        
        Args:
            links: List of link dictionaries
            link_types: List of link types to include
            domains: List of domains to include
            classifications: List of classifications to include
            
        Returns:
            Filtered list of links
        """
        filtered = links
        
        if link_types:
            filtered = [link for link in filtered if link.get('link_type') in link_types]
        
        if domains:
            domain_set = set(d.lower() for d in domains)
            filtered = [link for link in filtered if link.get('domain', '').lower() in domain_set]
        
        if classifications:
            filtered = [link for link in filtered if link.get('classification') in classifications]
        
        return filtered
    
    def get_link_statistics(self, links: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Calculate statistics for a list of links.
        
        Args:
            links: List of link dictionaries
            
        Returns:
            Dictionary containing link statistics
        """
        if not links:
            return {
                'total_links': 0,
                'unique_domains': 0,
                'internal_links': 0,
                'external_links': 0,
                'link_types': {},
                'domains': {}
            }
        
        total_links = len(links)
        unique_domains = set(link.get('domain', '') for link in links if link.get('domain'))
        internal_links = sum(1 for link in links if link.get('link_type') == 'internal')
        external_links = total_links - internal_links
        
        # Count link types
        link_types = {}
        for link in links:
            link_type = link.get('link_type', 'unknown')
            link_types[link_type] = link_types.get(link_type, 0) + 1
        
        # Count domains
        domains = {}
        for link in links:
            domain = link.get('domain', 'unknown')
            domains[domain] = domains.get(domain, 0) + 1
        
        return {
            'total_links': total_links,
            'unique_domains': len(unique_domains),
            'internal_links': internal_links,
            'external_links': external_links,
            'link_types': link_types,
            'domains': domains
        }