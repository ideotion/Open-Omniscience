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
Blockchain Module for Open-Omniscience

Provides per-article blockchain verification with:
- Local hash chain (SQLite) for offline verification
- Optional public blockchain anchoring (Ethereum, IPFS, Arweave)
- Merkle tree proofs for per-article verification
- Cryptographic integrity guarantees

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from .core.hash_chain import LocalHashChain, LocalBlock
from .core.anchor_service import AnchorService, VerificationResult
from .providers import get_provider, LocalProvider, EthereumProvider, IPFSProvider, ArweaveProvider
from .providers.base import BaseBlockchainProvider
from .config.settings import BlockchainSettings

# Global blockchain service instance
_blockchain_service = None


def get_blockchain_service():
    """Get the global blockchain service instance."""
    global _blockchain_service
    if _blockchain_service is None:
        _blockchain_service = BlockchainService()
    return _blockchain_service


def reset_blockchain_service():
    """Reset the global blockchain service instance (for testing)."""
    global _blockchain_service
    if _blockchain_service is not None:
        _blockchain_service.close()
    _blockchain_service = None


class BlockchainService:
    """
    Main blockchain service for Open-Omniscience.
    
    Provides per-article verification with optional blockchain anchoring.
    """
    
    def __init__(self, settings=None):
        """
        Initialize the blockchain service.
        
        Args:
            settings: BlockchainSettings object or None for defaults
        """
        if settings is None:
            self.settings = BlockchainSettings()
        elif isinstance(settings, BlockchainSettings):
            self.settings = settings
        else:
            # Convert dict to BlockchainSettings
            self.settings = BlockchainSettings.from_dict(settings)
        
        self.hash_chain = LocalHashChain(
            db_path=self.settings.local_chain.db_path,
            articles_per_block=self.settings.local_chain.articles_per_block,
            time_per_block=self.settings.local_chain.time_per_block
        )
        self.anchor_service = AnchorService(
            hash_chain=self.hash_chain,
            settings=self.settings
        )
    
    def add_article(self, article_id, content_hash, metadata_hash, source_hash):
        """
        Add an article to the blockchain.
        
        Args:
            article_id: Unique identifier for the article
            content_hash: SHA-256 hash of article content
            metadata_hash: SHA-256 hash of article metadata
            source_hash: SHA-256 hash of source URL + timestamp
        """
        return self.anchor_service.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
    
    def verify_article(self, article_id, expected_content_hash=None, 
                      expected_metadata_hash=None, expected_source_hash=None):
        """
        Verify a single article.
        
        Args:
            article_id: Article identifier
            expected_content_hash: Optional expected content hash
            expected_metadata_hash: Optional expected metadata hash
            expected_source_hash: Optional expected source hash
            
        Returns:
            VerificationResult with detailed verification information
        """
        return self.anchor_service.verify_article(
            article_id,
            expected_content_hash=expected_content_hash,
            expected_metadata_hash=expected_metadata_hash,
            expected_source_hash=expected_source_hash
        )
    
    def get_article_verification_data(self, article_id):
        """
        Get all data needed to verify an article.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Dictionary with hashes, block info, and Merkle proof
        """
        return self.anchor_service.get_article_verification_data(article_id)
    
    def get_merkle_proof(self, article_id):
        """
        Get Merkle proof for an article.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Dictionary with Merkle proof and related data
        """
        return self.hash_chain.get_merkle_proof(article_id)
    
    def verify_article_with_proof(self, article_id, content_hash, metadata_hash, 
                                 source_hash, merkle_proof, merkle_root):
        """
        Verify an article using a provided Merkle proof.
        
        Args:
            article_id: Article identifier
            content_hash: Expected content hash
            metadata_hash: Expected metadata hash
            source_hash: Expected source hash
            merkle_proof: Merkle proof for the article
            merkle_root: Expected Merkle root
            
        Returns:
            True if verification succeeds, False otherwise
        """
        return self.hash_chain.verify_article_with_proof(
            article_id, content_hash, metadata_hash, source_hash,
            merkle_proof, merkle_root
        )
    
    def close(self):
        """Close the blockchain service and its resources."""
        self.hash_chain.close()
        self.anchor_service.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
