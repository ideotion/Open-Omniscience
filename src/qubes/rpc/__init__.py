"""
Qubes RPC module for Open-Omniscience.

This module provides RPC communication between different qubes in a Qubes OS environment.
It allows secure, isolated components to communicate with each other.
"""

from .server import QubesRPCServer
from .client import QubesRPCClient, RPCClientConfig

__all__ = ['QubesRPCServer', 'QubesRPCClient', 'RPCClientConfig']
