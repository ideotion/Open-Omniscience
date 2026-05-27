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
Anchor Service for Open-Omniscience

Manages the local hash chain and provides per-article verification
with optional blockchain anchoring.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from pathlib import Path

from .hash_chain import LocalHashChain
from ..providers import get_provider
from ..providers.base import BaseBlockchainProvider


@dataclass
class VerificationResult:
    """
    Result of article verification.
    
    Attributes:
        article_id: The article identifier
        verified: Whether verification succeeded
        local_verification: Results of local verification
        blockchain_verifications: Results of blockchain verifications
        merkle_proof: Merkle proof for the article
        block_height: Block containing the article
        position: Position in the block
        warnings: Any warnings during verification
    """
    
    article_id: str
    verified: bool
    local_verification: Dict[str, bool] = field(default_factory=dict)
    blockchain_verifications: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    merkle_proof: Optional[List[Dict[str, Any]]] = None
    block_height: Optional[int] = None
    position: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'article_id': self.article_id,
            'verified': self.verified,
            'local_verification': self.local_verification,
            'blockchain_verifications': self.blockchain_verifications,
            'merkle_proof': self.merkle_proof,
            'block_height': self.block_height,
            'position': self.position,
            'warnings': self.warnings
        }


class AnchorService:
    """
    Service for managing blockchain anchoring and per-article verification.
    
    Provides:
    - Per-article verification via local hash chain
    - Optional blockchain anchoring of block Merkle roots
    - Merkle proof generation for decentralized verification
    - Integration with multiple blockchain providers
    """
    
    def __init__(self, hash_chain: LocalHashChain, settings=None):
        """
        Initialize the anchor service.
        
        Args:
            hash_chain: LocalHashChain instance
            settings: BlockchainSettings object
        """
        self.hash_chain = hash_chain
        self.settings = settings
        self.providers: Dict[str, BaseBlockchainProvider] = {}
        self._lock = threading.Lock()
        self._initialized = False
        
        self._initialize_providers()
    
    def _initialize_providers(self) -> None:
        """Initialize blockchain providers based on settings."""
        if self._initialized:
            return
        
        self._initialized = True
        
        if not self.settings:
            return
        
        # Initialize enabled providers
        if self.settings.anchoring.enabled:
            for provider_name in self.settings.anchoring.providers:
                try:
                    provider = get_provider(provider_name)
                    if provider:
                        self.providers[provider_name] = provider
                except Exception as e:
                    # Log error but don't fail
                    pass
    
    def add_article(self, article_id: str, content_hash: str,
                   metadata_hash: str, source_hash: str) -> Dict[str, Any]:
        """
        Add an article to the hash chain.
        
        Args:
            article_id: Unique identifier for the article
            content_hash: SHA-256 hash of article content
            metadata_hash: SHA-256 hash of article metadata
            source_hash: SHA-256 hash of source URL + timestamp
            
        Returns:
            Dictionary with article info and block assignment
        """
        return self.hash_chain.add_article(
            article_id, content_hash, metadata_hash, source_hash
        )
    
    def verify_article(self, article_id: str,
                      expected_content_hash: Optional[str] = None,
                      expected_metadata_hash: Optional[str] = None,
                      expected_source_hash: Optional[str] = None) -> VerificationResult:
        """
        Verify a single article.
        
        Performs:
        1. Local verification (hash comparison, Merkle proof)
        2. Block chain integrity check
        3. Optional blockchain verification (if anchoring enabled)
        
        Args:
            article_id: Article identifier
            expected_content_hash: Optional expected content hash
            expected_metadata_hash: Optional expected metadata hash
            expected_source_hash: Optional expected source hash
            
        Returns:
            VerificationResult with detailed verification information
        """
        warnings = []
        local_verification = {}
        blockchain_verifications = {}
        
        # Get article info
        article_info = self.hash_chain.get_article_hashes(article_id)
        if not article_info:
            return VerificationResult(
                article_id=article_id,
                verified=False,
                local_verification={'article_exists': False},
                warnings=[f"Article {article_id} not found in hash chain"]
            )
        
        # 1. Verify hashes match expected values
        content_match = True
        metadata_match = True
        source_match = True
        
        if expected_content_hash is not None:
            content_match = (article_info['content_hash'] == expected_content_hash)
            local_verification['content_hash_match'] = content_match
        
        if expected_metadata_hash is not None:
            metadata_match = (article_info['metadata_hash'] == expected_metadata_hash)
            local_verification['metadata_hash_match'] = metadata_match
        
        if expected_source_hash is not None:
            source_match = (article_info['source_hash'] == expected_source_hash)
            local_verification['source_hash_match'] = source_match
        
        # 2. Get Merkle proof and verify it
        merkle_proof_data = self.hash_chain.get_merkle_proof(article_id)
        if merkle_proof_data:
            # Verify the Merkle proof
            proof_tuples = [
                (p['hash'], p['is_right_sibling'])
                for p in merkle_proof_data['merkle_proof']
            ]
            
            from src.crypto.merkle_tree import MerkleTree
            # Use the hash_chain's verify_article_with_proof which handles the verification
            merkle_proof_valid = self.hash_chain.verify_article_with_proof(
                article_id,
                article_info['content_hash'],
                article_info['metadata_hash'],
                article_info['source_hash'],
                merkle_proof_data['merkle_proof'],
                merkle_proof_data['merkle_root']
            )
            local_verification['merkle_proof_valid'] = merkle_proof_valid
        else:
            merkle_proof_valid = False
            warnings.append(f"Could not generate Merkle proof for article {article_id}")
        
        # 3. Verify block chain integrity
        block_chain_intact = self.hash_chain.verify_block_chain_integrity()
        local_verification['block_chain_intact'] = block_chain_intact
        
        # 4. Blockchain verification (if enabled)
        if self.settings and self.settings.anchoring.enabled:
            block_height = article_info['block_height']
            block = self.hash_chain.get_block(block_height)
            if block:
                for provider_name, provider in self.providers.items():
                    try:
                        # Verify the block's Merkle root was anchored
                        result = provider.verify_anchor(
                            block.merkle_root,
                            block_height
                        )
                        blockchain_verifications[provider_name] = {
                            'verified': result,
                            'provider': provider_name
                        }
                    except Exception as e:
                        blockchain_verifications[provider_name] = {
                            'verified': False,
                            'provider': provider_name,
                            'error': str(e)
                        }
                        warnings.append(f"Blockchain verification failed for {provider_name}: {e}")
        
        # Determine overall verification result
        all_local_ok = all(local_verification.values()) if local_verification else True
        all_blockchain_ok = all(
            v.get('verified', False) 
            for v in blockchain_verifications.values()
        ) if blockchain_verifications else True
        
        # If no expected hashes were provided, we can't verify content
        if (expected_content_hash is None and 
            expected_metadata_hash is None and 
            expected_source_hash is None):
            # We can only verify the article exists and the chain is intact
            verified = (article_info is not None and 
                       merkle_proof_valid and 
                       block_chain_intact)
        else:
            verified = (content_match and metadata_match and source_match and
                       merkle_proof_valid and block_chain_intact)
        
        return VerificationResult(
            article_id=article_id,
            verified=verified,
            local_verification=local_verification,
            blockchain_verifications=blockchain_verifications,
            merkle_proof=merkle_proof_data['merkle_proof'] if merkle_proof_data else None,
            block_height=article_info['block_height'],
            position=article_info['position'],
            warnings=warnings
        )
    
    def verify_article_with_proof(self, article_id: str,
                                 expected_content_hash: str,
                                 expected_metadata_hash: str,
                                 expected_source_hash: str,
                                 merkle_proof: List[Dict[str, Any]],
                                 merkle_root: str) -> bool:
        """
        Verify an article using a provided Merkle proof.
        
        This allows decentralized verification without accessing the local database.
        
        Args:
            article_id: Article identifier
            expected_content_hash: Expected content hash
            expected_metadata_hash: Expected metadata hash
            expected_source_hash: Expected source hash
            merkle_proof: Merkle proof for the article
            merkle_root: Expected Merkle root
            
        Returns:
            True if verification succeeds, False otherwise
        """
        return self.hash_chain.verify_article_with_proof(
            article_id,
            expected_content_hash,
            expected_metadata_hash,
            expected_source_hash,
            merkle_proof,
            merkle_root
        )
    
    def get_article_verification_data(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Get all data needed to verify an article.
        
        Returns all information required for a third party to independently
        verify the article using Merkle proofs.
        
        Args:
            article_id: Article identifier
            
        Returns:
            Dictionary with hashes, block info, and Merkle proof, or None if not found
        """
        # Get Merkle proof
        merkle_proof_data = self.hash_chain.get_merkle_proof(article_id)
        if not merkle_proof_data:
            return None
        
        # Get article hashes
        article_info = self.hash_chain.get_article_hashes(article_id)
        if not article_info:
            return None
        
        # Get block info
        block = self.hash_chain.get_block(article_info['block_height'])
        if not block:
            return None
        
        return {
            'article_id': article_id,
            'content_hash': article_info['content_hash'],
            'metadata_hash': article_info['metadata_hash'],
            'source_hash': article_info['source_hash'],
            'block_height': article_info['block_height'],
            'position': article_info['position'],
            'timestamp': article_info['timestamp'],
            'merkle_proof': merkle_proof_data['merkle_proof'],
            'merkle_root': merkle_proof_data['merkle_root'],
            'block_hash': merkle_proof_data['block_hash'],
            'previous_block_hash': merkle_proof_data['previous_block_hash']
        }
    
    def anchor_current_block(self) -> Dict[str, Any]:
        """
        Anchor the current block's Merkle root to configured blockchains.
        
        This is typically called automatically or on a schedule.
        Also logs Chain of Custody entries for each article in the anchored block.
        
        Returns:
            Dictionary with anchoring results for each provider
        """
        if not self.settings or not self.settings.anchoring.enabled:
            return {'error': 'Anchoring is disabled'}
        
        # Get the latest block
        cursor = self.hash_chain.connection.cursor()
        cursor.execute("SELECT MAX(block_height) FROM blocks")
        max_height = cursor.fetchone()[0]
        
        if max_height is None:
            return {'error': 'No blocks to anchor'}
        
        block = self.hash_chain.get_block(max_height)
        if not block:
            return {'error': f'Block {max_height} not found'}
        
        results = {}
        for provider_name, provider in self.providers.items():
            try:
                # Anchor the Merkle root
                anchor_data = {
                    'block_height': block.block_height,
                    'merkle_root': block.merkle_root,
                    'article_count': block.article_count,
                    'timestamp': block.timestamp,
                    'block_hash': block.block_hash
                }
                
                transaction_hash = provider.anchor_hash(
                    block.merkle_root,
                    anchor_data
                )
                
                results[provider_name] = {
                    'success': True,
                    'transaction_hash': transaction_hash,
                    'block_height': block.block_height,
                    'merkle_root': block.merkle_root
                }
                
                # Log Chain of Custody ANCHOR action for each article in the block
                try:
                    from src.blockchain.core.coc import get_coc_logger, CoCAction
                    coc_logger = get_coc_logger()
                    for article_id in block.articles:
                        article_hashes = self.hash_chain.get_article_hashes(article_id)
                        if article_hashes:
                            coc_logger.log_action(
                                article_id=article_id,
                                article_hash=article_hashes['content_hash'],
                                action=CoCAction.ANCHOR,
                                actor_id=f"anchor_service:{provider_name}",
                                metadata={
                                    'block_height': block.block_height,
                                    'provider': provider_name,
                                    'transaction_hash': transaction_hash,
                                    'merkle_root': block.merkle_root
                                }
                            )
                except Exception as coc_e:
                    # Log warning but don't fail anchoring
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Failed to log CoC ANCHOR entries: {coc_e}")
                    
            except Exception as e:
                results[provider_name] = {
                    'success': False,
                    'error': str(e)
                }
        
        return results
    
    def get_anchors(self, block_height: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get all blockchain anchors.
        
        Args:
            block_height: Optional block height to filter by
            
        Returns:
            List of anchor records
        """
        anchors = []
        
        for provider_name, provider in self.providers.items():
            try:
                provider_anchors = provider.get_all_anchors()
                for anchor in provider_anchors:
                    if block_height is None or anchor.get('block_height') == block_height:
                        anchor['provider'] = provider_name
                        anchors.append(anchor)
            except Exception:
                continue
        
        return anchors
    
    def close(self) -> None:
        """Close the anchor service and its resources."""
        for provider in self.providers.values():
            try:
                provider.close()
            except Exception:
                pass
        self.providers.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
