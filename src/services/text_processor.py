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
Text Processing for Open Omniscience

This module provides comprehensive text processing capabilities for keyword extraction.

Author: Open Omniscience Team
"""

import re
import html
import unicodedata
from typing import List, Dict, Tuple, Optional
from collections import Counter


class TextProcessor:
    """
    Processes text for keyword extraction and analysis.
    """
    
    def __init__(self, min_word_length=2, max_word_length=50):
        self.min_word_length = min_word_length
        self.max_word_length = max_word_length
        
        # Patterns
        self.url_pattern = re.compile(r'https?://\S+|www\.\S+')
        self.email_pattern = re.compile(r'\S+@\S+')
        self.html_tag_pattern = re.compile(r'<[^>]+>')
        self.special_char_pattern = re.compile(r'[^\w\s\-]')
        self.multiple_space_pattern = re.compile(r'\s+')
        self.leading_trailing_space_pattern = re.compile(r'^\s+|\s+$')
        self.word_pattern = re.compile(r'[\w\-]+')
        
        # Contractions
        self.contractions = {
            "don't": "do not", "can't": "cannot", "won't": "will not",
            "isn't": "is not", "aren't": "are not", "wasn't": "was not",
            "hasn't": "has not", "haven't": "have not", "doesn't": "does not",
            "didn't": "did not", "i'm": "i am", "you're": "you are",
            "he's": "he is", "she's": "she is", "it's": "it is",
            "we're": "we are", "they're": "they are",
        }
    
    def clean_text(self, text):
        if not text:
            return ""
        text = str(text)
        text = html.unescape(text)
        text = self.url_pattern.sub(' ', text)
        text = self.email_pattern.sub(' ', text)
        text = self.html_tag_pattern.sub(' ', text)
        text = self.special_char_pattern.sub(' ', text)
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(char for char in text if unicodedata.category(char)[0] != 'C')
        text = self.multiple_space_pattern.sub(' ', text)
        text = self.leading_trailing_space_pattern.sub('', text)
        return text
    
    def normalize_text(self, text, lowercase=True, expand_contractions=True):
        if not text:
            return ""
        text = self.clean_text(text)
        if expand_contractions:
            text = self._expand_contractions(text)
        if lowercase:
            text = text.lower()
        return text
    
    def _expand_contractions(self, text):
        for contraction, expansion in self.contractions.items():
            pattern = re.compile(r'\b' + re.escape(contraction) + r'\b')
            text = pattern.sub(expansion, text)
        return text
    
    def tokenize(self, text):
        if not text:
            return []
        text = self.normalize_text(text)
        words = self.word_pattern.findall(text)
        words = [word for word in words if self.min_word_length <= len(word) <= self.max_word_length]
        return words
    
    def remove_stopwords(self, words, language='en'):
        from .stopwords import stopwords_manager
        return stopwords_manager.filter_stopwords(words, language)
    
    def extract_ngrams(self, words, n=2):
        if len(words) < n:
            return []
        ngrams = []
        for i in range(len(words) - n + 1):
            ngram = ' '.join(words[i:i+n])
            ngrams.append(ngram)
        return ngrams
    
    def process_text(self, text, language='en', remove_stopwords=True, 
                   include_ngrams=True, ngram_range=(1, 3)):
        if not text:
            return {'unigrams': [], 'bigrams': [], 'trigrams': [], 'all_ngrams': [], 'words': []}
        
        words = self.tokenize(text)
        if remove_stopwords:
            words = self.remove_stopwords(words, language)
        
        ngrams = {}
        if include_ngrams:
            for n in range(ngram_range[0], ngram_range[1] + 1):
                ngram_key = 'unigrams' if n == 1 else f"{'n' * n}grams"
                ngrams[ngram_key] = self.extract_ngrams(words, n)
        
        result = {'words': words, 'unigrams': words, **ngrams}
        all_ngrams = []
        for n in range(ngram_range[0], ngram_range[1] + 1):
            all_ngrams.extend(self.extract_ngrams(words, n))
        result['all_ngrams'] = all_ngrams
        return result
    
    def get_word_frequency(self, text, language='en', normalize=True):
        if not text:
            return {}
        if normalize:
            text = self.normalize_text(text)
        words = self.tokenize(text)
        words = self.remove_stopwords(words, language)
        freq = {}
        for word in words:
            freq[word] = freq.get(word, 0) + 1
        return freq


text_processor = TextProcessor()
