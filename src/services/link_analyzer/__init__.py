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
Link Analyzer Service for Open Omniscience

This module provides comprehensive link analysis functionality including:
- Link extraction from HTML content
- Link classification (source, reference, ad, social, navigation, other)
- Source identification and tracking
- Temporal analysis (article date vs. source date)
- Network analysis of source relationships
- Credibility scoring

Author: Open Omniscience Team
"""

from .extractor import LinkExtractor
from .classifier import LinkClassifier
from .source_identifier import SourceIdentifier
from .source_scraper import SourceScraper
from .relationship_tracker import RelationshipTracker
from .temporal_analyzer import TemporalAnalyzer
from .network_analyzer import NetworkAnalyzer
from .credibility_scorer import CredibilityScorer

# Main service class that combines all functionality
class LinkAnalyzerService:
    """
    Main service class for link analysis operations.
    
    This class provides a unified interface for all link analysis functionality,
    including extraction, classification, source identification, and relationship tracking.
    """
    
    def __init__(self):
        """Initialize the LinkAnalyzerService with all sub-services."""
        self.extractor = LinkExtractor()
        self.classifier = LinkClassifier()
        self.source_identifier = SourceIdentifier()
        self.source_scraper = SourceScraper()
        self.relationship_tracker = RelationshipTracker()
        self.temporal_analyzer = TemporalAnalyzer()
        self.network_analyzer = NetworkAnalyzer()
        self.credibility_scorer = CredibilityScorer()
    
    def extract_and_analyze_links(self, article_id, html_content, article_url=None, article_published_at=None):
        """
        Extract links from HTML content and perform comprehensive analysis.
        
        Args:
            article_id: ID of the article
            html_content: HTML content to extract links from
            article_url: URL of the article (for base URL resolution)
            article_published_at: Publication date of the article (for temporal analysis)
            
        Returns:
            dict: Comprehensive analysis results including:
                - extracted_links: List of extracted links with metadata
                - classified_links: Links with classification
                - identified_sources: Identified external sources
                - relationships: Article-source relationships
                - temporal_analysis: Temporal analysis results
        """
        # Extract links
        extracted_links = self.extractor.extract_links(
            html_content, 
            base_url=article_url,
            article_id=article_id
        )
        
        # Classify links
        classified_links = self.classifier.classify_links(extracted_links)
        
        # Identify sources
        identified_sources = self.source_identifier.identify_sources(classified_links)
        
        # Track relationships
        relationships = self.relationship_tracker.track_relationships(
            article_id, 
            classified_links, 
            identified_sources,
            article_published_at=article_published_at
        )
        
        # Perform temporal analysis
        temporal_analysis = self.temporal_analyzer.analyze_temporal_patterns(
            article_id, 
            relationships,
            article_published_at=article_published_at
        )
        
        return {
            'extracted_links': extracted_links,
            'classified_links': classified_links,
            'identified_sources': identified_sources,
            'relationships': relationships,
            'temporal_analysis': temporal_analysis
        }
    

    
    def analyze_source_network(self, source_ids=None, time_range=None):
        """
        Analyze the network of sources and their relationships.
        
        Args:
            source_ids: List of source IDs to analyze (None for all)
            time_range: Time range for analysis (start_date, end_date)
            
        Returns:
            dict: Network analysis results
        """
        return self.network_analyzer.analyze_network(source_ids, time_range)
    
    def calculate_credibility_scores(self, source_ids=None):
        """
        Calculate credibility scores for sources.
        
        Args:
            source_ids: List of source IDs to score (None for all)
            
        Returns:
            dict: Credibility scores for each source
        """
        return self.credibility_scorer.calculate_scores(source_ids)
    
    def get_link_statistics(self, article_ids=None, time_range=None):
        """
        Get statistics about links and sources.
        
        Args:
            article_ids: List of article IDs to analyze (None for all)
            time_range: Time range for analysis
            
        Returns:
            dict: Link and source statistics
        """
        # This will be implemented to aggregate statistics from the database
        pass

# Create a singleton instance for easy access
link_analyzer = LinkAnalyzerService()

# Export all classes for direct access
__all__ = [
    'LinkAnalyzerService',
    'LinkExtractor',
    'LinkClassifier', 
    'SourceIdentifier',
    'SourceScraper',
    'RelationshipTracker',
    'TemporalAnalyzer',
    'NetworkAnalyzer',
    'CredibilityScorer',
    'link_analyzer'
]