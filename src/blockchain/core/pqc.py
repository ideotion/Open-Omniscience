"""
Post-Quantum Cryptography (PQC) Module for Open-Omniscience
============================================================

This module provides hybrid cryptographic signatures (Ed25519 + CRYSTALS-Dilithium)
for quantum-resistant Chain of Custody (CoC) verification.

Key Features:
-------------
1. **Hybrid Signatures**: Combines Ed25519 (classical) and Dilithium3 (post-quantum) signatures.
2. **Backward Compatibility**: Falls back to Ed25519 if Dilithium is unavailable.
3. **SHA-3 Support**: Uses SHA-3-512 for hashing (resistant to Grover's algorithm).
4. **Key Management**: Supports Ed25519 and Dilithium key pairs.

Security Considerations:
-----------------------
- **Ed25519**: Vulnerable to Shor's algorithm on a cryptographically relevant quantum computer (CRQC).
- **Dilithium3**: NIST-selected post-quantum signature algorithm (resistant to Shor's algorithm).
- **SHA-3-512**: Resistant to Grover's algorithm (2^256 security).

References:
-----------
- NIST PQC Standardization Project: https://csrc.nist.gov/projects/post-quantum-cryptography
- CRYSTALS-Dilithium: https://pq-crystals.org/dilithium/
- RFC 8032 (Ed25519): https://datatracker.ietf.org/doc/html/rfc8032
- FIPS 202 (SHA-3): https://csrc.nist.gov/publications/detail/fips/202/final

Author: Open-Omniscience Team
License: GNU GPLv3
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Optional imports (graceful degradation if not available)
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    ED25519_AVAILABLE = True
except ImportError:
    ED25519_AVAILABLE = False
    Ed25519PrivateKey = None
    Ed25519PublicKey = None

try:
    from pqcrypto.sign.dilithium3 import generate_keypair, sign, verify
    DILITHIUM_AVAILABLE = True
except ImportError:
    DILITHIUM_AVAILABLE = False

logger = logging.getLogger(__name__)


class HashAlgorithm(Enum):
    """Supported hash algorithms for post-quantum resistance."""
    SHA256 = "sha256"
    SHA3_256 = "sha3_256"
    SHA3_512 = "sha3_512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"


class SignatureAlgorithm(Enum):
    """Supported signature algorithms."""
    ED25519 = "ed25519"
    DILITHIUM3 = "dilithium3"
    HYBRID = "hybrid"  # Ed25519 + Dilithium3


@dataclass
class HybridSignature:
    """
    A hybrid signature combining Ed25519 and Dilithium3 signatures.
    
    This provides:
    - Backward compatibility (Ed25519)
    - Quantum resistance (Dilithium3)
    
    Attributes:
        ed25519_signature: The Ed25519 signature (bytes).
        dilithium_signature: The Dilithium3 signature (bytes).
        algorithm: The signature algorithm used (default: HYBRID).
    """
    ed25519_signature: Optional[bytes] = None
    dilithium_signature: Optional[bytes] = None
    algorithm: SignatureAlgorithm = SignatureAlgorithm.HYBRID
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ed25519_signature": self.ed25519_signature.hex() if self.ed25519_signature else None,
            "dilithium_signature": self.dilithium_signature.hex() if self.dilithium_signature else None,
            "algorithm": self.algorithm.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HybridSignature":
        """Create from dictionary."""
        return cls(
            ed25519_signature=bytes.fromhex(data["ed25519_signature"]) if data.get("ed25519_signature") else None,
            dilithium_signature=bytes.fromhex(data["dilithium_signature"]) if data.get("dilithium_signature") else None,
            algorithm=SignatureAlgorithm(data.get("algorithm", "hybrid")),
        )
    
    def is_valid(self) -> bool:
        """Check if at least one signature is present."""
        return self.ed25519_signature is not None or self.dilithium_signature is not None
    
    def is_quantum_resistant(self) -> bool:
        """Check if the signature is quantum-resistant (Dilithium3 present)."""
        return self.dilithium_signature is not None


@dataclass
class HybridKeyPair:
    """
    A hybrid key pair combining Ed25519 and Dilithium3 keys.
    
    Attributes:
        ed25519_private_key: The Ed25519 private key (PEM format).
        ed25519_public_key: The Ed25519 public key (PEM format).
        dilithium_private_key: The Dilithium3 private key (bytes).
        dilithium_public_key: The Dilithium3 public key (bytes).
        key_id: Unique identifier for this key pair.
        version: Version number (for key rotation).
        created_at: Timestamp when the key was created.
    """
    ed25519_private_key: Optional[bytes] = None
    ed25519_public_key: Optional[bytes] = None
    dilithium_private_key: Optional[bytes] = None
    dilithium_public_key: Optional[bytes] = None
    key_id: str = field(default_factory=lambda: os.urandom(16).hex())
    version: int = 1
    created_at: float = field(default_factory=lambda: time.time())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ed25519_private_key": self.ed25519_private_key.hex() if self.ed25519_private_key else None,
            "ed25519_public_key": self.ed25519_public_key.hex() if self.ed25519_public_key else None,
            "dilithium_private_key": self.dilithium_private_key.hex() if self.dilithium_private_key else None,
            "dilithium_public_key": self.dilithium_public_key.hex() if self.dilithium_public_key else None,
            "key_id": self.key_id,
            "version": self.version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HybridKeyPair":
        """Create from dictionary."""
        return cls(
            ed25519_private_key=bytes.fromhex(data["ed25519_private_key"]) if data.get("ed25519_private_key") else None,
            ed25519_public_key=bytes.fromhex(data["ed25519_public_key"]) if data.get("ed25519_public_key") else None,
            dilithium_private_key=bytes.fromhex(data["dilithium_private_key"]) if data.get("dilithium_private_key") else None,
            dilithium_public_key=bytes.fromhex(data["dilithium_public_key"]) if data.get("dilithium_public_key") else None,
            key_id=data.get("key_id", os.urandom(16).hex()),
            version=data.get("version", 1),
            created_at=data.get("created_at", time.time()),
        )
    
    def get_ed25519_private_key_obj(self) -> Optional[Ed25519PrivateKey]:
        """Get the Ed25519 private key as a cryptography object."""
        if not ED25519_AVAILABLE or not self.ed25519_private_key:
            return None
        return serialization.load_pem_private_key(self.ed25519_private_key)
    
    def get_ed25519_public_key_obj(self) -> Optional[Ed25519PublicKey]:
        """Get the Ed25519 public key as a cryptography object."""
        if not ED25519_AVAILABLE or not self.ed25519_public_key:
            return None
        return serialization.load_pem_public_key(self.ed25519_public_key)


# Import time at the bottom to avoid circular imports
import time


class PQCError(Exception):
    """Base exception for PQC-related errors."""
    pass


class PQCNotAvailableError(PQCError):
    """Raised when a required PQC algorithm is not available."""
    pass


class SignatureVerificationError(PQCError):
    """Raised when signature verification fails."""
    pass


def hash_data(data: bytes, algorithm: HashAlgorithm = HashAlgorithm.SHA3_512) -> bytes:
    """
    Hash data using the specified algorithm.
    
    Args:
        data: The data to hash.
        algorithm: The hash algorithm to use.
    
    Returns:
        The hash digest as bytes.
    
    Raises:
        ValueError: If the algorithm is not supported.
    """
    if algorithm == HashAlgorithm.SHA256:
        return hashlib.sha256(data).digest()
    elif algorithm == HashAlgorithm.SHA3_256:
        return hashlib.sha3_256(data).digest()
    elif algorithm == HashAlgorithm.SHA3_512:
        return hashlib.sha3_512(data).digest()
    elif algorithm == HashAlgorithm.BLAKE2B:
        return hashlib.blake2b(data, digest_size=64).digest()
    elif algorithm == HashAlgorithm.BLAKE2S:
        return hashlib.blake2s(data, digest_size=32).digest()
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")


def generate_ed25519_keypair() -> Tuple[bytes, bytes]:
    """
    Generate an Ed25519 key pair.
    
    Returns:
        Tuple of (private_key_pem, public_key_pem).
    
    Raises:
        PQCNotAvailableError: If Ed25519 is not available.
    """
    if not ED25519_AVAILABLE:
        raise PQCNotAvailableError("Ed25519 is not available (cryptography library missing)")
    
    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key_pem, public_key_pem


def generate_dilithium3_keypair() -> Tuple[bytes, bytes]:
    """
    Generate a Dilithium3 key pair.
    
    Returns:
        Tuple of (private_key, public_key) as bytes.
    
    Raises:
        PQCNotAvailableError: If Dilithium3 is not available.
    """
    if not DILITHIUM_AVAILABLE:
        raise PQCNotAvailableError("Dilithium3 is not available (pqcrypto library missing)")
    
    public_key, private_key = generate_keypair()
    return private_key, public_key


def generate_hybrid_keypair() -> HybridKeyPair:
    """
    Generate a hybrid key pair (Ed25519 + Dilithium3).
    
    Returns:
        HybridKeyPair with both key types.
    
    Notes:
        - If Dilithium3 is not available, only Ed25519 keys are generated.
        - If Ed25519 is not available, only Dilithium3 keys are generated.
    """
    ed25519_private = None
    ed25519_public = None
    dilithium_private = None
    dilithium_public = None
    
    try:
        ed25519_private, ed25519_public = generate_ed25519_keypair()
    except PQCNotAvailableError as e:
        logger.warning(f"Ed25519 not available: {e}")
    
    try:
        dilithium_private, dilithium_public = generate_dilithium3_keypair()
    except PQCNotAvailableError as e:
        logger.warning(f"Dilithium3 not available: {e}")
    
    return HybridKeyPair(
        ed25519_private_key=ed25519_private,
        ed25519_public_key=ed25519_public,
        dilithium_private_key=dilithium_private,
        dilithium_public_key=dilithium_public,
    )


def sign_ed25519(private_key_pem: bytes, data: bytes) -> bytes:
    """
    Sign data using Ed25519.
    
    Args:
        private_key_pem: The Ed25519 private key in PEM format.
        data: The data to sign.
    
    Returns:
        The signature as bytes.
    
    Raises:
        PQCNotAvailableError: If Ed25519 is not available.
    """
    if not ED25519_AVAILABLE:
        raise PQCNotAvailableError("Ed25519 is not available")
    
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    return private_key.sign(data)


def verify_ed25519(public_key_pem: bytes, signature: bytes, data: bytes) -> bool:
    """
    Verify an Ed25519 signature.
    
    Args:
        public_key_pem: The Ed25519 public key in PEM format.
        signature: The signature to verify.
        data: The original data.
    
    Returns:
        True if the signature is valid, False otherwise.
    
    Raises:
        PQCNotAvailableError: If Ed25519 is not available.
    """
    if not ED25519_AVAILABLE:
        raise PQCNotAvailableError("Ed25519 is not available")
    
    public_key = serialization.load_pem_public_key(public_key_pem)
    try:
        public_key.verify(signature, data)
        return True
    except Exception:
        return False


def sign_dilithium3(private_key: bytes, data: bytes) -> bytes:
    """
    Sign data using Dilithium3.
    
    Args:
        private_key: The Dilithium3 private key as bytes.
        data: The data to sign.
    
    Returns:
        The signature as bytes.
    
    Raises:
        PQCNotAvailableError: If Dilithium3 is not available.
    """
    if not DILITHIUM_AVAILABLE:
        raise PQCNotAvailableError("Dilithium3 is not available")
    
    return sign(private_key, data)


def verify_dilithium3(public_key: bytes, signature: bytes, data: bytes) -> bool:
    """
    Verify a Dilithium3 signature.
    
    Args:
        public_key: The Dilithium3 public key as bytes.
        signature: The signature to verify.
        data: The original data.
    
    Returns:
        True if the signature is valid, False otherwise.
    
    Raises:
        PQCNotAvailableError: If Dilithium3 is not available.
    """
    if not DILITHIUM_AVAILABLE:
        raise PQCNotAvailableError("Dilithium3 is not available")
    
    try:
        verify(public_key, signature, data)
        return True
    except Exception:
        return False


def sign_hybrid(
    hybrid_key_pair: HybridKeyPair,
    data: bytes,
    hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512,
) -> HybridSignature:
    """
    Sign data using a hybrid key pair (Ed25519 + Dilithium3).
    
    Args:
        hybrid_key_pair: The hybrid key pair to use for signing.
        data: The data to sign.
        hash_algorithm: The hash algorithm to use (default: SHA3-512).
    
    Returns:
        HybridSignature containing both signatures (if available).
    
    Notes:
        - If Dilithium3 is not available, only the Ed25519 signature is included.
        - If Ed25519 is not available, only the Dilithium3 signature is included.
    """
    # Hash the data first
    hashed_data = hash_data(data, hash_algorithm)
    
    ed25519_sig = None
    dilithium_sig = None
    
    # Try Ed25519
    if hybrid_key_pair.ed25519_private_key:
        try:
            ed25519_sig = sign_ed25519(hybrid_key_pair.ed25519_private_key, hashed_data)
        except Exception as e:
            logger.warning(f"Ed25519 signing failed: {e}")
    
    # Try Dilithium3
    if hybrid_key_pair.dilithium_private_key:
        try:
            dilithium_sig = sign_dilithium3(hybrid_key_pair.dilithium_private_key, hashed_data)
        except Exception as e:
            logger.warning(f"Dilithium3 signing failed: {e}")
    
    # Determine the algorithm
    if ed25519_sig and dilithium_sig:
        algorithm = SignatureAlgorithm.HYBRID
    elif ed25519_sig:
        algorithm = SignatureAlgorithm.ED25519
    elif dilithium_sig:
        algorithm = SignatureAlgorithm.DILITHIUM3
    else:
        raise PQCError("No signing algorithm available")
    
    return HybridSignature(
        ed25519_signature=ed25519_sig,
        dilithium_signature=dilithium_sig,
        algorithm=algorithm,
    )


def verify_hybrid(
    hybrid_key_pair: HybridKeyPair,
    signature: HybridSignature,
    data: bytes,
    hash_algorithm: HashAlgorithm = HashAlgorithm.SHA3_512,
) -> bool:
    """
    Verify a hybrid signature.
    
    Args:
        hybrid_key_pair: The hybrid key pair to use for verification.
        signature: The hybrid signature to verify.
        data: The original data.
        hash_algorithm: The hash algorithm used for signing.
    
    Returns:
        True if at least one signature is valid, False otherwise.
    
    Notes:
        - If both signatures are present, both are verified (but only one needs to pass).
        - If only one signature is present, only that one is verified.
    """
    hashed_data = hash_data(data, hash_algorithm)
    
    # Try Ed25519
    if signature.ed25519_signature and hybrid_key_pair.ed25519_public_key:
        try:
            if verify_ed25519(
                hybrid_key_pair.ed25519_public_key,
                signature.ed25519_signature,
                hashed_data,
            ):
                return True
        except Exception as e:
            logger.warning(f"Ed25519 verification failed: {e}")
    
    # Try Dilithium3
    if signature.dilithium_signature and hybrid_key_pair.dilithium_public_key:
        try:
            if verify_dilithium3(
                hybrid_key_pair.dilithium_public_key,
                signature.dilithium_signature,
                hashed_data,
            ):
                return True
        except Exception as e:
            logger.warning(f"Dilithium3 verification failed: {e}")
    
    return False


def get_available_algorithms() -> Dict[str, bool]:
    """
    Get the availability of all cryptographic algorithms.
    
    Returns:
        Dictionary mapping algorithm names to their availability.
    """
    return {
        "ed25519": ED25519_AVAILABLE,
        "dilithium3": DILITHIUM_AVAILABLE,
        "hybrid": ED25519_AVAILABLE and DILITHIUM_AVAILABLE,
        "sha3_512": True,  # Always available (hashlib)
    }


# Singleton for global hybrid key pair (optional)
_global_hybrid_key_pair: Optional[HybridKeyPair] = None


def generate_global_hybrid_keypair() -> HybridKeyPair:
    """
    Generate a global hybrid key pair (singleton).
    
    Returns:
        The global HybridKeyPair.
    """
    global _global_hybrid_key_pair
    if _global_hybrid_key_pair is None:
        _global_hybrid_key_pair = generate_hybrid_keypair()
    return _global_hybrid_key_pair


def get_global_hybrid_keypair() -> Optional[HybridKeyPair]:
    """
    Get the global hybrid key pair.
    
    Returns:
        The global HybridKeyPair, or None if not generated yet.
    """
    return _global_hybrid_key_pair


def reset_global_hybrid_keypair() -> None:
    """Reset the global hybrid key pair (for testing)."""
    global _global_hybrid_key_pair
    _global_hybrid_key_pair = None
