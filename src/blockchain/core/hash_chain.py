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
Local Hash Chain Implementation for Open-Omniscience

Provides a SQLite-based hash chain for per-article verification.
Each article is individually hashed and stored, with blocks containing
Merkle roots for efficient verification.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import sqlite3
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

# Import existing Merkle tree functionality
from src.crypto.merkle_tree import compute_merkle_root, MerkleTree


@dataclass
class LocalBlock:
    """
    Represents a block in the local hash chain.
    
    Attributes:
        block_height: Unique identifier for the block (0 = genesis)
        previous_hash: SHA-256 hash of the previous block's header
        merkle_root: Merkle root of all article hashes in this block
        timestamp: Unix timestamp when block was created
        article_count: Number of articles in this block
        articles: List of article_ids in this block
        block_hash: SHA-256 hash of this block's header (computed automatically)
    """
    
    block_height: int
    previous_hash: str
    merkle_root: str
    timestamp: int
    article_count: int
    articles: List[str]
    block_hash: str = field(init=False)
    
    def __post_init__(self):
        """Compute block_hash from all other fields."""
        data = {
            'block_height': self.block_height,
            'previous_hash': self.previous_hash,
            'merkle_root': self.merkle_root,
            'timestamp': self.timestamp,
            'article_count': self.article_count,
            'articles': sorted(self.articles)  # Sort for deterministic hashing
        }
        self.block_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert block to dictionary."""
        return {
            'block_height': self.block_height,
            'previous_hash': self.previous_hash,
            'merkle_root': self.merkle_root,
            'timestamp': self.timestamp,
            'article_count': self.article_count,
            'articles': self.articles,
            'block_hash': self.block_hash
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LocalBlock':
        """Create LocalBlock from dictionary."""
        return cls(
            block_height=data['block_height'],
            previous_hash=data['previous_hash'],
            merkle_root=data['merkle_root'],
            timestamp=data['timestamp'],
            article_count=data['article_count'],
            articles=data['articles']
        )


class LocalHashChain:
    """
    SQLite-based hash chain for per-article verification.
    
    Stores individual article hashes and organizes them into blocks
    with Merkle roots for efficient verification. Supports:
    - Per-article verification via Merkle proofs
    - Block chain integrity verification
    - Offline operation (100% local)
    
    Database Schema:
    - blocks: Block headers with Merkle roots
    - block_articles: Mapping of articles to blocks
    - article_hashes: Individual article hashes (content, metadata, source)
    """
    
    DEFAULT_DB_PATH = "data/blockchain/local_hash_chain.db"
    DEFAULT_ARTICLES_PER_BLOCK = 100
    DEFAULT_TIME_PER_BLOCK = 86400  # 24 hours in seconds
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH,
                 articles_per_block: int = DEFAULT_ARTICLES_PER_BLOCK,
                 time_per_block: int = DEFAULT_TIME_PER_BLOCK):
        """
        Initialize the local hash chain.
        
        Args:
            db_path: Path to SQLite database file
            articles_per_block: Maximum articles per block
            time_per_block: Maximum time (seconds) per block
        """
        self.db_path = Path(db_path)
        self.articles_per_block = articles_per_block
        self.time_per_block = time_per_block
        self.connection: Optional[sqlite3.Connection] = None
        
        # Create parent directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize the SQLite database with required tables."""
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        
        cursor = self.connection.cursor()
        
        # Blocks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                block_height INTEGER PRIMARY KEY,
                previous_hash TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                article_count INTEGER NOT NULL,
                block_hash TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL
            )
        """)
        
        # Block-articles mapping table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS block_articles (
                block_height INTEGER NOT NULL,
                article_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (block_height, article_id),
                FOREIGN KEY (block_height) REFERENCES blocks(block_height) ON DELETE CASCADE
            )
        """)
        
        # Article hashes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_hashes (
                article_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                block_height INTEGER,
                position INTEGER,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (block_height) REFERENCES blocks(block_height) ON DELETE SET NULL
            )
        """)
        
        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(block_height)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blocks_hash ON blocks(block_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_block_articles_block ON block_articles(block_height)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_block_articles_article ON block_articles(article_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_hashes_block ON article_hashes(block_height)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_hashes_article ON article_hashes(article_id)")
        
        self.connection.commit()
        
        # Create genesis block if database is empty
        self._ensure_genesis_block()
    
    def _ensure_genesis_block(self) -> None:
        """Create genesis block if database is empty."""
        cursor = self.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM blocks")
        if cursor.fetchone()[0] == 0:
            # Create genesis block
            genesis_block = LocalBlock(
                block_height=0,
                previous_hash="0" * 64,  # All zeros for genesis
                merkle_root=hashlib.sha256(b'').hexdigest(),  # Empty tree
                timestamp=int(time.time()),
                article_count=0,
                articles=[]
            )
            
            cursor.execute("""
                INSERT INTO blocks 
                (block_height, previous_hash, merkle_root, timestamp, article_count, block_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                genesis_block.block_height,
                genesis_block.previous_hash,
                genesis_block.merkle_root,
                genesis_block.timestamp,
                genesis_block.article_count,
                genesis_block.block_hash,
                int(time.time())
            ))
            self.connection.commit()
    
    def _get_current_block(self) -> Optional[LocalBlock]:
        """Get the current (most recent) block that can accept more articles."""
        cursor = self.connection.cursor()
        
        # Get the highest block
        cursor.execute("SELECT block_height FROM blocks ORDER BY block_height DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        
        current_height = row[0]
        
        # Check if current block is full (by count or time)
        cursor.execute("""
            SELECT block_height, previous_hash, merkle_root, timestamp, article_count
            FROM blocks WHERE block_height = ?
        """, (current_height,))
        row = cursor.fetchone()
        if not row:
            return None
        
        block_height, previous_hash, merkle_root, timestamp, article_count = row
        
        # Get articles in this block
        cursor.execute("""
            SELECT article_id FROM block_articles 
            WHERE block_height = ? 
            ORDER BY position ASC
        """, (current_height,))
        articles = [row[0] for row in cursor.fetchall()]
        
        # Check if block is full
        current_time = int(time.time())
        time_elapsed = current_time - timestamp
        is_full_by_count = article_count >= self.articles_per_block
        is_full_by_time = time_elapsed >= self.time_per_block
        
        if is_full_by_count or is_full_by_time:
            # Current block is full, need to create a new one
            return None
        
        return LocalBlock(
            block_height=block_height,
            previous_hash=previous_hash,
            merkle_root=merkle_root,
            timestamp=timestamp,
            article_count=article_count,
            articles=articles
        )
    
    def _create_new_block(self, previous_block: LocalBlock) -> LocalBlock:
        """Create a new block in the chain."""
        new_height = previous_block.block_height + 1
        current_time = int(time.time())
        
        # New block starts with empty Merkle root
        empty_merkle_root = hashlib.sha256(b'').hexdigest()
        
        new_block = LocalBlock(
            block_height=new_height,
            previous_hash=previous_block.block_hash,
            merkle_root=empty_merkle_root,
            timestamp=current_time,
            article_count=0,
            articles=[]
        )
        
        # Store the new block
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO blocks 
            (block_height, previous_hash, merkle_root, timestamp, article_count, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            new_block.block_height,
            new_block.previous_hash,
            new_block.merkle_root,
            new_block.timestamp,
            new_block.article_count,
            new_block.block_hash,
            current_time
        ))
        self.connection.commit()
        
        return new_block
    
    def _update_block_merkle_root(self, block_height: int) -> str:
        """Update the Merkle root for a block and return it."""
        cursor = self.connection.cursor()
        
        # Get all article content hashes in this block (sorted by position)
        cursor.execute("""
            SELECT ba.article_id, ah.content_hash
            FROM block_articles ba
            JOIN article_hashes ah ON ba.article_id = ah.article_id
            WHERE ba.block_height = ?
            ORDER BY ba.position ASC
        """, (block_height,))
        
        article_hashes = [row[1] for row in cursor.fetchall()]
        
        if not article_hashes:
            # Empty block
            merkle_root = hashlib.sha256(b'').hexdigest()
        else:
            # Compute Merkle root
            merkle_root = compute_merkle_root(article_hashes)
        
        # Update the block
        cursor.execute("""
            UPDATE blocks 
            SET merkle_root = ?, article_count = ?
            WHERE block_height = ?
        """, (merkle_root, len(article_hashes), block_height))
        
        # Need to recompute block_hash since merkle_root changed
        cursor.execute("""
            SELECT block_height, previous_hash, timestamp, article_count
            FROM blocks WHERE block_height = ?
        """, (block_height,))
        row = cursor.fetchone()
        if row:
            block_height, previous_hash, timestamp, article_count = row
            cursor.execute("SELECT article_id FROM block_articles WHERE block_height = ? ORDER BY position ASC", (block_height,))
            articles = [r[0] for r in cursor.fetchall()]
            
            new_block = LocalBlock(
                block_height=block_height,
                previous_hash=previous_hash,
                merkle_root=merkle_root,
                timestamp=timestamp,
                article_count=article_count,
                articles=articles
            )
            
            cursor.execute("""
                UPDATE blocks 
                SET block_hash = ?
                WHERE block_height = ?
            """, (new_block.block_hash, block_height))
        
        self.connection.commit()
        return merkle_root
    
    def add_article(self, article_id: str, content_hash: str, 
                   metadata_hash: str, source_hash: str) -> Dict[str, Any]:
        """
        Add an article to the hash chain.
        
        Creates a new block if the current block is full (by count or time).
        
        Args:
            article_id: Unique identifier for the article
            content_hash: SHA-256 hash of article content
            metadata_hash: SHA-256 hash of article metadata
            source_hash: SHA-256 hash of source URL + timestamp
            
        Returns:
            Dictionary with block_height, position, and status
        """
        current_time = int(time.time())
        
        # Get or create current block
        current_block = self._get_current_block()
        
        if current_block is None:
            # Get the latest block to create a new one
            cursor = self.connection.cursor()
            cursor.execute("SELECT block_height FROM blocks ORDER BY block_height DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("No blocks exist in the chain")
            
            prev_height = row[0]
            
            # Get the previous block's hash and other info
            cursor.execute("""
                SELECT block_hash, previous_hash, timestamp
                FROM blocks WHERE block_height = ?
            """, (prev_height,))
            prev_row = cursor.fetchone()
            if not prev_row:
                raise RuntimeError(f"Block {prev_height} not found")
            
            prev_block_hash, prev_prev_hash, prev_timestamp = prev_row
            
            # Get articles in previous block
            cursor.execute("""
                SELECT article_id FROM block_articles 
                WHERE block_height = ? 
                ORDER BY position ASC
            """, (prev_height,))
            prev_articles = [r[0] for r in cursor.fetchall()]
            
            # Create a minimal previous block for creating new block
            prev_block = LocalBlock(
                block_height=prev_height,
                previous_hash=prev_prev_hash,
                merkle_root="",  # Will be computed
                timestamp=prev_timestamp,
                article_count=len(prev_articles),
                articles=prev_articles
            )
            prev_block.block_hash = prev_block_hash
            
            current_block = self._create_new_block(prev_block)
        
        # Get the current article count for this block from the database
        cursor = self.connection.cursor()
        cursor.execute("SELECT article_count FROM blocks WHERE block_height = ?", 
                      (current_block.block_height,))
        current_count = cursor.fetchone()[0]
        position = current_count
        
        # Store article hashes
        cursor.execute("""
            INSERT OR REPLACE INTO article_hashes 
            (article_id, content_hash, metadata_hash, source_hash, block_height, position, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            article_id,
            content_hash,
            metadata_hash,
            source_hash,
            current_block.block_height,
            position,
            current_time
        ))
        
        # Map article to block
        cursor.execute("""
            INSERT OR REPLACE INTO block_articles 
            (block_height, article_id, position)
            VALUES (?, ?, ?)
        """, (
            current_block.block_height,
            article_id,
            position
        ))
        
        # Update block article count
        new_count = current_count + 1
        cursor.execute("""
            UPDATE blocks 
            SET article_count = ?
            WHERE block_height = ?
        """, (new_count, current_block.block_height))
        
        self.connection.commit()
        
        # Update the block's Merkle root
        self._update_block_merkle_root(current_block.block_height)
        
        return {
            'article_id': article_id,
            'block_height': current_block.block_height,
            'position': position,
            'content_hash': content_hash,
            'metadata_hash': metadata_hash,
            'source_hash': source_hash,
            'timestamp': current_time
        }
    
    def get_article_hashes(self, article_id: str) -> Optional[Dict[str, str]]:
        """
        Retrieve the 3 hashes for an article.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Dictionary with content_hash, metadata_hash, source_hash or None if not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT content_hash, metadata_hash, source_hash, block_height, position, timestamp
            FROM article_hashes 
            WHERE article_id = ?
        """, (article_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        content_hash, metadata_hash, source_hash, block_height, position, timestamp = row
        
        return {
            'article_id': article_id,
            'content_hash': content_hash,
            'metadata_hash': metadata_hash,
            'source_hash': source_hash,
            'block_height': block_height,
            'position': position,
            'timestamp': timestamp
        }
    
    def get_article_block(self, article_id: str) -> Optional[int]:
        """
        Get the block height containing an article.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Block height or None if article not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT block_height FROM article_hashes 
            WHERE article_id = ?
        """, (article_id,))
        
        row = cursor.fetchone()
        return row[0] if row else None
    
    def get_block(self, block_height: int) -> Optional[LocalBlock]:
        """
        Get a block by its height.
        
        Args:
            block_height: Block height
            
        Returns:
            LocalBlock object or None if not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT block_height, previous_hash, merkle_root, timestamp, article_count, block_hash
            FROM blocks 
            WHERE block_height = ?
        """, (block_height,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        block_height, previous_hash, merkle_root, timestamp, article_count, block_hash = row
        
        # Get articles in this block
        cursor.execute("""
            SELECT article_id FROM block_articles 
            WHERE block_height = ? 
            ORDER BY position ASC
        """, (block_height,))
        articles = [r[0] for r in cursor.fetchall()]
        
        block = LocalBlock(
            block_height=block_height,
            previous_hash=previous_hash,
            merkle_root=merkle_root,
            timestamp=timestamp,
            article_count=article_count,
            articles=articles
        )
        
        # Verify block_hash matches
        if block.block_hash != block_hash:
            # Recompute and update if needed
            block.block_hash = block_hash
        
        return block
    
    def get_merkle_proof(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Generate a Merkle proof for an article.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Dictionary with Merkle proof and related data, or None if article not found
        """
        # Get article info
        article_info = self.get_article_hashes(article_id)
        if not article_info:
            return None
        
        block_height = article_info['block_height']
        position = article_info['position']
        content_hash = article_info['content_hash']
        
        # Get the block
        block = self.get_block(block_height)
        if not block:
            return None
        
        # Get all article hashes in the block (sorted by position)
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT ba.article_id, ah.content_hash
            FROM block_articles ba
            JOIN article_hashes ah ON ba.article_id = ah.article_id
            WHERE ba.block_height = ?
            ORDER BY ba.position ASC
        """, (block_height,))
        
        article_hashes = []
        article_ids = []
        for row in cursor.fetchall():
            article_ids.append(row[0])
            article_hashes.append(row[1])
        
        # Create Merkle tree and get proof
        if not article_hashes:
            return None
        
        tree = MerkleTree(article_hashes)
        proof = tree.get_proof(position)
        
        # Convert proof to serializable format
        serializable_proof = [
            {'hash': sibling_hash, 'is_right_sibling': is_right}
            for sibling_hash, is_right in proof
        ]
        
        return {
            'article_id': article_id,
            'content_hash': content_hash,
            'metadata_hash': article_info['metadata_hash'],
            'source_hash': article_info['source_hash'],
            'block_height': block_height,
            'position': position,
            'merkle_proof': serializable_proof,
            'merkle_root': block.merkle_root,
            'block_hash': block.block_hash,
            'previous_block_hash': block.previous_hash,
            'timestamp': article_info['timestamp']
        }
    
    def verify_article_with_proof(self, article_id: str, content_hash: str,
                                 metadata_hash: str, source_hash: str,
                                 merkle_proof: List[Dict[str, Any]],
                                 merkle_root: str) -> bool:
        """
        Verify an article using a provided Merkle proof.
        
        Args:
            article_id: Article identifier
            content_hash: Expected content hash
            metadata_hash: Expected metadata hash
            source_hash: Expected source hash
            merkle_proof: Merkle proof (list of sibling hashes with position)
            merkle_root: Expected Merkle root
            
        Returns:
            True if verification succeeds, False otherwise
        """
        # First, verify the stored hashes match
        article_info = self.get_article_hashes(article_id)
        if not article_info:
            return False
        
        if (article_info['content_hash'] != content_hash or
            article_info['metadata_hash'] != metadata_hash or
            article_info['source_hash'] != source_hash):
            return False
        
        # Convert proof to format expected by MerkleTree.verify_proof
        proof_tuples = [
            (p['hash'], p['is_right_sibling'])
            for p in merkle_proof
        ]
        
        # Verify the Merkle proof
        # The Merkle tree hashes the leaf data (content_hash), so we need to
        # start with hash(content_hash) as the leaf hash
        try:
            # Hash the content_hash to get the leaf hash (Merkle tree hashes leaf data)
            current_hash = hashlib.sha256(content_hash.encode('utf-8')).hexdigest()
            
            # If there's no proof (single article in block), 
            # the merkle root should be hash(content_hash)
            if not proof_tuples:
                # For a single article, Merkle root = hash(content_hash)
                return current_hash == merkle_root
            
            for sibling_hash, is_right_sibling in proof_tuples:
                if is_right_sibling:
                    # Sibling is to the right, so current + sibling
                    combined = current_hash + sibling_hash
                else:
                    # Sibling is to the left, so sibling + current
                    combined = sibling_hash + current_hash
                current_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()
            
            return current_hash == merkle_root
        except Exception:
            return False
    
    def verify_block_chain_integrity(self, max_height: Optional[int] = None) -> bool:
        """
        Verify the integrity of the entire block chain.
        
        Args:
            max_height: Maximum block height to verify (None for all)
            
        Returns:
            True if chain is intact, False otherwise
        """
        cursor = self.connection.cursor()
        
        if max_height is None:
            cursor.execute("SELECT MAX(block_height) FROM blocks")
            max_height = cursor.fetchone()[0]
        
        if max_height is None or max_height == 0:
            return True  # Only genesis block
        
        # Check each block's previous_hash matches the prior block's block_hash
        for height in range(1, max_height + 1):
            cursor.execute("""
                SELECT previous_hash FROM blocks WHERE block_height = ?
            """, (height,))
            prev_hash = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT block_hash FROM blocks WHERE block_height = ?
            """, (height - 1,))
            expected_prev_hash = cursor.fetchone()
            
            if not expected_prev_hash or expected_prev_hash[0] != prev_hash:
                return False
        
        return True
    
    def get_all_blocks(self, limit: Optional[int] = None) -> List[LocalBlock]:
        """
        Get all blocks in the chain.
        
        Args:
            limit: Maximum number of blocks to return
            
        Returns:
            List of LocalBlock objects
        """
        cursor = self.connection.cursor()
        query = """
            SELECT block_height, previous_hash, merkle_root, timestamp, article_count, block_hash
            FROM blocks 
            ORDER BY block_height ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        
        blocks = []
        for row in cursor.fetchall():
            block_height, previous_hash, merkle_root, timestamp, article_count, block_hash = row
            
            # Get articles
            cursor.execute("""
                SELECT article_id FROM block_articles 
                WHERE block_height = ? 
                ORDER BY position ASC
            """, (block_height,))
            articles = [r[0] for r in cursor.fetchall()]
            
            block = LocalBlock(
                block_height=block_height,
                previous_hash=previous_hash,
                merkle_root=merkle_root,
                timestamp=timestamp,
                article_count=article_count,
                articles=articles
            )
            block.block_hash = block_hash  # Override computed hash with stored one
            blocks.append(block)
        
        return blocks
    
    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function to create a hash chain
def create_hash_chain(db_path: str = LocalHashChain.DEFAULT_DB_PATH,
                     articles_per_block: int = LocalHashChain.DEFAULT_ARTICLES_PER_BLOCK,
                     time_per_block: int = LocalHashChain.DEFAULT_TIME_PER_BLOCK) -> LocalHashChain:
    """
    Factory function to create a new local hash chain.
    
    Args:
        db_path: Path to SQLite database
        articles_per_block: Maximum articles per block
        time_per_block: Maximum time (seconds) per block
        
    Returns:
        New LocalHashChain instance
    """
    return LocalHashChain(db_path, articles_per_block, time_per_block)
