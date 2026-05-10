"""
Relationship Tracker Service for Open Omniscience

This module provides functionality for tracking relationships between articles
and their external sources, including temporal analysis.

Author: Open Omniscience Team
"""

import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta
import logging

# Configure logging
logger = logging.getLogger(__name__)


class RelationshipTracker:
    """
    Service for tracking relationships between articles and external sources.
    
    This class provides methods to:
    - Track which external sources are referenced in which articles
    - Calculate temporal relationships (article date vs. source date)
    - Identify temporal anomalies
    - Calculate confidence scores for relationships
    - Store and retrieve relationship information
    """
    
    def __init__(self):
        """Initialize the RelationshipTracker."""
        # Relationship type definitions
        self.relationship_types = {
            'citation': 'Direct citation or reference to a source article',
            'reference': 'General reference to a source or topic',
            'source': 'Source article provides primary information for the article',
            'mention': 'Brief mention of a source or entity',
            'quote': 'Direct quote from a source article',
            'interview': 'Interview with someone from the source',
            'press_release': 'Press release from the source',
            'data_source': 'Source provides data used in the article',
            'background': 'Source provides background information'
        }
    
    def track_relationships(self, article_id: int, classified_links: List[Dict[str, Any]], 
                           identified_sources: List[Dict[str, Any]], 
                           article_published_at: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Track relationships between an article and its external sources.
        
        Args:
            article_id: ID of the article
            classified_links: List of classified links from the article
            identified_sources: List of identified external sources
            article_published_at: Publication date of the article (ISO format)
            
        Returns:
            List of relationship dictionaries
        """
        relationships = []
        
        # Parse article publication date
        article_date = self._parse_date(article_published_at) if article_published_at else None
        
        # Track which sources we've already created relationships for
        seen_sources = set()
        
        for link in classified_links:
            # Skip non-source links
            if link.get('classification') not in ['source', 'reference']:
                continue
            
            domain = link.get('domain', '')
            if not domain:
                continue
            
            # Find the corresponding source
            source_info = None
            for source in identified_sources:
                if source.get('domain') == domain:
                    source_info = source
                    break
            
            if not source_info:
                # Create a basic source info if not found
                source_info = {
                    'domain': domain,
                    'name': domain.capitalize(),
                    'source_type': 'unknown'
                }
            
            # Skip if we've already created a relationship for this source
            source_key = source_info.get('domain', '')
            if source_key in seen_sources:
                continue
            
            seen_sources.add(source_key)
            
            # Determine relationship type
            relationship_type = self._determine_relationship_type(link, source_info)
            
            # Calculate temporal information
            time_delta_days, is_temporal_anomaly = self._calculate_temporal_info(
                article_date, 
                source_info.get('published_at')
            )
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                link, source_info, relationship_type
            )
            
            # Create relationship
            relationship = {
                'article_id': article_id,
                'source_id': source_info.get('id'),
                'source_domain': source_info.get('domain'),
                'source_name': source_info.get('name'),
                'source_type': source_info.get('source_type'),
                'link_id': link.get('id'),
                'link_url': link.get('url'),
                'link_text': link.get('link_text'),
                'relationship_type': relationship_type,
                'time_delta_days': time_delta_days,
                'is_temporal_anomaly': is_temporal_anomaly,
                'confidence_score': confidence_score,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Add source article information if available
            if 'source_article_id' in link:
                relationship['source_article_id'] = link['source_article_id']
            
            relationships.append(relationship)
        
        return relationships
    
    def _determine_relationship_type(self, link: Dict[str, Any], source_info: Dict[str, Any]) -> str:
        """
        Determine the type of relationship based on link and source information.
        
        Args:
            link: Link dictionary
            source_info: Source information dictionary
            
        Returns:
            Relationship type string
        """
        classification = link.get('classification', '')
        link_text = link.get('link_text', '').lower()
        url = link.get('url', '').lower()
        
        # Check for citation patterns
        citation_patterns = [
            r'\bcite\b', r'\breference\b', r'\bsource\b', r'\baccording to\b',
            r'\bas reported by\b', r'\bstudy by\b', r'\bresearch by\b',
            r'\bquoted from\b', r'\bquoting\b'
        ]
        
        for pattern in citation_patterns:
            if re.search(pattern, link_text):
                return 'citation'
        
        # Check for quote patterns
        quote_patterns = [
            r'\bquote\b', r'\bquoted\b', r'\bsaid\b', r'\btold\b',
            r'\bstated\b', r'\bexplained\b'
        ]
        
        for pattern in quote_patterns:
            if re.search(pattern, link_text):
                return 'quote'
        
        # Check for interview patterns
        interview_patterns = [
            r'\binterview\b', r'\btalked to\b', r'\bspoke with\b',
            r'\bexclusive\b'
        ]
        
        for pattern in interview_patterns:
            if re.search(pattern, link_text):
                return 'interview'
        
        # Check for press release patterns
        press_patterns = [
            r'\bpress release\b', r'\bnews release\b', r'\bannouncement\b'
        ]
        
        for pattern in press_patterns:
            if re.search(pattern, link_text) or re.search(pattern, url):
                return 'press_release'
        
        # Check for data source patterns
        data_patterns = [
            r'\bdata\b', r'\bstatistics\b', r'\bchart\b', r'\bgraph\b',
            r'\bstudy\b', r'\breport\b', r'\banalysis\b'
        ]
        
        for pattern in data_patterns:
            if re.search(pattern, link_text):
                return 'data_source'
        
        # Default based on classification
        if classification == 'source':
            return 'source'
        elif classification == 'reference':
            return 'reference'
        
        return 'mention'
    
    def _calculate_temporal_info(self, article_date: Optional[datetime], 
                               source_date_str: Optional[str]) -> Tuple[Optional[float], bool]:
        """
        Calculate temporal information between article and source.
        
        Args:
            article_date: Article publication date (datetime object)
            source_date_str: Source publication date (string)
            
        Returns:
            Tuple of (time_delta_days, is_temporal_anomaly)
        """
        if not article_date:
            return None, False
        
        if not source_date_str:
            return None, False
        
        try:
            # Parse source date
            source_date = self._parse_date(source_date_str)
            if not source_date:
                return None, False
            
            # Calculate time difference
            time_delta = article_date - source_date
            time_delta_days = time_delta.total_seconds() / (24 * 3600)
            
            # Check for temporal anomaly (article published before source)
            is_temporal_anomaly = time_delta_days < 0
            
            return time_delta_days, is_temporal_anomaly
            
        except Exception as e:
            logger.warning(f"Error calculating temporal info: {e}")
            return None, False
    
    def _calculate_confidence_score(self, link: Dict[str, Any], source_info: Dict[str, Any], 
                                   relationship_type: str) -> float:
        """
        Calculate confidence score for a relationship.
        
        Args:
            link: Link dictionary
            source_info: Source information dictionary
            relationship_type: Type of relationship
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = 0.5  # Base confidence
        
        # Increase confidence for certain relationship types
        type_weights = {
            'citation': 0.2,
            'quote': 0.2,
            'interview': 0.15,
            'source': 0.1,
            'reference': 0.05,
            'mention': 0.0
        }
        
        confidence += type_weights.get(relationship_type, 0.0)
        
        # Increase confidence if link text contains source name
        link_text = link.get('link_text', '').lower()
        source_name = source_info.get('name', '').lower()
        if source_name and source_name in link_text:
            confidence += 0.1
        
        # Increase confidence if source is verified
        if source_info.get('is_verified', False):
            confidence += 0.1
        
        # Increase confidence if source has high credibility
        credibility = source_info.get('credibility_score', 50)
        if credibility > 70:
            confidence += 0.05
        elif credibility > 80:
            confidence += 0.1
        
        # Ensure confidence is between 0.0 and 1.0
        confidence = max(0.0, min(1.0, confidence))
        
        return confidence
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.
        
        Args:
            date_str: Date string in various formats
            
        Returns:
            Datetime object, or None if parsing failed
        """
        if not date_str:
            return None
        
        try:
            # Try ISO format first
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            
            # Try parsing with dateutil
            dt = date_parser.parse(date_str)
            
            # If no timezone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            return dt
            
        except Exception as e:
            logger.warning(f"Error parsing date {date_str}: {e}")
            return None
    
    def analyze_temporal_patterns(self, article_id: int, relationships: List[Dict[str, Any]],
                                article_published_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze temporal patterns in article-source relationships.
        
        Args:
            article_id: ID of the article
            relationships: List of relationship dictionaries
            article_published_at: Publication date of the article
            
        Returns:
            Dictionary containing temporal analysis results
        """
        if not relationships:
            return {
                'article_id': article_id,
                'total_relationships': 0,
                'temporal_anomalies': 0,
                'avg_time_delta_days': 0,
                'time_delta_distribution': {},
                'source_types': {}
            }
        
        # Parse article date
        article_date = self._parse_date(article_published_at) if article_published_at else None
        
        temporal_anomalies = 0
        time_deltas = []
        source_types = {}
        time_delta_distribution = {}
        
        for rel in relationships:
            # Count source types
            source_type = rel.get('source_type', 'unknown')
            source_types[source_type] = source_types.get(source_type, 0) + 1
            
            # Analyze temporal information
            time_delta = rel.get('time_delta_days')
            if time_delta is not None:
                time_deltas.append(time_delta)
                
                # Categorize time delta
                if time_delta < -7:
                    category = 'article_before_source_1week+'
                elif time_delta < -1:
                    category = 'article_before_source_1-7days'
                elif time_delta < 0:
                    category = 'article_before_source_1day'
                elif time_delta < 1:
                    category = 'same_day'
                elif time_delta < 7:
                    category = 'article_after_source_1-7days'
                elif time_delta < 30:
                    category = 'article_after_source_1-4weeks'
                else:
                    category = 'article_after_source_1month+'
                
                time_delta_distribution[category] = time_delta_distribution.get(category, 0) + 1
            
            # Count temporal anomalies
            if rel.get('is_temporal_anomaly', False):
                temporal_anomalies += 1
        
        # Calculate average time delta
        avg_time_delta = sum(time_deltas) / len(time_deltas) if time_deltas else 0
        
        return {
            'article_id': article_id,
            'total_relationships': len(relationships),
            'temporal_anomalies': temporal_anomalies,
            'avg_time_delta_days': avg_time_delta,
            'time_delta_distribution': time_delta_distribution,
            'source_types': source_types
        }
    
    def get_relationship_statistics(self, relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics about relationships.
        
        Args:
            relationships: List of relationship dictionaries
            
        Returns:
            Dictionary containing relationship statistics
        """
        if not relationships:
            return {
                'total': 0,
                'by_type': {},
                'by_source_type': {},
                'temporal_anomalies': 0,
                'avg_confidence': 0.0
            }
        
        by_type = {}
        by_source_type = {}
        temporal_anomalies = 0
        confidence_scores = []
        
        for rel in relationships:
            # Count by relationship type
            rel_type = rel.get('relationship_type', 'unknown')
            by_type[rel_type] = by_type.get(rel_type, 0) + 1
            
            # Count by source type
            source_type = rel.get('source_type', 'unknown')
            by_source_type[source_type] = by_source_type.get(source_type, 0) + 1
            
            # Count temporal anomalies
            if rel.get('is_temporal_anomaly', False):
                temporal_anomalies += 1
            
            # Collect confidence scores
            confidence = rel.get('confidence_score', 0.0)
            confidence_scores.append(confidence)
        
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
        
        return {
            'total': len(relationships),
            'by_type': by_type,
            'by_source_type': by_source_type,
            'temporal_anomalies': temporal_anomalies,
            'avg_confidence': avg_confidence
        }
    
    def identify_temporal_anomalies(self, relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify temporal anomalies in relationships.
        
        Args:
            relationships: List of relationship dictionaries
            
        Returns:
            List of relationships with temporal anomalies
        """
        anomalies = []
        
        for rel in relationships:
            if rel.get('is_temporal_anomaly', False):
                anomalies.append(rel)
        
        return anomalies
    
    def get_relationship_types(self) -> Dict[str, str]:
        """
        Get all available relationship types with descriptions.
        
        Returns:
            Dictionary of relationship types and descriptions
        """
        return self.relationship_types.copy()
    
    def create_relationship(self, article_id: int, source_id: int, 
                           relationship_type: str = 'reference',
                           link_id: Optional[int] = None,
                           source_article_id: Optional[int] = None,
                           time_delta_days: Optional[float] = None,
                           is_temporal_anomaly: bool = False,
                           confidence_score: float = 0.5,
                           notes: str = '') -> Dict[str, Any]:
        """
        Create a new relationship record.
        
        Args:
            article_id: ID of the article
            source_id: ID of the external source
            relationship_type: Type of relationship
            link_id: ID of the link that created this relationship
            source_article_id: ID of the source article
            time_delta_days: Time difference in days
            is_temporal_anomaly: Whether there's a temporal anomaly
            confidence_score: Confidence score (0.0 to 1.0)
            notes: Additional notes
            
        Returns:
            Relationship dictionary
        """
        return {
            'article_id': article_id,
            'source_id': source_id,
            'source_article_id': source_article_id,
            'link_id': link_id,
            'relationship_type': relationship_type,
            'time_delta_days': time_delta_days,
            'is_temporal_anomaly': is_temporal_anomaly,
            'confidence_score': confidence_score,
            'notes': notes,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }