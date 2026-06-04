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
Stopwords Management for Open Omniscience

This module provides comprehensive stopwords management for multiple languages,
used in keyword extraction and text processing.

Author: Open Omniscience Team
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

# Configure logging
logger = logging.getLogger(__name__)


class StopwordsManager:
    """
    Manages stopwords for multiple languages.
    
    Stopwords are common words that are typically filtered out during
    text processing (e.g., "the", "and", "a", "an", "in", etc.).
    
    Attributes:
        default_stopwords: Default English stopwords
        language_stopwords: Dictionary mapping language codes to stopword sets
        custom_stopwords: Custom stopwords added by users
    """
    
    # Default English stopwords
    DEFAULT_ENGLISH_STOPWORDS = {
        'a', 'an', 'the', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'its', 'our',
        'their', 'mine', 'yours', 'hers', 'ours', 'theirs',
        'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'shall', 'should', 'can', 'could', 'may', 'might', 'must',
        'very', 'too', 'so', 'just', 'only', 'also', 'here', 'there',
        'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each',
        'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
        'about', 'above', 'after', 'again', 'against', 'all', 'and', 'any',
        'as', 'at', 'because', 'been', 'before', 'being', 'below',
        'between', 'both', 'but', 'by', 'can', 'during', 'each', 'for',
        'from', 'if', 'in', 'into', 'is', 'it', 'its', 'of', 'off', 'on',
        'once', 'only', 'or', 'other', 'ought', 'our', 'out', 'over',
        'own', 'same', 'than', 'that', 'the', 'their', 'them', 'then',
        'there', 'these', 'they', 'this', 'those', 'through', 'to',
        'under', 'until', 'up', 'very', 'was', 'we', 'were', 'what',
        'when', 'where', 'which', 'while', 'who', 'whom', 'why', 'with',
        's', 't', 'd', 'll', 're', 've', 'm', 'ma',
    }
    
    NEWS_STOPWORDS = {
        'said', 'say', 'says', 'saying', 'told', 'tell', 'tells',
        'according', 'report', 'reports', 'reported', 'reporting',
        'source', 'sources', 'official', 'officials',
        'announced', 'announcement', 'announces',
        'released', 'release', 'releases',
        'published', 'publish', 'publishes',
        'wrote', 'write', 'writes', 'writing', 'written',
        'photo', 'photos', 'image', 'images',
        'video', 'videos', 'footage',
        'story', 'stories', 'article', 'articles', 'news',
        'breaking', 'live', 'exclusive', 'first', 'latest',
        'year', 'years', 'month', 'months', 'week', 'weeks',
        'day', 'days', 'today', 'yesterday', 'tomorrow',
        'now', 'then', 'soon', 'later', 'early', 'late',
    }
    
    LANGUAGE_STOPWORDS = {
        'en': DEFAULT_ENGLISH_STOPWORDS | NEWS_STOPWORDS,
        'fr': {
            'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'l',
            'ce', 'cet', 'cette', 'ces', 'mon', 'ton', 'son',
            'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles',
            'suis', 'es', 'est', 'sommes', 'etes', 'sont',
            'que', 'qui', 'quoi', 'dont', 'ou', 'et', 'mais', 'ou',
            'avec', 'sans', 'sous', 'sur', 'de', 'par', 'pour',
        },
    }
    
    def __init__(self, custom_stopwords=None):
        self.default_stopwords = self.DEFAULT_ENGLISH_STOPWORDS.copy()
        self.language_stopwords = {}
        self.custom_stopwords = set(custom_stopwords or [])
        
        for lang, words in self.LANGUAGE_STOPWORDS.items():
            self.language_stopwords[lang] = words.copy()
    
    def get_stopwords(self, language='en'):
        lang = language.lower()
        if lang in self.language_stopwords:
            stopwords = self.language_stopwords[lang].copy()
        else:
            stopwords = self.default_stopwords.copy()
        stopwords.update(self.custom_stopwords)
        return stopwords
    
    def filter_stopwords(self, words, language='en'):
        stopwords = self.get_stopwords(language)
        return [word for word in words if word.lower() not in stopwords]


stopwords_manager = StopwordsManager()
