"""
Merkle Tree Implementation for Open-Omniscience Pillar 4

Provides SHA-256 based Merkle tree for cryptographic provenance.
This implementation ensures immutable data verification for legal admissibility.

Author: Open-Omniscience Team
License: MIT
"""

import hashlib
from typing import List, Optional, Tuple, Any
import json


class MerkleNode:
    """
    Represents a node in the Merkle tree.
    
    Attributes:
        hash_value: SHA-256 hash of the node's content
        left: Left child node (for non-leaf nodes)
        right: Right child node (for non-leaf nodes)
        data: Original data (for leaf nodes)
        is_leaf: Boolean indicating if this is a leaf node
    """
    
    def __init__(self, data: Any = None, left: Optional['MerkleNode'] = None, 
                 right: Optional['MerkleNode'] = None):
        """
        Initialize a Merkle tree node.
        
        Args:
            data: Data for leaf nodes (will be hashed)
            left: Left child for internal nodes
            right: Right child for internal nodes
        """
        self.left = left
        self.right = right
        self.data = data
        # A node is a leaf if it has data (even None) and no children
        # A node is internal if it has children (left/right) and no data
        self.is_leaf = left is None and right is None
        
        if self.is_leaf:
            # Leaf node: hash the data
            data_str = json.dumps(data, sort_keys=True) if not isinstance(data, str) else data
            self.hash_value = self._sha256_hash(data_str.encode('utf-8'))
        else:
            # Internal node: hash the concatenation of child hashes
            if left and right:
                combined = left.hash_value + right.hash_value
                self.hash_value = self._sha256_hash(combined.encode('utf-8'))
            elif left:
                # Odd number of nodes, duplicate last hash
                combined = left.hash_value + left.hash_value
                self.hash_value = self._sha256_hash(combined.encode('utf-8'))
            else:
                self.hash_value = self._sha256_hash(b'')
    
    @staticmethod
    def _sha256_hash(data: bytes) -> str:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(data).hexdigest()
    
    def __repr__(self) -> str:
        return f"MerkleNode(hash={self.hash_value[:8]}..., is_leaf={self.is_leaf})"
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MerkleNode):
            return False
        return self.hash_value == other.hash_value


class MerkleTree:
    """
    Merkle Tree implementation for cryptographic provenance.
    
    Provides efficient verification of data integrity through hierarchical
    hashing. Each non-leaf node is the hash of its children, and the root
    hash represents the entire dataset.
    
    Attributes:
        root: Root node of the Merkle tree
        leaves: List of leaf nodes
        height: Height of the tree
    """
    
    def __init__(self, data_list: List[Any]):
        """
        Initialize a Merkle tree from a list of data items.
        
        Args:
            data_list: List of data items to include in the tree
        
        Raises:
            ValueError: If data_list is empty
        """
        if not data_list:
            raise ValueError("Cannot create Merkle tree from empty data list")
        
        self.leaves = [MerkleNode(data) for data in data_list]
        self.root = self._build_tree(self.leaves)
        self.height = self._calculate_height(len(data_list))
    
    def _build_tree(self, nodes: List[MerkleNode]) -> MerkleNode:
        """
        Recursively build the Merkle tree from leaf nodes.
        
        Args:
            nodes: List of nodes at current level
            
        Returns:
            Root node of the subtree
        """
        if len(nodes) == 1:
            return nodes[0]
        
        # Pair up nodes
        next_level = []
        for i in range(0, len(nodes), 2):
            if i + 1 < len(nodes):
                parent = MerkleNode(left=nodes[i], right=nodes[i + 1])
            else:
                # Odd number of nodes, duplicate the last one
                parent = MerkleNode(left=nodes[i], right=nodes[i])
            next_level.append(parent)
        
        return self._build_tree(next_level)
    
    def _calculate_height(self, num_leaves: int) -> int:
        """Calculate the height of the tree based on number of leaves."""
        height = 0
        while num_leaves > 1:
            num_leaves = (num_leaves + 1) // 2
            height += 1
        return height
    
    @property
    def root_hash(self) -> str:
        """Get the root hash of the Merkle tree."""
        return self.root.hash_value
    
    def get_proof(self, index: int) -> List[Tuple[str, bool]]:
        """
        Get a Merkle proof for a leaf at the given index.
        
        The proof consists of sibling hashes and their position (left/right)
        needed to verify the leaf's inclusion in the tree.
        
        Args:
            index: Index of the leaf node
            
        Returns:
            List of tuples (sibling_hash, is_right_sibling)
            where is_right_sibling=True means the sibling is to the right
            
        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= len(self.leaves):
            raise IndexError(f"Leaf index {index} out of range")
        
        proof = []
        current_index = index
        
        # Start from the leaves and work our way up to the root
        current_level = self.leaves
        
        while len(current_level) > 1:
            # Determine if current node is left or right child
            is_right = current_index % 2 == 1
            
            if is_right:
                # Current node is right child, sibling is left
                sibling_index = current_index - 1
                if sibling_index >= 0:
                    sibling_hash = current_level[sibling_index].hash_value
                    proof.append((sibling_hash, False))  # False means sibling is left
            else:
                # Current node is left child, sibling is right
                sibling_index = current_index + 1
                if sibling_index < len(current_level):
                    sibling_hash = current_level[sibling_index].hash_value
                    proof.append((sibling_hash, True))  # True means sibling is right
                else:
                    # Odd number of nodes, duplicate the current node
                    sibling_hash = current_level[current_index].hash_value
                    proof.append((sibling_hash, True))  # Treat as right sibling
            
            # Move to parent level
            current_index = current_index // 2
            
            # Build the next level (parents)
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    parent = MerkleNode(left=current_level[i], right=current_level[i + 1])
                else:
                    # Odd number of nodes, duplicate the last one
                    parent = MerkleNode(left=current_level[i], right=current_level[i])
                next_level.append(parent)
            
            current_level = next_level
        
        return proof
    
    def verify_proof(self, leaf_data: Any, proof: List[Tuple[str, bool]], 
                    expected_root_hash: str) -> bool:
        """
        Verify a Merkle proof for given leaf data.
        
        Args:
            leaf_data: The data to verify
            proof: Merkle proof from get_proof()
            expected_root_hash: Expected root hash of the tree
            
        Returns:
            True if the proof is valid, False otherwise
        """
        # Hash the leaf data
        leaf_hash = MerkleNode._sha256_hash(
            json.dumps(leaf_data, sort_keys=True).encode('utf-8') 
            if not isinstance(leaf_data, str) else leaf_data.encode('utf-8')
        )
        
        current_hash = leaf_hash
        
        for sibling_hash, is_right_sibling in proof:
            if is_right_sibling:
                # Sibling is to the right, so current + sibling
                combined = current_hash + sibling_hash
            else:
                # Sibling is to the left, so sibling + current
                combined = sibling_hash + current_hash
            current_hash = MerkleNode._sha256_hash(combined.encode('utf-8'))
        
        return current_hash == expected_root_hash
    
    def verify_leaf(self, index: int) -> bool:
        """
        Verify that a leaf at the given index is correctly included in the tree.
        
        Args:
            index: Index of the leaf to verify
            
        Returns:
            True if the leaf is valid, False otherwise
        """
        if index < 0 or index >= len(self.leaves):
            return False
        
        proof = self.get_proof(index)
        return self.verify_proof(self.leaves[index].data, proof, self.root_hash)
    
    def add_leaf(self, data: Any) -> 'MerkleTree':
        """
        Add a new leaf to the tree and return a new Merkle tree.
        
        Note: Merkle trees are immutable, so this creates a new tree.
        
        Args:
            data: Data to add as a new leaf
            
        Returns:
            New MerkleTree with the additional leaf
        """
        new_data_list = [leaf.data for leaf in self.leaves] + [data]
        return MerkleTree(new_data_list)
    
    def get_leaf(self, index: int) -> MerkleNode:
        """Get a leaf node by index."""
        if index < 0 or index >= len(self.leaves):
            raise IndexError(f"Leaf index {index} out of range")
        return self.leaves[index]
    
    def __len__(self) -> int:
        """Return the number of leaves in the tree."""
        return len(self.leaves)
    
    def __repr__(self) -> str:
        return f"MerkleTree(leaves={len(self.leaves)}, root_hash={self.root_hash[:16]}...)"
    
    def to_dict(self) -> dict:
        """Serialize the Merkle tree to a dictionary."""
        return {
            'root_hash': self.root_hash,
            'num_leaves': len(self.leaves),
            'height': self.height
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MerkleTree':
        """
        Deserialize a Merkle tree from a dictionary.
        
        Note: This only reconstructs the structure, not the full tree.
        For full reconstruction, you need the original data.
        """
        # This is a placeholder - full reconstruction requires original data
        raise NotImplementedError("Full tree reconstruction requires original data")


def compute_merkle_root(data_list: List[Any]) -> str:
    """
    Convenience function to compute Merkle root hash from a list of data.
    
    Args:
        data_list: List of data items
        
    Returns:
        Merkle root hash as hex string
    """
    if not data_list:
        return hashlib.sha256(b'').hexdigest()
    
    tree = MerkleTree(data_list)
    return tree.root_hash


def verify_data_integrity(data_list: List[Any], expected_root_hash: str) -> bool:
    """
    Verify that a list of data items produces the expected Merkle root hash.
    
    Args:
        data_list: List of data items
        expected_root_hash: Expected root hash
        
    Returns:
        True if the computed root hash matches the expected hash
    """
    if not data_list:
        return expected_root_hash == hashlib.sha256(b'').hexdigest()
    
    tree = MerkleTree(data_list)
    return tree.root_hash == expected_root_hash


# Example usage and testing
if __name__ == "__main__":
    # Create sample data
    data_items = [
        {"id": 1, "content": "Document A", "timestamp": "2024-01-01"},
        {"id": 2, "content": "Document B", "timestamp": "2024-01-02"},
        {"id": 3, "content": "Document C", "timestamp": "2024-01-03"},
        {"id": 4, "content": "Document D", "timestamp": "2024-01-04"}
    ]
    
    # Create Merkle tree
    tree = MerkleTree(data_items)
    print(f"Created Merkle tree with {len(tree)} leaves")
    print(f"Root hash: {tree.root_hash}")
    print(f"Tree height: {tree.height}")
    
    # Get proof for first leaf
    proof = tree.get_proof(0)
    print(f"Proof for leaf 0: {len(proof)} steps")
    
    # Verify the proof
    is_valid = tree.verify_proof(data_items[0], proof, tree.root_hash)
    print(f"Proof verification: {'VALID' if is_valid else 'INVALID'}")
    
    # Verify all leaves
    for i in range(len(data_items)):
        is_valid = tree.verify_leaf(i)
        print(f"Leaf {i} verification: {'VALID' if is_valid else 'INVALID'}")
    
    # Test data integrity
    tampered_data = data_items.copy()
    tampered_data[0]["content"] = "Tampered Document A"
    
    is_tampered = not verify_data_integrity(tampered_data, tree.root_hash)
    print(f"Tampering detected: {'YES' if is_tampered else 'NO'}")