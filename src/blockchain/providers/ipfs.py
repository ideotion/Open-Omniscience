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
IPFS Blockchain Provider for Open-Omniscience

Provides anchoring of block Merkle roots to IPFS (InterPlanetary File System).
This enables decentralized verification using content-addressed storage.

Note: This provider requires ipfshttpclient or similar IPFS client library.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import json
import time
from typing import Dict, Any, List, Optional

from .base import BaseBlockchainProvider


class IPFSProvider(BaseBlockchainProvider):
    """
    IPFS blockchain provider.
    
    Anchors block Merkle roots to IPFS for decentralized verification.
    Each anchor is stored as a JSON file with the Merkle root and metadata.
    """
    
    DEFAULT_IPFS_HOST = "localhost"
    DEFAULT_IPFS_PORT = 5001
    
    def __init__(self, host: str = DEFAULT_IPFS_HOST, 
                 port: int = DEFAULT_IPFS_PORT,
                 use_https: bool = False):
        """
        Initialize the IPFS provider.
        
        Args:
            host: IPFS node host
            port: IPFS node API port
            use_https: Use HTTPS instead of HTTP
        """
        self.host = host
        self.port = port
        self.use_https = use_https
        self._initialized = False
        self._client = None
        
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize IPFS client."""
        try:
            import ipfshttpclient
            
            # Connect to IPFS node
            if self.use_https:
                client = ipfshttpclient.connect(f"https://{self.host}:{self.port}")
            else:
                client = ipfshttpclient.connect(f"http://{self.host}:{self.port}")
            
            # Test connection
            client.id()
            self._client = client
            self._initialized = True
        except ImportError:
            # ipfshttpclient not installed
            self._initialized = False
            self._client = None
        except Exception:
            # Connection failed
            self._initialized = False
            self._client = None
    
    def anchor_hash(self, merkle_root: str, metadata: Dict[str, Any]) -> str:
        """
        Anchor a Merkle root to IPFS.
        
        Creates a JSON file with the anchor data and adds it to IPFS.
        
        Args:
            merkle_root: The Merkle root hash to anchor
            metadata: Additional metadata
            
        Returns:
            IPFS content identifier (CID)
            
        Raises:
            Exception: If anchoring fails or IPFS is not available
        """
        if not self._initialized or not self._client:
            raise Exception("IPFS provider not initialized. Check IPFS node connection.")
        
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
        
        # Add to IPFS
        result = self._client.add_str(json_data)
        
        return result['Hash']
    
    def verify_anchor(self, merkle_root: str, block_height: Optional[int] = None) -> bool:
        """
        Verify that a Merkle root was anchored to IPFS.
        
        Note: This is a simplified verification that checks if we can
        find an anchor with the given Merkle root. In practice, you would
        need to know the CID to retrieve the specific anchor.
        
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
            # maintain an index of CIDs by Merkle root
            # For now, we'll just return False as we can't efficiently search IPFS
            return False
        except Exception:
            return False
    
    def get_anchor_data(self, transaction_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve anchored data by transaction hash (CID).
        
        Args:
            transaction_hash: The IPFS CID
            
        Returns:
            Dictionary with anchor data or None if not found
        """
        if not self._initialized or not self._client:
            return None
        
        try:
            # Get the data from IPFS
            data = self._client.cat(transaction_hash)
            
            if not data:
                return None
            
            # Parse JSON
            anchor_data = json.loads(data.decode('utf-8'))
            
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
        Get all anchors from IPFS.
        
        Note: This is not practical for IPFS as there's no way to list all
        files added by this node. This method returns an empty list.
        
        In practice, you would need to maintain a separate index of CIDs.
        
        Returns:
            Empty list (not supported)
        """
        # IPFS doesn't provide a way to list all files added by a node
        # In practice, you would maintain a local database of CIDs
        return []
    
    def close(self) -> None:
        """Close the provider."""
        self._initialized = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None


# Import ipfshttpclient for type hints (optional)
try:
    import ipfshttpclient
except ImportError:
    ipfshttpclient = None
