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
Ethereum Blockchain Provider for Open-Omniscience

Provides anchoring of block Merkle roots to Ethereum smart contracts.
This enables decentralized verification using the Ethereum blockchain.

Note: This provider requires web3.py and an Ethereum node connection.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import json
import time
from typing import Dict, Any, List, Optional

from .base import BaseBlockchainProvider


class EthereumProvider(BaseBlockchainProvider):
    """
    Ethereum blockchain provider.
    
    Anchors block Merkle roots to an Ethereum smart contract for
    decentralized verification.
    """
    
    def __init__(self, contract_address: str = None, 
                 rpc_url: str = "http://localhost:8545",
                 private_key: str = None,
                 contract_abi: Optional[List[Dict[str, Any]]] = None):
        """
        Initialize the Ethereum provider.
        
        Args:
            contract_address: Address of the OpenOmniscienceAnchor smart contract
            rpc_url: Ethereum node RPC URL
            private_key: Private key for signing transactions
            contract_abi: ABI of the smart contract
        """
        self.contract_address = contract_address
        self.rpc_url = rpc_url
        self.private_key = private_key
        self.contract_abi = contract_abi or self._get_default_abi()
        self._initialized = False
        
        # Try to initialize web3
        self._initialize_web3()
    
    def _get_default_abi(self) -> List[Dict[str, Any]]:
        """Get the default ABI for OpenOmniscienceAnchor contract."""
        return [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "merkleRoot", "type": "bytes32"},
                    {"indexed": False, "name": "timestamp", "type": "uint256"},
                    {"indexed": False, "name": "articleCount", "type": "uint256"},
                    {"indexed": False, "name": "metadataCID", "type": "string"}
                ],
                "name": "AnchorCreated",
                "type": "event"
            },
            {
                "constant": False,
                "inputs": [
                    {"name": "merkleRoot", "type": "bytes32"},
                    {"name": "timestamp", "type": "uint256"},
                    {"name": "articleCount", "type": "uint256"},
                    {"name": "metadataCID", "type": "string"}
                ],
                "name": "anchor",
                "outputs": [],
                "payable": False,
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [
                    {"name": "merkleRoot", "type": "bytes32"}
                ],
                "name": "getAnchor",
                "outputs": [
                    {"name": "", "type": "uint256"},
                    {"name": "", "type": "uint256"},
                    {"name": "", "type": "string"}
                ],
                "payable": False,
                "stateMutability": "view",
                "type": "function"
            }
        ]
    
    def _initialize_web3(self) -> None:
        """Initialize web3 connection."""
        try:
            import web3
            self.w3 = web3.Web3(web3.HTTPProvider(self.rpc_url))
            self._initialized = self.w3.is_connected()
            
            if self._initialized and self.contract_address:
                self.contract = self.w3.eth.contract(
                    address=self.contract_address,
                    abi=self.contract_abi
                )
        except ImportError:
            # web3 not installed
            self._initialized = False
            self.w3 = None
            self.contract = None
        except Exception as e:
            # Connection failed
            self._initialized = False
            self.w3 = None
            self.contract = None
    
    def anchor_hash(self, merkle_root: str, metadata: Dict[str, Any]) -> str:
        """
        Anchor a Merkle root to Ethereum.
        
        Args:
            merkle_root: The Merkle root hash to anchor
            metadata: Additional metadata
            
        Returns:
            Transaction hash
            
        Raises:
            Exception: If anchoring fails or web3 is not available
        """
        if not self._initialized or not self.contract:
            raise Exception("Ethereum provider not initialized. Check RPC connection and contract address.")
        
        if not self.private_key:
            raise Exception("Private key required for signing transactions")
        
        # Convert merkle_root to bytes32
        merkle_root_bytes = self._hex_to_bytes32(merkle_root)
        
        # Extract metadata
        timestamp = metadata.get('timestamp', int(time.time()))
        article_count = metadata.get('article_count', 0)
        
        # For metadata CID, we could store additional data on IPFS
        # For now, just use a hash of the metadata
        metadata_cid = self._compute_metadata_cid(metadata)
        
        # Get the account from private key
        account = self.w3.eth.account.from_key(self.private_key)
        
        # Build and send transaction
        tx = self.contract.functions.anchor(
            merkle_root_bytes,
            timestamp,
            article_count,
            metadata_cid
        ).build_transaction({
            'from': account.address,
            'nonce': self.w3.eth.get_transaction_count(account.address),
            'gas': 200000,
            'gasPrice': self.w3.eth.gas_price
        })
        
        signed_tx = account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        return tx_hash.hex()
    
    def verify_anchor(self, merkle_root: str, block_height: Optional[int] = None) -> bool:
        """
        Verify that a Merkle root was anchored to Ethereum.
        
        Args:
            merkle_root: The Merkle root to verify
            block_height: Optional block height (not used for Ethereum)
            
        Returns:
            True if the Merkle root was found in the contract, False otherwise
        """
        if not self._initialized or not self.contract:
            return False
        
        try:
            merkle_root_bytes = self._hex_to_bytes32(merkle_root)
            
            # Call the contract's getAnchor function
            result = self.contract.functions.getAnchor(merkle_root_bytes).call()
            
            # If we get a result (timestamp > 0), the anchor exists
            return result[0] > 0
        except Exception:
            return False
    
    def get_anchor_data(self, transaction_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve anchored data by transaction hash.
        
        Args:
            transaction_hash: The Ethereum transaction hash
            
        Returns:
            Dictionary with anchor data or None if not found
        """
        if not self._initialized or not self.w3:
            return None
        
        try:
            # Get transaction receipt
            receipt = self.w3.eth.get_transaction_receipt(transaction_hash)
            
            if not receipt:
                return None
            
            # Parse the AnchorCreated event
            for log in receipt.logs:
                try:
                    event = self.contract.events.AnchorCreated().processReceipt(
                        receipt, errors=web3.exceptions.Discard
                    )
                    if event:
                        # Found the event
                        merkle_root_hex = event[0].args.merkleRoot.hex()
                        timestamp = event[0].args.timestamp
                        article_count = event[0].args.articleCount
                        metadata_cid = event[0].args.metadataCID
                        
                        return {
                            'transaction_hash': transaction_hash,
                            'merkle_root': merkle_root_hex,
                            'timestamp': timestamp,
                            'article_count': article_count,
                            'metadata_cid': metadata_cid,
                            'block_number': receipt.blockNumber
                        }
                except Exception:
                    continue
            
            return None
        except Exception:
            return None
    
    def get_all_anchors(self) -> List[Dict[str, Any]]:
        """
        Get all anchors from the Ethereum contract.
        
        Note: This requires scanning all events, which can be slow for
        contracts with many anchors.
        
        Returns:
            List of anchor records
        """
        if not self._initialized or not self.contract:
            return []
        
        try:
            # Get all AnchorCreated events
            events = self.contract.events.AnchorCreated().get_logs(
                fromBlock=0, toBlock='latest'
            )
            
            anchors = []
            for event in events:
                anchors.append({
                    'transaction_hash': event.transactionHash.hex(),
                    'merkle_root': event.args.merkleRoot.hex(),
                    'timestamp': event.args.timestamp,
                    'article_count': event.args.articleCount,
                    'metadata_cid': event.args.metadataCID,
                    'block_number': event.blockNumber
                })
            
            return anchors
        except Exception:
            return []
    
    def _hex_to_bytes32(self, hex_string: str) -> bytes:
        """Convert a hex string to bytes32."""
        # Remove 0x prefix if present
        if hex_string.startswith('0x'):
            hex_string = hex_string[2:]
        
        # Pad to 64 characters (32 bytes)
        hex_string = hex_string.zfill(64)
        
        return bytes.fromhex(hex_string)
    
    def _compute_metadata_cid(self, metadata: Dict[str, Any]) -> str:
        """Compute a CID-like hash for metadata."""
        metadata_json = json.dumps(metadata, sort_keys=True)
        return hashlib.sha256(metadata_json.encode()).hexdigest()
    
    def close(self) -> None:
        """Close the provider."""
        self._initialized = False
        self.w3 = None
        self.contract = None


# Import web3 for type hints (optional)
try:
    import web3
except ImportError:
    web3 = None
