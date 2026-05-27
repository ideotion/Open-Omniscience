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
Tests for Blockchain Providers

Tests the various blockchain provider implementations.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import unittest
import tempfile
import shutil
import hashlib
import json
from pathlib import Path

from src.blockchain.providers import (
    get_provider, register_provider, get_available_providers,
    LocalProvider, BaseBlockchainProvider
)


class TestProviderRegistry(unittest.TestCase):
    """Tests for provider registry functions."""
    
    def test_get_available_providers(self):
        """Test getting list of available providers."""
        providers = get_available_providers()
        
        self.assertIsInstance(providers, list)
        self.assertIn('local', providers)
        self.assertIn('ethereum', providers)
        self.assertIn('ipfs', providers)
        self.assertIn('arweave', providers)
    
    def test_get_provider_local(self):
        """Test getting local provider."""
        provider = get_provider('local')
        
        self.assertIsInstance(provider, LocalProvider)
    
    def test_get_provider_invalid(self):
        """Test getting invalid provider."""
        with self.assertRaises(ValueError):
            get_provider('invalid_provider')
    
    def test_register_provider(self):
        """Test registering a custom provider."""
        
        class CustomProvider(BaseBlockchainProvider):
            def anchor_hash(self, merkle_root, metadata):
                return "custom_tx_hash"
            
            def verify_anchor(self, merkle_root, block_height=None):
                return True
            
            def get_anchor_data(self, transaction_hash):
                return {"custom": "data"}
            
            def get_all_anchors(self):
                return []
        
        # Register the custom provider
        register_provider('custom', CustomProvider)
        
        # Get the custom provider
        provider = get_provider('custom')
        
        self.assertIsInstance(provider, CustomProvider)


class TestLocalProvider(unittest.TestCase):
    """Tests for LocalProvider."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_local_provider.db"
        self.provider = LocalProvider(db_path=str(self.db_path))
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.provider.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_anchor_hash(self):
        """Test anchoring a hash."""
        merkle_root = hashlib.sha256(b"test merkle root").hexdigest()
        metadata = {
            'block_height': 0,
            'article_count': 10,
            'timestamp': 1234567890
        }
        
        tx_hash = self.provider.anchor_hash(merkle_root, metadata)
        
        self.assertIsNotNone(tx_hash)
        self.assertEqual(len(tx_hash), 64)  # SHA-256 hash length
    
    def test_verify_anchor(self):
        """Test verifying an anchor."""
        merkle_root = hashlib.sha256(b"verify merkle root").hexdigest()
        metadata = {
            'block_height': 1,
            'article_count': 5
        }
        
        # Anchor the hash
        tx_hash = self.provider.anchor_hash(merkle_root, metadata)
        
        # Verify it exists
        is_valid = self.provider.verify_anchor(merkle_root, block_height=1)
        
        self.assertTrue(is_valid)
    
    def test_verify_nonexistent_anchor(self):
        """Test verifying a non-existent anchor."""
        is_valid = self.provider.verify_anchor("nonexistent_merkle_root")
        
        self.assertFalse(is_valid)
    
    def test_get_anchor_data(self):
        """Test getting anchor data."""
        merkle_root = hashlib.sha256(b"get anchor data").hexdigest()
        metadata = {
            'block_height': 2,
            'article_count': 8,
            'timestamp': 1234567890,
            'block_hash': 'block_hash_value',
            'previous_block_hash': 'prev_block_hash_value'
        }
        
        # Anchor the hash
        tx_hash = self.provider.anchor_hash(merkle_root, metadata)
        
        # Get the anchor data
        anchor_data = self.provider.get_anchor_data(tx_hash)
        
        self.assertIsNotNone(anchor_data)
        self.assertEqual(anchor_data['transaction_hash'], tx_hash)
        self.assertEqual(anchor_data['merkle_root'], merkle_root)
        self.assertEqual(anchor_data['block_height'], 2)
        self.assertEqual(anchor_data['article_count'], 8)
    
    def test_get_all_anchors(self):
        """Test getting all anchors."""
        # Anchor multiple hashes
        for i in range(3):
            merkle_root = hashlib.sha256(f"all anchors {i}".encode()).hexdigest()
            metadata = {
                'block_height': i,
                'article_count': i * 10
            }
            self.provider.anchor_hash(merkle_root, metadata)
        
        # Get all anchors
        anchors = self.provider.get_all_anchors()
        
        self.assertIsInstance(anchors, list)
        self.assertEqual(len(anchors), 3)
    
    def test_context_manager(self):
        """Test using provider as context manager."""
        with LocalProvider(db_path=str(Path(self.temp_dir) / "context_test.db")) as provider:
            merkle_root = hashlib.sha256(b"context test").hexdigest()
            metadata = {'block_height': 0}
            
            tx_hash = provider.anchor_hash(merkle_root, metadata)
            
            self.assertIsNotNone(tx_hash)
            self.assertTrue(provider.verify_anchor(merkle_root))


class TestProviderInterface(unittest.TestCase):
    """Tests for BaseBlockchainProvider interface."""
    
    def test_abstract_methods(self):
        """Test that abstract methods are properly defined."""
        # We can't instantiate BaseBlockchainProvider directly
        # but we can check that it has the required methods
        
        self.assertTrue(hasattr(BaseBlockchainProvider, 'anchor_hash'))
        self.assertTrue(hasattr(BaseBlockchainProvider, 'verify_anchor'))
        self.assertTrue(hasattr(BaseBlockchainProvider, 'get_anchor_data'))
        self.assertTrue(hasattr(BaseBlockchainProvider, 'get_all_anchors'))
        self.assertTrue(hasattr(BaseBlockchainProvider, 'close'))


if __name__ == "__main__":
    unittest.main()
