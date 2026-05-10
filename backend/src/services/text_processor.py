"""
Text Processor for Open-Omniscience
Text cleaning, tokenization, and n-gram generation
"""

import re
from typing import List, Tuple, Dict, Optional
from collections import Counter
import unicodedata

from .stopwords import stopwords_manager


class TextProcessor:
    """
    Processes text for keyword extraction and analysis.
    Handles cleaning, tokenization, normalization, and n-gram generation.
    """
    
    def __init__(self, language: str = 'en', use_stopwords: bool = True):
        """
        Initialize the text processor.
        
        Args:
            language: Language code for stopwords (default: 'en')
            use_stopwords: Whether to filter stopwords (default: True)
        """
        self.language = language
        self.use_stopwords = use_stopwords
        self._stopwords = stopwords_manager.get_stopwords(language) if use_stopwords else set()
    
    def clean_text(self, text: str) -> str:
        """
        Clean text by removing special characters, extra whitespace, etc.
        
        Args:
            text: Input text to clean
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Normalize unicode characters
        text = unicodedata.normalize('NFKD', text)
        
        # Remove control characters
        text = ''.join(char for char in text if unicodedata.category(char)[0] != 'C')
        
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def normalize_text(self, text: str, lowercase: bool = True, remove_punctuation: bool = True) -> str:
        """
        Normalize text for processing.
        
        Args:
            text: Input text
            lowercase: Convert to lowercase (default: True)
            remove_punctuation: Remove punctuation (default: True)
            
        Returns:
            Normalized text
        """
        text = self.clean_text(text)
        
        if lowercase:
            text = text.lower()
        
        if remove_punctuation:
            # Remove punctuation but keep apostrophes for contractions
            text = re.sub(r"[\\!\"#$%&'()*+,-./:;<=>?@\[\\\]^_`{|}~]", " ", text)
            # Replace multiple spaces again
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
        
        return text
    
    def tokenize(self, text: str, lowercase: bool = True, remove_punctuation: bool = True) -> List[str]:
        """
        Tokenize text into words.
        
        Args:
            text: Input text
            lowercase: Convert to lowercase (default: True)
            remove_punctuation: Remove punctuation (default: True)
            
        Returns:
            List of tokens (words)
        """
        text = self.normalize_text(text, lowercase=lowercase, remove_punctuation=remove_punctuation)
        
        if not text:
            return []
        
        # Split on whitespace
        tokens = text.split()
        
        # Filter out empty strings
        tokens = [token for token in tokens if token]
        
        return tokens
    
    def filter_stopwords(self, tokens: List[str]) -> List[str]:
        """
        Filter stopwords from tokens.
        
        Args:
            tokens: List of tokens
            
        Returns:
            List of tokens with stopwords removed
        """
        if not self.use_stopwords:
            return tokens
        
        return [token for token in tokens if token.lower() not in self._stopwords]
    
    def process_text(self, text: str, lowercase: bool = True, remove_punctuation: bool = True, 
                     filter_stopwords: bool = True) -> List[str]:
        """
        Full text processing pipeline.
        
        Args:
            text: Input text
            lowercase: Convert to lowercase (default: True)
            remove_punctuation: Remove punctuation (default: True)
            filter_stopwords: Filter stopwords (default: True)
            
        Returns:
            List of processed tokens
        """
        tokens = self.tokenize(text, lowercase=lowercase, remove_punctuation=remove_punctuation)
        
        if filter_stopwords and self.use_stopwords:
            tokens = self.filter_stopwords(tokens)
        
        return tokens
    
    def generate_ngrams(self, tokens: List[str], n: int = 2) -> List[Tuple[str, ...]]:
        """
        Generate n-grams from tokens.
        
        Args:
            tokens: List of tokens
            n: N-gram size (default: 2 for bigrams)
            
        Returns:
            List of n-grams (tuples of n tokens)
        """
        if n <= 0:
            return []
        
        if len(tokens) < n:
            return []
        
        ngrams = []
        for i in range(len(tokens) - n + 1):
            ngram = tuple(tokens[i:i+n])
            ngrams.append(ngram)
        
        return ngrams
    
    def generate_ngrams_string(self, tokens: List[str], n: int = 2, separator: str = ' ') -> List[str]:
        """
        Generate n-grams as joined strings.
        
        Args:
            tokens: List of tokens
            n: N-gram size (default: 2)
            separator: Separator for joining tokens (default: ' ')
            
        Returns:
            List of n-grams as strings
        """
        ngrams = self.generate_ngrams(tokens, n)
        return [separator.join(ngram) for ngram in ngrams]
    
    def get_word_frequencies(self, tokens: List[str], normalize: bool = False) -> Dict[str, float]:
        """
        Calculate word frequencies.
        
        Args:
            tokens: List of tokens
            normalize: Normalize frequencies to sum to 1 (default: False)
            
        Returns:
            Dictionary of word frequencies
        """
        if not tokens:
            return {}
        
        counter = Counter(tokens)
        
        if normalize:
            total = sum(counter.values())
            if total > 0:
                return {word: count / total for word, count in counter.items()}
        
        return dict(counter)
    
    def get_ngram_frequencies(self, tokens: List[str], n: int = 2, normalize: bool = False) -> Dict[str, float]:
        """
        Calculate n-gram frequencies.
        
        Args:
            tokens: List of tokens
            n: N-gram size (default: 2)
            normalize: Normalize frequencies to sum to 1 (default: False)
            
        Returns:
            Dictionary of n-gram frequencies
        """
        ngrams = self.generate_ngrams_string(tokens, n)
        return self.get_word_frequencies(ngrams, normalize=normalize)
    
    def remove_short_words(self, tokens: List[str], min_length: int = 2) -> List[str]:
        """
        Remove short words from tokens.
        
        Args:
            tokens: List of tokens
            min_length: Minimum word length to keep (default: 2)
            
        Returns:
            List of tokens with short words removed
        """
        return [token for token in tokens if len(token) >= min_length]
    
    def remove_long_words(self, tokens: List[str], max_length: int = 30) -> List[str]:
        """
        Remove long words from tokens.
        
        Args:
            tokens: List of tokens
            max_length: Maximum word length to keep (default: 30)
            
        Returns:
            List of tokens with long words removed
        """
        return [token for token in tokens if len(token) <= max_length]
    
    def remove_numeric(self, tokens: List[str]) -> List[str]:
        """
        Remove numeric tokens.
        
        Args:
            tokens: List of tokens
            
        Returns:
            List of tokens with numeric tokens removed
        """
        return [token for token in tokens if not token.isdigit()]
    
    def extract_sentences(self, text: str) -> List[str]:
        """
        Extract sentences from text.
        
        Args:
            text: Input text
            
        Returns:
            List of sentences
        """
        text = self.clean_text(text)
        
        # Split on sentence boundaries
        # This is a simple approach; for better results, consider using nltk or similar
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Filter out empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences


# Global instance
text_processor = TextProcessor()
