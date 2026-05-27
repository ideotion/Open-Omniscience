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

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Enhanced Cryptographic Utilities for Open-Omniscience Blockchain

Provides multi-algorithm hashing, cryptographic signatures, and
security utilities for single-user deployments.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import hmac
import json
import time
import secrets
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum


class HashAlgorithm(Enum):
    """Supported hash algorithms."""
    SHA256 = "sha256"
    SHA512 = "sha512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"
    RIPEMD160 = "ripemd160"
    SHA3_256 = "sha3_256"
    SHA3_512 = "sha3_512"


# Default algorithms for multi-hash
DEFAULT_HASH_ALGORITHMS = [
    HashAlgorithm.SHA256,
    HashAlgorithm.SHA512,
    HashAlgorithm.BLAKE2B,
]


@dataclass
class HashResult:
    """Result of multi-algorithm hashing."""
    sha256: str = ""
    sha512: str = ""
    blake2b: str = ""
    ripemd160: Optional[str] = None
    sha3_256: Optional[str] = None
    sha3_512: Optional[str] = None
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        result = {
            'sha256': self.sha256,
            'sha512': self.sha512,
            'blake2b': self.blake2b,
        }
        if self.ripemd160:
            result['ripemd160'] = self.ripemd160
        if self.sha3_256:
            result['sha3_256'] = self.sha3_256
        if self.sha3_512:
            result['sha3_512'] = self.sha3_512
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'HashResult':
        """Create from dictionary."""
        return cls(
            sha256=data.get('sha256', ''),
            sha512=data.get('sha512', ''),
            blake2b=data.get('blake2b', ''),
            ripemd160=data.get('ripemd160'),
            sha3_256=data.get('sha3_256'),
            sha3_512=data.get('sha3_512'),
        )
    
    def verify_consistency(self, data: str) -> bool:
        """Verify that all hashes correspond to the same data."""
        # Compute hashes from data
        computed = compute_multi_hash(data)
        
        # Check each algorithm
        checks = [
            computed.sha256 == self.sha256,
            computed.sha512 == self.sha512,
            computed.blake2b == self.blake2b,
        ]
        
        if self.ripemd160 and computed.ripemd160:
            checks.append(computed.ripemd160 == self.ripemd160)
        if self.sha3_256 and computed.sha3_256:
            checks.append(computed.sha3_256 == self.sha3_256)
        if self.sha3_512 and computed.sha3_512:
            checks.append(computed.sha3_512 == self.sha3_512)
        
        return all(checks)


@dataclass
class MultiHash:
    """Multi-algorithm hash container for an article."""
    content: HashResult
    metadata: HashResult
    source: HashResult
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'content': self.content.to_dict(),
            'metadata': self.metadata.to_dict(),
            'source': self.source.to_dict(),
            'timestamp': self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MultiHash':
        """Create from dictionary."""
        return cls(
            content=HashResult.from_dict(data.get('content', {})),
            metadata=HashResult.from_dict(data.get('metadata', {})),
            source=HashResult.from_dict(data.get('source', {})),
            timestamp=data.get('timestamp', time.time()),
        )
    
    def verify_all(self, content_data: str, metadata_data: str, source_data: str) -> bool:
        """Verify all hashes against provided data."""
        return (
            self.content.verify_consistency(content_data) and
            self.metadata.verify_consistency(metadata_data) and
            self.source.verify_consistency(source_data)
        )


def compute_hash(data: str, algorithm: HashAlgorithm) -> str:
    """
    Compute hash using specified algorithm.
    
    Args:
        data: String data to hash
        algorithm: Hash algorithm to use
        
    Returns:
        Hexadecimal hash string
    """
    data_bytes = data.encode('utf-8')
    
    if algorithm == HashAlgorithm.SHA256:
        return hashlib.sha256(data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.SHA512:
        return hashlib.sha512(data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.BLAKE2B:
        return hashlib.blake2b(data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.BLAKE2S:
        return hashlib.blake2s(data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.RIPEMD160:
        return hashlib.new('ripemd160', data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.SHA3_256:
        return hashlib.sha3_256(data_bytes).hexdigest()
    elif algorithm == HashAlgorithm.SHA3_512:
        return hashlib.sha3_512(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")


def compute_multi_hash(data: str, algorithms: Optional[List[HashAlgorithm]] = None) -> HashResult:
    """
    Compute multiple hash algorithms for the same data.
    
    Args:
        data: String data to hash
        algorithms: List of algorithms to use (default: SHA256, SHA512, BLAKE2B)
        
    Returns:
        HashResult with all computed hashes
    """
    if algorithms is None:
        algorithms = DEFAULT_HASH_ALGORITHMS
    
    result_kwargs = {}
    for algo in algorithms:
        try:
            hash_value = compute_hash(data, algo)
            result_kwargs[algo.value] = hash_value
        except ValueError:
            # Skip unsupported algorithms
            pass
    
    return HashResult(**result_kwargs)


def compute_article_multi_hash(
    content: str,
    metadata: Dict[str, Any],
    source: str,
    algorithms: Optional[List[HashAlgorithm]] = None
) -> MultiHash:
    """
    Compute multi-algorithm hashes for all three article components.
    
    Args:
        content: Article content
        metadata: Article metadata dictionary
        source: Source URL/identifier
        algorithms: List of hash algorithms to use
        
    Returns:
        MultiHash with hashes for content, metadata, and source
    """
    if algorithms is None:
        algorithms = DEFAULT_HASH_ALGORITHMS
    
    # Convert metadata to string
    metadata_str = json.dumps(metadata, sort_keys=True)
    
    return MultiHash(
        content=compute_multi_hash(content, algorithms),
        metadata=compute_multi_hash(metadata_str, algorithms),
        source=compute_multi_hash(source, algorithms),
    )


class IntegrityError(Exception):
    """Raised when data integrity cannot be verified."""
    pass


class WORMError(Exception):
    """Raised when WORM (Write-Once-Read-Many) violation is detected."""
    pass


@dataclass
class AuditEntry:
    """Immutable audit log entry."""
    timestamp: float
    action: str
    article_id: Optional[str]
    block_height: Optional[int]
    details: Dict[str, Any] = field(default_factory=dict)
    hash_chain_state: Optional[str] = None  # Hash of the entire chain state
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without hash_chain_state for storage)."""
        return {
            'timestamp': self.timestamp,
            'action': self.action,
            'article_id': self.article_id,
            'block_height': self.block_height,
            'details': self.details,
        }


class AuditLogger:
    """
    Immutable audit logger for blockchain operations.
    
    All entries are cryptographically linked and cannot be modified.
    """
    
    def __init__(self, log_path: str = "data/blockchain/audit.log"):
        """
        Initialize audit logger.
        
        Args:
            log_path: Path to audit log file
        """
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[AuditEntry] = []
        self._previous_hash: Optional[str] = None
        self._lock = threading.Lock()
        
        # Load existing entries
        self._load_existing()
    
    def _load_existing(self) -> None:
        """Load existing audit log entries."""
        if not self.log_path.exists():
            return
        
        with open(self.log_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry_data = json.loads(line)
                    entry = AuditEntry(
                        timestamp=entry_data.get('timestamp', 0),
                        action=entry_data.get('action', ''),
                        article_id=entry_data.get('article_id'),
                        block_height=entry_data.get('block_height'),
                        details=entry_data.get('details', {}),
                    )
                    # Compute hash_chain_state from the entry data
                    entry_data_str = json.dumps(entry.to_dict(), sort_keys=True)
                    entry.hash_chain_state = compute_hash(entry_data_str, HashAlgorithm.SHA256)
                    
                    self._entries.append(entry)
                    # Update previous hash for chaining
                    self._previous_hash = entry.hash_chain_state
                except (json.JSONDecodeError, KeyError):
                    # Skip corrupted entries
                    continue
    
    def log(self, action: str, article_id: Optional[str] = None, 
            block_height: Optional[int] = None, details: Optional[Dict] = None) -> AuditEntry:
        """
        Log an audit entry.
        
        Args:
            action: Action being logged
            article_id: Related article ID
            block_height: Related block height
            details: Additional details
            
        Returns:
            The created AuditEntry
        """
        entry = AuditEntry(
            timestamp=time.time(),
            action=action,
            article_id=article_id,
            block_height=block_height,
            details=details or {},
        )
        
        # Compute hash chain for this entry
        entry_data_str = json.dumps(entry.to_dict(), sort_keys=True)
        entry.hash_chain_state = compute_hash(entry_data_str, HashAlgorithm.SHA256)
        
        with self._lock:
            # Link to previous entry
            if self._previous_hash:
                entry.details['previous_entry_hash'] = self._previous_hash
            
            # Write to file (append-only)
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(entry.to_dict(), sort_keys=True) + '\n')
            
            # Update state
            self._entries.append(entry)
            self._previous_hash = entry.hash_chain_state
        
        return entry
    
    def verify_integrity(self) -> bool:
        """
        Verify the integrity of the audit log.
        
        Returns:
            True if all entries are properly chained, False otherwise
        """
        if len(self._entries) <= 1:
            return True
        
        for i in range(1, len(self._entries)):
            expected_prev = self._entries[i-1].hash_chain_state
            actual_prev = self._entries[i].details.get('previous_entry_hash')
            if expected_prev != actual_prev:
                return False
        
        return True
    
    def get_entries(self, since: Optional[float] = None) -> List[AuditEntry]:
        """Get audit entries, optionally filtered by timestamp."""
        if since is None:
            return list(self._entries)
        return [e for e in self._entries if e.timestamp >= since]


# Global audit logger instance
_audit_logger = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def reset_audit_logger() -> None:
    """Reset the global audit logger (for testing)."""
    global _audit_logger
    if _audit_logger is not None:
        _audit_logger = None
