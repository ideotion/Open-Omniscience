"""
Tests for Post-Quantum Cryptography (PQC) Module
===============================================

Tests for hybrid signatures (Ed25519 + Dilithium3), SHA-3 hashing,
and key management in Open-Omniscience's Chain of Custody system.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import json
import os
import pytest
import time

from src.blockchain.core.pqc import (
    HybridSignature,
    HybridKeyPair,
    HashAlgorithm,
    SignatureAlgorithm,
    generate_ed25519_keypair,
    generate_dilithium3_keypair,
    generate_hybrid_keypair,
    sign_ed25519,
    verify_ed25519,
    sign_dilithium3,
    verify_dilithium3,
    sign_hybrid,
    verify_hybrid,
    hash_data,
    get_available_algorithms,
    PQCError,
    PQCNotAvailableError,
    ED25519_AVAILABLE,
    DILITHIUM_AVAILABLE,
)


class TestHashAlgorithm:
    """Tests for HashAlgorithm enum."""
    
    def test_hash_algorithm_values(self):
        """Test HashAlgorithm enum values."""
        assert HashAlgorithm.SHA256.value == "sha256"
        assert HashAlgorithm.SHA3_256.value == "sha3_256"
        assert HashAlgorithm.SHA3_512.value == "sha3_512"
        assert HashAlgorithm.BLAKE2B.value == "blake2b"
        assert HashAlgorithm.BLAKE2S.value == "blake2s"


class TestSignatureAlgorithm:
    """Tests for SignatureAlgorithm enum."""
    
    def test_signature_algorithm_values(self):
        """Test SignatureAlgorithm enum values."""
        assert SignatureAlgorithm.ED25519.value == "ed25519"
        assert SignatureAlgorithm.DILITHIUM3.value == "dilithium3"
        assert SignatureAlgorithm.HYBRID.value == "hybrid"


class TestHybridSignature:
    """Tests for HybridSignature dataclass."""
    
    def test_hybrid_signature_creation(self):
        """Test creating a HybridSignature."""
        sig = HybridSignature(
            ed25519_signature=b"ed25519_sig_bytes",
            dilithium_signature=b"dilithium_sig_bytes",
            algorithm=SignatureAlgorithm.HYBRID,
        )
        assert sig.ed25519_signature == b"ed25519_sig_bytes"
        assert sig.dilithium_signature == b"dilithium_sig_bytes"
        assert sig.algorithm == SignatureAlgorithm.HYBRID
    
    def test_hybrid_signature_ed25519_only(self):
        """Test HybridSignature with only Ed25519."""
        sig = HybridSignature(
            ed25519_signature=b"ed25519_sig_bytes",
            algorithm=SignatureAlgorithm.ED25519,
        )
        assert sig.is_valid()
        assert not sig.is_quantum_resistant()
    
    def test_hybrid_signature_dilithium_only(self):
        """Test HybridSignature with only Dilithium3."""
        sig = HybridSignature(
            dilithium_signature=b"dilithium_sig_bytes",
            algorithm=SignatureAlgorithm.DILITHIUM3,
        )
        assert sig.is_valid()
        assert sig.is_quantum_resistant()
    
    def test_hybrid_signature_both(self):
        """Test HybridSignature with both signatures."""
        sig = HybridSignature(
            ed25519_signature=b"ed25519_sig_bytes",
            dilithium_signature=b"dilithium_sig_bytes",
            algorithm=SignatureAlgorithm.HYBRID,
        )
        assert sig.is_valid()
        assert sig.is_quantum_resistant()
    
    def test_hybrid_signature_empty(self):
        """Test empty HybridSignature."""
        sig = HybridSignature()
        assert not sig.is_valid()
        assert not sig.is_quantum_resistant()
    
    def test_hybrid_signature_to_dict(self):
        """Test converting HybridSignature to dict."""
        sig = HybridSignature(
            ed25519_signature=b"ed25519_sig_bytes",
            dilithium_signature=b"dilithium_sig_bytes",
            algorithm=SignatureAlgorithm.HYBRID,
        )
        data = sig.to_dict()
        assert data["ed25519_signature"] == b"ed25519_sig_bytes".hex()
        assert data["dilithium_signature"] == b"dilithium_sig_bytes".hex()
        assert data["algorithm"] == "hybrid"
    
    def test_hybrid_signature_from_dict(self):
        """Test creating HybridSignature from dict."""
        data = {
            "ed25519_signature": b"ed25519_sig_bytes".hex(),
            "dilithium_signature": b"dilithium_sig_bytes".hex(),
            "algorithm": "hybrid",
        }
        sig = HybridSignature.from_dict(data)
        assert sig.ed25519_signature == b"ed25519_sig_bytes"
        assert sig.dilithium_signature == b"dilithium_sig_bytes"
        assert sig.algorithm == SignatureAlgorithm.HYBRID


class TestHybridKeyPair:
    """Tests for HybridKeyPair dataclass."""
    
    def test_hybrid_key_pair_creation(self):
        """Test creating a HybridKeyPair."""
        key_pair = HybridKeyPair(
            ed25519_private_key=b"ed25519_private",
            ed25519_public_key=b"ed25519_public",
            dilithium_private_key=b"dilithium_private",
            dilithium_public_key=b"dilithium_public",
            key_id="test_key_id",
            version=1,
            created_at=time.time(),
        )
        assert key_pair.ed25519_private_key == b"ed25519_private"
        assert key_pair.ed25519_public_key == b"ed25519_public"
        assert key_pair.dilithium_private_key == b"dilithium_private"
        assert key_pair.dilithium_public_key == b"dilithium_public"
        assert key_pair.key_id == "test_key_id"
        assert key_pair.version == 1
    
    def test_hybrid_key_pair_to_dict(self):
        """Test converting HybridKeyPair to dict."""
        key_pair = HybridKeyPair(
            ed25519_private_key=b"ed25519_private",
            ed25519_public_key=b"ed25519_public",
            key_id="test_key_id",
        )
        data = key_pair.to_dict()
        assert data["ed25519_private_key"] == b"ed25519_private".hex()
        assert data["ed25519_public_key"] == b"ed25519_public".hex()
        assert data["key_id"] == "test_key_id"
    
    def test_hybrid_key_pair_from_dict(self):
        """Test creating HybridKeyPair from dict."""
        data = {
            "ed25519_private_key": b"ed25519_private".hex(),
            "ed25519_public_key": b"ed25519_public".hex(),
            "key_id": "test_key_id",
            "version": 1,
        }
        key_pair = HybridKeyPair.from_dict(data)
        assert key_pair.ed25519_private_key == b"ed25519_private"
        assert key_pair.ed25519_public_key == b"ed25519_public"
        assert key_pair.key_id == "test_key_id"
        assert key_pair.version == 1


class TestHashData:
    """Tests for hash_data function."""
    
    def test_hash_data_sha256(self):
        """Test hashing with SHA-256."""
        data = b"test data"
        expected = hashlib.sha256(data).digest()
        result = hash_data(data, HashAlgorithm.SHA256)
        assert result == expected
    
    def test_hash_data_sha3_256(self):
        """Test hashing with SHA3-256."""
        data = b"test data"
        expected = hashlib.sha3_256(data).digest()
        result = hash_data(data, HashAlgorithm.SHA3_256)
        assert result == expected
    
    def test_hash_data_sha3_512(self):
        """Test hashing with SHA3-512."""
        data = b"test data"
        expected = hashlib.sha3_512(data).digest()
        result = hash_data(data, HashAlgorithm.SHA3_512)
        assert result == expected
    
    def test_hash_data_blake2b(self):
        """Test hashing with BLAKE2B."""
        data = b"test data"
        expected = hashlib.blake2b(data, digest_size=64).digest()
        result = hash_data(data, HashAlgorithm.BLAKE2B)
        assert result == expected
    
    def test_hash_data_blake2s(self):
        """Test hashing with BLAKE2S."""
        data = b"test data"
        expected = hashlib.blake2s(data, digest_size=32).digest()
        result = hash_data(data, HashAlgorithm.BLAKE2S)
        assert result == expected
    
    def test_hash_data_unsupported(self):
        """Test hashing with unsupported algorithm."""
        data = b"test data"
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            hash_data(data, "unsupported")


class TestGetAvailableAlgorithms:
    """Tests for get_available_algorithms function."""
    
    def test_get_available_algorithms(self):
        """Test getting available algorithms."""
        algorithms = get_available_algorithms()
        assert "ed25519" in algorithms
        assert "dilithium3" in algorithms
        assert "hybrid" in algorithms
        assert "sha3_512" in algorithms


@pytest.mark.skipif(not ED25519_AVAILABLE, reason="Ed25519 not available")
class TestEd25519:
    """Tests for Ed25519 key generation and signing."""
    
    def test_generate_ed25519_keypair(self):
        """Test generating Ed25519 key pair."""
        private_key, public_key = generate_ed25519_keypair()
        assert isinstance(private_key, bytes)
        assert isinstance(public_key, bytes)
        assert len(private_key) > 0
        assert len(public_key) > 0
    
    def test_ed25519_sign_and_verify(self):
        """Test Ed25519 signing and verification."""
        private_key, public_key = generate_ed25519_keypair()
        data = b"test data for signing"
        
        signature = sign_ed25519(private_key, data)
        assert isinstance(signature, bytes)
        assert len(signature) > 0
        
        is_valid = verify_ed25519(public_key, signature, data)
        assert is_valid
    
    def test_ed25519_verify_invalid_signature(self):
        """Test Ed25519 verification with invalid signature."""
        private_key, public_key = generate_ed25519_keypair()
        data = b"test data for signing"
        wrong_data = b"wrong data"
        
        signature = sign_ed25519(private_key, data)
        is_valid = verify_ed25519(public_key, signature, wrong_data)
        assert not is_valid


@pytest.mark.skipif(not DILITHIUM_AVAILABLE, reason="Dilithium3 not available")
class TestDilithium3:
    """Tests for Dilithium3 key generation and signing."""
    
    def test_generate_dilithium3_keypair(self):
        """Test generating Dilithium3 key pair."""
        private_key, public_key = generate_dilithium3_keypair()
        assert isinstance(private_key, bytes)
        assert isinstance(public_key, bytes)
        assert len(private_key) > 0
        assert len(public_key) > 0
    
    def test_dilithium3_sign_and_verify(self):
        """Test Dilithium3 signing and verification."""
        private_key, public_key = generate_dilithium3_keypair()
        data = b"test data for signing"
        
        signature = sign_dilithium3(private_key, data)
        assert isinstance(signature, bytes)
        assert len(signature) > 0
        
        is_valid = verify_dilithium3(public_key, signature, data)
        assert is_valid
    
    def test_dilithium3_verify_invalid_signature(self):
        """Test Dilithium3 verification with invalid signature."""
        private_key, public_key = generate_dilithium3_keypair()
        data = b"test data for signing"
        wrong_data = b"wrong data"
        
        signature = sign_dilithium3(private_key, data)
        is_valid = verify_dilithium3(public_key, signature, wrong_data)
        assert not is_valid


@pytest.mark.skipif(
    not (ED25519_AVAILABLE and DILITHIUM_AVAILABLE),
    reason="Both Ed25519 and Dilithium3 not available"
)
class TestHybridSigning:
    """Tests for hybrid signing (Ed25519 + Dilithium3)."""
    
    def test_generate_hybrid_keypair(self):
        """Test generating hybrid key pair."""
        key_pair = generate_hybrid_keypair()
        assert isinstance(key_pair, HybridKeyPair)
        assert key_pair.ed25519_private_key is not None
        assert key_pair.ed25519_public_key is not None
        assert key_pair.dilithium_private_key is not None
        assert key_pair.dilithium_public_key is not None
    
    def test_sign_hybrid(self):
        """Test hybrid signing."""
        key_pair = generate_hybrid_keypair()
        data = b"test data for hybrid signing"
        
        signature = sign_hybrid(
            key_pair,
            data,
            hash_algorithm=HashAlgorithm.SHA3_512,
        )
        assert isinstance(signature, HybridSignature)
        assert signature.is_valid()
        assert signature.is_quantum_resistant()
        assert signature.ed25519_signature is not None
        assert signature.dilithium_signature is not None
        assert signature.algorithm == SignatureAlgorithm.HYBRID
    
    def test_sign_hybrid_sha256(self):
        """Test hybrid signing with SHA-256."""
        key_pair = generate_hybrid_keypair()
        data = b"test data"
        
        signature = sign_hybrid(
            key_pair,
            data,
            hash_algorithm=HashAlgorithm.SHA256,
        )
        assert signature.is_valid()
    
    def test_verify_hybrid(self):
        """Test hybrid signature verification."""
        key_pair = generate_hybrid_keypair()
        data = b"test data for verification"
        
        signature = sign_hybrid(
            key_pair,
            data,
            hash_algorithm=HashAlgorithm.SHA3_512,
        )
        
        is_valid = verify_hybrid(
            key_pair,
            signature,
            data,
            hash_algorithm=HashAlgorithm.SHA3_512,
        )
        assert is_valid
    
    def test_verify_hybrid_invalid_data(self):
        """Test hybrid verification with invalid data."""
        key_pair = generate_hybrid_keypair()
        data = b"test data"
        wrong_data = b"wrong data"
        
        signature = sign_hybrid(key_pair, data)
        is_valid = verify_hybrid(key_pair, signature, wrong_data)
        assert not is_valid
    
    def test_verify_hybrid_ed25519_only(self):
        """Test hybrid verification with Ed25519-only signature."""
        # Create a key pair with only Ed25519
        key_pair = HybridKeyPair(
            ed25519_private_key=generate_ed25519_keypair()[0],
            ed25519_public_key=generate_ed25519_keypair()[1],
        )
        data = b"test data"
        
        # Manually create a signature with only Ed25519
        from src.blockchain.core.pqc import hash_data, sign_ed25519
        hashed_data = hash_data(data, HashAlgorithm.SHA3_512)
        ed25519_sig = sign_ed25519(key_pair.ed25519_private_key, hashed_data)
        signature = HybridSignature(
            ed25519_signature=ed25519_sig,
            algorithm=SignatureAlgorithm.ED25519,
        )
        
        is_valid = verify_hybrid(key_pair, signature, data)
        assert is_valid
    
    def test_verify_hybrid_dilithium_only(self):
        """Test hybrid verification with Dilithium3-only signature."""
        # Create a key pair with only Dilithium3
        key_pair = HybridKeyPair(
            dilithium_private_key=generate_dilithium3_keypair()[0],
            dilithium_public_key=generate_dilithium3_keypair()[1],
        )
        data = b"test data"
        
        # Manually create a signature with only Dilithium3
        from src.blockchain.core.pqc import hash_data, sign_dilithium3
        hashed_data = hash_data(data, HashAlgorithm.SHA3_512)
        dilithium_sig = sign_dilithium3(key_pair.dilithium_private_key, hashed_data)
        signature = HybridSignature(
            dilithium_signature=dilithium_sig,
            algorithm=SignatureAlgorithm.DILITHIUM3,
        )
        
        is_valid = verify_hybrid(key_pair, signature, data)
        assert is_valid


class TestGlobalHybridKeyPair:
    """Tests for global hybrid key pair singleton."""
    
    def test_global_hybrid_keypair_singleton(self):
        """Test global hybrid key pair singleton."""
        from src.blockchain.core.pqc import (
            generate_global_hybrid_keypair,
            get_global_hybrid_keypair,
            reset_global_hybrid_keypair,
        )
        
        # Reset to ensure clean state
        reset_global_hybrid_keypair()
        
        # Generate global key pair
        key_pair1 = generate_global_hybrid_keypair()
        key_pair2 = get_global_hybrid_keypair()
        
        assert key_pair1 is key_pair2
        assert key_pair1.key_id == key_pair2.key_id
        
        # Reset and generate new
        reset_global_hybrid_keypair()
        key_pair3 = generate_global_hybrid_keypair()
        
        assert key_pair3.key_id != key_pair1.key_id


class TestErrorHandling:
    """Tests for error handling in PQC module."""
    
    def test_pqc_error_hierarchy(self):
        """Test PQC error hierarchy."""
        assert issubclass(PQCNotAvailableError, PQCError)
    
    def test_unsupported_hash_algorithm_error(self):
        """Test error for unsupported hash algorithm."""
        with pytest.raises(ValueError):
            hash_data(b"data", "unsupported_algorithm")
