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
Tests for Local Hash Chain Implementation

Tests the SQLite-based hash chain for per-article verification.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import unittest
import tempfile
import shutil
import hashlib
import json
import time
from pathlib import Path

from src.blockchain.core.hash_chain import LocalHashChain, LocalBlock, create_hash_chain


class TestLocalBlock(unittest.TestCase):
    """Tests for LocalBlock dataclass."""
    
    def test_block_creation(self):
        """Test creating a LocalBlock."""
        block = LocalBlock(
            block_height=0,
            previous_hash="0" * 64,
            merkle_root="a" * 64,
            timestamp=int(time.time()),
            article_count=0,
            articles=[]
        )
        
        self.assertEqual(block.block_height, 0)
        self.assertEqual(block.previous_hash, "0" * 64)
        self.assertEqual(block.merkle_root, "a" * 64)
        self.assertEqual(block.article_count, 0)
        self.assertEqual(block.articles, [])
        self.assertIsNotNone(block.block_hash)
        self.assertEqual(len(block.block_hash), 64)  # SHA-256 hash length
    
    def test_block_hash_consistency(self):
        """Test that block_hash is computed consistently."""
        data = {
            'block_height': 5,
            'previous_hash': "abc123",
            'merkle_root': "def456",
            'timestamp': 1234567890,
            'article_count': 10,
            'articles': ['article1', 'article2']
        }
        
        block1 = LocalBlock(**data)
        block2 = LocalBlock(**data)
        
        self.assertEqual(block1.block_hash, block2.block_hash)
    
    def test_block_to_dict(self):
        """Test converting block to dictionary."""
        block = LocalBlock(
            block_height=1,
            previous_hash="prev_hash",
            merkle_root="merkle_root",
            timestamp=12345,
            article_count=5,
            articles=['a1', 'a2', 'a3', 'a4', 'a5']
        )
        
        data = block.to_dict()
        
        self.assertEqual(data['block_height'], 1)
        self.assertEqual(data['previous_hash'], "prev_hash")
        self.assertEqual(data['merkle_root'], "merkle_root")
        self.assertEqual(data['timestamp'], 12345)
        self.assertEqual(data['article_count'], 5)
        self.assertEqual(data['articles'], ['a1', 'a2', 'a3', 'a4', 'a5'])
        self.assertIn('block_hash', data)
    
    def test_block_from_dict(self):
        """Test creating block from dictionary."""
        data = {
            'block_height': 2,
            'previous_hash': "prev",
            'merkle_root': "merkle",
            'timestamp': 1000,
            'article_count': 3,
            'articles': ['x', 'y', 'z']
        }
        
        block = LocalBlock.from_dict(data)
        
        self.assertEqual(block.block_height, 2)
        self.assertEqual(block.previous_hash, "prev")
        self.assertEqual(block.merkle_root, "merkle")
        self.assertEqual(block.timestamp, 1000)
        self.assertEqual(block.article_count, 3)
        self.assertEqual(block.articles, ['x', 'y', 'z'])


class TestLocalHashChain(unittest.TestCase):
    """Tests for LocalHashChain class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_hash_chain.db"
        self.hash_chain = create_hash_chain(
            db_path=str(self.db_path),
            articles_per_block=10,
            time_per_block=3600  # 1 hour for testing
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.hash_chain.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_genesis_block_creation(self):
        """Test that genesis block is created on initialization."""
        blocks = self.hash_chain.get_all_blocks()
        
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].block_height, 0)
        self.assertEqual(blocks[0].previous_hash, "0" * 64)
    
    def test_add_article(self):
        """Test adding an article to the hash chain."""
        article_id = "test_article_1"
        content_hash = hashlib.sha256(b"test content").hexdigest()
        metadata_hash = hashlib.sha256(b"test metadata").hexdigest()
        source_hash = hashlib.sha256(b"test source").hexdigest()
        
        result = self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        self.assertEqual(result['article_id'], article_id)
        self.assertEqual(result['content_hash'], content_hash)
        self.assertEqual(result['metadata_hash'], metadata_hash)
        self.assertEqual(result['source_hash'], source_hash)
        self.assertEqual(result['block_height'], 0)  # Should be in genesis block
        self.assertEqual(result['position'], 0)
    
    def test_get_article_hashes(self):
        """Test retrieving article hashes."""
        article_id = "test_article_2"
        content_hash = hashlib.sha256(b"content 2").hexdigest()
        metadata_hash = hashlib.sha256(b"metadata 2").hexdigest()
        source_hash = hashlib.sha256(b"source 2").hexdigest()
        
        self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        hashes = self.hash_chain.get_article_hashes(article_id)
        
        self.assertIsNotNone(hashes)
        self.assertEqual(hashes['article_id'], article_id)
        self.assertEqual(hashes['content_hash'], content_hash)
        self.assertEqual(hashes['metadata_hash'], metadata_hash)
        self.assertEqual(hashes['source_hash'], source_hash)
    
    def test_get_article_block(self):
        """Test getting the block containing an article."""
        article_id = "test_article_3"
        content_hash = hashlib.sha256(b"content 3").hexdigest()
        metadata_hash = hashlib.sha256(b"metadata 3").hexdigest()
        source_hash = hashlib.sha256(b"source 3").hexdigest()
        
        self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        block_height = self.hash_chain.get_article_block(article_id)
        
        self.assertIsNotNone(block_height)
        self.assertEqual(block_height, 0)
    
    def test_get_merkle_proof(self):
        """Test generating a Merkle proof for an article."""
        # Add multiple articles to create a non-trivial Merkle tree
        for i in range(5):
            article_id = f"article_{i}"
            content_hash = hashlib.sha256(f"content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"source {i}".encode()).hexdigest()
            
            self.hash_chain.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Get proof for the middle article
        proof_data = self.hash_chain.get_merkle_proof("article_2")
        
        self.assertIsNotNone(proof_data)
        self.assertEqual(proof_data['article_id'], "article_2")
        self.assertIn('content_hash', proof_data)
        self.assertIn('metadata_hash', proof_data)
        self.assertIn('source_hash', proof_data)
        self.assertIn('block_height', proof_data)
        self.assertEqual(proof_data['position'], 2)
        self.assertIn('merkle_proof', proof_data)
        self.assertIn('merkle_root', proof_data)
        self.assertIn('block_hash', proof_data)
        self.assertIn('previous_block_hash', proof_data)
        
        # Verify the proof is a list
        self.assertIsInstance(proof_data['merkle_proof'], list)
    
    def test_verify_article_with_proof(self):
        """Test verifying an article using a Merkle proof."""
        # Add an article
        article_id = "verify_test_article"
        content_hash = hashlib.sha256(b"verify content").hexdigest()
        metadata_hash = hashlib.sha256(b"verify metadata").hexdigest()
        source_hash = hashlib.sha256(b"verify source").hexdigest()
        
        self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Get the proof
        proof_data = self.hash_chain.get_merkle_proof(article_id)
        
        # Verify using the proof
        is_valid = self.hash_chain.verify_article_with_proof(
            article_id,
            content_hash,
            metadata_hash,
            source_hash,
            proof_data['merkle_proof'],
            proof_data['merkle_root']
        )
        
        self.assertTrue(is_valid)
    
    def test_verify_block_chain_integrity(self):
        """Test verifying the integrity of the block chain."""
        # Add some articles
        for i in range(3):
            article_id = f"integrity_test_{i}"
            content_hash = hashlib.sha256(f"integrity content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"integrity metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"integrity source {i}".encode()).hexdigest()
            
            self.hash_chain.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Verify chain integrity
        is_valid = self.hash_chain.verify_block_chain_integrity()
        
        self.assertTrue(is_valid)
    
    def test_multiple_blocks(self):
        """Test that articles are organized into multiple blocks."""
        # Add more articles than fit in one block
        for i in range(15):  # More than articles_per_block (10)
            article_id = f"multi_block_{i}"
            content_hash = hashlib.sha256(f"multi content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"multi metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"multi source {i}".encode()).hexdigest()
            
            self.hash_chain.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Check that we have multiple blocks
        blocks = self.hash_chain.get_all_blocks()
        self.assertGreater(len(blocks), 1)
        
        # Check that articles are distributed across blocks
        block_0_articles = self.hash_chain.get_block(0)
        block_1_articles = self.hash_chain.get_block(1)
        
        self.assertIsNotNone(block_0_articles)
        self.assertIsNotNone(block_1_articles)
        self.assertEqual(len(block_0_articles.articles), 10)  # First block should be full
        self.assertEqual(len(block_1_articles.articles), 5)   # Second block should have remaining
    
    def test_get_block(self):
        """Test getting a specific block."""
        # Add some articles
        for i in range(3):
            article_id = f"block_test_{i}"
            content_hash = hashlib.sha256(f"block content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"block metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"block source {i}".encode()).hexdigest()
            
            self.hash_chain.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Get block 0
        block = self.hash_chain.get_block(0)
        
        self.assertIsNotNone(block)
        self.assertEqual(block.block_height, 0)
        self.assertEqual(len(block.articles), 3)
    
    def test_context_manager(self):
        """Test using hash chain as context manager."""
        with create_hash_chain(
            db_path=str(Path(self.temp_dir) / "context_test.db"),
            articles_per_block=5,
            time_per_block=3600
        ) as hash_chain:
            # Add an article
            article_id = "context_test_article"
            content_hash = hashlib.sha256(b"context content").hexdigest()
            metadata_hash = hashlib.sha256(b"context metadata").hexdigest()
            source_hash = hashlib.sha256(b"context source").hexdigest()
            
            hash_chain.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
            
            # Verify it was added
            hashes = hash_chain.get_article_hashes(article_id)
            self.assertIsNotNone(hashes)


class TestLocalHashChainEdgeCases(unittest.TestCase):
    """Edge case tests for LocalHashChain."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "edge_case_test.db"
        self.hash_chain = create_hash_chain(
            db_path=str(self.db_path),
            articles_per_block=5,
            time_per_block=3600
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.hash_chain.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_nonexistent_article(self):
        """Test handling of non-existent articles."""
        hashes = self.hash_chain.get_article_hashes("nonexistent")
        self.assertIsNone(hashes)
        
        block = self.hash_chain.get_article_block("nonexistent")
        self.assertIsNone(block)
        
        proof = self.hash_chain.get_merkle_proof("nonexistent")
        self.assertIsNone(proof)
    
    def test_nonexistent_block(self):
        """Test handling of non-existent blocks."""
        block = self.hash_chain.get_block(999)
        self.assertIsNone(block)
    
    def test_empty_hash_chain(self):
        """Test empty hash chain (only genesis block)."""
        blocks = self.hash_chain.get_all_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].article_count, 0)
    
    def test_verify_with_wrong_hash(self):
        """Test verification with wrong hash."""
        article_id = "wrong_hash_test"
        content_hash = hashlib.sha256(b"content").hexdigest()
        metadata_hash = hashlib.sha256(b"metadata").hexdigest()
        source_hash = hashlib.sha256(b"source").hexdigest()
        
        self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Get proof
        proof_data = self.hash_chain.get_merkle_proof(article_id)
        
        # Try to verify with wrong content hash
        is_valid = self.hash_chain.verify_article_with_proof(
            article_id,
            "wrong_hash",  # Wrong content hash
            metadata_hash,
            source_hash,
            proof_data['merkle_proof'],
            proof_data['merkle_root']
        )
        
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()
