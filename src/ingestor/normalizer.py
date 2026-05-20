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
Data Normalization for Open Omniscience

This module provides data normalization capabilities for standardizing
article metadata and content before storage.

Features:
- Standardize metadata fields (title, date, author, language, region)
- Clean and normalize text content
- Extract and normalize URLs
- Language detection and normalization
- Region/country detection from text

Author: Ideotion
"""

import re
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import string

# Configure logging
from src.utils.logging_config import setup_logging
logger = setup_logging("normalizer")


@dataclass
class NormalizedArticle:
    """Normalized article data structure."""
    url: str
    canonical_url: str
    title: str
    content: str
    published_at: Optional[datetime]
    language: str
    region: Optional[str]
    country: Optional[str]
    author: Optional[str]
    source_domain: str
    tags: List[str]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "content": self.content,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "language": self.language,
            "region": self.region,
            "country": self.country,
            "author": self.author,
            "source_domain": self.source_domain,
            "tags": self.tags,
            "metadata": self.metadata
        }


class TextNormalizer:
    """
    Text normalization utilities.
    
    Provides methods for cleaning and normalizing text content.
    """
    
    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """
        Normalize whitespace in text.
        
        Args:
            text: Input text.
            
        Returns:
            Text with normalized whitespace.
        """
        # Replace multiple whitespace characters with single space
        text = re.sub(r'\s+', ' ', text)
        # Strip leading/trailing whitespace
        text = text.strip()
        return text
    
    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Normalize Unicode characters in text.
        
        Args:
            text: Input text.
            
        Returns:
            Text with normalized Unicode characters.
        """
        # Normalize to NFC form (canonical composition)
        text = unicodedata.normalize('NFC', text)
        return text
    
    @staticmethod
    def remove_control_chars(text: str) -> str:
        """
        Remove control characters from text.
        
        Args:
            text: Input text.
            
        Returns:
            Text without control characters.
        """
        # Remove control characters (except newline, tab, carriage return)
        text = ''.join(
            char for char in text
            if char in '\n\r\t' or (char >= ' ' and char != '\x7f')
        )
        return text
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        Clean text by applying multiple normalization steps.
        
        Args:
            text: Input text.
            
        Returns:
            Cleaned text.
        """
        # Remove control characters
        text = TextNormalizer.remove_control_chars(text)
        # Normalize Unicode
        text = TextNormalizer.normalize_unicode(text)
        # Normalize whitespace
        text = TextNormalizer.normalize_whitespace(text)
        return text
    
    @staticmethod
    def extract_main_content(html: str) -> str:
        """
        Extract main content from HTML.
        
        This is a simple heuristic-based extraction. For more robust
        extraction, consider using readability-lxml or similar.
        
        Args:
            html: HTML content.
            
        Returns:
            Extracted main text content.
        """
        from bs4 import BeautifulSoup
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Try to find article tag
            article = soup.find('article')
            if article:
                return article.get_text(separator=' ', strip=True)
            
            # Try common content classes
            for selector in ['.content', '.main', '.body', '.post', '.article-body']:
                content = soup.select_one(selector)
                if content:
                    return content.get_text(separator=' ', strip=True)
            
            # Try to find the largest text block
            paragraphs = soup.find_all('p')
            if paragraphs:
                return ' '.join(p.get_text(strip=True) for p in paragraphs)
            
            # Fallback to all text
            return soup.get_text(separator=' ', strip=True)
            
        except Exception as e:
            logger.warning(f"Error extracting main content: {e}")
            return html
    
    @staticmethod
    def remove_boilerplate(text: str) -> str:
        """
        Remove boilerplate text from content.
        
        Args:
            text: Input text.
            
        Returns:
            Text with boilerplate removed.
        """
        # Common boilerplate patterns
        patterns = [
            r'\bCopyright\b.*?\d{4}',
            r'\bAll rights reserved\b',
            r'\bPrivacy Policy\b.*?\bTerms of Service\b',
            r'\bCookie Policy\b',
            r'\bSubscribe to our newsletter\b',
            r'\bFollow us on\b',
            r'\bShare this article\b',
            r'\bPrint this page\b',
            r'\bAdvertisement\b',
            r'\bSponsored by\b',
            r'\bAbout us\b',
            r'\bContact us\b',
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
        
        # Remove short lines (likely boilerplate)
        lines = text.split('\n')
        cleaned_lines = [line for line in lines if len(line.strip()) > 20]
        text = '\n'.join(cleaned_lines)
        
        return text


class DateNormalizer:
    """
    Date normalization utilities.
    
    Provides methods for parsing and normalizing date strings.
    """
    
    # Common date formats to try
    DATE_FORMATS = [
        # ISO 8601 formats
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
        
        # RFC 2822
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S',
        
        # Common formats
        '%d %b %Y %H:%M:%S',
        '%d %B %Y %H:%M:%S',
        '%b %d, %Y %H:%M:%S',
        '%B %d, %Y %H:%M:%S',
        '%d/%m/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M:%S',
        '%d-%m-%Y %H:%M:%S',
        '%m-%d-%Y %H:%M:%S',
        
        # Date only
        '%d %b %Y',
        '%d %B %Y',
        '%b %d, %Y',
        '%B %d, %Y',
        '%d/%m/%Y',
        '%m/%d/%Y',
        '%d-%m-%Y',
        '%m-%d-%Y',
        
        # Time only
        '%H:%M:%S',
        '%H:%M',
    ]
    
    @classmethod
    def parse_date(cls, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.
        
        Args:
            date_str: Date string to parse.
            
        Returns:
            datetime object if parsing succeeds, None otherwise.
        """
        if not date_str or not isinstance(date_str, str):
            return None
        
        # Clean the date string
        date_str = date_str.strip()
        
        # Try all formats
        for fmt in cls.DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str, fmt)
                # If timezone naive, assume UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        
        # Try with dateutil if available
        try:
            from dateutil.parser import parse
            dt = parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"dateutil parse failed: {e}")
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    @classmethod
    def normalize_date(cls, date_str: str) -> Optional[str]:
        """
        Normalize a date string to ISO 8601 format.
        
        Args:
            date_str: Date string to normalize.
            
        Returns:
            ISO 8601 formatted date string, or None if parsing fails.
        """
        dt = cls.parse_date(date_str)
        if dt:
            return dt.isoformat()
        return None


class LanguageDetector:
    """
    Language detection utilities.
    
    Provides methods for detecting and normalizing language codes.
    """
    
    # Common language codes and their variants
    LANGUAGE_MAP = {
        'en': 'en', 'eng': 'en', 'english': 'en',
        'es': 'es', 'spa': 'es', 'spanish': 'es',
        'fr': 'fr', 'fra': 'fr', 'french': 'fr',
        'de': 'de', 'deu': 'de', 'german': 'de',
        'it': 'it', 'ita': 'it', 'italian': 'it',
        'pt': 'pt', 'por': 'pt', 'portuguese': 'pt',
        'ru': 'ru', 'rus': 'ru', 'russian': 'ru',
        'zh': 'zh', 'zho': 'zh', 'chinese': 'zh',
        'ja': 'ja', 'jpn': 'ja', 'japanese': 'ja',
        'ar': 'ar', 'ara': 'ar', 'arabic': 'ar',
        'hi': 'hi', 'hin': 'hi', 'hindi': 'hi',
        'bn': 'bn', 'ben': 'bn', 'bengali': 'bn',
        'pa': 'pa', 'pan': 'pa', 'punjabi': 'pa',
        'tr': 'tr', 'tur': 'tr', 'turkish': 'tr',
        'nl': 'nl', 'nld': 'nl', 'dutch': 'nl',
        'sv': 'sv', 'swe': 'sv', 'swedish': 'sv',
        'fi': 'fi', 'fin': 'fi', 'finnish': 'fi',
        'da': 'da', 'dan': 'da', 'danish': 'da',
        'no': 'no', 'nor': 'no', 'norwegian': 'no',
        'pl': 'pl', 'pol': 'pl', 'polish': 'pl',
        'uk': 'uk', 'ukr': 'uk', 'ukrainian': 'uk',
        'ko': 'ko', 'kor': 'ko', 'korean': 'ko',
        'vi': 'vi', 'vie': 'vi', 'vietnamese': 'vi',
        'th': 'th', 'tha': 'th', 'thai': 'th',
        'id': 'id', 'ind': 'id', 'indonesian': 'id',
        'ms': 'ms', 'msa': 'ms', 'malay': 'ms',
        'he': 'he', 'heb': 'he', 'hebrew': 'he',
        'el': 'el', 'ell': 'el', 'greek': 'el',
        'hu': 'hu', 'hun': 'hu', 'hungarian': 'hu',
        'cs': 'cs', 'ces': 'cs', 'czech': 'cs',
        'ro': 'ro', 'ron': 'ro', 'romanian': 'ro',
    }
    
    @classmethod
    def normalize_language(cls, lang: str) -> str:
        """
        Normalize a language code to ISO 639-1 format.
        
        Args:
            lang: Language code or name.
            
        Returns:
            Normalized ISO 639-1 language code.
        """
        if not lang:
            return 'en'  # Default to English
        
        lang = lang.lower().strip()
        
        # Check direct mapping
        if lang in cls.LANGUAGE_MAP:
            return cls.LANGUAGE_MAP[lang]
        
        # Check if it's already a 2-letter code
        if len(lang) == 2 and lang.isalpha():
            return lang
        
        # Default to English
        return 'en'
    
    @classmethod
    def detect_language(cls, text: str) -> str:
        """
        Detect the language of a text.
        
        Uses a simple heuristic based on common words.
        For more accurate detection, use langdetect or fasttext.
        
        Args:
            text: Text to analyze.
            
        Returns:
            Detected ISO 639-1 language code.
        """
        if not text or len(text) < 50:
            return 'en'  # Default to English for short texts
        
        # Try using langdetect if available
        try:
            from langdetect import detect
            lang = detect(text)
            return cls.normalize_language(lang)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"langdetect failed: {e}")
        
        # Fallback to simple heuristic
        text_lower = text.lower()
        
        # Check for common words in different languages
        language_indicators = {
            'en': ['the', 'and', 'of', 'to', 'in', 'is', 'it', 'that'],
            'es': ['el', 'la', 'de', 'y', 'en', 'es', 'los', 'las'],
            'fr': ['le', 'la', 'de', 'et', 'en', 'est', 'les', 'des'],
            'de': ['der', 'die', 'das', 'und', 'in', 'ist', 'den', 'von'],
            'it': ['il', 'la', 'di', 'e', 'in', 'è', 'un', 'una'],
            'pt': ['o', 'a', 'de', 'e', 'em', 'é', 'um', 'uma'],
            'ru': ['и', 'в', 'не', 'на', 'я', 'что', 'то', 'он'],
            'zh': ['的', '了', '和', '是', '在', '我', '有', '不'],
            'ja': ['の', 'は', 'が', 'を', 'に', 'も', 'と', 'で'],
            'ar': ['و', 'في', 'لا', 'من', 'ما', 'على', 'أن', 'إلى'],
        }
        
        for lang, words in language_indicators.items():
            count = sum(text_lower.count(word) for word in words)
            if count > 5:  # Arbitrary threshold
                return lang
        
        return 'en'  # Default to English


class RegionDetector:
    """
    Region/country detection utilities.
    
    Provides methods for detecting region or country from text.
    """
    
    # Country names and their ISO codes
    COUNTRY_NAMES = {
        'united states': 'US', 'usa': 'US', 'america': 'US',
        'united kingdom': 'GB', 'uk': 'GB', 'britain': 'GB',
        'canada': 'CA',
        'australia': 'AU',
        'germany': 'DE', 'deutschland': 'DE',
        'france': 'FR',
        'italy': 'IT', 'italia': 'IT',
        'spain': 'ES', 'españa': 'ES',
        'china': 'CN',
        'japan': 'JP', 'nihon': 'JP',
        'india': 'IN', 'bharat': 'IN',
        'brazil': 'BR', 'brasil': 'BR',
        'russia': 'RU', 'rossiya': 'RU',
        'mexico': 'MX',
        'south korea': 'KR', 'korea': 'KR',
        'north korea': 'KP',
        'south africa': 'ZA',
        'nigeria': 'NG',
        'egypt': 'EG',
        'turkey': 'TR', 'türkiye': 'TR',
        'saudi arabia': 'SA',
        'iran': 'IR',
        'iraq': 'IQ',
        'pakistan': 'PK',
        'bangladesh': 'BD',
        'indonesia': 'ID',
        'philippines': 'PH',
        'vietnam': 'VN',
        'thailand': 'TH',
        'malaysia': 'MY',
        'singapore': 'SG',
        'israel': 'IL',
        'sweden': 'SE', 'sverige': 'SE',
        'norway': 'NO', 'norge': 'NO',
        'denmark': 'DK', 'danmark': 'DK',
        'finland': 'FI', 'suomi': 'FI',
        'netherlands': 'NL', 'holland': 'NL',
        'belgium': 'BE', 'belgië': 'BE',
        'switzerland': 'CH',
        'austria': 'AT', 'österreich': 'AT',
        'poland': 'PL', 'polska': 'PL',
        'greece': 'GR', 'hellas': 'GR',
        'argentina': 'AR',
        'colombia': 'CO',
        'chile': 'CL',
        'peru': 'PE',
        'venezuela': 'VE',
    }
    
    # Region to countries mapping
    REGION_COUNTRIES = {
        'north america': ['US', 'CA', 'MX'],
        'south america': ['BR', 'AR', 'CO', 'CL', 'PE', 'VE'],
        'europe': ['GB', 'DE', 'FR', 'IT', 'ES', 'NL', 'BE', 'CH', 'AT', 'PL', 'GR', 'SE', 'NO', 'DK', 'FI'],
        'asia': ['CN', 'JP', 'IN', 'KR', 'KP', 'PK', 'BD', 'ID', 'PH', 'VN', 'TH', 'MY', 'SG', 'IL', 'TR', 'SA', 'IR', 'IQ'],
        'africa': ['ZA', 'NG', 'EG'],
        'middle east': ['SA', 'IR', 'IQ', 'IL', 'TR'],
        'oceania': ['AU'],
    }
    
    @classmethod
    def detect_country(cls, text: str) -> Optional[str]:
        """
        Detect country from text.
        
        Args:
            text: Text to analyze.
            
        Returns:
            ISO 3166-1 alpha-2 country code, or None if not detected.
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        # Check for country names
        for name, code in cls.COUNTRY_NAMES.items():
            if name in text_lower:
                return code
        
        return None
    
    @classmethod
    def detect_region(cls, text: str) -> Optional[str]:
        """
        Detect region from text.
        
        Args:
            text: Text to analyze.
            
        Returns:
            Region name, or None if not detected.
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        # Check for region names
        for region, countries in cls.REGION_COUNTRIES.items():
            if region in text_lower:
                return region
        
        # Check for country codes and map to region
        country_code = cls.detect_country(text)
        if country_code:
            for region, countries in cls.REGION_COUNTRIES.items():
                if country_code in countries:
                    return region
        
        return None


class URLNormalizer:
    """
    URL normalization utilities.
    
    Provides methods for normalizing and canonicalizing URLs.
    """
    
    @staticmethod
    def canonicalize_url(url: str) -> str:
        """
        Canonicalize a URL.
        
        Args:
            url: URL to canonicalize.
            
        Returns:
            Canonicalized URL.
        """
        from src.utils.url_utils import canonicalize_url as utils_canonicalize_url
        return utils_canonicalize_url(url)
    
    @staticmethod
    def extract_domain(url: str) -> str:
        """
        Extract domain from URL.
        
        Args:
            url: URL to extract domain from.
            
        Returns:
            Domain name.
        """
        from urllib.parse import urlparse
        
        if not url:
            return ''
        
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain
            
        except Exception as e:
            logger.warning(f"Error extracting domain from {url}: {e}")
            return ''


class ArticleNormalizer:
    """
    Main article normalization class.
    
    Combines all normalization utilities to standardize article data.
    """
    
    def __init__(self):
        """Initialize the article normalizer."""
        self.text_normalizer = TextNormalizer()
        self.date_normalizer = DateNormalizer()
        self.language_detector = LanguageDetector()
        self.region_detector = RegionDetector()
        self.url_normalizer = URLNormalizer()
    
    def normalize(self, article_data: Dict) -> NormalizedArticle:
        """
        Normalize article data.
        
        Args:
            article_data: Raw article data dictionary.
            
        Returns:
            NormalizedArticle object.
        """
        # Extract and normalize URL
        url = article_data.get('url', '')
        canonical_url = self.url_normalizer.canonicalize_url(url)
        source_domain = self.url_normalizer.extract_domain(url)
        
        # Extract and normalize title
        title = article_data.get('title', 'No Title')
        title = self.text_normalizer.clean_text(title)
        if not title or len(title) < 5:
            title = 'No Title'
        
        # Extract and normalize content
        content = article_data.get('content', '')
        
        # If content looks like HTML, extract main text
        if '<' in content and '>' in content:
            content = self.text_normalizer.extract_main_content(content)
        
        content = self.text_normalizer.clean_text(content)
        content = self.text_normalizer.remove_boilerplate(content)
        
        # Normalize date
        published_at_str = article_data.get('published_at')
        published_at = self.date_normalizer.parse_date(published_at_str)
        
        # Detect or normalize language
        language = article_data.get('language', '')
        if not language:
            language = self.language_detector.detect_language(content)
        else:
            language = self.language_detector.normalize_language(language)
        
        # Detect region and country
        region = self.region_detector.detect_region(content)
        country = self.region_detector.detect_country(content)
        
        # Normalize author
        author = article_data.get('author')
        if author:
            author = self.text_normalizer.clean_text(author)
        
        # Normalize tags
        tags = article_data.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip().lower() for t in tags.split(',') if t.strip()]
        elif isinstance(tags, list):
            tags = [str(t).strip().lower() for t in tags if t]
        else:
            tags = []
        
        # Extract metadata
        metadata = {
            'original_url': url,
            'original_title': article_data.get('title'),
            'original_language': article_data.get('language'),
            'original_published_at': published_at_str,
            'word_count': len(content.split()),
            'character_count': len(content),
        }
        
        # Add any additional metadata from input
        for key, value in article_data.items():
            if key not in ['url', 'title', 'content', 'published_at', 'language', 'author', 'tags']:
                metadata[key] = value
        
        return NormalizedArticle(
            url=url,
            canonical_url=canonical_url,
            title=title,
            content=content,
            published_at=published_at,
            language=language,
            region=region,
            country=country,
            author=author,
            source_domain=source_domain,
            tags=tags,
            metadata=metadata
        )
    
    def batch_normalize(self, articles: List[Dict]) -> List[NormalizedArticle]:
        """
        Normalize a batch of articles.
        
        Args:
            articles: List of raw article data dictionaries.
            
        Returns:
            List of NormalizedArticle objects.
        """
        return [self.normalize(article) for article in articles]


if __name__ == "__main__":
    # Example usage
    normalizer = ArticleNormalizer()
    
    # Sample article data
    article = {
        'url': 'https://www.example.com/article/123?utm_source=twitter',
        'title': '  Breaking News: Important Event Happened  ',
        'content': '<html><body><h1>Title</h1><p>This is the main content.</p><p>Copyright 2024</p></body></html>',
        'published_at': '2024-05-15T10:30:00Z',
        'language': 'English',
        'author': 'John Doe',
        'tags': ['news', 'breaking', 'important']
    }
    
    # Normalize
    normalized = normalizer.normalize(article)
    
    print("Normalized Article:")
    print(f"  URL: {normalized.url}")
    print(f"  Canonical URL: {normalized.canonical_url}")
    print(f"  Title: {normalized.title}")
    print(f"  Content: {normalized.content[:100]}...")
    print(f"  Published At: {normalized.published_at}")
    print(f"  Language: {normalized.language}")
    print(f"  Region: {normalized.region}")
    print(f"  Country: {normalized.country}")
    print(f"  Author: {normalized.author}")
    print(f"  Source Domain: {normalized.source_domain}")
    print(f"  Tags: {normalized.tags}")
    print(f"  Metadata: {normalized.metadata}")
