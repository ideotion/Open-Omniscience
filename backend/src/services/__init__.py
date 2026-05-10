"""
Services package for Open-Omniscience
"""

# Import all service modules
from .stopwords import StopwordsManager, stopwords_manager
from .text_processor import TextProcessor, text_processor
from .keyword_extractor import KeywordExtractor, keyword_extractor
from .source_detector import SourceDetector, source_detector
from .web_scraper import WebScraper, web_scraper
from .similarity_engine import SimilarityEngine, similarity_engine
from .temporal_analyzer import TemporalAnalyzer, temporal_analyzer
from .export_service import ExportService, export_service

__all__ = [
    # Classes
    'StopwordsManager',
    'TextProcessor',
    'KeywordExtractor',
    'SourceDetector',
    'WebScraper',
    'SimilarityEngine',
    'TemporalAnalyzer',
    'ExportService',
    # Instances
    'stopwords_manager',
    'text_processor',
    'keyword_extractor',
    'source_detector',
    'web_scraper',
    'similarity_engine',
    'temporal_analyzer',
    'export_service',
]
