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
Local Blockchain Provider for Open-Omniscience

Provides SQLite-based offline anchoring of block Merkle roots.
This allows for local verification without requiring external blockchain access.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import sqlite3
import hashlib
import json
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

from .base import BaseBlockchainProvider


class LocalProvider(BaseBlockchainProvider):
    """
    SQLite-based local blockchain provider.
    
    Stores anchored Merkle roots in a local SQLite database for offline verification.
    """
    
    DEFAULT_DB_PATH = "data/blockchain/anchors.db"
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initialize the local provider.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None
        
        # Create parent directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize the SQLite database."""
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        
        cursor = self.connection.cursor()
        
        # Anchors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS anchors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_hash TEXT NOT NULL UNIQUE,
                merkle_root TEXT NOT NULL,
                block_height INTEGER NOT NULL,
                article_count INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                metadata_json TEXT,
                block_hash TEXT NOT NULL,
                previous_block_hash TEXT NOT NULL
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anchors_merkle ON anchors(merkle_root)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anchors_block ON anchors(block_height)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_anchors_transaction ON anchors(transaction_hash)")
        
        self.connection.commit()
    
    def anchor_hash(self, merkle_root: str, metadata: Dict[str, Any]) -> str:
        """
        Anchor a Merkle root to the local database.
        
        Args:
            merkle_root: The Merkle root hash to anchor
            metadata: Additional metadata (should include block_height, etc.)
            
        Returns:
            Transaction hash (computed from the anchor data)
        """
        current_time = int(time.time())
        
        # Extract metadata
        block_height = metadata.get('block_height', 0)
        article_count = metadata.get('article_count', 0)
        block_hash = metadata.get('block_hash', '')
        previous_block_hash = metadata.get('previous_block_hash', '')
        
        # Create transaction hash from all data
        anchor_data = {
            'merkle_root': merkle_root,
            'block_height': block_height,
            'article_count': article_count,
            'timestamp': current_time,
            'block_hash': block_hash,
            'previous_block_hash': previous_block_hash,
            'metadata': metadata
        }
        
        transaction_hash = hashlib.sha256(
            json.dumps(anchor_data, sort_keys=True).encode()
        ).hexdigest()
        
        # Store the anchor
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO anchors 
            (transaction_hash, merkle_root, block_height, article_count, 
             timestamp, metadata_json, block_hash, previous_block_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            transaction_hash,
            merkle_root,
            block_height,
            article_count,
            current_time,
            json.dumps(metadata),
            block_hash,
            previous_block_hash
        ))
        
        self.connection.commit()
        
        return transaction_hash
    
    def verify_anchor(self, merkle_root: str, block_height: Optional[int] = None) -> bool:
        """
        Verify that a Merkle root was anchored.
        
        Args:
            merkle_root: The Merkle root to verify
            block_height: Optional block height for additional verification
            
        Returns:
            True if the Merkle root was found, False otherwise
        """
        cursor = self.connection.cursor()
        
        if block_height is not None:
            cursor.execute("""
                SELECT COUNT(*) FROM anchors 
                WHERE merkle_root = ? AND block_height = ?
            """, (merkle_root, block_height))
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM anchors 
                WHERE merkle_root = ?
            """, (merkle_root,))
        
        count = cursor.fetchone()[0]
        return count > 0
    
    def get_anchor_data(self, transaction_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve anchored data by transaction hash.
        
        Args:
            transaction_hash: The transaction hash
            
        Returns:
            Dictionary with anchor data or None if not found
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT merkle_root, block_height, article_count, timestamp, 
                   metadata_json, block_hash, previous_block_hash
            FROM anchors 
            WHERE transaction_hash = ?
        """, (transaction_hash,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        merkle_root, block_height, article_count, timestamp, metadata_json, block_hash, previous_block_hash = row
        metadata = json.loads(metadata_json) if metadata_json else {}
        
        return {
            'transaction_hash': transaction_hash,
            'merkle_root': merkle_root,
            'block_height': block_height,
            'article_count': article_count,
            'timestamp': timestamp,
            'metadata': metadata,
            'block_hash': block_hash,
            'previous_block_hash': previous_block_hash
        }
    
    def get_all_anchors(self) -> List[Dict[str, Any]]:
        """
        Get all anchors stored by this provider.
        
        Returns:
            List of anchor records
        """
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT transaction_hash, merkle_root, block_height, article_count, 
                   timestamp, metadata_json, block_hash, previous_block_hash
            FROM anchors 
            ORDER BY block_height ASC, timestamp ASC
        """)
        
        anchors = []
        for row in cursor.fetchall():
            transaction_hash, merkle_root, block_height, article_count, timestamp, metadata_json, block_hash, previous_block_hash = row
            metadata = json.loads(metadata_json) if metadata_json else {}
            
            anchors.append({
                'transaction_hash': transaction_hash,
                'merkle_root': merkle_root,
                'block_height': block_height,
                'article_count': article_count,
                'timestamp': timestamp,
                'metadata': metadata,
                'block_hash': block_hash,
                'previous_block_hash': previous_block_hash
            })
        
        return anchors
    
    def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
