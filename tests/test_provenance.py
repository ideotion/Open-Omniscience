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
Tests for Cryptographic Provenance Ledger

Comprehensive test suite for the SQLite-based provenance ledger
used in Open-Omniscience Pillar 4 cryptographic provenance.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

# Add the src directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto.merkle_tree import MerkleTree
from crypto.provenance import DataProvenance, ProvenanceLedger


class TestDataProvenance(unittest.TestCase):
    """Test cases for DataProvenance class."""
    
    def test_provenance_creation(self):
        """Test creation of DataProvenance object."""
        data = {"id": 1, "content": "test data"}
        provenance = DataProvenance("test_id", data, "test_source")
        
        self.assertEqual(provenance.data_id, "test_id")
        self.assertEqual(provenance.source, "test_source")
        self.assertIsNotNone(provenance.original_hash)
        self.assertIsNotNone(provenance.current_hash)
        self.assertEqual(provenance.original_hash, provenance.current_hash)
        self.assertIsNotNone(provenance.timestamp)
    
    def test_provenance_hash_consistency(self):
        """Test that same data produces same hash."""
        data = "test data"
        prov1 = DataProvenance("id1", data, "source")
        prov2 = DataProvenance("id2", data, "source")
        
        self.assertEqual(prov1.original_hash, prov2.original_hash)
    
    def test_provenance_hash_different_data(self):
        """Test that different data produces different hashes."""
        prov1 = DataProvenance("id1", "data1", "source")
        prov2 = DataProvenance("id2", "data2", "source")
        
        self.assertNotEqual(prov1.original_hash, prov2.original_hash)
    
    def test_provenance_with_metadata(self):
        """Test provenance with metadata."""
        metadata = {"type": "document", "category": "legal"}
        provenance = DataProvenance("id", "data", "source", metadata)
        
        self.assertEqual(provenance.metadata, metadata)
    
    def test_update_hash(self):
        """Test updating hash with new data."""
        provenance = DataProvenance("id", "original data", "source")
        original_hash = provenance.current_hash
        
        new_hash = provenance.update_hash("new data")
        
        self.assertNotEqual(original_hash, new_hash)
        self.assertEqual(provenance.current_hash, new_hash)
    
    def test_is_unchanged(self):
        """Test is_unchanged method."""
        provenance = DataProvenance("id", "data", "source")
        
        self.assertTrue(provenance.is_unchanged())
        
        provenance.update_hash("new data")
        self.assertFalse(provenance.is_unchanged())
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        metadata = {"key": "value"}
        provenance = DataProvenance("id", "data", "source", metadata)
        
        data_dict = provenance.to_dict()
        
        self.assertIn('data_id', data_dict)
        self.assertIn('original_hash', data_dict)
        self.assertIn('current_hash', data_dict)
        self.assertIn('timestamp', data_dict)
        self.assertIn('source', data_dict)
        self.assertIn('metadata', data_dict)
        self.assertIn('is_unchanged', data_dict)
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        original = DataProvenance("id", "data", "source", {"key": "value"})
        data_dict = original.to_dict()
        
        # Remove timestamp for comparison (it will be different)
        data_dict_copy = data_dict.copy()
        
        restored = DataProvenance.from_dict(data_dict)
        
        self.assertEqual(restored.data_id, original.data_id)
        self.assertEqual(restored.original_hash, original.original_hash)
        self.assertEqual(restored.current_hash, original.current_hash)
        self.assertEqual(restored.source, original.source)
        self.assertEqual(restored.metadata, original.metadata)


class TestProvenanceLedger(unittest.TestCase):
    """Test cases for ProvenanceLedger class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_ledger.db")
        self.ledger = ProvenanceLedger(self.db_path)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.ledger.close()
        shutil.rmtree(self.temp_dir)
    
    def test_ledger_creation(self):
        """Test ledger creation and initialization."""
        self.assertIsNotNone(self.ledger.connection)
        self.assertTrue(os.path.exists(self.db_path))
    
    def test_add_data(self):
        """Test adding individual data entries."""
        data = {"id": 1, "content": "test data"}
        provenance = self.ledger.add_data("test_id", data, "test_source")
        
        self.assertIsNotNone(provenance)
        self.assertEqual(provenance.data_id, "test_id")
        self.assertEqual(provenance.source, "test_source")
    
    def test_add_data_with_metadata(self):
        """Test adding data with metadata."""
        metadata = {"type": "document", "category": "legal"}
        provenance = self.ledger.add_data(
            "test_id", "data", "source", metadata
        )
        
        self.assertEqual(provenance.metadata, metadata)
    
    def test_get_data_provenance(self):
        """Test retrieving data provenance."""
        # Add data first
        self.ledger.add_data("test_id", "test data", "test_source")
        
        # Retrieve it
        provenance = self.ledger.get_data_provenance("test_id")
        
        self.assertIsNotNone(provenance)
        self.assertEqual(provenance.data_id, "test_id")
        self.assertEqual(provenance.source, "test_source")
    
    def test_get_nonexistent_data(self):
        """Test retrieving non-existent data returns None."""
        provenance = self.ledger.get_data_provenance("nonexistent")
        self.assertIsNone(provenance)
    
    def test_add_data_batch(self):
        """Test adding a batch of data with Merkle tree."""
        data_items = [
            ("id1", "data1", "source1", {"type": "doc"}),
            ("id2", "data2", "source2", {"type": "doc"}),
            ("id3", "data3", "source3", {"type": "doc"})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Test batch")
        
        self.assertIsNotNone(batch_id)
        self.assertIsInstance(batch_id, int)
    
    def test_get_merkle_tree(self):
        """Test retrieving Merkle tree information."""
        data_items = [
            ("id1", "data1", "source1", {}),
            ("id2", "data2", "source2", {})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Test batch")
        tree_info = self.ledger.get_merkle_tree(batch_id)
        
        self.assertIsNotNone(tree_info)
        self.assertIn('id', tree_info)
        self.assertIn('root_hash', tree_info)
        self.assertIn('num_leaves', tree_info)
        self.assertIn('height', tree_info)
        self.assertEqual(tree_info['num_leaves'], 2)
    
    def test_get_merkle_tree_nonexistent(self):
        """Test retrieving non-existent Merkle tree returns None."""
        tree_info = self.ledger.get_merkle_tree(999)
        self.assertIsNone(tree_info)
    
    def test_get_data_by_merkle_tree(self):
        """Test retrieving data entries by Merkle tree ID."""
        data_items = [
            ("id1", "data1", "source1", {}),
            ("id2", "data2", "source2", {})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Test batch")
        data_entries = self.ledger.get_data_by_merkle_tree(batch_id)
        
        self.assertEqual(len(data_entries), 2)
        self.assertEqual(data_entries[0].data_id, "id1")
        self.assertEqual(data_entries[1].data_id, "id2")
    
    def test_verify_data_integrity(self):
        """Test data integrity verification."""
        # Add data
        self.ledger.add_data("test_id", "test data", "source")
        
        # Get provenance to get the expected hash
        provenance = self.ledger.get_data_provenance("test_id")
        
        # Verify with correct hash
        is_valid = self.ledger.verify_data_integrity("test_id", provenance.original_hash)
        self.assertTrue(is_valid)
        
        # Verify with wrong hash
        is_valid = self.ledger.verify_data_integrity("test_id", "0" * 64)
        self.assertFalse(is_valid)
    
    def test_verify_data_integrity_nonexistent(self):
        """Test verifying non-existent data returns False."""
        is_valid = self.ledger.verify_data_integrity("nonexistent", "some_hash")
        self.assertFalse(is_valid)
    
    def test_verify_merkle_tree_integrity(self):
        """Test Merkle tree integrity verification."""
        data_items = [
            ("id1", "data1", "source1", {}),
            ("id2", "data2", "source2", {}),
            ("id3", "data3", "source3", {})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Test batch")
        
        # Verify integrity (should be valid)
        is_valid = self.ledger.verify_merkle_tree_integrity(batch_id)
        self.assertTrue(is_valid)
    
    def test_record_custody_change(self):
        """Test recording custody changes."""
        # Add data first
        self.ledger.add_data("test_id", "test data", "source")
        
        # Record custody change
        success = self.ledger.record_custody_change(
            "test_id", "accessed", "user123"
        )
        
        self.assertTrue(success)
    
    def test_record_custody_change_with_new_data(self):
        """Test recording custody change with new data."""
        # Add data first
        self.ledger.add_data("test_id", "original data", "source")
        
        # Record custody change with new data
        success = self.ledger.record_custody_change(
            "test_id", "modified", "user456",
            new_data="modified data"
        )
        
        self.assertTrue(success)
        
        # Verify the data was updated
        provenance = self.ledger.get_data_provenance("test_id")
        self.assertNotEqual(provenance.original_hash, provenance.current_hash)
    
    def test_record_custody_change_nonexistent_data(self):
        """Test recording custody change for non-existent data returns False."""
        success = self.ledger.record_custody_change(
            "nonexistent", "accessed", "user123"
        )
        
        self.assertFalse(success)
    
    def test_get_custody_chain(self):
        """Test retrieving custody chain."""
        # Add data
        self.ledger.add_data("test_id", "test data", "source")
        
        # Record some custody changes
        self.ledger.record_custody_change("test_id", "accessed", "user1")
        self.ledger.record_custody_change("test_id", "modified", "user2")
        self.ledger.record_custody_change("test_id", "copied", "user3")
        
        # Get custody chain
        chain = self.ledger.get_custody_chain("test_id")
        
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[0]['action'], "accessed")
        self.assertEqual(chain[1]['action'], "modified")
        self.assertEqual(chain[2]['action'], "copied")
    
    def test_get_custody_chain_empty(self):
        """Test getting custody chain for data with no changes."""
        # Add data but don't record any changes
        self.ledger.add_data("test_id", "test data", "source")
        
        chain = self.ledger.get_custody_chain("test_id")
        self.assertEqual(len(chain), 0)
    
    def test_get_custody_chain_nonexistent(self):
        """Test getting custody chain for non-existent data."""
        chain = self.ledger.get_custody_chain("nonexistent")
        self.assertEqual(len(chain), 0)
    
    def test_get_all_data_entries(self):
        """Test retrieving all data entries."""
        # Add some data
        self.ledger.add_data("id1", "data1", "source1")
        self.ledger.add_data("id2", "data2", "source2")
        self.ledger.add_data("id3", "data3", "source3")
        
        entries = self.ledger.get_all_data_entries()
        
        self.assertEqual(len(entries), 3)
    
    def test_get_all_data_entries_with_limit(self):
        """Test retrieving data entries with limit."""
        # Add some data
        for i in range(10):
            self.ledger.add_data(f"id{i}", f"data{i}", f"source{i}")
        
        entries = self.ledger.get_all_data_entries(limit=5)
        
        self.assertEqual(len(entries), 5)
    
    def test_get_all_merkle_trees(self):
        """Test retrieving all Merkle trees."""
        # Add some batches
        self.ledger.add_data_batch([
            ("id1", "data1", "source1", {}),
            ("id2", "data2", "source2", {})
        ], "Batch 1")
        
        self.ledger.add_data_batch([
            ("id3", "data3", "source3", {}),
            ("id4", "data4", "source4", {})
        ], "Batch 2")
        
        trees = self.ledger.get_all_merkle_trees()
        
        self.assertEqual(len(trees), 2)
    
    def test_get_all_merkle_trees_with_limit(self):
        """Test retrieving Merkle trees with limit."""
        # Add some batches
        for i in range(5):
            self.ledger.add_data_batch([
                (f"id{i}_1", f"data{i}_1", f"source{i}", {}),
                (f"id{i}_2", f"data{i}_2", f"source{i}", {})
            ], f"Batch {i}")
        
        trees = self.ledger.get_all_merkle_trees(limit=3)
        
        self.assertEqual(len(trees), 3)
    
    def test_context_manager(self):
        """Test using ledger as context manager."""
        with ProvenanceLedger(self.db_path) as ledger:
            ledger.add_data("test_id", "test data", "source")
            entries = ledger.get_all_data_entries()
            self.assertEqual(len(entries), 1)
        
        # Connection should be closed after context
        self.assertIsNone(ledger.connection)
    
    def test_close(self):
        """Test closing the ledger."""
        self.ledger.close()
        self.assertIsNone(self.ledger.connection)


class TestIntegration(unittest.TestCase):
    """Integration tests for provenance ledger."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "integration_test.db")
        self.ledger = ProvenanceLedger(self.db_path)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.ledger.close()
        shutil.rmtree(self.temp_dir)
    
    def test_complete_workflow(self):
        """Test a complete workflow from data addition to verification."""
        # Step 1: Add data batch
        data_items = [
            ("doc1", {"id": 1, "content": "Document A", "timestamp": "2024-01-01"}, "source_a", {"type": "document"}),
            ("doc2", {"id": 2, "content": "Document B", "timestamp": "2024-01-02"}, "source_b", {"type": "document"}),
            ("doc3", {"id": 3, "content": "Document C", "timestamp": "2024-01-03"}, "source_c", {"type": "document"})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Test workflow batch")
        
        # Step 2: Verify Merkle tree integrity
        is_valid = self.ledger.verify_merkle_tree_integrity(batch_id)
        self.assertTrue(is_valid)
        
        # Step 3: Get individual data provenance
        provenance = self.ledger.get_data_provenance("doc1")
        self.assertIsNotNone(provenance)
        self.assertTrue(provenance.is_unchanged())
        
        # Step 4: Record custody changes
        self.ledger.record_custody_change("doc1", "accessed", "user1")
        self.ledger.record_custody_change("doc1", "modified", "user2", 
                                         {"id": 1, "content": "Modified Document A", "timestamp": "2024-01-01"})
        
        # Step 5: Verify custody chain
        chain = self.ledger.get_custody_chain("doc1")
        self.assertEqual(len(chain), 2)
        
        # Step 6: Verify data integrity after modification
        current_provenance = self.ledger.get_data_provenance("doc1")
        self.assertFalse(current_provenance.is_unchanged())
        
        # Step 7: Verify original hash is still valid for original data
        original_data = {"id": 1, "content": "Document A", "timestamp": "2024-01-01"}
        is_valid = self.ledger.verify_data_integrity("doc1", provenance.original_hash)
        self.assertFalse(is_valid)  # Current data is different from original
        
        # Step 8: Verify current hash is valid
        is_valid = self.ledger.verify_data_integrity("doc1", current_provenance.current_hash)
        self.assertTrue(is_valid)
    
    def test_cross_verification(self):
        """Test cross-verification between Merkle tree and ledger."""
        # Add data batch
        data_items = [
            ("id1", "data1", "source1", {}),
            ("id2", "data2", "source2", {}),
            ("id3", "data3", "source3", {})
        ]
        
        batch_id = self.ledger.add_data_batch(data_items, "Cross verification test")
        
        # Get Merkle tree info
        tree_info = self.ledger.get_merkle_tree(batch_id)
        
        # Get data entries - we need to retrieve the actual data from the database
        cursor = self.ledger.connection.cursor()
        cursor.execute("""
            SELECT data_json FROM data_entries WHERE merkle_tree_id = ?
        """, (batch_id,))
        
        data_list = []
        for row in cursor.fetchall():
            if row[0]:
                data_list.append(json.loads(row[0]))
        
        # Manually create Merkle tree from data
        manual_tree = MerkleTree(data_list)
        
        # Root hashes should match
        self.assertEqual(manual_tree.root_hash, tree_info['root_hash'])


class TestErrorConditions(unittest.TestCase):
    """Test error conditions and edge cases."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "error_test.db")
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
    
    def test_nonexistent_database(self):
        """Test opening non-existent database with create_if_not_exists=False."""
        with self.assertRaises(FileNotFoundError):
            ProvenanceLedger("/nonexistent/path/db.db", create_if_not_exists=False)
    
    def test_empty_batch(self):
        """Test adding empty batch raises ValueError."""
        ledger = ProvenanceLedger(self.db_path)
        
        with self.assertRaises(ValueError):
            ledger.add_data_batch([], "Empty batch")
        
        ledger.close()
    
    def test_duplicate_data_id(self):
        """Test adding data with duplicate ID."""
        ledger = ProvenanceLedger(self.db_path)
        
        # Add first data
        ledger.add_data("duplicate_id", "data1", "source1")
        
        # Try to add second data with same ID (should raise IntegrityError)
        with self.assertRaises(sqlite3.IntegrityError):
            ledger.add_data("duplicate_id", "data2", "source2")
        
        ledger.close()


if __name__ == "__main__":
    unittest.main()