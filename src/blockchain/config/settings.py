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
Blockchain Settings for Open-Omniscience

Provides configuration dataclasses for the blockchain module.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import yaml
from pathlib import Path


@dataclass
class LocalChainSettings:
    """Settings for the local hash chain."""
    
    enabled: bool = True
    db_path: str = "data/blockchain/local_hash_chain.db"
    articles_per_block: int = 100
    time_per_block: int = 86400  # 24 hours in seconds


@dataclass
class AnchoringSettings:
    """Settings for blockchain anchoring."""
    
    enabled: bool = True
    interval: int = 86400  # Seconds between anchors (24h)
    providers: List[str] = field(default_factory=lambda: ['local'])
    
    # Ethereum-specific settings
    ethereum: Dict[str, Any] = field(default_factory=dict)
    
    # IPFS-specific settings
    ipfs: Dict[str, Any] = field(default_factory=dict)
    
    # Arweave-specific settings
    arweave: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BlockchainSettings:
    """Main blockchain settings."""
    
    enabled: bool = True
    local_chain: LocalChainSettings = field(default_factory=LocalChainSettings)
    anchoring: AnchoringSettings = field(default_factory=AnchoringSettings)
    
    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'BlockchainSettings':
        """
        Load settings from a YAML file.
        
        Args:
            yaml_path: Path to YAML configuration file
            
        Returns:
            BlockchainSettings instance
        """
        path = Path(yaml_path)
        if not path.exists():
            return cls()  # Return defaults if file doesn't exist
        
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
        
        # Get blockchain config or empty dict
        blockchain_config = data.get('blockchain', {})
        
        # Build settings
        local_chain_config = blockchain_config.get('local_chain', {})
        local_chain = LocalChainSettings(
            enabled=local_chain_config.get('enabled', True),
            db_path=local_chain_config.get('db_path', LocalChainSettings.db_path),
            articles_per_block=local_chain_config.get('articles_per_block', LocalChainSettings.articles_per_block),
            time_per_block=local_chain_config.get('time_per_block', LocalChainSettings.time_per_block)
        )
        
        anchoring_config = blockchain_config.get('anchoring', {})
        anchoring = AnchoringSettings(
            enabled=anchoring_config.get('enabled', True),
            interval=anchoring_config.get('interval', AnchoringSettings.interval),
            providers=anchoring_config.get('providers', AnchoringSettings.providers),
            ethereum=anchoring_config.get('ethereum', {}),
            ipfs=anchoring_config.get('ipfs', {}),
            arweave=anchoring_config.get('arweave', {})
        )
        
        return cls(
            enabled=blockchain_config.get('enabled', True),
            local_chain=local_chain,
            anchoring=anchoring
        )
    
    def to_yaml(self, yaml_path: str) -> None:
        """
        Save settings to a YAML file.
        
        Args:
            yaml_path: Path to save YAML configuration
        """
        data = {
            'blockchain': {
                'enabled': self.enabled,
                'local_chain': {
                    'enabled': self.local_chain.enabled,
                    'db_path': self.local_chain.db_path,
                    'articles_per_block': self.local_chain.articles_per_block,
                    'time_per_block': self.local_chain.time_per_block
                },
                'anchoring': {
                    'enabled': self.anchoring.enabled,
                    'interval': self.anchoring.interval,
                    'providers': self.anchoring.providers,
                    'ethereum': self.anchoring.ethereum,
                    'ipfs': self.anchoring.ipfs,
                    'arweave': self.anchoring.arweave
                }
            }
        }
        
        path = Path(yaml_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BlockchainSettings':
        """
        Create settings from a dictionary.
        
        Args:
            data: Dictionary with settings data
            
        Returns:
            BlockchainSettings instance
        """
        blockchain_config = data.get('blockchain', {})
        
        local_chain_config = blockchain_config.get('local_chain', {})
        local_chain = LocalChainSettings(
            enabled=local_chain_config.get('enabled', True),
            db_path=local_chain_config.get('db_path', LocalChainSettings.db_path),
            articles_per_block=local_chain_config.get('articles_per_block', LocalChainSettings.articles_per_block),
            time_per_block=local_chain_config.get('time_per_block', LocalChainSettings.time_per_block)
        )
        
        anchoring_config = blockchain_config.get('anchoring', {})
        anchoring = AnchoringSettings(
            enabled=anchoring_config.get('enabled', True),
            interval=anchoring_config.get('interval', AnchoringSettings.interval),
            providers=anchoring_config.get('providers', AnchoringSettings.providers),
            ethereum=anchoring_config.get('ethereum', {}),
            ipfs=anchoring_config.get('ipfs', {}),
            arweave=anchoring_config.get('arweave', {})
        )
        
        return cls(
            enabled=blockchain_config.get('enabled', True),
            local_chain=local_chain,
            anchoring=anchoring
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            'blockchain': {
                'enabled': self.enabled,
                'local_chain': {
                    'enabled': self.local_chain.enabled,
                    'db_path': self.local_chain.db_path,
                    'articles_per_block': self.local_chain.articles_per_block,
                    'time_per_block': self.local_chain.time_per_block
                },
                'anchoring': {
                    'enabled': self.anchoring.enabled,
                    'interval': self.anchoring.interval,
                    'providers': self.anchoring.providers,
                    'ethereum': self.anchoring.ethereum,
                    'ipfs': self.anchoring.ipfs,
                    'arweave': self.anchoring.arweave
                }
            }
        }
