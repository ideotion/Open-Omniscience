"""
Keyword Extractor for Open-Omniscience
Extracts keywords from text with relevance scoring
"""

import re
from typing import List, Dict, Tuple, Optional
from collections import Counter
import math

from .text_processor import TextProcessor, text_processor
from .stopwords import StopwordsManager, stopwords_manager


class KeywordExtractor:
    """
    Extracts keywords from text using various methods.
    Supports TF-IDF, TextRank, and simple frequency-based extraction.
    """
    
    def __init__(self, language: str = 'en', top_n: int = 10):
        """
        Initialize the keyword extractor.
        
        Args:
            language: Language code (default: 'en')
            top_n: Number of top keywords to extract (default: 10)
        """
        self.language = language
        self.top_n = top_n
        self.text_processor = TextProcessor(language=language)
        self.stopwords_manager = stopwords_manager
    
    def extract_keywords_frequency(self, text: str, top_n: Optional[int] = None, 
                                    min_length: int = 2, max_length: int = 30) -> List[Tuple[str, float]]:
        """
        Extract keywords based on word frequency.
        
        Args:
            text: Input text
            top_n: Number of keywords to return (default: self.top_n)
            min_length: Minimum word length (default: 2)
            max_length: Maximum word length (default: 30)
            
        Returns:
            List of (keyword, score) tuples sorted by score
        """
        if not text:
            return []
        
        top_n = top_n or self.top_n
        
        # Process text
        tokens = self.text_processor.process_text(
            text, 
            lowercase=True, 
            remove_punctuation=True, 
            filter_stopwords=True
        )
        
        # Filter by length
        tokens = [t for t in tokens if min_length <= len(t) <= max_length]
        
        if not tokens:
            return []
        
        # Count frequencies
        word_counts = Counter(tokens)
        
        # Sort by frequency
        sorted_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Return top N
        return sorted_keywords[:top_n]
    
    def extract_keywords_tfidf(self, text: str, documents: List[str], 
                                top_n: Optional[int] = None) -> List[Tuple[str, float]]:
        """
        Extract keywords using TF-IDF.
        
        Args:
            text: Input text
            documents: List of all documents for IDF calculation
            top_n: Number of keywords to return (default: self.top_n)
            
        Returns:
            List of (keyword, tfidf_score) tuples sorted by score
        """
        if not text or not documents:
            return []
        
        top_n = top_n or self.top_n
        
        # Process the target text
        target_tokens = self.text_processor.process_text(
            text,
            lowercase=True,
            remove_punctuation=True,
            filter_stopwords=True
        )
        
        if not target_tokens:
            return []
        
        # Calculate TF for target document
        target_tf = self._calculate_tf(target_tokens)
        
        # Calculate IDF from all documents
        idf = self._calculate_idf(documents)
        
        # Calculate TF-IDF scores
        tfidf_scores = {}
        for word, tf in target_tf.items():
            if word in idf:
                tfidf_scores[word] = tf * idf[word]
        
        # Sort by score
        sorted_keywords = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)
        
        return sorted_keywords[:top_n]
    
    def _calculate_tf(self, tokens: List[str]) -> Dict[str, float]:
        """
        Calculate term frequency (TF) for tokens.
        
        Args:
            tokens: List of tokens
            
        Returns:
            Dictionary of term frequencies
        """
        if not tokens:
            return {}
        
        counter = Counter(tokens)
        total = len(tokens)
        
        return {word: count / total for word, count in counter.items()}
    
    def _calculate_idf(self, documents: List[str]) -> Dict[str, float]:
        """
        Calculate inverse document frequency (IDF) from documents.
        
        Args:
            documents: List of documents
            
        Returns:
            Dictionary of IDF scores
        """
        if not documents:
            return {}
        
        # Count in how many documents each word appears
        doc_word_counts = {}
        for doc in documents:
            tokens = self.text_processor.process_text(
                doc,
                lowercase=True,
                remove_punctuation=True,
                filter_stopwords=True
            )
            unique_words = set(tokens)
            for word in unique_words:
                doc_word_counts[word] = doc_word_counts.get(word, 0) + 1
        
        # Calculate IDF
        total_docs = len(documents)
        idf = {}
        for word, count in doc_word_counts.items():
            idf[word] = math.log(total_docs / (1 + count))
        
        return idf
    
    def extract_keywords_textrank(self, text: str, top_n: Optional[int] = None,
                                  window_size: int = 2, damping: float = 0.85,
                                  max_iter: int = 10) -> List[Tuple[str, float]]:
        """
        Extract keywords using TextRank algorithm (simplified version).
        
        Args:
            text: Input text
            top_n: Number of keywords to return (default: self.top_n)
            window_size: Size of co-occurrence window (default: 2)
            damping: Damping factor for PageRank (default: 0.85)
            max_iter: Maximum iterations (default: 10)
            
        Returns:
            List of (keyword, score) tuples sorted by score
        """
        if not text:
            return []
        
        top_n = top_n or self.top_n
        
        # Process text
        tokens = self.text_processor.process_text(
            text,
            lowercase=True,
            remove_punctuation=True,
            filter_stopwords=True
        )
        
        if not tokens:
            return []
        
        # Build co-occurrence graph
        graph = self._build_cooccurrence_graph(tokens, window_size)
        
        # Apply PageRank
        scores = self._pagerank(graph, damping=damping, max_iter=max_iter)
        
        # Sort by score
        sorted_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        return sorted_keywords[:top_n]
    
    def _build_cooccurrence_graph(self, tokens: List[str], window_size: int = 2) -> Dict[str, Dict[str, int]]:
        """
        Build co-occurrence graph from tokens.
        
        Args:
            tokens: List of tokens
            window_size: Size of co-occurrence window
            
        Returns:
            Co-occurrence graph as adjacency list
        """
        graph = {}
        
        for i, token in enumerate(tokens):
            if token not in graph:
                graph[token] = {}
            
            # Look at neighboring tokens within window
            start = max(0, i - window_size)
            end = min(len(tokens), i + window_size + 1)
            
            for j in range(start, end):
                if i != j:
                    neighbor = tokens[j]
                    graph[token][neighbor] = graph[token].get(neighbor, 0) + 1
        
        return graph
    
    def _pagerank(self, graph: Dict[str, Dict[str, int]], damping: float = 0.85, 
                  max_iter: int = 10) -> Dict[str, float]:
        """
        Apply PageRank algorithm to graph.
        
        Args:
            graph: Co-occurrence graph
            damping: Damping factor
            max_iter: Maximum iterations
            
        Returns:
            Dictionary of node scores
        """
        if not graph:
            return {}
        
        # Initialize scores
        nodes = list(graph.keys())
        scores = {node: 1.0 / len(nodes) for node in nodes}
        
        for _ in range(max_iter):
            new_scores = {}
            
            for node in nodes:
                # Sum of incoming scores
                incoming = 0.0
                for other_node in nodes:
                    if node in graph[other_node]:
                        # Weight by edge count
                        edge_count = sum(graph[other_node].values())
                        if edge_count > 0:
                            incoming += scores[other_node] * (graph[other_node][node] / edge_count)
                
                # Apply damping
                new_scores[node] = (1 - damping) / len(nodes) + damping * incoming
            
            scores = new_scores
        
        return scores
    
    def extract_keyphrases(self, text: str, top_n: Optional[int] = None,
                           min_phrase_length: int = 2, max_phrase_length: int = 4) -> List[Tuple[str, float]]:
        """
        Extract keyphrases (multi-word expressions) from text.
        
        Args:
            text: Input text
            top_n: Number of keyphrases to return (default: self.top_n)
            min_phrase_length: Minimum number of words in phrase (default: 2)
            max_phrase_length: Maximum number of words in phrase (default: 4)
            
        Returns:
            List of (keyphrase, score) tuples sorted by score
        """
        if not text:
            return []
        
        top_n = top_n or self.top_n
        
        # Process text
        tokens = self.text_processor.process_text(
            text,
            lowercase=True,
            remove_punctuation=True,
            filter_stopwords=False  # Don't filter yet, we'll do it per phrase
        )
        
        if not tokens:
            return []
        
        # Generate candidate phrases
        phrases = []
        for length in range(min_phrase_length, min(max_phrase_length, len(tokens)) + 1):
            for i in range(len(tokens) - length + 1):
                phrase = ' '.join(tokens[i:i+length])
                phrases.append(phrase)
        
        if not phrases:
            return []
        
        # Score phrases by frequency and length
        phrase_counts = Counter(phrases)
        scored_phrases = []
        
        for phrase, count in phrase_counts.items():
            # Filter out phrases containing stopwords
            phrase_tokens = phrase.split()
            if any(self.stopwords_manager.is_stopword(t, self.language) for t in phrase_tokens):
                continue
            
            # Score: frequency * length (to prefer longer phrases)
            score = count * len(phrase_tokens)
            scored_phrases.append((phrase, score))
        
        # Sort by score
        scored_phrases.sort(key=lambda x: x[1], reverse=True)
        
        return scored_phrases[:top_n]
    
    def extract_keywords(self, text: str, method: str = 'frequency', 
                         top_n: Optional[int] = None, **kwargs) -> List[Tuple[str, float]]:
        """
        Extract keywords using specified method.
        
        Args:
            text: Input text
            method: Extraction method ('frequency', 'tfidf', 'textrank', 'keyphrases')
            top_n: Number of keywords to return
            **kwargs: Additional arguments for specific methods
            
        Returns:
            List of (keyword, score) tuples
        """
        methods = {
            'frequency': self.extract_keywords_frequency,
            'tfidf': self.extract_keywords_tfidf,
            'textrank': self.extract_keywords_textrank,
            'keyphrases': self.extract_keyphrases,
        }
        
        if method not in methods:
            raise ValueError(f"Unknown method: {method}. Available: {list(methods.keys())}")
        
        return methods[method](text, top_n=top_n, **kwargs)


# Global instance
keyword_extractor = KeywordExtractor()
