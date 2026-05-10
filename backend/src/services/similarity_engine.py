"""
Similarity Engine for Open-Omniscience
Calculates similarity between articles using various methods
"""

from typing import List, Dict, Tuple, Optional
from collections import Counter
import math
import numpy as np

from .text_processor import TextProcessor, text_processor


class SimilarityEngine:
    """
    Calculates similarity between documents using TF-IDF, cosine, Jaccard, etc.
    """
    
    def __init__(self):
        """Initialize the similarity engine."""
        self.text_processor = text_processor
    
    def cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector (word -> weight)
            vec2: Second vector (word -> weight)
            
        Returns:
            Cosine similarity score (0 to 1)
        """
        # Get all unique words
        all_words = set(vec1.keys()) | set(vec2.keys())
        
        # Create vectors
        v1 = np.array([vec1.get(word, 0.0) for word in all_words])
        v2 = np.array([vec2.get(word, 0.0) for word in all_words])
        
        # Calculate cosine similarity
        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot_product / (norm1 * norm2))
    
    def jaccard_similarity(self, set1: set, set2: set) -> float:
        """
        Calculate Jaccard similarity between two sets.
        
        Args:
            set1: First set
            set2: Second set
            
        Returns:
            Jaccard similarity score (0 to 1)
        """
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        if union == 0:
            return 0.0
        
        return float(intersection / union)
    
    def calculate_tfidf_similarity(self, doc1: str, doc2: str, 
                                   documents: Optional[List[str]] = None) -> float:
        """
        Calculate TF-IDF cosine similarity between two documents.
        
        Args:
            doc1: First document text
            doc2: Second document text
            documents: Optional list of all documents for IDF calculation
            
        Returns:
            Similarity score (0 to 1)
        """
        if not doc1 or not doc2:
            return 0.0
        
        # If no documents provided, just use the two docs
        if documents is None:
            documents = [doc1, doc2]
        
        # Process documents
        processed_docs = []
        for doc in documents:
            tokens = self.text_processor.process_text(doc)
            processed_docs.append(tokens)
        
        # Calculate TF for each document
        tf_docs = []
        for tokens in processed_docs:
            tf = self._calculate_tf(tokens)
            tf_docs.append(tf)
        
        # Calculate IDF
        idf = self._calculate_idf(processed_docs)
        
        # Calculate TF-IDF vectors
        tfidf_docs = []
        for tf in tf_docs:
            tfidf = {word: tf_val * idf.get(word, 0.0) for word, tf_val in tf.items()}
            tfidf_docs.append(tfidf)
        
        # Get vectors for the two documents
        vec1 = tfidf_docs[0] if len(tfidf_docs) > 0 else {}
        vec2 = tfidf_docs[1] if len(tfidf_docs) > 1 else {}
        
        return self.cosine_similarity(vec1, vec2)
    
    def _calculate_tf(self, tokens: List[str]) -> Dict[str, float]:
        """Calculate term frequency."""
        if not tokens:
            return {}
        
        counter = Counter(tokens)
        total = len(tokens)
        return {word: count / total for word, count in counter.items()}
    
    def _calculate_idf(self, documents: List[List[str]]) -> Dict[str, float]:
        """Calculate inverse document frequency."""
        if not documents:
            return {}
        
        # Count in how many documents each word appears
        doc_word_counts = {}
        for doc in documents:
            unique_words = set(doc)
            for word in unique_words:
                doc_word_counts[word] = doc_word_counts.get(word, 0) + 1
        
        # Calculate IDF
        total_docs = len(documents)
        idf = {}
        for word, count in doc_word_counts.items():
            idf[word] = math.log(total_docs / (1 + count))
        
        return idf
    
    def calculate_jaccard_similarity(self, doc1: str, doc2: str) -> float:
        """
        Calculate Jaccard similarity between two documents.
        
        Args:
            doc1: First document text
            doc2: Second document text
            
        Returns:
            Jaccard similarity score (0 to 1)
        """
        tokens1 = set(self.text_processor.process_text(doc1))
        tokens2 = set(self.text_processor.process_text(doc2))
        
        return self.jaccard_similarity(tokens1, tokens2)
    
    def calculate_similarity(self, doc1: str, doc2: str, method: str = 'cosine',
                            documents: Optional[List[str]] = None) -> float:
        """
        Calculate similarity between two documents using specified method.
        
        Args:
            doc1: First document text
            doc2: Second document text
            method: Similarity method ('cosine', 'jaccard', 'tfidf')
            documents: Optional list of all documents for TF-IDF
            
        Returns:
            Similarity score (0 to 1)
        """
        methods = {
            'cosine': lambda: self.calculate_tfidf_similarity(doc1, doc2, documents),
            'jaccard': lambda: self.calculate_jaccard_similarity(doc1, doc2),
            'tfidf': lambda: self.calculate_tfidf_similarity(doc1, doc2, documents),
        }
        
        if method not in methods:
            raise ValueError(f"Unknown method: {method}. Available: {list(methods.keys())}")
        
        return methods[method]()
    
    def find_similar_documents(self, target_doc: str, documents: List[str],
                               top_n: int = 5, method: str = 'cosine') -> List[Tuple[int, float]]:
        """
        Find most similar documents to a target document.
        
        Args:
            target_doc: Target document text
            documents: List of documents to compare against
            top_n: Number of similar documents to return
            method: Similarity method to use
            
        Returns:
            List of (document_index, similarity_score) tuples
        """
        if not target_doc or not documents:
            return []
        
        similarities = []
        for i, doc in enumerate(documents):
            similarity = self.calculate_similarity(target_doc, doc, method=method)
            similarities.append((i, similarity))
        
        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        return similarities[:top_n]


# Global instance
similarity_engine = SimilarityEngine()
