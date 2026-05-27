"""
Tests for Key Manager Module
============================

Tests for key rotation, forward secrecy, and key revocation in Open-Omniscience's
Chain of Custody system.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import json
import os
import pytest
import sqlite3
import tempfile
import time

from src.blockchain.core.key_manager import (
    KeyManager,
    KeyMetadata,
    KeyRevocationEntry,
    KeyStatus,
    KeyType,
    KeyManagerError,
    KeyNotFoundError,
    KeyRevokedError,
    KeyExpiredError,
    get_key_manager,
    reset_key_manager,
)
from src.blockchain.core.pqc import (
    HybridKeyPair,
    HashAlgorithm,
    generate_hybrid_keypair,
    ED25519_AVAILABLE,
    DILITHIUM_AVAILABLE,
)


class TestKeyMetadata:
    """Tests for KeyMetadata dataclass."""
    
    def test_key_metadata_creation(self):
        """Test creating KeyMetadata."""
        metadata = KeyMetadata(
            key_id="test_key_id",
            version=1,
            status=KeyStatus.ACTIVE,
            key_type=KeyType.SOFTWARE,
        )
        assert metadata.key_id == "test_key_id"
        assert metadata.version == 1
        assert metadata.status == KeyStatus.ACTIVE
        assert metadata.key_type == KeyType.SOFTWARE
    
    def test_key_metadata_defaults(self):
        """Test KeyMetadata default values."""
        metadata = KeyMetadata(
            key_id="test_key_id",
            version=1,
        )
        assert metadata.status == KeyStatus.ACTIVE
        assert metadata.key_type == KeyType.SOFTWARE
        assert metadata.created_at > 0
        assert metadata.expires_at == 0.0
        assert metadata.last_used == 0.0
    
    def test_key_metadata_to_dict(self):
        """Test converting KeyMetadata to dict."""
        metadata = KeyMetadata(
            key_id="test_key_id",
            version=1,
            status=KeyStatus.INACTIVE,
            key_type=KeyType.YUBIKEY,
        )
        data = metadata.to_dict()
        assert data["key_id"] == "test_key_id"
        assert data["version"] == 1
        assert data["status"] == "inactive"
        assert data["key_type"] == "yubikey"
    
    def test_key_metadata_from_dict(self):
        """Test creating KeyMetadata from dict."""
        data = {
            "key_id": "test_key_id",
            "version": 2,
            "status": "revoked",
            "key_type": "tpm",
        }
        metadata = KeyMetadata.from_dict(data)
        assert metadata.key_id == "test_key_id"
        assert metadata.version == 2
        assert metadata.status == KeyStatus.REVOKED
        assert metadata.key_type == KeyType.TPM
    
    def test_key_metadata_is_valid_for_signing(self):
        """Test KeyMetadata.is_valid_for_signing()."""
        # Active key
        active = KeyMetadata(key_id="active", version=1, status=KeyStatus.ACTIVE)
        assert active.is_valid_for_signing()
        
        # Inactive key
        inactive = KeyMetadata(key_id="inactive", version=1, status=KeyStatus.INACTIVE)
        assert not inactive.is_valid_for_signing()
        
        # Revoked key
        revoked = KeyMetadata(key_id="revoked", version=1, status=KeyStatus.REVOKED)
        assert not revoked.is_valid_for_signing()
        
        # Expired key
        expired = KeyMetadata(
            key_id="expired",
            version=1,
            status=KeyStatus.ACTIVE,
            expires_at=time.time() - 100,  # Expired 100 seconds ago
        )
        assert not expired.is_valid_for_signing()
    
    def test_key_metadata_is_valid_for_verification(self):
        """Test KeyMetadata.is_valid_for_verification()."""
        # Active key
        active = KeyMetadata(key_id="active", version=1, status=KeyStatus.ACTIVE)
        assert active.is_valid_for_verification()
        
        # Inactive key
        inactive = KeyMetadata(key_id="inactive", version=1, status=KeyStatus.INACTIVE)
        assert inactive.is_valid_for_verification()
        
        # Revoked key
        revoked = KeyMetadata(key_id="revoked", version=1, status=KeyStatus.REVOKED)
        assert not revoked.is_valid_for_verification()


class TestKeyRevocationEntry:
    """Tests for KeyRevocationEntry dataclass."""
    
    def test_key_revocation_entry_creation(self):
        """Test creating KeyRevocationEntry."""
        entry = KeyRevocationEntry(
            key_id="test_key_id",
            reason="Private key leaked",
            revoked_by="admin@open-omniscience.org",
        )
        assert entry.key_id == "test_key_id"
        assert entry.reason == "Private key leaked"
        assert entry.revoked_by == "admin@open-omniscience.org"
        assert entry.revoked_at > 0
    
    def test_key_revocation_entry_to_dict(self):
        """Test converting KeyRevocationEntry to dict."""
        entry = KeyRevocationEntry(
            key_id="test_key_id",
            reason="Test reason",
        )
        data = entry.to_dict()
        assert data["key_id"] == "test_key_id"
        assert data["reason"] == "Test reason"
    
    def test_key_revocation_entry_from_dict(self):
        """Test creating KeyRevocationEntry from dict."""
        data = {
            "key_id": "test_key_id",
            "reason": "Test reason",
            "revoked_by": "test@example.com",
        }
        entry = KeyRevocationEntry.from_dict(data)
        assert entry.key_id == "test_key_id"
        assert entry.reason == "Test reason"
        assert entry.revoked_by == "test@example.com"


class TestKeyManager:
    """Tests for KeyManager class."""
    
    def test_key_manager_initialization(self, temp_db, temp_key_dir):
        """Test KeyManager initialization."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
            rotation_interval=86400,  # 1 day
            key_lifetime=31536000,    # 1 year
        )
        km.initialize()
        
        assert km._initialized
        assert len(km._keys) == 1  # One key generated on init
        assert len(km._metadata) == 1
        assert km._current_key_id is not None
    
    def test_key_manager_get_current_key(self, temp_db, temp_key_dir):
        """Test getting the current key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key = km.get_current_key()
        assert isinstance(current_key, HybridKeyPair)
        assert current_key.key_id == km._current_key_id
    
    def test_key_manager_get_key(self, temp_db, temp_key_dir):
        """Test getting a key by ID."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key = km.get_current_key()
        retrieved_key = km.get_key(current_key.key_id)
        
        assert retrieved_key.key_id == current_key.key_id
    
    def test_key_manager_get_key_not_found(self, temp_db, temp_key_dir):
        """Test getting a non-existent key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        with pytest.raises(KeyNotFoundError):
            km.get_key("non_existent_key_id")
    
    def test_key_manager_rotate_key(self, temp_db, temp_key_dir):
        """Test key rotation."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
            rotation_interval=86400,
        )
        km.initialize()
        
        old_key_id = km._current_key_id
        old_version = km._metadata[old_key_id].version
        
        # Rotate key
        new_key = km.rotate_key(reason="Test rotation")
        
        assert new_key.key_id != old_key_id
        assert km._current_key_id == new_key.key_id
        assert km._metadata[new_key.key_id].version == old_version + 1
        assert km._metadata[old_key_id].status == KeyStatus.INACTIVE
    
    def test_key_manager_sign_and_verify(self, temp_db, temp_key_dir):
        """Test signing and verification with KeyManager."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        data = b"test data for signing"
        signature, key_id = km.sign(data)
        
        assert signature.is_valid()
        assert key_id is not None
        
        # Verify with the same key
        is_valid = km.verify(data, signature, key_id)
        assert is_valid
    
    def test_key_manager_sign_invalid_key(self, temp_db, temp_key_dir):
        """Test signing with an invalid key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        data = b"test data"
        with pytest.raises(KeyNotFoundError):
            km.sign(data, key_id="non_existent_key_id")
    
    def test_key_manager_revoke_key(self, temp_db, temp_key_dir):
        """Test revoking a key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key_id = km._current_key_id
        
        # Revoke the current key
        km.revoke_key(
            key_id=current_key_id,
            reason="Test revocation",
            revoked_by="test@example.com",
        )
        
        assert km.is_key_revoked(current_key_id)
        assert km._metadata[current_key_id].status == KeyStatus.REVOKED
        # A new key should have been generated
        assert km._current_key_id != current_key_id
    
    def test_key_manager_revoke_nonexistent_key(self, temp_db, temp_key_dir):
        """Test revoking a non-existent key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        with pytest.raises(KeyNotFoundError):
            km.revoke_key(
                key_id="non_existent_key_id",
                reason="Test",
            )
    
    def test_key_manager_is_key_revoked(self, temp_db, temp_key_dir):
        """Test checking if a key is revoked."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key_id = km._current_key_id
        
        # Initially not revoked
        assert not km.is_key_revoked(current_key_id)
        
        # Revoke the key
        km.revoke_key(current_key_id, reason="Test")
        
        # Now revoked
        assert km.is_key_revoked(current_key_id)
    
    def test_key_manager_get_all_keys(self, temp_db, temp_key_dir):
        """Test getting all keys."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        # Rotate a few times
        for _ in range(3):
            km.rotate_key()
        
        all_keys = km.get_all_keys()
        assert len(all_keys) == 4  # Initial + 3 rotations
    
    def test_key_manager_get_active_keys(self, temp_db, temp_key_dir):
        """Test getting active keys."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        # Rotate a few times
        for _ in range(3):
            km.rotate_key()
        
        active_keys = km.get_active_keys()
        assert len(active_keys) == 1  # Only the current key is active
    
    def test_key_manager_get_valid_keys(self, temp_db, temp_key_dir):
        """Test getting valid keys (for verification)."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        # Rotate a few times
        for _ in range(3):
            km.rotate_key()
        
        valid_keys = km.get_valid_keys()
        assert len(valid_keys) == 4  # All keys except revoked ones
    
    def test_key_manager_check_and_rotate(self, temp_db, temp_key_dir):
        """Test automatic key rotation check."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
            rotation_interval=1,  # 1 second (for testing)
        )
        km.initialize()
        
        old_key_id = km._current_key_id
        
        # Wait for rotation interval to pass
        time.sleep(1.1)
        
        # Check and rotate
        new_key = km.check_and_rotate()
        
        assert new_key is not None
        assert new_key.key_id != old_key_id
    
    def test_key_manager_cleanup_expired_keys(self, temp_db, temp_key_dir):
        """Test cleaning up expired keys."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
            key_lifetime=1,  # 1 second (for testing)
        )
        km.initialize()
        
        # Rotate to create an old key
        old_key_id = km._current_key_id
        km.rotate_key()
        
        # Wait for old key to expire
        time.sleep(1.1)
        
        # Cleanup expired keys
        removed_count = km.cleanup_expired_keys()
        
        assert removed_count >= 1
        assert old_key_id not in km._keys
    
    def test_key_manager_export_key(self, temp_db, temp_key_dir):
        """Test exporting a key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key_id = km._current_key_id
        
        # Export without private key
        exported = km.export_key(current_key_id, include_private=False)
        assert "key_id" in exported
        assert "metadata" in exported
        assert "public_keys" in exported
        assert "private_keys" not in exported
        
        # Export with private key
        exported_private = km.export_key(current_key_id, include_private=True)
        assert "private_keys" in exported_private
    
    def test_key_manager_export_nonexistent_key(self, temp_db, temp_key_dir):
        """Test exporting a non-existent key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        with pytest.raises(KeyNotFoundError):
            km.export_key("non_existent_key_id")
    
    def test_key_manager_import_key(self, temp_db, temp_key_dir):
        """Test importing a key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        # Export a key
        current_key_id = km._current_key_id
        exported = km.export_key(current_key_id, include_private=True)
        
        # Create a new KeyManager and import the key
        km2 = KeyManager(
            key_dir=temp_key_dir + "_2",
            db_path=temp_db + "_2",
        )
        km2.initialize()
        
        imported_key_id = km2.import_key(exported)
        assert imported_key_id == current_key_id
        assert imported_key_id in km2._keys


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_key_dir():
    """Create a temporary key directory for testing."""
    with tempfile.TemporaryDirectory() as key_dir:
        yield key_dir


class TestGlobalKeyManager:
    """Tests for global KeyManager singleton."""
    
    def test_global_key_manager_singleton(self, temp_db):
        """Test global KeyManager singleton."""
        # Reset to ensure clean state
        reset_key_manager()
        
        # Get global key manager
        km1 = get_key_manager(db_path=temp_db)
        km2 = get_key_manager(db_path=temp_db)
        
        assert km1 is km2
    
    def test_global_key_manager_reset(self, temp_db):
        """Test resetting global KeyManager."""
        reset_key_manager()
        
        km1 = get_key_manager(db_path=temp_db)
        km1_id = id(km1)
        
        reset_key_manager()
        
        km2 = get_key_manager(db_path=temp_db)
        km2_id = id(km2)
        
        assert km1_id != km2_id


class TestErrorHandling:
    """Tests for error handling in KeyManager."""
    
    def test_key_manager_error_hierarchy(self):
        """Test KeyManager error hierarchy."""
        assert issubclass(KeyNotFoundError, KeyManagerError)
        assert issubclass(KeyRevokedError, KeyManagerError)
        assert issubclass(KeyExpiredError, KeyManagerError)
    
    def test_verify_with_revoked_key(self, temp_db, temp_key_dir):
        """Test verification with a revoked key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key_id = km._current_key_id
        data = b"test data"
        signature, _ = km.sign(data)
        
        # Revoke the key
        km.revoke_key(current_key_id, reason="Test")
        
        # Verification should fail
        with pytest.raises(KeyRevokedError):
            km.verify(data, signature, current_key_id)
    
    def test_sign_with_revoked_key(self, temp_db, temp_key_dir):
        """Test signing with a revoked key."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key_id = km._current_key_id
        
        # Revoke the key
        km.revoke_key(current_key_id, reason="Test")
        
        # Signing should fail
        data = b"test data"
        with pytest.raises(KeyRevokedError):
            km.sign(data, key_id=current_key_id)


@pytest.mark.skipif(
    not (ED25519_AVAILABLE and DILITHIUM_AVAILABLE),
    reason="Both Ed25519 and Dilithium3 not available"
)
class TestKeyManagerWithPQC:
    """Tests for KeyManager with PQC enabled."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)
    
    @pytest.fixture
    def temp_key_dir(self):
        """Create a temporary key directory for testing."""
        with tempfile.TemporaryDirectory() as key_dir:
            yield key_dir
    
    def test_key_manager_with_pqc(self, temp_db, temp_key_dir):
        """Test KeyManager with PQC enabled."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        current_key = km.get_current_key()
        
        # Check that hybrid keys are generated
        assert current_key.ed25519_private_key is not None
        assert current_key.ed25519_public_key is not None
        assert current_key.dilithium_private_key is not None
        assert current_key.dilithium_public_key is not None
    
    def test_sign_with_pqc(self, temp_db, temp_key_dir):
        """Test signing with PQC enabled."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        data = b"test data for PQC signing"
        signature, key_id = km.sign(data)
        
        # Check that hybrid signature is created
        assert signature.is_valid()
        assert signature.is_quantum_resistant()
        assert signature.ed25519_signature is not None
        assert signature.dilithium_signature is not None
    
    def test_verify_with_pqc(self, temp_db, temp_key_dir):
        """Test verification with PQC enabled."""
        km = KeyManager(
            key_dir=temp_key_dir,
            db_path=temp_db,
        )
        km.initialize()
        
        data = b"test data for PQC verification"
        signature, key_id = km.sign(data)
        
        is_valid = km.verify(data, signature, key_id)
        assert is_valid
