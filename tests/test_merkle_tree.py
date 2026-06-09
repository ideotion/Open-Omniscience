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
Tests for Merkle Tree Implementation

Comprehensive test suite for the SHA-256 Merkle tree implementation
used in Open-Omniscience Pillar 4 cryptographic provenance.
"""

import hashlib
import os
import sys
import unittest

# Add the src directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from crypto.merkle_tree import MerkleNode, MerkleTree, compute_merkle_root, verify_data_integrity


class TestMerkleNode(unittest.TestCase):
    """Test cases for MerkleNode class."""
    
    def test_leaf_node_creation(self):
        """Test creation of leaf nodes with data."""
        data = {"id": 1, "content": "test"}
        node = MerkleNode(data)
        
        self.assertTrue(node.is_leaf)
        self.assertEqual(node.data, data)
        self.assertIsNotNone(node.hash_value)
        self.assertEqual(len(node.hash_value), 64)  # SHA-256 hex length
    
    def test_leaf_node_hash_consistency(self):
        """Test that leaf nodes with same data produce same hash."""
        data = "test data"
        node1 = MerkleNode(data)
        node2 = MerkleNode(data)
        
        self.assertEqual(node1.hash_value, node2.hash_value)
    
    def test_leaf_node_hash_different_data(self):
        """Test that different data produces different hashes."""
        node1 = MerkleNode("data1")
        node2 = MerkleNode("data2")
        
        self.assertNotEqual(node1.hash_value, node2.hash_value)
    
    def test_internal_node_creation(self):
        """Test creation of internal nodes with children."""
        left = MerkleNode("left data")
        right = MerkleNode("right data")
        parent = MerkleNode(left=left, right=right)
        
        self.assertFalse(parent.is_leaf)
        self.assertIsNone(parent.data)
        self.assertEqual(parent.left, left)
        self.assertEqual(parent.right, right)
        self.assertIsNotNone(parent.hash_value)
    
    def test_internal_node_hash(self):
        """Test that internal node hash is derived from children."""
        left = MerkleNode("left")
        right = MerkleNode("right")
        parent = MerkleNode(left=left, right=right)
        
        # Internal nodes use the 0x01 domain-separation prefix (leaves use 0x00)
        combined = left.hash_value + right.hash_value
        expected_hash = hashlib.sha256(b"\x01" + combined.encode('utf-8')).hexdigest()

        self.assertEqual(parent.hash_value, expected_hash)
        # No second-preimage: the same material without the prefix must NOT match.
        self.assertNotEqual(parent.hash_value,
                            hashlib.sha256(combined.encode('utf-8')).hexdigest())
    
    def test_node_equality(self):
        """Test node equality based on hash values."""
        node1 = MerkleNode("same data")
        node2 = MerkleNode("same data")
        node3 = MerkleNode("different data")
        
        self.assertEqual(node1, node2)
        self.assertNotEqual(node1, node3)
        self.assertNotEqual(node1, "not a node")


class TestMerkleTree(unittest.TestCase):
    """Test cases for MerkleTree class."""
    
    def test_tree_creation(self):
        """Test basic Merkle tree creation."""
        data_list = ["data1", "data2", "data3", "data4"]
        tree = MerkleTree(data_list)
        
        self.assertEqual(len(tree), 4)
        self.assertIsNotNone(tree.root)
        self.assertIsNotNone(tree.root_hash)
        self.assertEqual(len(tree.root_hash), 64)
    
    def test_empty_tree_raises_error(self):
        """Test that empty data list raises ValueError."""
        with self.assertRaises(ValueError):
            MerkleTree([])
    
    def test_single_leaf_tree(self):
        """Test tree with single leaf node."""
        data_list = ["single data"]
        tree = MerkleTree(data_list)
        
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree.root, tree.leaves[0])
        self.assertEqual(tree.height, 0)
    
    def test_tree_height_calculation(self):
        """Test height calculation for different tree sizes."""
        # 1 leaf: height 0
        tree1 = MerkleTree(["data1"])
        self.assertEqual(tree1.height, 0)
        
        # 2 leaves: height 1
        tree2 = MerkleTree(["data1", "data2"])
        self.assertEqual(tree2.height, 1)
        
        # 3-4 leaves: height 2
        tree3 = MerkleTree(["data1", "data2", "data3"])
        self.assertEqual(tree3.height, 2)
        
        tree4 = MerkleTree(["data1", "data2", "data3", "data4"])
        self.assertEqual(tree4.height, 2)
        
        # 5-8 leaves: height 3
        tree5 = MerkleTree([f"data{i}" for i in range(5)])
        self.assertEqual(tree5.height, 3)
        
        tree8 = MerkleTree([f"data{i}" for i in range(8)])
        self.assertEqual(tree8.height, 3)
    
    def test_odd_number_of_leaves(self):
        """Test tree with odd number of leaves (duplicates last hash)."""
        data_list = ["data1", "data2", "data3"]
        tree = MerkleTree(data_list)
        
        self.assertEqual(len(tree), 3)
        self.assertIsNotNone(tree.root_hash)
        
        # Verify all leaves are present
        self.assertEqual(tree.leaves[0].data, "data1")
        self.assertEqual(tree.leaves[1].data, "data2")
        self.assertEqual(tree.leaves[2].data, "data3")
    
    def test_get_leaf(self):
        """Test retrieving leaf nodes by index."""
        data_list = ["data1", "data2", "data3"]
        tree = MerkleTree(data_list)
        
        leaf0 = tree.get_leaf(0)
        self.assertEqual(leaf0.data, "data1")
        
        leaf2 = tree.get_leaf(2)
        self.assertEqual(leaf2.data, "data3")
    
    def test_get_leaf_out_of_range(self):
        """Test that out-of-range index raises IndexError."""
        tree = MerkleTree(["data1", "data2"])
        
        with self.assertRaises(IndexError):
            tree.get_leaf(2)
        
        with self.assertRaises(IndexError):
            tree.get_leaf(-1)
    
    def test_get_proof(self):
        """Test Merkle proof generation."""
        data_list = ["data1", "data2", "data3", "data4"]
        tree = MerkleTree(data_list)
        
        # Get proof for first leaf
        proof = tree.get_proof(0)
        self.assertIsInstance(proof, list)
        self.assertGreater(len(proof), 0)
        
        # Each proof step should be a tuple of (hash, bool)
        for step in proof:
            self.assertIsInstance(step, tuple)
            self.assertEqual(len(step), 2)
            self.assertIsInstance(step[0], str)
            self.assertIsInstance(step[1], bool)
    
    def test_get_proof_out_of_range(self):
        """Test that out-of-range index raises IndexError for proof."""
        tree = MerkleTree(["data1", "data2"])
        
        with self.assertRaises(IndexError):
            tree.get_proof(2)
    
    def test_verify_proof(self):
        """Test Merkle proof verification."""
        data_list = ["data1", "data2", "data3", "data4"]
        tree = MerkleTree(data_list)
        
        # Get proof for each leaf and verify
        for i, data in enumerate(data_list):
            proof = tree.get_proof(i)
            is_valid = tree.verify_proof(data, proof, tree.root_hash)
            self.assertTrue(is_valid, f"Proof verification failed for leaf {i}")
    
    def test_verify_proof_invalid(self):
        """Test that invalid proofs are rejected."""
        data_list = ["data1", "data2", "data3", "data4"]
        tree = MerkleTree(data_list)
        
        # Get valid proof for first leaf
        proof = tree.get_proof(0)
        
        # Try to verify with wrong data
        is_valid = tree.verify_proof("wrong data", proof, tree.root_hash)
        self.assertFalse(is_valid)
        
        # Try to verify with wrong root hash
        is_valid = tree.verify_proof(data_list[0], proof, "0" * 64)
        self.assertFalse(is_valid)
    
    def test_verify_leaf(self):
        """Test leaf verification method."""
        data_list = ["data1", "data2", "data3", "data4"]
        tree = MerkleTree(data_list)
        
        # Verify all leaves
        for i in range(len(data_list)):
            is_valid = tree.verify_leaf(i)
            self.assertTrue(is_valid, f"Leaf verification failed for leaf {i}")
    
    def test_verify_leaf_out_of_range(self):
        """Test that out-of-range leaf verification returns False."""
        tree = MerkleTree(["data1", "data2"])
        
        is_valid = tree.verify_leaf(2)
        self.assertFalse(is_valid)
    
    def test_add_leaf(self):
        """Test adding a new leaf to create a new tree."""
        original_data = ["data1", "data2"]
        tree1 = MerkleTree(original_data)
        
        # Add a new leaf
        tree2 = tree1.add_leaf("data3")
        
        self.assertEqual(len(tree1), 2)
        self.assertEqual(len(tree2), 3)
        self.assertNotEqual(tree1.root_hash, tree2.root_hash)
        
        # Verify the new tree contains all data
        self.assertEqual(tree2.leaves[0].data, "data1")
        self.assertEqual(tree2.leaves[1].data, "data2")
        self.assertEqual(tree2.leaves[2].data, "data3")
    
    def test_to_dict(self):
        """Test tree serialization to dictionary."""
        data_list = ["data1", "data2", "data3"]
        tree = MerkleTree(data_list)
        
        tree_dict = tree.to_dict()
        
        self.assertIn('root_hash', tree_dict)
        self.assertIn('num_leaves', tree_dict)
        self.assertIn('height', tree_dict)
        self.assertEqual(tree_dict['num_leaves'], 3)
    
    def test_repr(self):
        """Test tree string representation."""
        data_list = ["data1", "data2"]
        tree = MerkleTree(data_list)
        
        repr_str = repr(tree)
        self.assertIn("MerkleTree", repr_str)
        self.assertIn("leaves=2", repr_str)
        self.assertIn("root_hash=", repr_str)


class TestConvenienceFunctions(unittest.TestCase):
    """Test cases for convenience functions."""
    
    def test_compute_merkle_root(self):
        """Test compute_merkle_root function."""
        data_list = ["data1", "data2", "data3", "data4"]
        
        root_hash = compute_merkle_root(data_list)
        
        self.assertIsNotNone(root_hash)
        self.assertEqual(len(root_hash), 64)
        
        # Should match tree root hash
        tree = MerkleTree(data_list)
        self.assertEqual(root_hash, tree.root_hash)
    
    def test_compute_merkle_root_empty(self):
        """Test compute_merkle_root with empty list."""
        root_hash = compute_merkle_root([])
        expected_hash = hashlib.sha256(b'').hexdigest()
        
        self.assertEqual(root_hash, expected_hash)
    
    def test_verify_data_integrity(self):
        """Test verify_data_integrity function."""
        data_list = ["data1", "data2", "data3"]
        
        # Get expected root hash
        expected_hash = compute_merkle_root(data_list)
        
        # Verify with same data
        is_valid = verify_data_integrity(data_list, expected_hash)
        self.assertTrue(is_valid)
        
        # Verify with different data
        is_valid = verify_data_integrity(["data1", "data2", "different"], expected_hash)
        self.assertFalse(is_valid)
        
        # Verify with empty data
        empty_hash = hashlib.sha256(b'').hexdigest()
        is_valid = verify_data_integrity([], empty_hash)
        self.assertTrue(is_valid)


class TestComplexDataTypes(unittest.TestCase):
    """Test Merkle tree with complex data types."""
    
    def test_dict_data(self):
        """Test Merkle tree with dictionary data."""
        data_list = [
            {"id": 1, "name": "Alice", "data": [1, 2, 3]},
            {"id": 2, "name": "Bob", "data": [4, 5, 6]},
            {"id": 3, "name": "Charlie", "data": [7, 8, 9]}
        ]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 3)
        
        # Verify all leaves
        for i in range(3):
            self.assertTrue(tree.verify_leaf(i))
    
    def test_nested_data(self):
        """Test Merkle tree with deeply nested data."""
        data_list = [
            {
                "level1": {
                    "level2": {
                        "level3": ["a", "b", "c"],
                        "level3b": {"key": "value"}
                    }
                }
            },
            {"simple": "data"}
        ]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 2)
        
        # Verify integrity
        for i in range(2):
            self.assertTrue(tree.verify_leaf(i))
    
    def test_mixed_data_types(self):
        """Test Merkle tree with mixed data types."""
        data_list = [
            "string data",
            12345,
            {"key": "value"},
            [1, 2, 3],
            True,
            None,
            3.14159
        ]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 7)
        
        # Verify all leaves
        for i in range(7):
            self.assertTrue(tree.verify_leaf(i))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""
    
    def test_large_dataset(self):
        """Test Merkle tree with large dataset."""
        # Create 1000 data items
        data_list = [f"data_{i}" for i in range(1000)]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 1000)
        
        # Verify a few random leaves
        import random
        for _ in range(10):
            idx = random.randint(0, 999)
            self.assertTrue(tree.verify_leaf(idx))
    
    def test_unicode_data(self):
        """Test Merkle tree with Unicode data."""
        data_list = [
            "Hello 世界",
            "Привет мир",
            "مرحبا بالعالم",
            "こんにちは世界"
        ]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 4)
        
        for i in range(4):
            self.assertTrue(tree.verify_leaf(i))
    
    def test_binary_data(self):
        """Test Merkle tree with binary-like data (as bytes)."""
        # Note: Our implementation expects string or JSON-serializable data
        # But we can test with base64 encoded binary data
        import base64
        
        binary_data = b"\x00\x01\x02\x03\x04\x05"
        data_list = [
            base64.b64encode(binary_data).decode('utf-8'),
            "regular string"
        ]
        
        tree = MerkleTree(data_list)
        self.assertEqual(len(tree), 2)
        
        for i in range(2):
            self.assertTrue(tree.verify_leaf(i))


if __name__ == "__main__":
    unittest.main()