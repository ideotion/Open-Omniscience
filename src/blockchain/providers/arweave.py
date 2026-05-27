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
Arweave Blockchain Provider for Open-Omniscience

Provides anchoring of block Merkle roots to Arweave for permanent,
low-cost storage with blockchain verification.

Note: This provider requires arweave-python or similar Arweave client library.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import json
import time
from typing import Dict, Any, List, Optional

from .base import BaseBlockchainProvider


class ArweaveProvider(BaseBlockchainProvider):
    """
    Arweave blockchain provider.
    
    Anchors block Merkle roots to Arweave for permanent, decentralized storage.
    Arweave provides low-cost, permanent storage with blockchain verification.
    """
    
    DEFAULT_ARWEAVE_URL = "https://arweave.net"
    
    def __init__(self, wallet_path: str = None, 
                 wallet_key: str = None,
                 arweave_url: str = DEFAULT_ARWEAVE_URL):
        """
        Initialize the Arweave provider.
        
        Args:
            wallet_path: Path to Arweave wallet file (JSON)
            wallet_key: Wallet key data (JSON string)
            arweave_url: Arweave node URL
        """
        self.wallet_path = wallet_path
        self.wallet_key = wallet_key
        self.arweave_url = arweave_url
        self._initialized = False
        self._wallet = None
        self._client = None
        
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize Arweave client."""
        try:
            import arweave
            
            # Load wallet
            if self.wallet_key:
                self._wallet = json.loads(self.wallet_key)
            elif self.wallet_path:
                with open(self.wallet_path, 'r') as f:
                    self._wallet = json.load(f)
            
            if not self._wallet:
                raise ValueError("Wallet path or key required for Arweave")
            
            # Initialize client
            self._client = arweave.Client(self.arweave_url)
            self._initialized = True
        except ImportError:
            # arweave-python not installed
            self._initialized = False
            self._client = None
            self._wallet = None
        except Exception:
            # Initialization failed
            self._initialized = False
            self._client = None
            self._wallet = None
    
    def anchor_hash(self, merkle_root: str, metadata: Dict[str, Any]) -> str:
        """
        Anchor a Merkle root to Arweave.
        
        Creates a transaction with the anchor data and submits it to Arweave.
        
        Args:
            merkle_root: The Merkle root hash to anchor
            metadata: Additional metadata
            
        Returns:
            Transaction ID
            
        Raises:
            Exception: If anchoring fails or Arweave is not available
        """
        if not self._initialized or not self._client or not self._wallet:
            raise Exception("Arweave provider not initialized. Check wallet and connection.")
        
        current_time = int(time.time())
        
        # Create anchor data structure
        anchor_data = {
            'version': '1.0',
            'type': 'open-omniscience-anchor',
            'merkle_root': merkle_root,
            'block_height': metadata.get('block_height', 0),
            'article_count': metadata.get('article_count', 0),
            'timestamp': current_time,
            'block_hash': metadata.get('block_hash', ''),
            'previous_block_hash': metadata.get('previous_block_hash', ''),
            'metadata': metadata
        }
        
        # Convert to JSON string
        json_data = json.dumps(anchor_data, sort_keys=True)
        
        # Create and submit transaction
        transaction = self._client.create_transaction(
            data=json_data.encode('utf-8'),
            wallet=self._wallet
        )
        
        # Sign transaction
        self._client.sign_transaction(transaction, self._wallet)
        
        # Submit transaction
        response = self._client.submit_transaction(transaction)
        
        if response.status_code != 200:
            raise Exception(f"Failed to submit transaction: {response.text}")
        
        return transaction.id
    
    def verify_anchor(self, merkle_root: str, block_height: Optional[int] = None) -> bool:
        """
        Verify that a Merkle root was anchored to Arweave.
        
        Note: This is a simplified verification. In practice, you would
        need to know the transaction ID to retrieve the specific anchor.
        
        Args:
            merkle_root: The Merkle root to verify
            block_height: Optional block height for additional verification
            
        Returns:
            True if an anchor with this Merkle root exists, False otherwise
        """
        if not self._initialized or not self._client:
            return False
        
        try:
            # This is a simplified check - in practice, you would need to
            # maintain an index of transaction IDs by Merkle root
            # For now, we'll just return False as we can't efficiently search Arweave
            return False
        except Exception:
            return False
    
    def get_anchor_data(self, transaction_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve anchored data by transaction hash.
        
        Args:
            transaction_hash: The Arweave transaction ID
            
        Returns:
            Dictionary with anchor data or None if not found
        """
        if not self._initialized or not self._client:
            return None
        
        try:
            # Get transaction data
            transaction = self._client.get_transaction(transaction_hash)
            
            if not transaction or not transaction.data:
                return None
            
            # Parse JSON data
            data = transaction.data.decode('utf-8')
            anchor_data = json.loads(data)
            
            return {
                'transaction_hash': transaction_hash,
                'merkle_root': anchor_data.get('merkle_root'),
                'block_height': anchor_data.get('block_height'),
                'article_count': anchor_data.get('article_count'),
                'timestamp': anchor_data.get('timestamp'),
                'block_hash': anchor_data.get('block_hash'),
                'previous_block_hash': anchor_data.get('previous_block_hash'),
                'metadata': anchor_data.get('metadata', {})
            }
        except Exception:
            return None
    
    def get_all_anchors(self) -> List[Dict[str, Any]]:
        """
        Get all anchors from Arweave.
        
        Note: This is not practical for Arweave as there's no way to list all
        transactions by a specific address without scanning the entire chain.
        This method returns an empty list.
        
        In practice, you would need to maintain a separate index of transaction IDs.
        
        Returns:
            Empty list (not supported)
        """
        # Arweave doesn't provide a practical way to list all transactions
        # In practice, you would maintain a local database of transaction IDs
        return []
    
    def close(self) -> None:
        """Close the provider."""
        self._initialized = False
        self._client = None
        self._wallet = None


# Import arweave for type hints (optional)
try:
    import arweave
except ImportError:
    arweave = None
