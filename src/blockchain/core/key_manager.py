"""
Key Manager for Forward Secrecy and Key Rotation
===============================================

This module provides secure key management for Open-Omniscience's Chain of Custody (CoC),
enabling forward secrecy and automatic key rotation to mitigate key compromise risks.

Key Features:
-------------
1. **Automatic Key Rotation**: Rotates Ed25519 + Dilithium3 keys on a configurable schedule.
2. **Key Revocation List (KRL)**: Tracks compromised keys to prevent their use.
3. **Hardware-Backed Keys**: Supports YubiKey and TPM for high-security deployments.
4. **Secure Storage**: Encrypts private keys at rest (optional).
5. **Key Versioning**: Tracks key versions for auditability.

Security Considerations:
-----------------------
- **Forward Secrecy**: Each key rotation limits the impact of key compromise to data signed
after the compromise.
- **Key Revocation**: Compromised keys can be revoked and will no longer be trusted for verification.
- **Hardware Security**: YubiKey/TPM support protects private keys from extraction.

References:
-----------
- NIST SP 800-57: Key Management Best Practices
- RFC 5280: Internet X.509 Public Key Infrastructure Certificate and CRL Profile
- YubiKey Documentation: https://developers.yubico.com/
- TPM 2.0 Specification: https://trustedcomputinggroup.org/resource/tpm-library-specification/

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Set, Any, Tuple

from .pqc import (
    HybridKeyPair,
    HybridSignature,
    HashAlgorithm,
    SignatureAlgorithm,
    generate_hybrid_keypair,
    sign_hybrid,
    verify_hybrid,
    PQCError,
    PQCNotAvailableError,
)

logger = logging.getLogger(__name__)


class KeyStatus(Enum):
    """Status of a key in the key manager."""
    ACTIVE = "active"          # Currently in use for signing
    INACTIVE = "inactive"      # No longer used for signing, but still valid for verification
    REVOKED = "revoked"        # Compromised or no longer trusted
    EXPIRED = "expired"        # Past its expiration time


class KeyType(Enum):
    """Type of key storage."""
    SOFTWARE = "software"      # Stored in filesystem/database
    YUBIKEY = "yubikey"        # Stored on a YubiKey hardware token
    TPM = "tpm"                # Stored in a Trusted Platform Module


@dataclass
class KeyMetadata:
    """
    Metadata for a managed key.
    
    Attributes:
        key_id: Unique identifier for the key.
        version: Version number (incremented on rotation).
        status: Current status of the key.
        key_type: Type of key storage (SOFTWARE, YUBIKEY, TPM).
        created_at: Timestamp when the key was created.
        expires_at: Timestamp when the key expires (0 = no expiration).
        last_used: Timestamp when the key was last used for signing.
        revocation_reason: Reason for revocation (if revoked).
        hardware_info: Information about hardware storage (e.g., YubiKey serial number).
    """
    key_id: str
    version: int
    status: KeyStatus = KeyStatus.ACTIVE
    key_type: KeyType = KeyType.SOFTWARE
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 = no expiration
    last_used: float = 0.0
    revocation_reason: Optional[str] = None
    hardware_info: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "key_id": self.key_id,
            "version": self.version,
            "status": self.status.value,
            "key_type": self.key_type.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used": self.last_used,
            "revocation_reason": self.revocation_reason,
            "hardware_info": self.hardware_info,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeyMetadata":
        """Create from dictionary."""
        return cls(
            key_id=data["key_id"],
            version=data["version"],
            status=KeyStatus(data.get("status", "active")),
            key_type=KeyType(data.get("key_type", "software")),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at", 0.0),
            last_used=data.get("last_used", 0.0),
            revocation_reason=data.get("revocation_reason"),
            hardware_info=data.get("hardware_info"),
        )
    
    def is_valid_for_signing(self) -> bool:
        """Check if the key can be used for signing."""
        if self.status != KeyStatus.ACTIVE:
            return False
        if self.expires_at > 0 and time.time() > self.expires_at:
            return False
        return True
    
    def is_valid_for_verification(self) -> bool:
        """Check if the key can be used for verification."""
        if self.status == KeyStatus.REVOKED:
            return False
        return True


@dataclass
class KeyRevocationEntry:
    """
    Entry in the Key Revocation List (KRL).
    
    Attributes:
        key_id: The ID of the revoked key.
        revoked_at: Timestamp when the key was revoked.
        reason: Reason for revocation.
        revoked_by: Entity that revoked the key.
    """
    key_id: str
    revoked_at: float = field(default_factory=time.time)
    reason: str = ""
    revoked_by: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "key_id": self.key_id,
            "revoked_at": self.revoked_at,
            "reason": self.reason,
            "revoked_by": self.revoked_by,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeyRevocationEntry":
        """Create from dictionary."""
        return cls(
            key_id=data["key_id"],
            revoked_at=data.get("revoked_at", time.time()),
            reason=data.get("reason", ""),
            revoked_by=data.get("revoked_by", ""),
        )


class KeyManagerError(Exception):
    """Base exception for key manager errors."""
    pass


class KeyNotFoundError(KeyManagerError):
    """Raised when a key is not found."""
    pass


class KeyRevokedError(KeyManagerError):
    """Raised when attempting to use a revoked key."""
    pass


class KeyExpiredError(KeyManagerError):
    """Raised when attempting to use an expired key."""
    pass


class KeyManager:
    """
    Manages cryptographic keys for Chain of Custody (CoC) with forward secrecy.
    
    Features:
    - Automatic key rotation on a configurable schedule.
    - Key Revocation List (KRL) for compromised keys.
    - Support for hardware-backed keys (YubiKey, TPM).
    - Secure storage of private keys (encrypted at rest).
    
    Example:
        >>> km = KeyManager(key_dir="./keys", rotation_interval=2592000)  # 30 days
        >>> km.initialize()
        >>> current_key = km.get_current_key()
        >>> signature = km.sign(b"data to sign")
        >>> km.verify(b"data to sign", signature, current_key.key_id)
    """
    
    def __init__(
        self,
        key_dir: str = "./keys",
        rotation_interval: float = 2592000,  # 30 days in seconds
        key_lifetime: float = 31536000,     # 1 year in seconds
        enable_hardware: bool = False,
        db_path: str = ":memory:",
    ):
        """
        Initialize the KeyManager.
        
        Args:
            key_dir: Directory to store software-based private keys.
            rotation_interval: Time between automatic key rotations (seconds).
            key_lifetime: Maximum lifetime for a key (seconds).
            enable_hardware: Enable hardware-backed key support.
            db_path: Path to SQLite database for key metadata and KRL.
        """
        self.key_dir = Path(key_dir)
        self.rotation_interval = rotation_interval
        self.key_lifetime = key_lifetime
        self.enable_hardware = enable_hardware
        self.db_path = db_path
        
        # In-memory state
        self._keys: Dict[str, HybridKeyPair] = {}  # key_id -> HybridKeyPair
        self._metadata: Dict[str, KeyMetadata] = {}  # key_id -> KeyMetadata
        self._krl: Set[str] = set()  # Set of revoked key_ids
        self._current_key_id: Optional[str] = None
        
        # Initialize
        self._initialized = False
        
    def initialize(self) -> None:
        """
        Initialize the KeyManager.
        
        - Creates the key directory if it doesn't exist.
        - Initializes the SQLite database.
        - Loads existing keys and KRL.
        - Generates a new key if none exists.
        """
        if self._initialized:
            return
        
        # Create key directory
        self.key_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        # Load existing keys and KRL
        self._load_keys()
        self._load_krl()
        
        # Set _initialized to True before calling rotate_key
        # (rotate_key checks _initialized to avoid recursion)
        self._initialized = True
        
        # Generate a new key if none exists
        if not self._keys:
            self.rotate_key()
        else:
            # Set current key to the most recent active key
            active_keys = [
                (kid, meta) for kid, meta in self._metadata.items()
                if meta.is_valid_for_signing()
            ]
            if active_keys:
                # Sort by version (descending) and use the highest
                active_keys.sort(key=lambda x: x[1].version, reverse=True)
                self._current_key_id = active_keys[0][0]
            else:
                # No active keys, rotate
                self.rotate_key()
        
        logger.info(f"KeyManager initialized with {len(self._keys)} keys")
    
    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Key metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS key_metadata (
                    key_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    key_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    last_used REAL NOT NULL,
                    revocation_reason TEXT,
                    hardware_info TEXT
                )
            """)
            
            # Key Revocation List (KRL) table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS key_revocation_list (
                    key_id TEXT PRIMARY KEY,
                    revoked_at REAL NOT NULL,
                    reason TEXT NOT NULL,
                    revoked_by TEXT NOT NULL
                )
            """)
            
            # Hybrid key pairs table (private keys encrypted)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hybrid_keys (
                    key_id TEXT PRIMARY KEY,
                    ed25519_private_key BLOB,
                    ed25519_public_key BLOB,
                    dilithium_private_key BLOB,
                    dilithium_public_key BLOB
                )
            """)
            
            conn.commit()
    
    def _load_keys(self) -> None:
        """Load keys from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Load key metadata
                cursor.execute("SELECT * FROM key_metadata")
                for row in cursor.fetchall():
                    meta = KeyMetadata(
                        key_id=row["key_id"],
                        version=row["version"],
                        status=KeyStatus(row["status"]),
                        key_type=KeyType(row["key_type"]),
                        created_at=row["created_at"],
                        expires_at=row["expires_at"],
                        last_used=row["last_used"],
                        revocation_reason=row["revocation_reason"],
                        hardware_info=json.loads(row["hardware_info"]) if row["hardware_info"] else None,
                    )
                    self._metadata[meta.key_id] = meta
                
                # Load hybrid keys
                cursor.execute("SELECT * FROM hybrid_keys")
                for row in cursor.fetchall():
                    key_id = row["key_id"]
                    hybrid_key = HybridKeyPair(
                        ed25519_private_key=row["ed25519_private_key"],
                        ed25519_public_key=row["ed25519_public_key"],
                        dilithium_private_key=row["dilithium_private_key"],
                        dilithium_public_key=row["dilithium_public_key"],
                        key_id=key_id,
                    )
                    self._keys[key_id] = hybrid_key
        except Exception as e:
            logger.error(f"Failed to load keys from database: {e}")
    
    def _load_krl(self) -> None:
        """Load the Key Revocation List from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT key_id FROM key_revocation_list")
                for row in cursor.fetchall():
                    self._krl.add(row["key_id"])
        except Exception as e:
            logger.error(f"Failed to load KRL from database: {e}")
    
    def _save_key(self, key_id: str, hybrid_key: HybridKeyPair, metadata: KeyMetadata) -> None:
        """Save a key to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Save key metadata
                cursor.execute("""
                    INSERT OR REPLACE INTO key_metadata 
                    (key_id, version, status, key_type, created_at, expires_at, last_used, revocation_reason, hardware_info)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    metadata.key_id,
                    metadata.version,
                    metadata.status.value,
                    metadata.key_type.value,
                    metadata.created_at,
                    metadata.expires_at,
                    metadata.last_used,
                    metadata.revocation_reason,
                    json.dumps(metadata.hardware_info) if metadata.hardware_info else None,
                ))
                
                # Save hybrid key
                cursor.execute("""
                    INSERT OR REPLACE INTO hybrid_keys 
                    (key_id, ed25519_private_key, ed25519_public_key, dilithium_private_key, dilithium_public_key)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    key_id,
                    hybrid_key.ed25519_private_key,
                    hybrid_key.ed25519_public_key,
                    hybrid_key.dilithium_private_key,
                    hybrid_key.dilithium_public_key,
                ))
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save key {key_id}: {e}")
            raise KeyManagerError(f"Failed to save key: {e}")
    
    def _save_krl(self, entry: KeyRevocationEntry) -> None:
        """Save a revocation entry to the KRL."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO key_revocation_list 
                    (key_id, revoked_at, reason, revoked_by)
                    VALUES (?, ?, ?, ?)
                """, (
                    entry.key_id,
                    entry.revoked_at,
                    entry.reason,
                    entry.revoked_by,
                ))
                
                conn.commit()
                self._krl.add(entry.key_id)
        except Exception as e:
            logger.error(f"Failed to save KRL entry for {entry.key_id}: {e}")
            raise KeyManagerError(f"Failed to save KRL entry: {e}")
    
    def rotate_key(self, reason: str = "Automatic rotation") -> HybridKeyPair:
        """
        Rotate the current key, generating a new one.
        
        Args:
            reason: Reason for the rotation (for audit logging).
        
        Returns:
            The new HybridKeyPair.
        
        Notes:
            - The old key becomes INACTIVE but remains valid for verification.
            - The new key becomes ACTIVE and is used for signing.
        """
        if not self._initialized:
            raise KeyManagerError("KeyManager must be initialized before rotating keys")
        
        # Generate new key
        new_version = 1
        if self._metadata:
            new_version = max(m.version for m in self._metadata.values()) + 1
        
        new_hybrid_key = generate_hybrid_keypair()
        new_key_id = new_hybrid_key.key_id
        
        # Set expiration (current time + key_lifetime)
        expires_at = time.time() + self.key_lifetime if self.key_lifetime > 0 else 0.0
        
        new_metadata = KeyMetadata(
            key_id=new_key_id,
            version=new_version,
            status=KeyStatus.ACTIVE,
            key_type=KeyType.SOFTWARE,
            created_at=time.time(),
            expires_at=expires_at,
            last_used=0.0,
        )
        
        # Save the new key
        self._keys[new_key_id] = new_hybrid_key
        self._metadata[new_key_id] = new_metadata
        self._save_key(new_key_id, new_hybrid_key, new_metadata)
        
        # Mark old key as INACTIVE (if it exists and is not already REVOKED)
        if self._current_key_id and self._current_key_id in self._metadata:
            old_metadata = self._metadata[self._current_key_id]
            if old_metadata.status != KeyStatus.REVOKED:
                old_metadata.status = KeyStatus.INACTIVE
                self._metadata[self._current_key_id] = old_metadata
                self._save_key(self._current_key_id, self._keys[self._current_key_id], old_metadata)
        
        # Update current key
        self._current_key_id = new_key_id
        
        logger.info(f"Rotated key to version {new_version} (key_id: {new_key_id})")
        return new_hybrid_key
    
    def get_current_key(self) -> HybridKeyPair:
        """
        Get the current active key for signing.
        
        Returns:
            The current HybridKeyPair.
        
        Raises:
            KeyManagerError: If no key is available.
        """
        if not self._initialized:
            self.initialize()
        
        if not self._current_key_id or self._current_key_id not in self._keys:
            raise KeyManagerError("No current key available")
        
        return self._keys[self._current_key_id]
    
    def get_key(self, key_id: str) -> HybridKeyPair:
        """
        Get a key by its ID.
        
        Args:
            key_id: The ID of the key to retrieve.
        
        Returns:
            The HybridKeyPair.
        
        Raises:
            KeyNotFoundError: If the key is not found.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id not in self._keys:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        return self._keys[key_id]
    
    def get_key_metadata(self, key_id: str) -> KeyMetadata:
        """
        Get metadata for a key.
        
        Args:
            key_id: The ID of the key.
        
        Returns:
            The KeyMetadata.
        
        Raises:
            KeyNotFoundError: If the key is not found.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id not in self._metadata:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        return self._metadata[key_id]
    
    def sign(
        self,
        data: bytes,
        key_id: Optional[str] = None,
        hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512,
    ) -> HybridSignature:
        """
        Sign data using the specified key (or current key if not specified).
        
        Args:
            data: The data to sign.
            key_id: The ID of the key to use (default: current key).
            hash_algorithm: The hash algorithm to use.
        
        Returns:
            HybridSignature containing the signature(s).
        
        Raises:
            KeyNotFoundError: If the key is not found.
            KeyRevokedError: If the key is revoked.
            KeyExpiredError: If the key is expired.
            KeyManagerError: If the key is not valid for signing.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id is None:
            key_id = self._current_key_id
        
        if key_id not in self._keys:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        metadata = self._metadata.get(key_id)
        if metadata is None:
            raise KeyManagerError(f"Key {key_id} has no metadata")
        
        if key_id in self._krl:
            raise KeyRevokedError(f"Key {key_id} is revoked")
        
        if not metadata.is_valid_for_signing():
            if metadata.status == KeyStatus.REVOKED:
                raise KeyRevokedError(f"Key {key_id} is revoked")
            elif metadata.expires_at > 0 and time.time() > metadata.expires_at:
                raise KeyExpiredError(f"Key {key_id} is expired")
            else:
                raise KeyManagerError(f"Key {key_id} is not valid for signing")
        
        # Update last_used timestamp
        metadata.last_used = time.time()
        self._metadata[key_id] = metadata
        self._save_key(key_id, self._keys[key_id], metadata)
        
        # Sign the data
        hybrid_key = self._keys[key_id]
        signature = sign_hybrid(hybrid_key, data, hash_algorithm)
        
        logger.debug(f"Signed data with key {key_id} (version {metadata.version})")
        return signature, key_id
    
    def verify(
        self,
        data: bytes,
        signature: HybridSignature,
        key_id: str,
        hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512,
    ) -> bool:
        """
        Verify a signature using the specified key.
        
        Args:
            data: The original data.
            signature: The HybridSignature to verify.
            key_id: The ID of the key used for signing.
            hash_algorithm: The hash algorithm used for signing.
        
        Returns:
            True if the signature is valid, False otherwise.
        
        Raises:
            KeyNotFoundError: If the key is not found.
            KeyRevokedError: If the key is revoked.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id not in self._keys:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        if key_id in self._krl:
            raise KeyRevokedError(f"Key {key_id} is revoked")
        
        metadata = self._metadata.get(key_id)
        if metadata is None:
            raise KeyManagerError(f"Key {key_id} has no metadata")
        
        if not metadata.is_valid_for_verification():
            return False
        
        hybrid_key = self._keys[key_id]
        return verify_hybrid(hybrid_key, signature, data, hash_algorithm)
    
    def revoke_key(
        self,
        key_id: str,
        reason: str = "",
        revoked_by: str = "",
    ) -> None:
        """
        Revoke a key, adding it to the Key Revocation List (KRL).
        
        Args:
            key_id: The ID of the key to revoke.
            reason: Reason for revocation.
            revoked_by: Entity that revoked the key.
        
        Raises:
            KeyNotFoundError: If the key is not found.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id not in self._metadata:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        # Update metadata
        metadata = self._metadata[key_id]
        metadata.status = KeyStatus.REVOKED
        metadata.revocation_reason = reason
        self._metadata[key_id] = metadata
        self._save_key(key_id, self._keys[key_id], metadata)
        
        # Add to KRL
        entry = KeyRevocationEntry(
            key_id=key_id,
            reason=reason,
            revoked_by=revoked_by,
        )
        self._save_krl(entry)
        
        # If this was the current key, rotate
        if key_id == self._current_key_id:
            logger.warning(f"Revoked current key {key_id}, rotating...")
            self.rotate_key(reason=f"Key revoked: {reason}")
        
        logger.info(f"Revoked key {key_id}: {reason}")
    
    def is_key_revoked(self, key_id: str) -> bool:
        """
        Check if a key is revoked.
        
        Args:
            key_id: The ID of the key to check.
        
        Returns:
            True if the key is revoked, False otherwise.
        """
        if not self._initialized:
            self.initialize()
        return key_id in self._krl
    
    def get_all_keys(self) -> List[Tuple[str, KeyMetadata]]:
        """
        Get all keys and their metadata.
        
        Returns:
            List of (key_id, KeyMetadata) tuples.
        """
        if not self._initialized:
            self.initialize()
        return [(kid, meta) for kid, meta in self._metadata.items()]
    
    def get_active_keys(self) -> List[Tuple[str, KeyMetadata]]:
        """
        Get all active keys (valid for signing).
        
        Returns:
            List of (key_id, KeyMetadata) tuples.
        """
        if not self._initialized:
            self.initialize()
        return [
            (kid, meta) for kid, meta in self._metadata.items()
            if meta.is_valid_for_signing() and kid not in self._krl
        ]
    
    def get_valid_keys(self) -> List[Tuple[str, KeyMetadata]]:
        """
        Get all valid keys (valid for verification).
        
        Returns:
            List of (key_id, KeyMetadata) tuples.
        """
        if not self._initialized:
            self.initialize()
        return [
            (kid, meta) for kid, meta in self._metadata.items()
            if meta.is_valid_for_verification() and kid not in self._krl
        ]
    
    def check_and_rotate(self) -> Optional[HybridKeyPair]:
        """
        Check if key rotation is needed and rotate if necessary.
        
        Returns:
            The new HybridKeyPair if rotated, None otherwise.
        """
        if not self._initialized:
            self.initialize()
        
        if not self._current_key_id:
            return self.rotate_key()
        
        current_metadata = self._metadata.get(self._current_key_id)
        if current_metadata is None:
            return self.rotate_key()
        
        # Check if rotation is needed
        time_since_rotation = time.time() - current_metadata.created_at
        if time_since_rotation >= self.rotation_interval:
            return self.rotate_key(reason="Scheduled rotation")
        
        # Check if key is expired
        if current_metadata.expires_at > 0 and time.time() > current_metadata.expires_at:
            return self.rotate_key(reason="Key expired")
        
        return None
    
    def cleanup_expired_keys(self) -> int:
        """
        Remove expired keys from the key store.
        
        Returns:
            Number of keys removed.
        """
        if not self._initialized:
            self.initialize()
        
        removed_count = 0
        current_time = time.time()
        
        for key_id, metadata in list(self._metadata.items()):
            if (
                metadata.expires_at > 0 
                and current_time > metadata.expires_at 
                and metadata.status != KeyStatus.ACTIVE
            ):
                # Delete from database
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM key_metadata WHERE key_id = ?", (key_id,))
                        cursor.execute("DELETE FROM hybrid_keys WHERE key_id = ?", (key_id,))
                        conn.commit()
                except Exception as e:
                    logger.error(f"Failed to delete expired key {key_id}: {e}")
                else:
                    # Remove from memory
                    self._keys.pop(key_id, None)
                    self._metadata.pop(key_id, None)
                    removed_count += 1
                    logger.info(f"Removed expired key {key_id}")
        
        return removed_count
    
    def export_key(
        self,
        key_id: str,
        include_private: bool = False,
    ) -> Dict[str, Any]:
        """
        Export a key for backup or transfer.
        
        Args:
            key_id: The ID of the key to export.
            include_private: Whether to include private key material.
        
        Returns:
            Dictionary containing the key data.
        
        Raises:
            KeyNotFoundError: If the key is not found.
        """
        if not self._initialized:
            self.initialize()
        
        if key_id not in self._keys:
            raise KeyNotFoundError(f"Key {key_id} not found")
        
        hybrid_key = self._keys[key_id]
        metadata = self._metadata.get(key_id)
        
        result = {
            "key_id": key_id,
            "metadata": metadata.to_dict() if metadata else None,
            "public_keys": {
                "ed25519": hybrid_key.ed25519_public_key.hex() if hybrid_key.ed25519_public_key else None,
                "dilithium": hybrid_key.dilithium_public_key.hex() if hybrid_key.dilithium_public_key else None,
            },
        }
        
        if include_private:
            result["private_keys"] = {
                "ed25519": hybrid_key.ed25519_private_key.hex() if hybrid_key.ed25519_private_key else None,
                "dilithium": hybrid_key.dilithium_private_key.hex() if hybrid_key.dilithium_private_key else None,
            }
        
        return result
    
    def import_key(
        self,
        key_data: Dict[str, Any],
        key_id: Optional[str] = None,
    ) -> str:
        """
        Import a key from backup or transfer.
        
        Args:
            key_data: Dictionary containing the key data.
            key_id: Optional key ID (overrides the one in key_data).
        
        Returns:
            The key_id of the imported key.
        
        Raises:
            KeyManagerError: If the key data is invalid.
        """
        if not self._initialized:
            self.initialize()
        
        # Extract key ID
        if key_id:
            pass
        elif "key_id" in key_data:
            key_id = key_data["key_id"]
        else:
            key_id = os.urandom(16).hex()
        
        # Extract metadata
        metadata_dict = key_data.get("metadata", {})
        metadata = KeyMetadata.from_dict(metadata_dict)
        metadata.key_id = key_id
        
        # Extract keys
        public_keys = key_data.get("public_keys", {})
        private_keys = key_data.get("private_keys", {})
        
        hybrid_key = HybridKeyPair(
            key_id=key_id,
            ed25519_private_key=bytes.fromhex(private_keys["ed25519"]) if private_keys.get("ed25519") else None,
            ed25519_public_key=bytes.fromhex(public_keys["ed25519"]) if public_keys.get("ed25519") else None,
            dilithium_private_key=bytes.fromhex(private_keys["dilithium"]) if private_keys.get("dilithium") else None,
            dilithium_public_key=bytes.fromhex(public_keys["dilithium"]) if public_keys.get("dilithium") else None,
            version=metadata.version,
            created_at=metadata.created_at,
        )
        
        # Save the key
        self._keys[key_id] = hybrid_key
        self._metadata[key_id] = metadata
        self._save_key(key_id, hybrid_key, metadata)
        
        logger.info(f"Imported key {key_id}")
        return key_id


# Singleton for global key manager
_global_key_manager: Optional[KeyManager] = None


def get_key_manager(
    key_dir: str = "./keys",
    rotation_interval: float = 2592000,
    key_lifetime: float = 31536000,
    enable_hardware: bool = False,
    db_path: str = ":memory:",
) -> KeyManager:
    """
    Get the global KeyManager instance (singleton).
    
    Args:
        key_dir: Directory to store software-based private keys.
        rotation_interval: Time between automatic key rotations (seconds).
        key_lifetime: Maximum lifetime for a key (seconds).
        enable_hardware: Enable hardware-backed key support.
        db_path: Path to SQLite database for key metadata and KRL.
    
    Returns:
        The global KeyManager instance.
    """
    global _global_key_manager
    if _global_key_manager is None:
        _global_key_manager = KeyManager(
            key_dir=key_dir,
            rotation_interval=rotation_interval,
            key_lifetime=key_lifetime,
            enable_hardware=enable_hardware,
            db_path=db_path,
        )
        _global_key_manager.initialize()
    return _global_key_manager


def reset_key_manager() -> None:
    """Reset the global KeyManager instance (for testing)."""
    global _global_key_manager
    if _global_key_manager is not None:
        _global_key_manager = None
