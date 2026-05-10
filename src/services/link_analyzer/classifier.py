"""
Link Classifier Service for Open Omniscience

This module provides functionality for classifying links into categories such as:
- Source: Links to news articles, research papers, or other content sources
- Reference: Links to supporting information or citations
- Ad: Advertisement links
- Social: Social media links
- Navigation: Site navigation links
- Other: Other types of links

Author: Open Omniscience Team
"""

import re
from urllib.parse import urlparse
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
import logging

# Configure logging
logger = logging.getLogger(__name__)


class LinkClassifier:
    """
    Service for classifying links into categories.
    
    This class uses a combination of:
    - Rule-based classification (URL patterns, domain matching)
    - Machine learning-based classification (future enhancement)
    - Context-based classification (link text, surrounding content)
    """
    
    def __init__(self):
        """Initialize the LinkClassifier."""
        # Classification rules loaded from database or configuration
        self.classification_rules = self._load_default_rules()
        
        # Compile regex patterns for efficiency
        self._compile_patterns()
    
    def _load_default_rules(self) -> List[Dict[str, Any]]:
        """
        Load default classification rules.
        
        Returns:
            List of classification rule dictionaries
        """
        return [
            # Source classification rules
            {
                'rule_name': 'news_source',
                'pattern': r'(news\.|nytimes\.|washingtonpost\.|bbc\.|cnn\.|reuters\.|apnews\.|bloomberg\.|wsj\.|ft\.|theguardian\.|npr\.|pbs\.)',
                'classification_type': 'source',
                'priority': 10,
                'is_active': True,
                'apply_to': ['domain', 'path']
            },
            {
                'rule_name': 'academic_source',
                'pattern': r'(arxiv\.org|doi\.org|jstor\.org|springer\.com|sciencedirect\.com|nature\.com|science\.org|plos\.org|researchgate\.net|academic\.oup\.)',
                'classification_type': 'source',
                'priority': 10,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'government_source',
                'pattern': r'(\.gov|\.gob|\.mil|un\.org|who\.int|worldbank\.org|imf\.org|eu\.europa\.eu)',
                'classification_type': 'source',
                'priority': 10,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'educational_source',
                'pattern': r'(\.edu|\.ac\.|harvard\.edu|mit\.edu|stanford\.edu|ox\.ac\.uk|cambridge\.org)',
                'classification_type': 'source',
                'priority': 10,
                'is_active': True,
                'apply_to': ['domain']
            },
            
            # Reference classification rules
            {
                'rule_name': 'wikipedia_reference',
                'pattern': r'(wikipedia\.org|wikimedia\.org|wiktionary\.org|wikiquote\.org|wikibooks\.org)',
                'classification_type': 'reference',
                'priority': 9,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'dictionary_reference',
                'pattern': r'(merriam-webster\.com|dictionary\.com|oxforddictionaries\.com|collinsdictionary\.com)',
                'classification_type': 'reference',
                'priority': 9,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'encyclopedia_reference',
                'pattern': r'(britannica\.com|encyclopedia\.com|infoplease\.com)',
                'classification_type': 'reference',
                'priority': 9,
                'is_active': True,
                'apply_to': ['domain']
            },
            
            # Ad classification rules
            {
                'rule_name': 'google_ads',
                'pattern': r'(googleads\.g\.doubleclick\.net|pagead2\.googlesyndication\.com|adservice\.google\.com)',
                'classification_type': 'ad',
                'priority': 8,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'ad_networks',
                'pattern': r'(adsystem\.com|adserver\.com|openx\.net|rubiconproject\.com|pubmatic\.com|indexww\.com|adnxs\.com|casalemedia\.com|media\.net|revcontent\.com)',
                'classification_type': 'ad',
                'priority': 8,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'affiliate_links',
                'pattern': r'(amazon\.com/.*tag=|amzn\.to/|click\.linksynergy\.com|awin1\.com|shareasale\.com|cj\.com|rakuten\.com)',
                'classification_type': 'ad',
                'priority': 8,
                'is_active': True,
                'apply_to': ['url']
            },
            
            # Social media classification rules
            {
                'rule_name': 'facebook_links',
                'pattern': r'(facebook\.com|fb\.com|fb\.me|messenger\.com)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'twitter_links',
                'pattern': r'(twitter\.com|x\.com|t\.co)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'linkedin_links',
                'pattern': r'(linkedin\.com|lnkd\.in)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'instagram_links',
                'pattern': r'(instagram\.com|instagr\.am)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'youtube_links',
                'pattern': r'(youtube\.com|youtu\.be|ytimg\.com)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            {
                'rule_name': 'other_social',
                'pattern': r'(reddit\.com|pinterest\.com|tumblr\.com|snapchat\.com|tiktok\.com|whatsapp\.com|telegram\.org)',
                'classification_type': 'social',
                'priority': 7,
                'is_active': True,
                'apply_to': ['domain']
            },
            
            # Navigation classification rules
            {
                'rule_name': 'home_link',
                'pattern': r'(home|index\.html|index\.php|default\.aspx)',
                'classification_type': 'navigation',
                'priority': 6,
                'is_active': True,
                'apply_to': ['path', 'link_text']
            },
            {
                'rule_name': 'about_link',
                'pattern': r'(about|about us|about\.html)',
                'classification_type': 'navigation',
                'priority': 6,
                'is_active': True,
                'apply_to': ['path', 'link_text']
            },
            {
                'rule_name': 'contact_link',
                'pattern': r'(contact|contact us|contact\.html|reach us)',
                'classification_type': 'navigation',
                'priority': 6,
                'is_active': True,
                'apply_to': ['path', 'link_text']
            },
            {
                'rule_name': 'privacy_link',
                'pattern': r'(privacy|privacy policy|terms|terms of service|cookie|cookie policy)',
                'classification_type': 'navigation',
                'priority': 6,
                'is_active': True,
                'apply_to': ['path', 'link_text']
            },
            
            # Default rule
            {
                'rule_name': 'default_external',
                'pattern': r'.*',
                'classification_type': 'other',
                'priority': 1,
                'is_active': True,
                'apply_to': ['domain']
            }
        ]
    
    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        for rule in self.classification_rules:
            if 'compiled_pattern' not in rule:
                try:
                    rule['compiled_pattern'] = re.compile(rule['pattern'], re.IGNORECASE)
                except Exception as e:
                    logger.error(f"Error compiling pattern {rule['pattern']}: {e}")
                    rule['compiled_pattern'] = None
    
    def classify_links(self, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Classify a list of links.
        
        Args:
            links: List of link dictionaries (from LinkExtractor)
            
        Returns:
            List of link dictionaries with added 'classification' field
        """
        classified_links = []
        
        for link in links:
            classified_link = link.copy()
            classification = self.classify_link(classified_link)
            classified_link['classification'] = classification
            classified_links.append(classified_link)
        
        return classified_links
    
    def classify_link(self, link: Dict[str, Any]) -> str:
        """
        Classify a single link.
        
        Args:
            link: Link dictionary
            
        Returns:
            Classification string
        """
        # Get link information
        url = link.get('url', '')
        domain = link.get('domain', '')
        path = link.get('path', '')
        link_text = link.get('link_text', '')
        link_type = link.get('link_type', '')
        
        # Skip classification for certain link types
        if link_type in ['image', 'script', 'stylesheet', 'media']:
            return link_type
        
        # Apply rules in priority order
        for rule in sorted(self.classification_rules, key=lambda x: x.get('priority', 0), reverse=True):
            if not rule.get('is_active', True):
                continue
            
            pattern = rule.get('compiled_pattern')
            if not pattern:
                continue
            
            apply_to = rule.get('apply_to', ['domain'])
            
            for field in apply_to:
                field_value = ''
                if field == 'domain':
                    field_value = domain
                elif field == 'path':
                    field_value = path
                elif field == 'url':
                    field_value = url
                elif field == 'link_text':
                    field_value = link_text
                
                if field_value and pattern.search(field_value):
                    return rule.get('classification_type', 'other')
        
        # Default classification
        return 'other'
    
    def add_custom_rule(self, rule_name: str, pattern: str, classification_type: str, 
                       priority: int = 1, is_active: bool = True, 
                       apply_to: List[str] = None) -> bool:
        """
        Add a custom classification rule.
        
        Args:
            rule_name: Name of the rule
            pattern: Regex pattern to match
            classification_type: Classification type
            priority: Priority of the rule
            is_active: Whether the rule is active
            apply_to: Fields to apply the rule to
            
        Returns:
            True if rule was added successfully
        """
        if not rule_name or not pattern or not classification_type:
            logger.error("Rule name, pattern, and classification type are required")
            return False
        
        # Check for duplicate rule name
        for rule in self.classification_rules:
            if rule.get('rule_name') == rule_name:
                logger.error(f"Rule with name '{rule_name}' already exists")
                return False
        
        # Add the rule
        new_rule = {
            'rule_name': rule_name,
            'pattern': pattern,
            'classification_type': classification_type,
            'priority': priority,
            'is_active': is_active,
            'apply_to': apply_to or ['domain']
        }
        
        try:
            new_rule['compiled_pattern'] = re.compile(pattern, re.IGNORECASE)
            self.classification_rules.append(new_rule)
            # Re-sort rules by priority
            self.classification_rules.sort(key=lambda x: x.get('priority', 0), reverse=True)
            return True
        except Exception as e:
            logger.error(f"Error compiling pattern '{pattern}': {e}")
            return False
    
    def remove_rule(self, rule_name: str) -> bool:
        """
        Remove a classification rule.
        
        Args:
            rule_name: Name of the rule to remove
            
        Returns:
            True if rule was removed successfully
        """
        for i, rule in enumerate(self.classification_rules):
            if rule.get('rule_name') == rule_name:
                self.classification_rules.pop(i)
                return True
        
        logger.error(f"Rule with name '{rule_name}' not found")
        return False
    
    def enable_rule(self, rule_name: str, enable: bool = True) -> bool:
        """
        Enable or disable a classification rule.
        
        Args:
            rule_name: Name of the rule
            enable: Whether to enable the rule
            
        Returns:
            True if rule was updated successfully
        """
        for rule in self.classification_rules:
            if rule.get('rule_name') == rule_name:
                rule['is_active'] = enable
                return True
        
        logger.error(f"Rule with name '{rule_name}' not found")
        return False
    
    def get_rules(self) -> List[Dict[str, Any]]:
        """
        Get all classification rules.
        
        Returns:
            List of all classification rules
        """
        return [
            {
                'rule_name': rule.get('rule_name'),
                'pattern': rule.get('pattern'),
                'classification_type': rule.get('classification_type'),
                'priority': rule.get('priority'),
                'is_active': rule.get('is_active'),
                'apply_to': rule.get('apply_to')
            }
            for rule in self.classification_rules
        ]
    
    def classify_link_with_context(self, link: Dict[str, Any], article_content: str = "", 
                                   surrounding_text: str = "") -> str:
        """
        Classify a link with additional context.
        
        Args:
            link: Link dictionary
            article_content: Full article content
            surrounding_text: Text surrounding the link
            
        Returns:
            Classification string
        """
        # First try basic classification
        classification = self.classify_link(link)
        
        # If classification is 'other', try context-based classification
        if classification == 'other':
            classification = self._classify_by_context(link, article_content, surrounding_text)
        
        return classification
    
    def _classify_by_context(self, link: Dict[str, Any], article_content: str, 
                           surrounding_text: str) -> str:
        """
        Classify a link based on context.
        
        Args:
            link: Link dictionary
            article_content: Full article content
            surrounding_text: Text surrounding the link
            
        Returns:
            Classification string
        """
        link_text = link.get('link_text', '').lower()
        surrounding_text = surrounding_text.lower()
        
        # Check for citation patterns
        citation_patterns = [
            r'\bcite\b', r'\breference\b', r'\bsource\b', r'\baccording to\b',
            r'\bas reported by\b', r'\bstudy by\b', r'\bresearch by\b'
        ]
        
        for pattern in citation_patterns:
            if (link_text and re.search(pattern, link_text)) or \
               (surrounding_text and re.search(pattern, surrounding_text)):
                return 'source'
        
        # Check for reference patterns
        reference_patterns = [
            r'\bsee\b', r'\bfor more information\b', r'\bvisit\b',
            r'\blearn more\b', r'\bclick here\b', r'\bmore details\b'
        ]
        
        for pattern in reference_patterns:
            if (link_text and re.search(pattern, link_text)) or \
               (surrounding_text and re.search(pattern, surrounding_text)):
                return 'reference'
        
        # Default to basic classification
        return self.classify_link(link)
    
    def get_classification_statistics(self, links: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics about link classifications.
        
        Args:
            links: List of classified links
            
        Returns:
            Dictionary containing classification statistics
        """
        if not links:
            return {'total': 0, 'classifications': {}}
        
        classifications = {}
        for link in links:
            classification = link.get('classification', 'unclassified')
            classifications[classification] = classifications.get(classification, 0) + 1
        
        return {
            'total': len(links),
            'classifications': classifications
        }