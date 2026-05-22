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
Cryptographic Provenance Ledger for Open-Omniscience Pillar 4

Provides SQLite-based immutable ledger for tracking data provenance
using SHA-256 hashes and Merkle trees. This ensures legal admissibility
by maintaining cryptographic proof of data origin and integrity.

Author: Open-Omniscience Team
License: MIT
"""

import sqlite3
import hashlib
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import os
from pathlib import Path

from .merkle_tree import MerkleTree, compute_merkle_root


class DataProvenance:
    """
    Represents the provenance information for a single data item.
    
    Attributes:
        data_id: Unique identifier for the data
        original_hash: SHA-256 hash of the original data
        current_hash: SHA-256 hash of the current data
        timestamp: When the data was recorded
        source: Origin of the data
        metadata: Additional metadata about the data
    """
    
    def __init__(self, data_id: str, data: Any, source: str = "unknown", 
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize provenance record for data.
        
        Args:
            data_id: Unique identifier for the data
            data: The actual data content
            source: Origin/source of the data
            metadata: Additional metadata
        """
        self.data_id = data_id
        self.source = source
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        
        # Compute hashes
        data_str = json.dumps(data, sort_keys=True) if not isinstance(data, str) else data
        self.original_hash = self._compute_sha256(data_str.encode('utf-8'))
        self.current_hash = self.original_hash
    
    @staticmethod
    def _compute_sha256(data: bytes) -> str:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(data).hexdigest()
    
    def update_hash(self, new_data: Any) -> str:
        """
        Update the current hash with new data.
        
        Args:
            new_data: New data to hash
            
        Returns:
            New SHA-256 hash
        """
        data_str = json.dumps(new_data, sort_keys=True) if not isinstance(new_data, str) else new_data
        self.current_hash = self._compute_sha256(data_str.encode('utf-8'))
        return self.current_hash
    
    def is_unchanged(self) -> bool:
        """Check if data has been modified since creation."""
        return self.original_hash == self.current_hash
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'data_id': self.data_id,
            'original_hash': self.original_hash,
            'current_hash': self.current_hash,
            'timestamp': self.timestamp,
            'source': self.source,
            'metadata': self.metadata,
            'is_unchanged': self.is_unchanged()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataProvenance':
        """Create DataProvenance from dictionary."""
        provenance = cls(
            data_id=data['data_id'],
            data=None,  # Data not included in serialization
            source=data.get('source', 'unknown'),
            metadata=data.get('metadata', {})
        )
        provenance.original_hash = data['original_hash']
        provenance.current_hash = data['current_hash']
        provenance.timestamp = data['timestamp']
        return provenance
    
    def __repr__(self) -> str:
        return f"DataProvenance(id={self.data_id}, hash={self.original_hash[:16]}...)"


class ProvenanceLedger:
    """
    SQLite-based ledger for tracking cryptographic provenance of data.
    
    This ledger maintains:
    - Individual data hashes (SHA-256)
    - Merkle tree roots for batches of data
    - Chain of custody information
    - Timestamped records for legal admissibility
    
    The database schema includes:
    - data_entries: Individual data items with their hashes
    - merkle_trees: Merkle tree roots for batches
    - provenance_chain: Chain of custody records
    """
    
    DEFAULT_DB_PATH = "provenance_ledger.db"
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH, create_if_not_exists: bool = True):
        """
        Initialize the provenance ledger.
        
        Args:
            db_path: Path to SQLite database file
            create_if_not_exists: Create database if it doesn't exist
        """
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None
        self._initialize_database(create_if_not_exists)
    
    def _initialize_database(self, create_if_not_exists: bool) -> None:
        """Initialize the SQLite database with required tables."""
        if not create_if_not_exists and not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")
        
        # Create parent directory if needed and allowed
        if create_if_not_exists:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        
        # Create tables if they don't exist
        cursor = self.connection.cursor()
        
        # Data entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_entries (
                id TEXT PRIMARY KEY,
                original_hash TEXT NOT NULL,
                current_hash TEXT NOT NULL,
                data_json TEXT,
                source TEXT NOT NULL,
                metadata_json TEXT,
                timestamp TEXT NOT NULL,
                merkle_tree_id INTEGER,
                FOREIGN KEY (merkle_tree_id) REFERENCES merkle_trees(id)
            )
        """)
        
        # Merkle trees table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS merkle_trees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_hash TEXT NOT NULL UNIQUE,
                num_leaves INTEGER NOT NULL,
                height INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                description TEXT
            )
        """)
        
        # Provenance chain table (for chain of custody)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS provenance_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_id TEXT NOT NULL,
                action TEXT NOT NULL,
                user_id TEXT,
                timestamp TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                new_hash TEXT NOT NULL,
                metadata_json TEXT,
                FOREIGN KEY (data_id) REFERENCES data_entries(id)
            )
        """)
        
        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_entries_hash ON data_entries(original_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_data_entries_merkle ON data_entries(merkle_tree_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_provenance_chain_data ON provenance_chain(data_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_provenance_chain_timestamp ON provenance_chain(timestamp)")
        
        self.connection.commit()
    
    def add_data(self, data_id: str, data: Any, source: str = "unknown", 
                 metadata: Optional[Dict[str, Any]] = None, batch_id: Optional[int] = None) -> DataProvenance:
        """
        Add a new data entry to the ledger.
        
        Args:
            data_id: Unique identifier for the data
            data: The data content
            source: Origin of the data
            metadata: Additional metadata
            batch_id: Optional Merkle tree batch ID to associate with
            
        Returns:
            DataProvenance object for the added data
        """
        provenance = DataProvenance(data_id, data, source, metadata)
        
        # Serialize data and metadata
        data_json = json.dumps(data, sort_keys=True) if data is not None else None
        metadata_json = json.dumps(metadata or {})
        
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO data_entries 
            (id, original_hash, current_hash, data_json, source, metadata_json, timestamp, merkle_tree_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data_id,
            provenance.original_hash,
            provenance.current_hash,
            data_json,
            source,
            metadata_json,
            provenance.timestamp,
            batch_id
        ))
        
        self.connection.commit()
        return provenance
    
    def add_data_batch(self, data_items: List[Tuple[str, Any, str, Dict[str, Any]]], 
                       description: str = "") -> int:
        """
        Add a batch of data items and create a Merkle tree for them.
        
        Args:
            data_items: List of tuples (data_id, data, source, metadata)
            description: Description of this batch
            
        Returns:
            Merkle tree ID
        """
        if not data_items:
            raise ValueError("Cannot add empty batch")
        
        # Extract data for Merkle tree
        data_list = [item[1] for item in data_items]
        
        # Create Merkle tree
        tree = MerkleTree(data_list)
        
        # Store Merkle tree
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO merkle_trees (root_hash, num_leaves, height, created_at, description)
            VALUES (?, ?, ?, ?, ?)
        """, (
            tree.root_hash,
            len(data_list),
            tree.height,
            datetime.now(timezone.utc).isoformat(),
            description
        ))
        
        merkle_tree_id = cursor.lastrowid
        
        # Add individual data entries
        for data_id, data, source, metadata in data_items:
            self.add_data(data_id, data, source, metadata, merkle_tree_id)
        
        self.connection.commit()
        return merkle_tree_id
    
    def get_data_provenance(self, data_id: str) -> Optional[DataProvenance]:
        """
        Retrieve provenance information for a data item.
        
        Args:
            data_id: Unique identifier for the data
            
        Returns:
            DataProvenance object or None if not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT id, original_hash, current_hash, source, metadata_json, timestamp
            FROM data_entries WHERE id = ?
        """, (data_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        data_id, original_hash, current_hash, source, metadata_json, timestamp = row
        metadata = json.loads(metadata_json) if metadata_json else {}
        
        provenance = DataProvenance(data_id, None, source, metadata)
        provenance.original_hash = original_hash
        provenance.current_hash = current_hash
        provenance.timestamp = timestamp
        
        return provenance
    
    def get_merkle_tree(self, tree_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve Merkle tree information by ID.
        
        Args:
            tree_id: Merkle tree ID
            
        Returns:
            Dictionary with tree information or None if not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT id, root_hash, num_leaves, height, created_at, description
            FROM merkle_trees WHERE id = ?
        """, (tree_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            'id': row[0],
            'root_hash': row[1],
            'num_leaves': row[2],
            'height': row[3],
            'created_at': row[4],
            'description': row[5]
        }
    
    def get_data_by_merkle_tree(self, tree_id: int) -> List[DataProvenance]:
        """
        Get all data entries associated with a Merkle tree.
        
        Args:
            tree_id: Merkle tree ID
            
        Returns:
            List of DataProvenance objects
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT id, original_hash, current_hash, source, metadata_json, timestamp
            FROM data_entries WHERE merkle_tree_id = ?
        """, (tree_id,))
        
        results = []
        for row in cursor.fetchall():
            data_id, original_hash, current_hash, source, metadata_json, timestamp = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            
            provenance = DataProvenance(data_id, None, source, metadata)
            provenance.original_hash = original_hash
            provenance.current_hash = current_hash
            provenance.timestamp = timestamp
            
            results.append(provenance)
        
        return results
    
    def verify_data_integrity(self, data_id: str, expected_hash: str) -> bool:
        """
        Verify that a data item's current hash matches the expected hash.
        
        Args:
            data_id: Data identifier
            expected_hash: Expected SHA-256 hash
            
        Returns:
            True if hash matches, False otherwise
        """
        provenance = self.get_data_provenance(data_id)
        if not provenance:
            return False
        return provenance.current_hash == expected_hash
    
    def verify_merkle_tree_integrity(self, tree_id: int) -> bool:
        """
        Verify the integrity of all data in a Merkle tree.
        
        Args:
            tree_id: Merkle tree ID
            
        Returns:
            True if all data hashes are consistent, False otherwise
        """
        data_entries = self.get_data_by_merkle_tree(tree_id)
        if not data_entries:
            return False
        
        # Get the expected root hash
        tree_info = self.get_merkle_tree(tree_id)
        if not tree_info:
            return False
        
        expected_root_hash = tree_info['root_hash']
        
        # Recompute Merkle root from current data
        data_list = []
        for entry in data_entries:
            # We need to retrieve the actual data to recompute the hash
            cursor = self.connection.cursor()
            cursor.execute("SELECT data_json FROM data_entries WHERE id = ?", (entry.data_id,))
            row = cursor.fetchone()
            if row and row[0]:
                data_list.append(json.loads(row[0]))
            else:
                # If data is not stored, we can't verify
                return False
        
        if not data_list:
            return False
        
        computed_root_hash = compute_merkle_root(data_list)
        return computed_root_hash == expected_root_hash
    
    def record_custody_change(self, data_id: str, action: str, user_id: str = None,
                              new_data: Any = None, metadata: Dict[str, Any] = None) -> bool:
        """
        Record a change in custody or modification of data.
        
        Args:
            data_id: Data identifier
            action: Description of the action (e.g., 'accessed', 'modified', 'copied')
            user_id: User who performed the action
            new_data: New data if modified
            metadata: Additional metadata about the action
            
        Returns:
            True if recorded successfully, False otherwise
        """
        # Get current provenance
        provenance = self.get_data_provenance(data_id)
        if not provenance:
            return False
        
        previous_hash = provenance.current_hash
        cursor = self.connection.cursor()
        
        # If new data is provided, update the hash
        if new_data is not None:
            new_hash = provenance.update_hash(new_data)
            
            # Update the data entry
            cursor.execute("""
                UPDATE data_entries 
                SET current_hash = ?, data_json = ?
                WHERE id = ?
            """, (new_hash, json.dumps(new_data, sort_keys=True), data_id))
        else:
            new_hash = previous_hash
        
        # Record the custody change
        metadata_json = json.dumps(metadata or {})
        timestamp = datetime.now(timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO provenance_chain 
            (data_id, action, user_id, timestamp, previous_hash, new_hash, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data_id, action, user_id, timestamp, previous_hash, new_hash, metadata_json))
        
        self.connection.commit()
        return True
    
    def get_custody_chain(self, data_id: str) -> List[Dict[str, Any]]:
        """
        Get the complete chain of custody for a data item.
        
        Args:
            data_id: Data identifier
            
        Returns:
            List of custody records in chronological order
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT action, user_id, timestamp, previous_hash, new_hash, metadata_json
            FROM provenance_chain 
            WHERE data_id = ? 
            ORDER BY timestamp ASC
        """, (data_id,))
        
        results = []
        for row in cursor.fetchall():
            action, user_id, timestamp, previous_hash, new_hash, metadata_json = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            
            results.append({
                'action': action,
                'user_id': user_id,
                'timestamp': timestamp,
                'previous_hash': previous_hash,
                'new_hash': new_hash,
                'metadata': metadata
            })
        
        return results
    
    def get_all_data_entries(self, limit: int = None) -> List[DataProvenance]:
        """
        Get all data entries in the ledger.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of DataProvenance objects
        """
        cursor = self.connection.cursor()
        query = """
            SELECT id, original_hash, current_hash, source, metadata_json, timestamp
            FROM data_entries
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        
        results = []
        for row in cursor.fetchall():
            data_id, original_hash, current_hash, source, metadata_json, timestamp = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            
            provenance = DataProvenance(data_id, None, source, metadata)
            provenance.original_hash = original_hash
            provenance.current_hash = current_hash
            provenance.timestamp = timestamp
            
            results.append(provenance)
        
        return results
    
    def get_all_merkle_trees(self, limit: int = None) -> List[Dict[str, Any]]:
        """
        Get all Merkle trees in the ledger.
        
        Args:
            limit: Maximum number of trees to return
            
        Returns:
            List of Merkle tree information dictionaries
        """
        cursor = self.connection.cursor()
        query = """
            SELECT id, root_hash, num_leaves, height, created_at, description
            FROM merkle_trees
            ORDER BY created_at DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row[0],
                'root_hash': row[1],
                'num_leaves': row[2],
                'height': row[3],
                'created_at': row[4],
                'description': row[5]
            })
        
        return results
    
    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def __repr__(self) -> str:
        return f"ProvenanceLedger(db_path={self.db_path})"


def create_provenance_ledger(db_path: str = ProvenanceLedger.DEFAULT_DB_PATH) -> ProvenanceLedger:
    """
    Factory function to create a new provenance ledger.
    
    Args:
        db_path: Path to the SQLite database
        
    Returns:
        New ProvenanceLedger instance
    """
    return ProvenanceLedger(db_path)


# Example usage and testing
if __name__ == "__main__":
    import tempfile
    import shutil
    
    # Create a temporary directory for testing
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_provenance.db")
    
    try:
        # Create ledger
        ledger = ProvenanceLedger(db_path)
        
        # Add some data
        data_items = [
            ("doc1", {"id": 1, "content": "Document A", "timestamp": "2024-01-01"}, "source_a", {"type": "document"}),
            ("doc2", {"id": 2, "content": "Document B", "timestamp": "2024-01-02"}, "source_b", {"type": "document"}),
            ("doc3", {"id": 3, "content": "Document C", "timestamp": "2024-01-03"}, "source_c", {"type": "document"}),
        ]
        
        # Add data batch with Merkle tree
        batch_id = ledger.add_data_batch(data_items, "Test batch")
        print(f"Created batch with ID: {batch_id}")
        
        # Get Merkle tree info
        tree_info = ledger.get_merkle_tree(batch_id)
        print(f"Merkle tree root hash: {tree_info['root_hash']}")
        print(f"Number of leaves: {tree_info['num_leaves']}")
        
        # Verify integrity
        is_valid = ledger.verify_merkle_tree_integrity(batch_id)
        print(f"Merkle tree integrity: {'VALID' if is_valid else 'INVALID'}")
        
        # Get data provenance
        provenance = ledger.get_data_provenance("doc1")
        print(f"Data provenance for doc1: {provenance}")
        
        # Record custody change
        ledger.record_custody_change("doc1", "accessed", "user123")
        ledger.record_custody_change("doc1", "modified", "user456", 
                                    {"id": 1, "content": "Modified Document A", "timestamp": "2024-01-01"})
        
        # Get custody chain
        custody_chain = ledger.get_custody_chain("doc1")
        print(f"Custody chain for doc1: {len(custody_chain)} records")
        for record in custody_chain:
            print(f"  - {record['action']} by {record['user_id']} at {record['timestamp']}")
        
        # Verify data integrity after modification
        is_valid = ledger.verify_data_integrity("doc1", provenance.original_hash)
        print(f"Original data integrity: {'VALID' if is_valid else 'INVALID'}")
        
        # Get current provenance
        current_provenance = ledger.get_data_provenance("doc1")
        is_current_valid = ledger.verify_data_integrity("doc1", current_provenance.current_hash)
        print(f"Current data integrity: {'VALID' if is_current_valid else 'INVALID'}")
        
    finally:
        # Clean up
        ledger.close()
        shutil.rmtree(temp_dir)
        print("Test completed and cleaned up")