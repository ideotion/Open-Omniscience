"""
Keyword Extractor Module

Extracts keywords from financial instrument names, descriptions, and articles.
Uses NLP techniques for intelligent keyword extraction.
"""

import re
import json
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections import Counter

from pillar5.src.scraping.base import EthicalScraper, ScraperConfig
from pillar5.src.models import InstrumentKeyword, InstrumentKeywordDB


@dataclass
class ExtractedKeyword:
    """A keyword extracted from text."""
    keyword: str
    weight: float = 1.0
    source: str = "name"  # name, description, sector, article
    language: str = "en"
    
    def to_instrument_keyword(self, instrument_id: str) -> InstrumentKeyword:
        """Convert to InstrumentKeyword dataclass."""
        return InstrumentKeyword(
            id=f"{instrument_id}:{self.keyword}",
            instrument_id=instrument_id,
            keyword=self.keyword,
            source=self.source,
            weight=self.weight,
            language=self.language,
        )


class KeywordExtractor:
    """
    Extracts keywords from text using NLP techniques.
    
    Features:
    - Stop word removal
    - Stemming/lemmatization
    - N-gram extraction
    - Named entity recognition (basic)
    - Sector/industry classification
    - Keyword weighting
    """
    
    # Common stop words
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
        'to', 'was', 'were', 'will', 'with', 'i', 'you', 'your', 'they',
        'this', 'that', 'these', 'those', 'am', 'do', 'does', 'did', 'have',
        'has', 'had', 'but', 'or', 'so', 'if', 'because', 'as', 'until',
        'while', 'of', 'at', 'by', 'about', 'into', 'through', 'during',
        'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down',
        'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further',
        'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how',
        'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other',
        'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'than',
        'too', 'very', 'can', 'will', 'just', 'should', 'now',
    }
    
    # Common financial terms that should be kept
    FINANCIAL_TERMS = {
        'stock', 'etf', 'index', 'commodity', 'forex', 'crypto', 'market',
        'exchange', 'trade', 'trading', 'invest', 'investment', 'portfolio',
        'asset', 'assets', 'security', 'securities', 'financial', 'finance',
        'bank', 'banks', 'broker', 'brokerage', 'fund', 'funds', 'capital',
        'price', 'prices', 'value', 'values', 'rate', 'rates', 'return',
        'returns', 'yield', 'yields', 'dividend', 'dividends', 'earn', 'earnings',
        'revenue', 'profit', 'loss', 'growth', 'risk', 'volatility',
        'technology', 'healthcare', 'energy', 'financials', 'consumer',
        'industrial', 'utilities', 'materials', 'real', 'estate',
    }
    
    # Sector keywords
    SECTOR_KEYWORDS = {
        'technology': ['tech', 'technology', 'software', 'hardware', 'semiconductor', 'chip', 'ai', 'cloud', 'saas'],
        'healthcare': ['health', 'healthcare', 'medical', 'pharma', 'pharmaceutical', 'biotech', 'hospital'],
        'financial': ['financial', 'bank', 'insurance', 'fintech', 'payment', 'credit', 'loan'],
        'energy': ['energy', 'oil', 'gas', 'petroleum', 'renewable', 'solar', 'wind', 'electric'],
        'consumer discretionary': ['consumer', 'retail', 'automotive', 'luxury', 'apparel', 'ecommerce'],
        'consumer staples': ['staples', 'food', 'beverage', 'tobacco', 'household'],
        'industrials': ['industrial', 'manufacturing', 'aerospace', 'defense', 'construction'],
        'utilities': ['utility', 'electric', 'water', 'gas', 'power'],
        'materials': ['material', 'chemical', 'metal', 'mining', 'steel', 'aluminum'],
        'real estate': ['real', 'estate', 'property', 'reit', 'housing', 'commercial'],
        'communication services': ['communication', 'telecom', 'media', 'entertainment', 'internet'],
    }
    
    # Industry keywords
    INDUSTRY_KEYWORDS = {
        'software': ['software', 'saas', 'platform', 'application', 'enterprise'],
        'hardware': ['hardware', 'chip', 'semiconductor', 'processor', 'device'],
        'internet': ['internet', 'web', 'online', 'digital', 'ecommerce'],
        'banks': ['bank', 'banking', 'credit', 'loan', 'mortgage'],
        'insurance': ['insurance', 'underwriting', 'actuarial', 'risk'],
        'pharmaceuticals': ['pharma', 'pharmaceutical', 'drug', 'medicine', 'biotech'],
        'oil & gas': ['oil', 'gas', 'petroleum', 'energy', 'fuel'],
        'automotive': ['auto', 'automotive', 'car', 'vehicle', 'electric'],
        'retail': ['retail', 'store', 'shop', 'ecommerce', 'online'],
    }
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """Initialize KeywordExtractor."""
        self.config = config
    
    def extract_keywords(
        self,
        text: str,
        source: str = "name",
        min_length: int = 3,
        max_length: int = 30,
        top_n: Optional[int] = None
    ) -> List[ExtractedKeyword]:
        """
        Extract keywords from text.
        
        Args:
            text: The text to extract keywords from
            source: The source of the text (name, description, sector, article)
            min_length: Minimum keyword length
            max_length: Maximum keyword length
            top_n: Maximum number of keywords to return (None for all)
            
        Returns:
            List of ExtractedKeyword objects
        """
        if not text or not isinstance(text, str):
            return []
        
        # Clean and normalize text
        text = self._clean_text(text)
        
        # Tokenize
        tokens = self._tokenize(text)
        
        # Filter tokens
        filtered_tokens = self._filter_tokens(tokens, min_length, max_length)
        
        # Count frequencies
        token_counts = Counter(filtered_tokens)
        
        # Calculate weights
        total_tokens = len(filtered_tokens)
        keywords = []
        
        for token, count in token_counts.items():
            # Calculate weight based on frequency and position
            weight = self._calculate_weight(token, count, total_tokens, text)
            
            keyword = ExtractedKeyword(
                keyword=token,
                weight=weight,
                source=source,
                language="en"
            )
            keywords.append(keyword)
        
        # Sort by weight
        keywords.sort(key=lambda k: k.weight, reverse=True)
        
        # Return top N
        if top_n is not None:
            keywords = keywords[:top_n]
        
        return keywords
    
    def extract_from_instrument(
        self,
        instrument_id: str,
        name: str,
        description: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None
    ) -> List[InstrumentKeyword]:
        """
        Extract keywords from an instrument's metadata.
        
        Args:
            instrument_id: The instrument ID
            name: The instrument name
            description: The instrument description
            sector: The instrument sector
            industry: The instrument industry
            
        Returns:
            List of InstrumentKeyword objects
        """
        keywords = []
        
        # Extract from name
        name_keywords = self.extract_keywords(name, source="name")
        for kw in name_keywords:
            keywords.append(kw.to_instrument_keyword(instrument_id))
        
        # Extract from description
        if description:
            desc_keywords = self.extract_keywords(description, source="description")
            for kw in desc_keywords:
                # Avoid duplicates
                if not any(k.keyword == kw.keyword for k in keywords):
                    keywords.append(kw.to_instrument_keyword(instrument_id))
        
        # Add sector as keyword
        if sector:
            sector_keyword = ExtractedKeyword(
                keyword=sector.lower(),
                weight=0.9,
                source="sector",
                language="en"
            )
            if not any(k.keyword == sector_keyword.keyword for k in keywords):
                keywords.append(sector_keyword.to_instrument_keyword(instrument_id))
        
        # Add industry as keyword
        if industry:
            industry_keyword = ExtractedKeyword(
                keyword=industry.lower(),
                weight=0.8,
                source="sector",
                language="en"
            )
            if not any(k.keyword == industry_keyword.keyword for k in keywords):
                keywords.append(industry_keyword.to_instrument_keyword(instrument_id))
        
        return keywords
    
    def extract_from_article(
        self,
        article_text: str,
        instrument_id: Optional[str] = None
    ) -> List[ExtractedKeyword]:
        """
        Extract keywords from article text.
        
        Args:
            article_text: The article text
            instrument_id: Optional instrument ID to associate with keywords
            
        Returns:
            List of ExtractedKeyword objects
        """
        # Extract keywords from article
        keywords = self.extract_keywords(article_text, source="article", top_n=20)
        
        # Boost weight for financial terms
        for kw in keywords:
            if kw.keyword in self.FINANCIAL_TERMS:
                kw.weight = min(kw.weight * 1.5, 1.0)
        
        return keywords
    
    def match_keywords_to_instrument(
        self,
        keywords: List[str],
        instrument: InstrumentKeywordDB
    ) -> List[str]:
        """
        Match a list of keywords to an instrument's keywords.
        
        Args:
            keywords: List of keywords to match
            instrument: The instrument with its keywords
            
        Returns:
            List of matched keyword strings
        """
        # This would be used in the correlation engine
        # For now, simple exact matching
        matched = []
        
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if kw_lower in [k.keyword.lower() for k in instrument.keywords]:
                matched.append(kw_lower)
        
        return matched
    
    def get_sector_from_keywords(self, keywords: List[str]) -> Optional[str]:
        """
        Infer sector from a list of keywords.
        
        Args:
            keywords: List of keywords
            
        Returns:
            Inferred sector or None
        """
        keyword_set = set(kw.lower() for kw in keywords)
        
        for sector, sector_keywords in self.SECTOR_KEYWORDS.items():
            matches = keyword_set.intersection(set(sector_keywords))
            if matches:
                return sector
        
        return None
    
    def get_industry_from_keywords(self, keywords: List[str]) -> Optional[str]:
        """
        Infer industry from a list of keywords.
        
        Args:
            keywords: List of keywords
            
        Returns:
            Inferred industry or None
        """
        keyword_set = set(kw.lower() for kw in keywords)
        
        for industry, industry_keywords in self.INDUSTRY_KEYWORDS.items():
            matches = keyword_set.intersection(set(industry_keywords))
            if matches:
                return industry
        
        return None
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        # Remove special characters except spaces and hyphens
        text = re.sub(r'[^\w\s-]', ' ', text)
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        # Convert to lowercase
        text = text.lower().strip()
        return text
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        # Split on whitespace
        tokens = text.split()
        # Remove empty tokens
        tokens = [t for t in tokens if t]
        return tokens
    
    def _filter_tokens(
        self,
        tokens: List[str],
        min_length: int,
        max_length: int
    ) -> List[str]:
        """Filter tokens by length and stop words."""
        filtered = []
        
        for token in tokens:
            # Check length
            if len(token) < min_length or len(token) > max_length:
                continue
            
            # Skip stop words unless they're financial terms
            if token in self.STOP_WORDS and token not in self.FINANCIAL_TERMS:
                continue
            
            # Skip pure numbers
            if token.isdigit():
                continue
            
            filtered.append(token)
        
        return filtered
    
    def _calculate_weight(
        self,
        token: str,
        count: int,
        total_tokens: int,
        text: str
    ) -> float:
        """Calculate weight for a token."""
        # Base weight is frequency relative to total
        base_weight = count / total_tokens if total_tokens > 0 else 0
        
        # Boost for financial terms
        if token in self.FINANCIAL_TERMS:
            base_weight *= 1.5
        
        # Boost for longer tokens (more specific)
        if len(token) > 5:
            base_weight *= 1.2
        
        # Cap at 1.0
        return min(base_weight, 1.0)
    
    def save_to_database(
        self,
        keywords: List[InstrumentKeyword]
    ) -> int:
        """
        Save keywords to the database.
        
        Args:
            keywords: List of InstrumentKeyword objects to save
            
        Returns:
            Number of keywords saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for keyword in keywords:
                # Check if already exists
                existing = db.query(InstrumentKeywordDB).filter_by(
                    instrument_id=keyword.instrument_id,
                    keyword=keyword.keyword
                ).first()
                
                if existing:
                    # Update existing
                    existing.weight = keyword.weight
                    existing.source = keyword.source
                    existing.language = keyword.language
                else:
                    # Create new
                    keyword_db = InstrumentKeywordDB.from_dataclass(keyword)
                    db.add(keyword_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get keyword extractor statistics."""
        return {
            "stop_words": len(self.STOP_WORDS),
            "financial_terms": len(self.FINANCIAL_TERMS),
            "sectors": len(self.SECTOR_KEYWORDS),
            "industries": len(self.INDUSTRY_KEYWORDS),
        }
