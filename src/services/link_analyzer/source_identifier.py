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
Source Identifier Service for Open Omniscience

This module provides functionality for identifying and extracting information
about external sources referenced in articles.

Author: Open Omniscience Team
"""

import re
from urllib.parse import urlparse
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
import logging
import requests
from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)


class SourceIdentifier:
    """
    Service for identifying and extracting information about external sources.
    
    This class provides methods to:
    - Extract domain information from URLs
    - Identify source type (news, blog, academic, etc.)
    - Extract source metadata from websites
    - Match URLs to known sources
    """
    
    def __init__(self):
        """Initialize the SourceIdentifier."""
        # Known source patterns
        self.known_sources = self._load_known_sources()
        
        # Source type patterns
        self.source_type_patterns = {
            'news': [
                r'news\.', r'\.news\.', r'nytimes\.', r'washingtonpost\.',
                r'bbc\.', r'cnn\.', r'foxnews\.', r'msnbc\.', r'reuters\.',
                r'apnews\.', r'bloomberg\.', r'wsj\.', r'ft\.', r'theguardian\.',
                r'npr\.', r'pbs\.', r'abcnews\.', r'nbcnews\.', r'cbsnews\.',
                r'usatoday\.', r'latimes\.', r'chicagotribune\.', r'bostonglobe\.'
            ],
            'blog': [
                r'blog\.', r'\.blog\.', r'blogspot\.', r'wordpress\.',
                r'medium\.', r'tumblr\.', r'ghost\.', r'substack\.'
            ],
            'academic': [
                r'\.edu\.', r'\.ac\.uk\.', r'arxiv\.', r'jstor\.',
                r'springer\.', r'sciencedirect\.', r'nature\.', r'science\.',
                r'plos\.', r'researchgate\.', r'academic\.', r'oxford\.',
                r'cambridge\.', r'elsevier\.', r'wiley\.', r'taylor\.'
            ],
            'government': [
                r'\.gov\.', r'\.gob\.', r'\.mil\.', r'un\.', r'who\.',
                r'worldbank\.', r'imf\.', r'eu\.', r'parliament\.', r'congress\.'
            ],
            'social': [
                r'facebook\.', r'twitter\.', r'x\.', r'linkedin\.',
                r'instagram\.', r'youtube\.', r'tiktok\.', r'reddit\.',
                r'pinterest\.', r'tumblr\.', r'snapchat\.', r'whatsapp\.'
            ],
            'business': [
                r'forbes\.', r'fortune\.', r'bloomberg\.', r'wsj\.',
                r'ft\.', r'economist\.', r'hbr\.', r'inc\.', r'fastcompany\.'
            ],
            'technology': [
                r'techcrunch\.', r'wired\.', r'theverge\.', r'ars\.',
                r'engadget\.', r'gizmodo\.', r'mashable\.', r'venturebeat\.'
            ]
        }
    
    def _load_known_sources(self) -> Dict[str, Dict[str, Any]]:
        """
        Load known sources from configuration or database.
        
        Returns:
            Dictionary of known sources
        """
        # This would typically be loaded from a database
        # For now, return an empty dict that can be populated
        return {}
    
    def identify_sources(self, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify sources from a list of links.
        
        Args:
            links: List of link dictionaries
            
        Returns:
            List of source dictionaries with identified information
        """
        identified_sources = []
        seen_domains = set()
        
        for link in links:
            # Skip non-external links
            if link.get('link_type') in ['image', 'script', 'stylesheet', 'media', 'internal']:
                continue
            
            domain = link.get('domain', '')
            if not domain or domain in seen_domains:
                continue
            
            seen_domains.add(domain)
            
            # Identify source
            source_info = self.identify_source(domain, link.get('url', ''))
            if source_info:
                identified_sources.append(source_info)
        
        return identified_sources
    
    def identify_source(self, domain: str, url: str = "") -> Optional[Dict[str, Any]]:
        """
        Identify a source from a domain or URL.
        
        Args:
            domain: Domain name
            url: Full URL (optional)
            
        Returns:
            Source information dictionary, or None if not identified
        """
        if not domain:
            return None
        
        # Normalize domain
        domain = domain.lower().strip()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Check if we already know this source
        if domain in self.known_sources:
            source = self.known_sources[domain].copy()
            source['domain'] = domain
            source['url'] = url
            return source
        
        # Try to identify source type
        source_type = self.identify_source_type(domain)
        
        # Extract source name
        source_name = self.extract_source_name(domain, url)
        
        # Create basic source info
        source_info = {
            'domain': domain,
            'name': source_name,
            'url': url,
            'source_type': source_type,
            'credibility_score': 50.0,  # Default score
            'is_verified': False,
            'identified_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Try to extract additional information from the website
        try:
            additional_info = self.extract_source_metadata(domain, url)
            if additional_info:
                source_info.update(additional_info)
        except Exception as e:
            logger.warning(f"Error extracting metadata for {domain}: {e}")
        
        return source_info
    
    def identify_source_type(self, domain: str) -> str:
        """
        Identify the type of a source based on domain patterns.
        
        Args:
            domain: Domain name
            
        Returns:
            Source type string
        """
        domain_lower = domain.lower()
        
        for source_type, patterns in self.source_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, domain_lower, re.IGNORECASE):
                    return source_type
        
        # Default to unknown
        return 'unknown'
    
    def extract_source_name(self, domain: str, url: str = "") -> str:
        """
        Extract the source name from a domain or URL.
        
        Args:
            domain: Domain name
            url: Full URL (optional)
            
        Returns:
            Source name string
        """
        if not domain:
            return "Unknown"
        
        # Remove www. prefix
        domain_clean = domain.lower()
        if domain_clean.startswith('www.'):
            domain_clean = domain_clean[4:]
        
        # Split by dots and take the main part
        parts = domain_clean.split('.')
        if parts:
            # For domains like co.uk, take the last two parts
            if len(parts) > 2 and len(parts[-1]) == 2 and len(parts[-2]) == 2:
                # Likely a country code TLD (e.g., co.uk)
                main_part = parts[-3] if len(parts) > 2 else parts[0]
            else:
                main_part = parts[-2] if len(parts) > 1 else parts[0]
            
            # Capitalize the name
            return main_part.capitalize()
        
        return domain.capitalize()
    
    def extract_source_metadata(self, domain: str, url: str = "") -> Dict[str, Any]:
        """
        Extract metadata from a source's website.
        
        Args:
            domain: Domain name
            url: Full URL (optional)
            
        Returns:
            Dictionary containing extracted metadata
        """
        metadata = {}
        
        # Try to fetch the website
        try:
            # Use a reasonable timeout
            timeout = 10
            
            # Try to fetch the main page
            if url:
                fetch_url = url
            else:
                fetch_url = f"https://{domain}" if not domain.startswith(('http://', 'https://')) else domain
            
            # Add user agent to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Open Omniscience Source Identifier/1.0; +https://github.com/open-omniscience)'
            }
            
            response = requests.get(fetch_url, timeout=timeout, headers=headers)
            response.raise_for_status()
            
            # Parse HTML
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract title
            title = soup.title
            if title:
                metadata['name'] = title.get_text().strip()
            
            # Extract description
            description_meta = soup.find('meta', attrs={'name': 'description'})
            if description_meta:
                metadata['description'] = description_meta.get('content', '').strip()
            
            # Extract language
            lang_meta = soup.find('html', attrs={'lang': True})
            if lang_meta:
                metadata['language'] = lang_meta.get('lang', '')
            
            # Extract favicon
            favicon_link = soup.find('link', attrs={'rel': 'icon'}) or \
                         soup.find('link', attrs={'rel': 'shortcut icon'})
            if favicon_link and favicon_link.get('href'):
                favicon_url = favicon_link.get('href')
                if not favicon_url.startswith(('http://', 'https://')):
                    favicon_url = f"https://{domain}/{favicon_url.lstrip('/')}"
                metadata['favicon_url'] = favicon_url
            
            # Extract social media links
            social_links = {}
            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                if 'facebook.com' in href:
                    social_links['facebook'] = href
                elif 'twitter.com' in href or 'x.com' in href:
                    social_links['twitter'] = href
                elif 'linkedin.com' in href:
                    social_links['linkedin'] = href
                elif 'instagram.com' in href:
                    social_links['instagram'] = href
            
            if social_links:
                metadata['social_media'] = social_links
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error fetching {domain}: {e}")
        except Exception as e:
            logger.warning(f"Error parsing {domain}: {e}")
        
        return metadata
    
    def match_to_known_source(self, domain: str, url: str = "") -> Optional[Dict[str, Any]]:
        """
        Match a domain or URL to a known source.
        
        Args:
            domain: Domain name
            url: Full URL (optional)
            
        Returns:
            Known source information, or None if not found
        """
        domain_lower = domain.lower()
        if domain_lower.startswith('www.'):
            domain_lower = domain_lower[4:]
        
        # Check direct match
        if domain_lower in self.known_sources:
            return self.known_sources[domain_lower]
        
        # Check for subdomain matches
        for known_domain, source_info in self.known_sources.items():
            if domain_lower.endswith('.' + known_domain) or domain_lower == known_domain:
                return source_info
        
        return None
    
    def add_known_source(self, domain: str, source_info: Dict[str, Any]) -> bool:
        """
        Add a known source to the database.
        
        Args:
            domain: Domain name
            source_info: Source information dictionary
            
        Returns:
            True if source was added successfully
        """
        if not domain:
            logger.error("Domain is required")
            return False
        
        domain_lower = domain.lower()
        if domain_lower.startswith('www.'):
            domain_lower = domain_lower[4:]
        
        # Check for duplicate
        if domain_lower in self.known_sources:
            logger.error(f"Source with domain '{domain}' already exists")
            return False
        
        # Add the source
        source_info['domain'] = domain_lower
        self.known_sources[domain_lower] = source_info
        return True
    
    def get_source_types(self) -> List[str]:
        """
        Get all available source types.
        
        Returns:
            List of source type strings
        """
        return list(self.source_type_patterns.keys())
    
    def get_source_statistics(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics about identified sources.
        
        Args:
            sources: List of source dictionaries
            
        Returns:
            Dictionary containing source statistics
        """
        if not sources:
            return {'total': 0, 'types': {}, 'domains': {}}
        
        total = len(sources)
        types = {}
        domains = {}
        
        for source in sources:
            source_type = source.get('source_type', 'unknown')
            domain = source.get('domain', 'unknown')
            
            types[source_type] = types.get(source_type, 0) + 1
            domains[domain] = domains.get(domain, 0) + 1
        
        return {
            'total': total,
            'types': types,
            'domains': domains
        }