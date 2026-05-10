"""
Source Detector for Open-Omniscience
Detects and classifies sources/links from article text
"""

import re
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse, urljoin


class SourceDetector:
    """
    Detects URLs, domains, and sources from text content.
    Classifies sources by type (news, blog, social media, etc.)
    """
    
    # Common news domain patterns
    NEWS_DOMAINS = {
        'nytimes', 'washingtonpost', 'guardian', 'bbc', 'cnn', 'foxnews',
        'reuters', 'apnews', 'bloomberg', 'wsj', 'ft', 'thetimes', 'usatoday',
        'npr', 'abcnews', 'nbcnews', 'cbsnews', 'msnbc', 'politico', 'thehill',
        'axios', 'vox', 'buzzfeednews', 'theintercept', 'propublica',
    }
    
    # Social media domains
    SOCIAL_DOMAINS = {
        'twitter', 'facebook', 'instagram', 'linkedin', 'reddit', 'youtube',
        'tiktok', 'snapchat', 'tumblr', 'pinterest', 'medium',
    }
    
    # Blog platforms
    BLOG_DOMAINS = {
        'wordpress', 'blogspot', 'medium', 'substack', 'ghost', 'wix',
        'squarespace', 'weebly',
    }
    
    # Government TLDs
    GOV_TLDS = {
        'gov', 'mil', 'edu',
    }
    
    def __init__(self):
        """Initialize the source detector."""
        pass
    
    def extract_urls(self, text: str) -> List[str]:
        """
        Extract all URLs from text.
        
        Args:
            text: Input text
            
        Returns:
            List of unique URLs found
        """
        if not text:
            return []
        
        # URL pattern
        url_pattern = re.compile(
            r'https?://'  # http:// or https://
            r'(?:[-\w.]|(?:%[\da-fA-F]{2}))+'  # domain
            r'(?::\d+)?'  # port
            r'(?:/[-\w./?%&=]*)?'  # path
            r'(?:\?[-\w./?%&=]*)?'  # query
            r'(?:#[-\w./?%&=]*)?',  # fragment
            re.IGNORECASE
        )
        
        urls = url_pattern.findall(text)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL by removing tracking parameters, fragments, etc.
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        if not url:
            return url
        
        try:
            parsed = urlparse(url)
            
            # Remove fragment
            fragment = ''
            
            # Remove common tracking parameters
            query = parsed.query
            if query:
                query_parts = []
                for param in query.split('&'):
                    param_name = param.split('=')[0] if '=' in param else param
                    if param_name.lower() not in ['utm_source', 'utm_medium', 'utm_campaign', 
                                                     'utm_term', 'utm_content', 'gclid', 'fbclid',
                                                     'mc_cid', 'mc_eid', 'referrer']:
                        query_parts.append(param)
                query = '&'.join(query_parts) if query_parts else ''
            
            # Reconstruct URL
            normalized = urlparse(
                f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                f"{'?' + query if query else ''}"
            ).geturl()
            
            return normalized
        except Exception:
            return url
    
    def _extract_main_domain(self, domain: str) -> str:
        """
        Extract main domain from a domain string.
        Simple implementation without tldextract.
        
        Args:
            domain: Domain string (e.g., 'www.example.co.uk')
            
        Returns:
            Main domain (e.g., 'example')
        """
        if not domain:
            return ''
        
        # Remove www. prefix
        domain = domain.lower().replace('www.', '')
        
        # Split by dots
        parts = domain.split('.')
        
        # If we have at least 2 parts, return the first part
        if len(parts) >= 2:
            return parts[0]
        
        return domain
    
    def classify_source(self, url: str) -> Dict[str, str]:
        """
        Classify a source URL by type.
        
        Args:
            url: URL to classify
            
        Returns:
            Dictionary with classification info
        """
        result = {
            'url': url,
            'domain': '',
            'type': 'unknown',
            'category': 'other',
        }
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            if not domain:
                return result
            
            result['domain'] = domain
            
            # Extract main domain
            main_domain = self._extract_main_domain(domain)
            
            # Get TLD (last part after splitting)
            parts = domain.split('.')
            tld = parts[-1] if parts else ''
            
            # Classify by domain
            if main_domain in self.NEWS_DOMAINS:
                result['type'] = 'news'
                result['category'] = 'news'
            elif main_domain in self.SOCIAL_DOMAINS:
                result['type'] = 'social_media'
                result['category'] = 'social'
            elif main_domain in self.BLOG_DOMAINS:
                result['type'] = 'blog'
                result['category'] = 'blog'
            elif tld in self.GOV_TLDS:
                result['type'] = 'government'
                result['category'] = 'government'
            elif tld == 'edu':
                result['type'] = 'education'
                result['category'] = 'education'
            elif tld == 'org':
                result['type'] = 'organization'
                result['category'] = 'nonprofit'
            elif tld in ['com', 'net', 'io', 'co']:
                result['type'] = 'commercial'
                result['category'] = 'commercial'
            else:
                result['type'] = 'other'
                result['category'] = 'other'
        except Exception:
            pass
        
        return result
    
    def extract_sources_from_text(self, text: str) -> List[Dict[str, str]]:
        """
        Extract and classify all sources from text.
        
        Args:
            text: Input text
            
        Returns:
            List of source dictionaries with classification
        """
        urls = self.extract_urls(text)
        
        sources = []
        for url in urls:
            normalized = self.normalize_url(url)
            classified = self.classify_source(normalized)
            sources.append(classified)
        
        return sources
    
    def extract_domains(self, text: str) -> Set[str]:
        """
        Extract unique domains from text.
        
        Args:
            text: Input text
            
        Returns:
            Set of unique domains
        """
        urls = self.extract_urls(text)
        domains = set()
        
        for url in urls:
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    domains.add(parsed.netloc.lower())
            except Exception:
                pass
        
        return domains
    
    def extract_emails(self, text: str) -> List[str]:
        """
        Extract email addresses from text.
        
        Args:
            text: Input text
            
        Returns:
            List of unique email addresses
        """
        if not text:
            return []
        
        email_pattern = re.compile(
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        )
        
        emails = email_pattern.findall(text)
        
        # Remove duplicates
        seen = set()
        unique_emails = []
        for email in emails:
            if email.lower() not in seen:
                seen.add(email.lower())
                unique_emails.append(email)
        
        return unique_emails
    
    def extract_social_media_handles(self, text: str) -> List[str]:
        """
        Extract social media handles (e.g., @username) from text.
        
        Args:
            text: Input text
            
        Returns:
            List of unique handles
        """
        if not text:
            return []
        
        # Pattern for @username
        handle_pattern = re.compile(r'@([a-zA-Z0-9_]{1,30})')
        
        handles = handle_pattern.findall(text)
        
        # Remove duplicates
        seen = set()
        unique_handles = []
        for handle in handles:
            if handle.lower() not in seen:
                seen.add(handle.lower())
                unique_handles.append(f'@{handle}')
        
        return unique_handles


# Global instance
source_detector = SourceDetector()
