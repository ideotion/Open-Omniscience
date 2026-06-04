"""
Hybrid Correlation Engine

Implements hybrid linking between articles and financial instruments using:
- Temporal correlation
- Keyword matching
- Sector/industry matching
- Mention detection
"""

import re
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from pillar5.src.models import (
    ArticleFinancialLink,
    ArticleFinancialLinkDB,
    FinancialInstrumentDB,
    InstrumentKeywordDB,
)
from pillar5.src.scraping.keyword_extractor import KeywordExtractor
from pillar5.src.models.correlation import CorrelationType, Direction

# Add HYBRID to CorrelationType for our use
class ExtendedCorrelationType:
    """Extended correlation types including hybrid."""
    MENTION = "mention"
    EVENT = "event"
    SENTIMENT = "sentiment"
    TEMPORAL = "temporal"
    STATISTICAL = "statistical"
    KEYWORD = "keyword"
    SECTOR = "sector"
    HYBRID = "hybrid"


class CorrelationMethod(Enum):
    """Methods for calculating correlation."""
    TEMPORAL = "temporal"
    KEYWORD = "keyword"
    SECTOR = "sector"
    MENTION = "mention"
    HYBRID = "hybrid"


@dataclass
class CorrelationResult:
    """Result of correlation calculation."""
    article_id: str
    instrument_id: str
    correlation_score: float
    correlation_type: str
    matched_keywords: List[str] = field(default_factory=list)
    matched_sector: Optional[str] = None
    time_diff_hours: Optional[float] = None
    direction: str = Direction.SAME_TIME.value
    confidence: float = 0.0
    is_significant: bool = False
    
    def to_article_financial_link(self) -> ArticleFinancialLink:
        """Convert to ArticleFinancialLink dataclass."""
        return ArticleFinancialLink(
            id=f"{self.article_id}:{self.instrument_id}",
            article_id=self.article_id,
            instrument_id=self.instrument_id,
            correlation_score=self.correlation_score,
            correlation_type=self.correlation_type,
            time_diff_hours=self.time_diff_hours,
            direction=self.direction,
            matched_keywords=self.matched_keywords,
            matched_sector=self.matched_sector,
            confidence=self.confidence,
            is_significant=self.is_significant,
        )


class HybridCorrelationEngine:
    """
    Hybrid correlation engine for linking articles to financial instruments.
    
    Uses multiple correlation methods:
    1. Temporal: Time proximity between article and financial event
    2. Keyword: Keyword matching between article and instrument
    3. Sector: Sector/industry matching
    4. Mention: Direct mention of instrument in article
    
    Hybrid score formula:
    correlation_score = (mention * 0.4) + (keyword * 0.3) + (sector * 0.2) + (temporal * 0.1)
    """
    
    # Weights for hybrid scoring
    HYBRID_WEIGHTS = {
        ExtendedCorrelationType.MENTION: 0.4,
        ExtendedCorrelationType.KEYWORD: 0.3,
        ExtendedCorrelationType.SECTOR: 0.2,
        ExtendedCorrelationType.TEMPORAL: 0.1,
    }
    
    def __init__(self):
        """Initialize HybridCorrelationEngine."""
        self.keyword_extractor = KeywordExtractor()
    
    def calculate_correlation(
        self,
        article_id: str,
        article_text: str,
        article_timestamp: datetime,
        article_sentiment: Optional[float] = None,
        instruments: Optional[List[FinancialInstrumentDB]] = None,
        instrument_keywords: Optional[Dict[str, List[InstrumentKeywordDB]]] = None,
        time_window_hours: float = 24.0,
        min_score: float = 0.1
    ) -> List[CorrelationResult]:
        """
        Calculate correlations between an article and financial instruments.
        
        Args:
            article_id: The article ID
            article_text: The article text content
            article_timestamp: The article publication timestamp
            article_sentiment: Optional sentiment score for the article
            instruments: Optional list of instruments to correlate with
            instrument_keywords: Optional dict mapping instrument_id to keywords
            time_window_hours: Time window for temporal correlation (hours)
            min_score: Minimum correlation score to include
            
        Returns:
            List of CorrelationResult objects
        """
        results = []
        
        # Extract keywords from article
        article_keywords = self.keyword_extractor.extract_from_article(article_text)
        article_keyword_strings = [kw.keyword for kw in article_keywords]
        
        # Get instruments if not provided
        if instruments is None:
            from pillar5.src.models import SessionLocal
            with SessionLocal() as db:
                instruments = db.query(FinancialInstrumentDB).all()
        
        # Get instrument keywords if not provided
        if instrument_keywords is None:
            from pillar5.src.models import SessionLocal
            with SessionLocal() as db:
                all_keywords = db.query(InstrumentKeywordDB).all()
                instrument_keywords = {}
                for kw in all_keywords:
                    if kw.instrument_id not in instrument_keywords:
                        instrument_keywords[kw.instrument_id] = []
                    instrument_keywords[kw.instrument_id].append(kw)
        
        # Calculate correlation for each instrument
        for instrument in instruments:
            # Calculate individual correlation scores
            mention_score = self._calculate_mention_score(article_text, instrument)
            keyword_score = self._calculate_keyword_score(article_keyword_strings, instrument, instrument_keywords)
            sector_score = self._calculate_sector_score(article_text, instrument)
            temporal_score = self._calculate_temporal_score(article_timestamp, instrument, time_window_hours)
            
            # Calculate hybrid score
            hybrid_score = self._calculate_hybrid_score(
                mention_score, keyword_score, sector_score, temporal_score
            )
            
            # Only include if above minimum threshold
            if hybrid_score >= min_score:
                # Determine direction
                direction = self._determine_direction(article_timestamp, instrument)
                
                # Calculate time difference
                time_diff = self._calculate_time_diff(article_timestamp, instrument)
                
                result = CorrelationResult(
                    article_id=article_id,
                    instrument_id=instrument.id,
                    correlation_score=hybrid_score,
                    correlation_type=ExtendedCorrelationType.HYBRID,
                    matched_keywords=article_keyword_strings[:5],  # Top 5 keywords
                    matched_sector=instrument.sector,
                    time_diff_hours=time_diff,
                    direction=direction,
                    confidence=hybrid_score,
                    is_significant=hybrid_score >= 0.7,
                )
                results.append(result)
        
        # Sort by correlation score
        results.sort(key=lambda r: r.correlation_score, reverse=True)
        
        return results
    
    def calculate_single_correlation(
        self,
        article_id: str,
        article_text: str,
        article_timestamp: datetime,
        instrument: FinancialInstrumentDB,
        instrument_keywords: List[InstrumentKeywordDB],
        time_window_hours: float = 24.0
    ) -> CorrelationResult:
        """
        Calculate correlation between a single article and instrument.
        
        Args:
            article_id: The article ID
            article_text: The article text content
            article_timestamp: The article publication timestamp
            instrument: The financial instrument
            instrument_keywords: List of keywords for the instrument
            time_window_hours: Time window for temporal correlation
            
        Returns:
            CorrelationResult object
        """
        # Extract keywords from article
        article_keywords = self.keyword_extractor.extract_from_article(article_text)
        article_keyword_strings = [kw.keyword for kw in article_keywords]
        
        # Calculate individual scores
        mention_score = self._calculate_mention_score(article_text, instrument)
        keyword_score = self._calculate_keyword_score(article_keyword_strings, instrument, {instrument.id: instrument_keywords})
        sector_score = self._calculate_sector_score(article_text, instrument)
        temporal_score = self._calculate_temporal_score(article_timestamp, instrument, time_window_hours)
        
        # Calculate hybrid score
        hybrid_score = self._calculate_hybrid_score(
            mention_score, keyword_score, sector_score, temporal_score
        )
        
        # Determine direction and time difference
        direction = self._determine_direction(article_timestamp, instrument)
        time_diff = self._calculate_time_diff(article_timestamp, instrument)
        
        return CorrelationResult(
            article_id=article_id,
            instrument_id=instrument.id,
            correlation_score=hybrid_score,
            correlation_type=ExtendedCorrelationType.HYBRID,
            matched_keywords=article_keyword_strings[:5],
            matched_sector=instrument.sector,
            time_diff_hours=time_diff,
            direction=direction,
            confidence=hybrid_score,
            is_significant=hybrid_score >= 0.7,
        )
    
    def _calculate_mention_score(self, article_text: str, instrument: FinancialInstrumentDB) -> float:
        """
        Calculate mention score (0-1).
        
        Args:
            article_text: The article text
            instrument: The financial instrument
            
        Returns:
            Mention score (0-1)
        """
        if not article_text or not instrument.symbol:
            return 0.0
        
        # Check for exact symbol match
        symbol_pattern = r'\b' + re.escape(instrument.symbol) + r'\b'
        if re.search(symbol_pattern, article_text, re.IGNORECASE):
            return 1.0
        
        # Check for name match
        if instrument.name:
            name_pattern = r'\b' + re.escape(instrument.name) + r'\b'
            if re.search(name_pattern, article_text, re.IGNORECASE):
                return 0.9
        
        # Check for partial matches
        if instrument.symbol in article_text.upper():
            return 0.7
        
        if instrument.name and instrument.name.upper() in article_text.upper():
            return 0.6
        
        return 0.0
    
    def _calculate_keyword_score(
        self,
        article_keywords: List[str],
        instrument: FinancialInstrumentDB,
        instrument_keywords: Dict[str, List[InstrumentKeywordDB]]
    ) -> float:
        """
        Calculate keyword matching score (0-1).
        
        Args:
            article_keywords: List of keywords from the article
            instrument: The financial instrument
            instrument_keywords: Dict mapping instrument_id to keywords
            
        Returns:
            Keyword score (0-1)
        """
        if not article_keywords:
            return 0.0
        
        # Get instrument keywords
        inst_keywords = instrument_keywords.get(instrument.id, [])
        if not inst_keywords:
            # If no keywords, use sector/industry
            if instrument.sector:
                inst_keywords = [InstrumentKeywordDB(
                    id=f"{instrument.id}:{instrument.sector}",
                    instrument_id=instrument.id,
                    keyword=instrument.sector.lower(),
                    source="sector",
                    weight=0.9,
                    language="en",
                    created_at=datetime.now()
                )]
            if instrument.industry:
                inst_keywords.append(InstrumentKeywordDB(
                    id=f"{instrument.id}:{instrument.industry}",
                    instrument_id=instrument.id,
                    keyword=instrument.industry.lower(),
                    source="sector",
                    weight=0.8,
                    language="en",
                    created_at=datetime.now()
                ))
        
        if not inst_keywords:
            return 0.0
        
        inst_keyword_strings = [kw.keyword.lower() for kw in inst_keywords]
        
        # Count matches
        matches = 0
        total_weight = 0.0
        
        for article_kw in article_keywords:
            article_kw_lower = article_kw.lower()
            for inst_kw in inst_keyword_strings:
                if article_kw_lower == inst_kw:
                    matches += 1
                    break
        
        # Calculate score based on matches and weights
        if matches > 0:
            # Find matching keywords with weights
            matched_weights = []
            for article_kw in article_keywords:
                article_kw_lower = article_kw.lower()
                for kw in inst_keywords:
                    if article_kw_lower == kw.keyword.lower():
                        matched_weights.append(kw.weight)
                        break
            
            if matched_weights:
                # Weighted average of matched keywords
                avg_weight = sum(matched_weights) / len(matched_weights)
                # Normalize by number of article keywords
                score = (len(matched_weights) / len(article_keywords)) * avg_weight
                return min(score, 1.0)
        
        return 0.0
    
    def _calculate_sector_score(self, article_text: str, instrument: FinancialInstrumentDB) -> float:
        """
        Calculate sector matching score (0-1).
        
        Args:
            article_text: The article text
            instrument: The financial instrument
            
        Returns:
            Sector score (0-1)
        """
        if not instrument.sector:
            return 0.0
        
        # Extract keywords from article
        article_keywords = self.keyword_extractor.extract_keywords(article_text, top_n=20)
        article_keyword_strings = [kw.keyword for kw in article_keywords]
        
        # Check if sector keywords appear in article
        sector_keywords = self.keyword_extractor.SECTOR_KEYWORDS.get(
            instrument.sector.lower(), []
        )
        
        if not sector_keywords:
            # Direct sector name check
            if instrument.sector.lower() in article_text.lower():
                return 0.8
            return 0.0
        
        # Count sector keyword matches
        matches = 0
        for sector_kw in sector_keywords:
            if sector_kw in article_keyword_strings:
                matches += 1
        
        if matches > 0:
            return min(matches * 0.2, 1.0)
        
        # Check for direct sector mention
        if instrument.sector.lower() in article_text.lower():
            return 0.5
        
        return 0.0
    
    def _calculate_temporal_score(
        self,
        article_timestamp: datetime,
        instrument: FinancialInstrumentDB,
        time_window_hours: float = 24.0
    ) -> float:
        """
        Calculate temporal correlation score (0-1).
        
        Args:
            article_timestamp: The article timestamp
            instrument: The financial instrument
            time_window_hours: Time window for correlation
            
        Returns:
            Temporal score (0-1)
        """
        # For temporal correlation, we need financial data timestamps
        # This is a simplified version - in production, we would check
        # if there are financial data points close to the article timestamp
        
        # If instrument has last_updated, use that
        if instrument.last_updated:
            time_diff = abs((article_timestamp - instrument.last_updated).total_seconds()) / 3600
            if time_diff <= time_window_hours:
                # Linear decay within window
                return max(0, 1 - (time_diff / time_window_hours))
        
        # Default: assume some temporal correlation
        return 0.3
    
    def _calculate_hybrid_score(
        self,
        mention_score: float,
        keyword_score: float,
        sector_score: float,
        temporal_score: float
    ) -> float:
        """
        Calculate hybrid correlation score.
        
        Formula:
        correlation_score = (mention * 0.4) + (keyword * 0.3) + (sector * 0.2) + (temporal * 0.1)
        
        Args:
            mention_score: Mention score (0-1)
            keyword_score: Keyword score (0-1)
            sector_score: Sector score (0-1)
            temporal_score: Temporal score (0-1)
            
        Returns:
            Hybrid correlation score (0-1)
        """
        score = (
            mention_score * self.HYBRID_WEIGHTS[ExtendedCorrelationType.MENTION] +
            keyword_score * self.HYBRID_WEIGHTS[ExtendedCorrelationType.KEYWORD] +
            sector_score * self.HYBRID_WEIGHTS[ExtendedCorrelationType.SECTOR] +
            temporal_score * self.HYBRID_WEIGHTS[ExtendedCorrelationType.TEMPORAL]
        )
        
        return min(max(score, 0.0), 1.0)
    
    def _determine_direction(
        self,
        article_timestamp: datetime,
        instrument: FinancialInstrumentDB
    ) -> str:
        """
        Determine temporal direction.
        
        Args:
            article_timestamp: The article timestamp
            instrument: The financial instrument
            
        Returns:
            Direction string (before, after, same_time)
        """
        if instrument.last_updated:
            if article_timestamp < instrument.last_updated:
                return Direction.BEFORE.value
            elif article_timestamp > instrument.last_updated:
                return Direction.AFTER.value
        
        return Direction.SAME_TIME.value
    
    def _calculate_time_diff(
        self,
        article_timestamp: datetime,
        instrument: FinancialInstrumentDB
    ) -> Optional[float]:
        """
        Calculate time difference in hours.
        
        Args:
            article_timestamp: The article timestamp
            instrument: The financial instrument
            
        Returns:
            Time difference in hours or None
        """
        if instrument.last_updated:
            diff = abs((article_timestamp - instrument.last_updated).total_seconds()) / 3600
            return diff
        return None
    
    def save_to_database(
        self,
        results: List[CorrelationResult]
    ) -> int:
        """
        Save correlation results to the database.
        
        Args:
            results: List of CorrelationResult objects to save
            
        Returns:
            Number of results saved
        """
        from pillar5.src.models import SessionLocal
        
        count = 0
        with SessionLocal() as db:
            for result in results:
                # Check if already exists
                existing = db.query(ArticleFinancialLinkDB).filter_by(
                    article_id=result.article_id,
                    instrument_id=result.instrument_id
                ).first()
                
                if existing:
                    # Update existing
                    link = result.to_article_financial_link()
                    for key, value in link.__dict__.items():
                        if not key.startswith('_') and hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    # Create new
                    link = result.to_article_financial_link()
                    link_db = ArticleFinancialLinkDB.from_dataclass(link)
                    db.add(link_db)
                    count += 1
            
            db.commit()
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get correlation engine statistics."""
        return {
            "hybrid_weights": self.HYBRID_WEIGHTS,
            "methods": [m.value for m in CorrelationMethod],
        }
