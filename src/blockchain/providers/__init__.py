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
Blockchain Providers for Open-Omniscience

Provides interfaces and implementations for various blockchain providers:
- Local: SQLite-based offline anchoring
- Ethereum: Smart contract anchoring
- IPFS: Decentralized storage anchoring
- Arweave: Permanent storage anchoring

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from typing import List, Dict, Any

from .base import BaseBlockchainProvider
from .local import LocalProvider
from .ethereum import EthereumProvider
from .ipfs import IPFSProvider
from .arweave import ArweaveProvider

# Provider registry
_PROVIDERS: Dict[str, type] = {
    'local': LocalProvider,
    'ethereum': EthereumProvider,
    'ipfs': IPFSProvider,
    'arweave': ArweaveProvider
}


def get_provider(provider_name: str, **kwargs) -> BaseBlockchainProvider:
    """
    Get a blockchain provider instance by name.
    
    Args:
        provider_name: Name of the provider (local, ethereum, ipfs, arweave)
        **kwargs: Additional arguments to pass to the provider constructor
        
    Returns:
        Provider instance
        
    Raises:
        ValueError: If provider name is not recognized
    """
    provider_class = _PROVIDERS.get(provider_name.lower())
    if provider_class is None:
        raise ValueError(f"Unknown blockchain provider: {provider_name}")
    
    return provider_class(**kwargs)


def register_provider(provider_name: str, provider_class: type) -> None:
    """
    Register a custom blockchain provider.
    
    Args:
        provider_name: Name to register the provider under
        provider_class: Provider class (must inherit from BaseBlockchainProvider)
    """
    _PROVIDERS[provider_name.lower()] = provider_class


def get_available_providers() -> List[str]:
    """Get list of available provider names."""
    return list(_PROVIDERS.keys())


__all__ = [
    'BaseBlockchainProvider',
    'LocalProvider',
    'EthereumProvider',
    'IPFSProvider',
    'ArweaveProvider',
    'get_provider',
    'register_provider',
    'get_available_providers'
]
