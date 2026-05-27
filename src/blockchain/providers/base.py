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
Base Blockchain Provider Interface for Open-Omniscience

Defines the abstract interface that all blockchain providers must implement.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseBlockchainProvider(ABC):
    """
    Abstract base class for blockchain providers.
    
    All blockchain providers must implement these methods to support
    anchoring and verification of block Merkle roots.
    """
    
    @abstractmethod
    def anchor_hash(self, merkle_root: str, metadata: Dict[str, Any]) -> str:
        """
        Anchor a Merkle root hash to the blockchain.
        
        This method stores the Merkle root (representing a block of articles)
        on the blockchain for decentralized verification.
        
        Args:
            merkle_root: The Merkle root hash to anchor
            metadata: Additional metadata to store with the anchor
            
        Returns:
            Transaction hash or identifier for the anchor operation
            
        Raises:
            Exception: If anchoring fails
        """
        pass
    
    @abstractmethod
    def verify_anchor(self, merkle_root: str, block_height: Optional[int] = None) -> bool:
        """
        Verify that a Merkle root was anchored to the blockchain.
        
        Args:
            merkle_root: The Merkle root hash to verify
            block_height: Optional block height for additional verification
            
        Returns:
            True if the Merkle root was found and verified, False otherwise
        """
        pass
    
    @abstractmethod
    def get_anchor_data(self, transaction_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve anchored data by transaction hash.
        
        Args:
            transaction_hash: The transaction hash returned by anchor_hash
            
        Returns:
            Dictionary containing the anchored data (including merkle_root),
            or None if not found
        """
        pass
    
    @abstractmethod
    def get_all_anchors(self) -> List[Dict[str, Any]]:
        """
        Get all anchors stored by this provider.
        
        Returns:
            List of anchor records, each containing at least:
            - merkle_root: The anchored Merkle root
            - transaction_hash: The transaction identifier
            - timestamp: When the anchor was created
            - block_height: The block height (if available)
        """
        pass
    
    def close(self) -> None:
        """
        Close the provider and release any resources.
        
        Default implementation does nothing. Override if needed.
        """
        pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
