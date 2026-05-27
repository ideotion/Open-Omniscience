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
Tests for Anchor Service Implementation

Tests the anchor service for per-article verification and blockchain anchoring.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import unittest
import tempfile
import shutil
import hashlib
import json
from pathlib import Path

from src.blockchain.core.hash_chain import create_hash_chain
from src.blockchain.core.anchor_service import AnchorService, VerificationResult
from src.blockchain.config.settings import BlockchainSettings, LocalChainSettings, AnchoringSettings


class TestAnchorService(unittest.TestCase):
    """Tests for AnchorService class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_anchor.db"
        
        # Create hash chain
        self.hash_chain = create_hash_chain(
            db_path=str(self.db_path),
            articles_per_block=10,
            time_per_block=3600
        )
        
        # Create settings
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=10,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=False,  # Disable anchoring for most tests
                providers=[]
            )
        )
        
        # Create anchor service
        self.anchor_service = AnchorService(
            hash_chain=self.hash_chain,
            settings=self.settings
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.anchor_service.close()
        self.hash_chain.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_add_article(self):
        """Test adding an article through anchor service."""
        article_id = "service_test_article"
        content_hash = hashlib.sha256(b"service content").hexdigest()
        metadata_hash = hashlib.sha256(b"service metadata").hexdigest()
        source_hash = hashlib.sha256(b"service source").hexdigest()
        
        result = self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        self.assertEqual(result['article_id'], article_id)
        self.assertEqual(result['content_hash'], content_hash)
    
    def test_verify_article_basic(self):
        """Test basic article verification."""
        article_id = "verify_service_test"
        content_hash = hashlib.sha256(b"verify service content").hexdigest()
        metadata_hash = hashlib.sha256(b"verify service metadata").hexdigest()
        source_hash = hashlib.sha256(b"verify service source").hexdigest()
        
        self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Verify without expected hashes (just check existence)
        result = self.anchor_service.verify_article(article_id)
        
        self.assertIsInstance(result, VerificationResult)
        self.assertEqual(result.article_id, article_id)
        self.assertTrue(result.verified)
    
    def test_verify_article_with_expected_hashes(self):
        """Test article verification with expected hashes."""
        article_id = "verify_with_hashes_test"
        content_hash = hashlib.sha256(b"content for hash test").hexdigest()
        metadata_hash = hashlib.sha256(b"metadata for hash test").hexdigest()
        source_hash = hashlib.sha256(b"source for hash test").hexdigest()
        
        self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Verify with correct hashes
        result = self.anchor_service.verify_article(
            article_id,
            expected_content_hash=content_hash,
            expected_metadata_hash=metadata_hash,
            expected_source_hash=source_hash
        )
        
        self.assertTrue(result.verified)
        self.assertIn('content_hash_match', result.local_verification)
        self.assertTrue(result.local_verification['content_hash_match'])
        self.assertIn('metadata_hash_match', result.local_verification)
        self.assertTrue(result.local_verification['metadata_hash_match'])
        self.assertIn('source_hash_match', result.local_verification)
        self.assertTrue(result.local_verification['source_hash_match'])
    
    def test_verify_article_with_wrong_hash(self):
        """Test article verification with wrong hash."""
        article_id = "wrong_hash_service_test"
        content_hash = hashlib.sha256(b"correct content").hexdigest()
        metadata_hash = hashlib.sha256(b"correct metadata").hexdigest()
        source_hash = hashlib.sha256(b"correct source").hexdigest()
        
        self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Verify with wrong content hash
        result = self.anchor_service.verify_article(
            article_id,
            expected_content_hash="wrong_hash",
            expected_metadata_hash=metadata_hash,
            expected_source_hash=source_hash
        )
        
        self.assertFalse(result.verified)
        self.assertIn('content_hash_match', result.local_verification)
        self.assertFalse(result.local_verification['content_hash_match'])
    
    def test_verify_nonexistent_article(self):
        """Test verification of non-existent article."""
        result = self.anchor_service.verify_article("nonexistent_article")
        
        self.assertFalse(result.verified)
        self.assertIn('article_exists', result.local_verification)
        self.assertFalse(result.local_verification['article_exists'])
    
    def test_get_article_verification_data(self):
        """Test getting verification data for an article."""
        article_id = "verification_data_test"
        content_hash = hashlib.sha256(b"data content").hexdigest()
        metadata_hash = hashlib.sha256(b"data metadata").hexdigest()
        source_hash = hashlib.sha256(b"data source").hexdigest()
        
        self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        data = self.anchor_service.get_article_verification_data(article_id)
        
        self.assertIsNotNone(data)
        self.assertEqual(data['article_id'], article_id)
        self.assertEqual(data['content_hash'], content_hash)
        self.assertEqual(data['metadata_hash'], metadata_hash)
        self.assertEqual(data['source_hash'], source_hash)
        self.assertIn('merkle_proof', data)
        self.assertIn('merkle_root', data)
        self.assertIn('block_hash', data)
        self.assertIn('previous_block_hash', data)
    
    def test_verify_article_with_proof(self):
        """Test verifying article with provided proof."""
        article_id = "proof_verify_test"
        content_hash = hashlib.sha256(b"proof content").hexdigest()
        metadata_hash = hashlib.sha256(b"proof metadata").hexdigest()
        source_hash = hashlib.sha256(b"proof source").hexdigest()
        
        self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        # Get verification data
        data = self.anchor_service.get_article_verification_data(article_id)
        
        # Verify using the proof
        is_valid = self.anchor_service.verify_article_with_proof(
            article_id,
            content_hash,
            metadata_hash,
            source_hash,
            data['merkle_proof'],
            data['merkle_root']
        )
        
        self.assertTrue(is_valid)
    
    def test_verification_result_to_dict(self):
        """Test converting VerificationResult to dictionary."""
        result = VerificationResult(
            article_id="test_article",
            verified=True,
            local_verification={'content_hash_match': True},
            blockchain_verifications={'local': {'verified': True}},
            merkle_proof=[{'hash': 'abc', 'is_right_sibling': True}],
            block_height=0,
            position=0,
            warnings=[]
        )
        
        data = result.to_dict()
        
        self.assertEqual(data['article_id'], "test_article")
        self.assertTrue(data['verified'])
        self.assertEqual(data['local_verification'], {'content_hash_match': True})
        self.assertEqual(data['blockchain_verifications'], {'local': {'verified': True}})
        self.assertEqual(data['block_height'], 0)
        self.assertEqual(data['position'], 0)


class TestAnchorServiceWithLocalProvider(unittest.TestCase):
    """Tests for AnchorService with LocalProvider."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_anchor_local.db"
        self.anchors_db_path = Path(self.temp_dir) / "test_anchors.db"
        
        # Create hash chain
        self.hash_chain = create_hash_chain(
            db_path=str(self.db_path),
            articles_per_block=5,
            time_per_block=3600
        )
        
        # Create settings with local provider
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=5,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=True,
                providers=['local']
            )
        )
        
        # Create anchor service
        self.anchor_service = AnchorService(
            hash_chain=self.hash_chain,
            settings=self.settings
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.anchor_service.close()
        self.hash_chain.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_anchor_current_block(self):
        """Test anchoring the current block."""
        # Add some articles
        for i in range(3):
            article_id = f"anchor_test_{i}"
            content_hash = hashlib.sha256(f"anchor content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"anchor metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"anchor source {i}".encode()).hexdigest()
            
            self.anchor_service.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Anchor current block
        result = self.anchor_service.anchor_current_block()
        
        self.assertIn('local', result)
        self.assertTrue(result['local']['success'])
        self.assertIn('transaction_hash', result['local'])
    
    def test_get_anchors(self):
        """Test getting all anchors."""
        # Add and anchor some articles
        for i in range(3):
            article_id = f"get_anchors_test_{i}"
            content_hash = hashlib.sha256(f"get anchors content {i}".encode()).hexdigest()
            metadata_hash = hashlib.sha256(f"get anchors metadata {i}".encode()).hexdigest()
            source_hash = hashlib.sha256(f"get anchors source {i}".encode()).hexdigest()
            
            self.anchor_service.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
        
        # Anchor current block
        self.anchor_service.anchor_current_block()
        
        # Get anchors
        anchors = self.anchor_service.get_anchors()
        
        self.assertIsInstance(anchors, list)
        self.assertGreater(len(anchors), 0)
        
        # Check that we have local anchors
        local_anchors = [a for a in anchors if a.get('provider') == 'local']
        self.assertGreater(len(local_anchors), 0)


if __name__ == "__main__":
    unittest.main()
