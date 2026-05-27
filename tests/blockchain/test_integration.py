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
Integration Tests for Blockchain Module

Tests the integration of blockchain components with the rest of Open-Omniscience.

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

from src.blockchain import BlockchainService, get_blockchain_service, reset_blockchain_service
from src.blockchain.config.settings import BlockchainSettings
from src.main_pipeline import IngestedData


class TestBlockchainService(unittest.TestCase):
    """Tests for BlockchainService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_service.db"
        
        # Create settings
        from src.blockchain.config.settings import LocalChainSettings, AnchoringSettings
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=10,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=False,
                providers=[]
            )
        )
        
        # Create service
        self.service = BlockchainService(settings=self.settings)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.service.close()
        reset_blockchain_service()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_add_article(self):
        """Test adding an article through service."""
        article_id = "service_article_1"
        content_hash = hashlib.sha256(b"service content").hexdigest()
        metadata_hash = hashlib.sha256(b"service metadata").hexdigest()
        source_hash = hashlib.sha256(b"service source").hexdigest()
        
        result = self.service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        self.assertEqual(result['article_id'], article_id)
    
    def test_verify_article(self):
        """Test verifying an article through service."""
        article_id = "verify_service_article"
        content_hash = hashlib.sha256(b"verify content").hexdigest()
        metadata_hash = hashlib.sha256(b"verify metadata").hexdigest()
        source_hash = hashlib.sha256(b"verify source").hexdigest()
        
        self.service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        result = self.service.verify_article(article_id)
        
        self.assertTrue(result.verified)
        self.assertEqual(result.article_id, article_id)
    
    def test_get_article_verification_data(self):
        """Test getting verification data through service."""
        article_id = "data_service_article"
        content_hash = hashlib.sha256(b"data content").hexdigest()
        metadata_hash = hashlib.sha256(b"data metadata").hexdigest()
        source_hash = hashlib.sha256(b"data source").hexdigest()
        
        self.service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        data = self.service.get_article_verification_data(article_id)
        
        self.assertIsNotNone(data)
        self.assertEqual(data['article_id'], article_id)
        self.assertIn('merkle_proof', data)
    
    def test_get_merkle_proof(self):
        """Test getting Merkle proof through service."""
        article_id = "proof_service_article"
        content_hash = hashlib.sha256(b"proof content").hexdigest()
        metadata_hash = hashlib.sha256(b"proof metadata").hexdigest()
        source_hash = hashlib.sha256(b"proof source").hexdigest()
        
        self.service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
        
        proof = self.service.get_merkle_proof(article_id)
        
        self.assertIsNotNone(proof)
        self.assertIn('merkle_proof', proof)
    
    def test_context_manager(self):
        """Test using service as context manager."""
        with BlockchainService(settings=self.settings) as service:
            article_id = "context_service_article"
            content_hash = hashlib.sha256(b"context content").hexdigest()
            metadata_hash = hashlib.sha256(b"context metadata").hexdigest()
            source_hash = hashlib.sha256(b"context source").hexdigest()
            
            service.add_article(
                article_id, content_hash, metadata_hash, source_hash
            )
            
            result = service.verify_article(article_id)
            self.assertTrue(result.verified)


class TestGlobalBlockchainService(unittest.TestCase):
    """Tests for global blockchain service singleton."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_global.db"
        
        # Reset global service
        reset_blockchain_service()
        
        # Create settings
        from src.blockchain.config.settings import LocalChainSettings, AnchoringSettings
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=10,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=False,
                providers=[]
            )
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        reset_blockchain_service()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_get_blockchain_service_singleton(self):
        """Test that get_blockchain_service returns a singleton."""
        # Get service twice
        service1 = get_blockchain_service()
        service2 = get_blockchain_service()
        
        # Should be the same instance
        self.assertIs(service1, service2)
    
    def test_reset_blockchain_service(self):
        """Test resetting the global service."""
        # Get service
        service1 = get_blockchain_service()
        
        # Reset
        reset_blockchain_service()
        
        # Get new service
        service2 = get_blockchain_service()
        
        # Should be different instances
        self.assertIsNot(service1, service2)


class TestPipelineIntegration(unittest.TestCase):
    """Tests for blockchain integration with main pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_pipeline.db"
        
        # Reset global service
        reset_blockchain_service()
        
        # Create settings
        from src.blockchain.config.settings import LocalChainSettings, AnchoringSettings
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=10,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=False,
                providers=[]
            )
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        reset_blockchain_service()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_ingested_data_hashes(self):
        """Test that IngestedData has proper hash properties."""
        content = "Test content"
        raw_content = content.encode('utf-8')
        
        ingested_data = IngestedData(
            url="http://example.com",
            content=content,
            raw_content=raw_content,
            headers={"Content-Type": "text/html"},
            timestamp=1234567890,
            source_type="web",
            metadata={"status_code": 200}
        )
        
        # Test content_hash property
        expected_hash = hashlib.sha256(raw_content).hexdigest()
        self.assertEqual(ingested_data.content_hash, expected_hash)
        
        # Test domain property
        self.assertEqual(ingested_data.domain, "example.com")
    
    def test_ingested_data_to_dict(self):
        """Test IngestedData to_dict method."""
        ingested_data = IngestedData(
            url="http://example.com/test",
            content="Test content",
            raw_content=b"Test content",
            headers={"Content-Type": "text/html"},
            timestamp=1234567890,
            source_type="web",
            metadata={"status_code": 200}
        )
        
        data = ingested_data.to_dict()
        
        self.assertEqual(data['url'], "http://example.com/test")
        self.assertEqual(data['content'], "Test content")
        self.assertIn('content_hash', data)
        self.assertEqual(data['source_type'], "web")


class TestEndToEndWorkflow(unittest.TestCase):
    """End-to-end workflow tests."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_e2e.db"
        
        # Reset global service
        reset_blockchain_service()
        
        # Create settings
        from src.blockchain.config.settings import LocalChainSettings, AnchoringSettings
        self.settings = BlockchainSettings(
            enabled=True,
            local_chain=LocalChainSettings(
                enabled=True,
                db_path=str(self.db_path),
                articles_per_block=10,
                time_per_block=3600
            ),
            anchoring=AnchoringSettings(
                enabled=False,
                providers=[]
            )
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        reset_blockchain_service()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_complete_workflow(self):
        """Test complete workflow from ingestion to verification."""
        # Simulate ingestion
        url = "http://example.com/article1"
        content = "This is test article content"
        raw_content = content.encode('utf-8')
        timestamp = int(time.time())
        
        # Create ingested data
        ingested_data = IngestedData(
            url=url,
            content=content,
            raw_content=raw_content,
            headers={"Content-Type": "text/html"},
            timestamp=timestamp,
            source_type="web",
            metadata={"status_code": 200, "content_type": "text/html"}
        )
        
        # Compute hashes (as would be done in _add_to_blockchain)
        content_hash = ingested_data.content_hash
        metadata_str = json.dumps(ingested_data.metadata, sort_keys=True)
        metadata_hash = hashlib.sha256(metadata_str.encode()).hexdigest()
        source_hash = hashlib.sha256(f"{url}{timestamp}".encode()).hexdigest()
        
        # Create service with test settings
        from src.blockchain import BlockchainService
        service = BlockchainService(settings=self.settings)
        
        # Add to blockchain
        service.add_article(
            article_id="test_article_1",
            content_hash=content_hash,
            metadata_hash=metadata_hash,
            source_hash=source_hash
        )
        
        # Verify the article
        result = service.verify_article(
            "test_article_1",
            expected_content_hash=content_hash,
            expected_metadata_hash=metadata_hash,
            expected_source_hash=source_hash
        )
        
        self.assertTrue(result.verified)
        self.assertEqual(result.article_id, "test_article_1")
        
        # Get verification data for third-party verification
        verification_data = service.get_article_verification_data("test_article_1")
        
        self.assertIsNotNone(verification_data)
        self.assertEqual(verification_data['content_hash'], content_hash)
        self.assertEqual(verification_data['metadata_hash'], metadata_hash)
        self.assertEqual(verification_data['source_hash'], source_hash)
        
        # Verify using the proof
        is_valid = service.verify_article_with_proof(
            "test_article_1",
            content_hash,
            metadata_hash,
            source_hash,
            verification_data['merkle_proof'],
            verification_data['merkle_root']
        )
        
        self.assertTrue(is_valid)
        
        # Clean up
        service.close()


if __name__ == "__main__":
    import time
    unittest.main()
