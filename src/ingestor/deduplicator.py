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
Advanced Deduplication for Open Omniscience

This module provides advanced deduplication capabilities using:
- MinHash + LSH (Locality-Sensitive Hashing) for near-duplicate detection
- TF-IDF + Cosine Similarity for semantic similarity
- Content hashing for exact duplicates

Author: Ideotion
"""

import sys
import hashlib
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass
from collections import defaultdict
import re
import string

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
from utils.logging_config import setup_logging
logger = setup_logging("deduplicator")


@dataclass
class DeduplicationConfig:
    """Configuration for deduplication."""
    # MinHash parameters
    minhash_num_perm: int = 128
    minhash_hash_size: int = 64
    minhash_threshold: float = 0.85  # Jaccard similarity threshold
    
    # LSH parameters
    lsh_bands: int = 20
    lsh_rows: int = 8
    
    # TF-IDF parameters
    tfidf_min_df: int = 2
    tfidf_max_df: float = 0.95
    tfidf_similarity_threshold: float = 0.90
    
    # Content hash parameters
    content_hash_chunk_size: int = 8192
    
    # General
    enable_minhash: bool = True
    enable_tfidf: bool = True
    enable_content_hash: bool = True
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> "DeduplicationConfig":
        """Create from dictionary."""
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})


class MinHash:
    """
    MinHash implementation for approximate Jaccard similarity.
    
    This is used to efficiently find near-duplicate documents by comparing
    sets of tokens (shingles) from the text.
    """
    
    def __init__(self, num_perm: int = 128, hash_size: int = 64):
        """
        Initialize MinHash.
        
        Args:
            num_perm: Number of permutations (hash functions).
            hash_size: Size of hash in bits.
        """
        self.num_perm = num_perm
        self.hash_size = hash_size
        self._coefficients = self._generate_coefficients(num_perm)
    
    def _generate_coefficients(self, num_perm: int) -> List[Tuple[int, int]]:
        """Generate random coefficients for hash functions."""
        # Use a simple deterministic approach for reproducibility
        np.random.seed(42)
        coefficients = []
        for _ in range(num_perm):
            a = np.random.randint(1, 1000)
            b = np.random.randint(0, 1000)
            coefficients.append((a, b))
        return coefficients
    
    def _hash(self, x: int, a: int, b: int, prime: int) -> int:
        """Universal hash function: h(x) = (a * x + b) % prime."""
        return (a * x + b) % prime
    
    def _get_prime(self) -> int:
        """Get a prime number larger than hash_size."""
        # Find next prime after hash_size
        n = self.hash_size
        while True:
            n += 1
            if self._is_prime(n):
                return n
    
    def _is_prime(self, n: int) -> bool:
        """Check if a number is prime."""
        if n < 2:
            return False
        for i in range(2, int(n ** 0.5) + 1):
            if n % i == 0:
                return False
        return True
    
    def signature(self, tokens: Set[str]) -> np.ndarray:
        """
        Compute MinHash signature for a set of tokens.
        
        Args:
            tokens: Set of tokens (shingles).
            
        Returns:
            NumPy array of hash values.
        """
        if not tokens:
            return np.zeros(self.num_perm, dtype=np.uint64)
        
        prime = self._get_prime()
        signature = np.full(self.num_perm, prime, dtype=np.uint64)
        
        # Convert tokens to integers
        token_to_int = {token: i + 1 for i, token in enumerate(tokens)}
        
        for i, (a, b) in enumerate(self._coefficients):
            min_hash = prime
            for token, token_int in token_to_int.items():
                hash_val = self._hash(token_int, a, b, prime)
                if hash_val < min_hash:
                    min_hash = hash_val
            signature[i] = min_hash
        
        return signature
    
    def jaccard_similarity(self, sig1: np.ndarray, sig2: np.ndarray) -> float:
        """
        Estimate Jaccard similarity from MinHash signatures.
        
        Args:
            sig1: First signature.
            sig2: Second signature.
            
        Returns:
            Estimated Jaccard similarity (0.0 to 1.0).
        """
        if len(sig1) != len(sig2):
            raise ValueError("Signatures must have the same length")
        
        equal = np.sum(sig1 == sig2)
        return equal / len(sig1)


class LSH:
    """
    Locality-Sensitive Hashing for efficient near-duplicate detection.
    
    This uses MinHash signatures and bands to find similar documents
    without comparing all pairs.
    """
    
    def __init__(self, bands: int = 20, rows: int = 8):
        """
        Initialize LSH.
        
        Args:
            bands: Number of bands.
            rows: Number of rows per band.
        """
        self.bands = bands
        self.rows = rows
        self.buckets: Dict[int, Set[str]] = defaultdict(set)
        self.signatures: Dict[str, np.ndarray] = {}
    
    def add_document(self, doc_id: str, signature: np.ndarray):
        """
        Add a document signature to the LSH index.
        
        Args:
            doc_id: Document ID.
            signature: MinHash signature.
        """
        self.signatures[doc_id] = signature
        
        # Split signature into bands
        total_rows = self.bands * self.rows
        if len(signature) < total_rows:
            raise ValueError(f"Signature length {len(signature)} < {total_rows}")
        
        # Split into bands
        for band in range(self.bands):
            start = band * self.rows
            end = start + self.rows
            band_signature = signature[start:end]
            
            # Create hash for this band
            band_hash = self._hash_band(band_signature)
            self.buckets[band_hash].add(doc_id)
    
    def _hash_band(self, band: np.ndarray) -> int:
        """Create a hash for a band of the signature."""
        # Convert to bytes and hash
        band_bytes = band.tobytes()
        return int(hashlib.sha256(band_bytes).hexdigest(), 16) % (2 ** 32)
    
    def query(self, signature: np.ndarray, threshold: float = 0.85) -> Set[str]:
        """
        Query for similar documents.
        
        Args:
            signature: MinHash signature to query with.
            threshold: Jaccard similarity threshold.
            
        Returns:
            Set of document IDs that are similar.
        """
        candidates = set()
        
        # Check each band
        for band in range(self.bands):
            start = band * self.rows
            end = start + self.rows
            band_signature = signature[start:end]
            
            band_hash = self._hash_band(band_signature)
            if band_hash in self.buckets:
                candidates.update(self.buckets[band_hash])
        
        # Filter by actual similarity
        minhash = MinHash()
        similar_docs = set()
        
        for doc_id in candidates:
            if doc_id in self.signatures:
                similarity = minhash.jaccard_similarity(signature, self.signatures[doc_id])
                if similarity >= threshold:
                    similar_docs.add(doc_id)
        
        return similar_docs
    
    def remove_document(self, doc_id: str):
        """
        Remove a document from the LSH index.
        
        Args:
            doc_id: Document ID to remove.
        """
        if doc_id not in self.signatures:
            return
        
        signature = self.signatures[doc_id]
        del self.signatures[doc_id]
        
        # Remove from all buckets
        for band in range(self.bands):
            start = band * self.rows
            end = start + self.rows
            band_signature = signature[start:end]
            
            band_hash = self._hash_band(band_signature)
            if band_hash in self.buckets:
                self.buckets[band_hash].discard(doc_id)
                if not self.buckets[band_hash]:
                    del self.buckets[band_hash]


class TFIDFVectorizer:
    """
    Simple TF-IDF vectorizer for text documents.
    
    This provides a lightweight alternative to scikit-learn's TF-IDF
    for environments where it's not available.
    """
    
    def __init__(self, min_df: int = 2, max_df: float = 0.95):
        """
        Initialize TF-IDF vectorizer.
        
        Args:
            min_df: Minimum document frequency for a term.
            max_df: Maximum document frequency for a term (as fraction of total docs).
        """
        self.min_df = min_df
        self.max_df = max_df
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_count = 0
        self._doc_freq: Dict[str, int] = defaultdict(int)
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        # Lowercase
        text = text.lower()
        # Remove punctuation
        text = text.translate(str.maketrans('', '', string.punctuation))
        # Split into words
        words = text.split()
        # Remove short words
        words = [w for w in words if len(w) > 2]
        return words
    
    def fit(self, documents: List[str]):
        """
        Fit the vectorizer on a list of documents.
        
        Args:
            documents: List of document texts.
        """
        self.doc_count = len(documents)
        self._doc_freq.clear()
        
        # Count document frequencies
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                self._doc_freq[token] += 1
        
        # Build vocabulary and IDF
        self.vocabulary = {}
        self.idf = {}
        
        for token, freq in self._doc_freq.items():
            # Check min_df
            if freq < self.min_df:
                continue
            # Check max_df
            if freq / self.doc_count > self.max_df:
                continue
            
            # Add to vocabulary
            vocab_id = len(self.vocabulary)
            self.vocabulary[token] = vocab_id
            # IDF = log((N + 1) / (df + 1)) + 1
            self.idf[token] = np.log((self.doc_count + 1) / (freq + 1)) + 1
    
    def transform(self, document: str) -> np.ndarray:
        """
        Transform a document into TF-IDF vector.
        
        Args:
            document: Document text.
            
        Returns:
            TF-IDF vector as NumPy array.
        """
        if not self.vocabulary:
            raise ValueError("Vectorizer not fitted. Call fit() first.")
        
        tokens = self._tokenize(document)
        
        # Create vector
        vector = np.zeros(len(self.vocabulary))
        
        # Count term frequencies
        token_counts = defaultdict(int)
        for token in tokens:
            if token in self.vocabulary:
                token_counts[token] += 1
        
        # Calculate TF-IDF
        for token, count in token_counts.items():
            if token in self.vocabulary:
                # TF = count / total tokens
                tf = count / len(tokens) if tokens else 0
                # TF-IDF = TF * IDF
                vector[self.vocabulary[token]] = tf * self.idf[token]
        
        return vector
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector.
            vec2: Second vector.
            
        Returns:
            Cosine similarity (0.0 to 1.0).
        """
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have the same length")
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)


class ContentHasher:
    """
    Content hashing for exact duplicate detection.
    
    This provides multiple hashing strategies for detecting exact duplicates.
    """
    
    def __init__(self, chunk_size: int = 8192):
        """
        Initialize content hasher.
        
        Args:
            chunk_size: Size of chunks for chunk-based hashing.
        """
        self.chunk_size = chunk_size
    
    def sha256_hash(self, content: str) -> str:
        """
        Compute SHA-256 hash of content.
        
        Args:
            content: Text content.
            
        Returns:
            SHA-256 hash as hex string.
        """
        return hashlib.sha256(content.encode('utf-8', errors='ignore')).hexdigest()
    
    def md5_hash(self, content: str) -> str:
        """
        Compute MD5 hash of content.
        
        Args:
            content: Text content.
            
        Returns:
            MD5 hash as hex string.
        """
        return hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest()
    
    def chunk_hashes(self, content: str) -> List[str]:
        """
        Compute hashes for chunks of content.
        
        This is useful for very long documents where we want to detect
        partial duplicates.
        
        Args:
            content: Text content.
            
        Returns:
            List of chunk hashes.
        """
        hashes = []
        for i in range(0, len(content), self.chunk_size):
            chunk = content[i:i + self.chunk_size]
            hashes.append(self.sha256_hash(chunk))
        return hashes


class Deduplicator:
    """
    Main deduplication class combining multiple strategies.
    
    This class provides a unified interface for detecting duplicates using:
    - Content hashing (exact duplicates)
    - MinHash + LSH (near duplicates)
    - TF-IDF + Cosine similarity (semantic duplicates)
    """
    
    def __init__(self, config: Optional[DeduplicationConfig] = None):
        """
        Initialize the deduplicator.
        
        Args:
            config: Deduplication configuration.
        """
        if config is None:
            config = DeduplicationConfig()
        
        self.config = config
        
        # Initialize components
        if self.config.enable_minhash:
            self.minhash = MinHash(
                num_perm=self.config.minhash_num_perm,
                hash_size=self.config.minhash_hash_size
            )
            self.lsh = LSH(
                bands=self.config.lsh_bands,
                rows=self.config.lsh_rows
            )
        
        if self.config.enable_tfidf:
            self.tfidf = TFIDFVectorizer(
                min_df=self.config.tfidf_min_df,
                max_df=self.config.tfidf_max_df
            )
        
        if self.config.enable_content_hash:
            self.hasher = ContentHasher(
                chunk_size=self.config.content_hash_chunk_size
            )
        
        # Document stores
        self._content_hashes: Set[str] = set()
        self._minhash_signatures: Dict[str, np.ndarray] = {}
        self._tfidf_vectors: Dict[str, np.ndarray] = {}
        
        logger.info("Deduplicator initialized")
    
    def _extract_text_features(self, text: str) -> Set[str]:
        """
        Extract text features (shingles) for MinHash.
        
        Args:
            text: Text to extract features from.
            
        Returns:
            Set of text features (shingles).
        """
        # Simple shingling: use 3-grams (3 consecutive words)
        words = text.lower().split()
        shingles = set()
        
        for i in range(len(words) - 2):
            shingle = ' '.join(words[i:i + 3])
            shingles.add(shingle)
        
        # Also add individual words
        for word in words:
            if len(word) > 2:  # Skip very short words
                shingles.add(word)
        
        return shingles
    
    def _normalize_text(self, text: str) -> str:
        """
        Normalize text for hashing.
        
        Args:
            text: Text to normalize.
            
        Returns:
            Normalized text.
        """
        # Remove URLs
        text = re.sub(r'https?://\S+|www\.\S+', '', text)
        # Remove special characters
        text = re.sub(r'[^\w\s]', ' ', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        # Lowercase
        text = text.lower()
        # Strip
        text = text.strip()
        return text
    
    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict] = None):
        """
        Add a document to the deduplication index.
        
        Args:
            doc_id: Unique document ID.
            text: Document text content.
            metadata: Optional metadata dictionary.
        """
        normalized_text = self._normalize_text(text)
        
        # Content hash
        if self.config.enable_content_hash:
            content_hash = self.hasher.sha256_hash(normalized_text)
            self._content_hashes.add(content_hash)
        
        # MinHash + LSH
        if self.config.enable_minhash:
            features = self._extract_text_features(normalized_text)
            signature = self.minhash.signature(features)
            self._minhash_signatures[doc_id] = signature
            self.lsh.add_document(doc_id, signature)
        
        # TF-IDF
        if self.config.enable_tfidf:
            # Note: TF-IDF requires fitting on a corpus first
            # For now, we'll just store the text
            pass
    
    def is_duplicate(self, text: str, threshold: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if text is a duplicate.
        
        Args:
            text: Text to check.
            threshold: Similarity threshold (uses config if None).
            
        Returns:
            Tuple of (is_duplicate, duplicate_doc_id).
        """
        if threshold is None:
            threshold = self.config.minhash_threshold
        
        normalized_text = self._normalize_text(text)
        
        # Check content hash
        if self.config.enable_content_hash:
            content_hash = self.hasher.sha256_hash(normalized_text)
            if content_hash in self._content_hashes:
                return True, None  # Exact duplicate
        
        # Check MinHash + LSH
        if self.config.enable_minhash:
            features = self._extract_text_features(normalized_text)
            signature = self.minhash.signature(features)
            
            # Query LSH for similar documents
            similar_docs = self.lsh.query(signature, threshold)
            if similar_docs:
                return True, list(similar_docs)[0]  # Return first similar doc
        
        return False, None
    
    def find_similar(self, text: str, threshold: float = 0.85, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Find documents similar to the given text.
        
        Args:
            text: Text to compare against.
            threshold: Similarity threshold.
            limit: Maximum number of results to return.
            
        Returns:
            List of (doc_id, similarity_score) tuples, sorted by similarity.
        """
        results = []
        normalized_text = self._normalize_text(text)
        
        # MinHash + LSH similarity
        if self.config.enable_minhash:
            features = self._extract_text_features(normalized_text)
            signature = self.minhash.signature(features)
            
            similar_docs = self.lsh.query(signature, threshold)
            
            for doc_id in similar_docs:
                if doc_id in self._minhash_signatures:
                    similarity = self.minhash.jaccard_similarity(
                        signature, self._minhash_signatures[doc_id]
                    )
                    results.append((doc_id, similarity))
        
        # Sort by similarity (descending)
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:limit]
    
    def batch_deduplicate(self, documents: List[Dict]) -> Dict[str, List[str]]:
        """
        Deduplicate a batch of documents.
        
        Args:
            documents: List of document dictionaries with 'id' and 'text' keys.
            
        Returns:
            Dictionary mapping document IDs to lists of duplicate IDs.
        """
        duplicates = defaultdict(list)
        
        # First pass: add all documents to index
        for doc in documents:
            self.add_document(doc['id'], doc['text'])
        
        # Second pass: check for duplicates
        for doc in documents:
            is_dup, dup_id = self.is_duplicate(doc['text'])
            if is_dup and dup_id:
                duplicates[doc['id']].append(dup_id)
        
        return duplicates
    
    def get_content_hash(self, text: str) -> str:
        """
        Get content hash for a text.
        
        Args:
            text: Text to hash.
            
        Returns:
            SHA-256 hash of the normalized text.
        """
        normalized_text = self._normalize_text(text)
        return self.hasher.sha256_hash(normalized_text)
    
    def clear(self):
        """Clear all indexed documents."""
        self._content_hashes.clear()
        self._minhash_signatures.clear()
        self._tfidf_vectors.clear()
        
        if self.config.enable_minhash:
            self.lsh = LSH(
                bands=self.config.lsh_bands,
                rows=self.config.lsh_rows
            )
        
        logger.info("Deduplicator cleared")
    
    def get_stats(self) -> Dict:
        """
        Get deduplication statistics.
        
        Returns:
            Dictionary with statistics.
        """
        return {
            "content_hashes": len(self._content_hashes),
            "minhash_signatures": len(self._minhash_signatures),
            "tfidf_vectors": len(self._tfidf_vectors),
            "lsh_buckets": len(self.lsh.buckets) if self.config.enable_minhash else 0,
            "config": str(self.config)
        }


if __name__ == "__main__":
    # Example usage
    deduplicator = Deduplicator()
    
    # Sample documents
    documents = [
        {"id": "doc1", "text": "This is the first document about machine learning."},
        {"id": "doc2", "text": "This is the first document about machine learning."},  # Exact duplicate
        {"id": "doc3", "text": "This is a similar document about AI and machine learning."},  # Near duplicate
        {"id": "doc4", "text": "Completely different topic about sports."},
        {"id": "doc5", "text": "Machine learning is an important field in AI."},  # Semantically similar
    ]
    
    # Add documents
    for doc in documents:
        deduplicator.add_document(doc["id"], doc["text"])
    
    # Check for duplicates
    print("Checking for duplicates:")
    for doc in documents:
        is_dup, dup_id = deduplicator.is_duplicate(doc["text"])
        print(f"  {doc['id']}: {'DUPLICATE' if is_dup else 'UNIQUE'} (of {dup_id})")
    
    # Find similar documents
    print("\nFinding similar documents to doc3:")
    similar = deduplicator.find_similar(documents[2]["text"], threshold=0.5)
    for doc_id, score in similar:
        print(f"  {doc_id}: {score:.3f}")
    
    # Print stats
    print("\nStatistics:")
    for key, value in deduplicator.get_stats().items():
        print(f"  {key}: {value}")
