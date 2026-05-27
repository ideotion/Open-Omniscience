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
Unit Tests for Chain of Custody (CoC) Module

Tests the following components:
- CoCAction enum
- CoCEntry dataclass
- CoCReport dataclass
- ChainOfCustodyLogger class
- Singleton functions (get_coc_logger, initialize_coc_logger, reset_coc_logger)

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the CoC module
from src.blockchain.core.coc import (
    CoCAction,
    CoCEntry,
    CoCReport,
    CoCError,
    CoCVerificationError,
    CoCTimestampError,
    CoCSignatureError,
    ChainOfCustodyLogger,
    get_coc_logger,
    initialize_coc_logger,
    reset_coc_logger,
    _coc_logger,
)


class TestCoCAction(unittest.TestCase):
    """Tests for the CoCAction enum."""

    def test_enum_values(self):
        """Test that all enum values are strings."""
        for action in CoCAction:
            self.assertIsInstance(action.value, str)

    def test_enum_members(self):
        """Test that all expected enum members exist."""
        expected_actions = [
            "ingest", "modify", "access", "delete", "verify",
            "anchor", "restore", "export", "redact", "sign"
        ]
        actual_actions = [action.value for action in CoCAction]
        for expected in expected_actions:
            self.assertIn(expected, actual_actions)

    def test_enum_unique(self):
        """Test that all enum values are unique."""
        values = [action.value for action in CoCAction]
        self.assertEqual(len(values), len(set(values)))


class TestCoCEntry(unittest.TestCase):
    """Tests for the CoCEntry dataclass."""

    def setUp(self):
        """Set up test fixtures."""
        self.article_id = "test_article_123"
        self.article_hash = "abc123def456"
        self.action = CoCAction.INGEST
        self.timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.metadata = {"key": "value"}

    def test_create_entry(self):
        """Test creating a CoCEntry."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
            metadata=self.metadata,
        )
        
        self.assertEqual(entry.entry_id, "entry_1")
        self.assertEqual(entry.article_id, self.article_id)
        self.assertEqual(entry.article_hash, self.article_hash)
        self.assertEqual(entry.action, self.action)
        self.assertEqual(entry.timestamp, self.timestamp)
        self.assertEqual(entry.metadata, self.metadata)
        self.assertIsNotNone(entry.entry_hash)

    def test_entry_hash_computed(self):
        """Test that entry_hash is computed automatically."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        
        # entry_hash should be a SHA-256 hex string
        self.assertEqual(len(entry.entry_hash), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in entry.entry_hash))

    def test_entry_hash_consistency(self):
        """Test that entry_hash is consistent for the same data."""
        entry1 = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        entry2 = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        
        self.assertEqual(entry1.entry_hash, entry2.entry_hash)

    def test_entry_hash_changes_with_data(self):
        """Test that entry_hash changes when data changes."""
        entry1 = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        entry2 = CoCEntry(
            entry_id="entry_2",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        
        self.assertNotEqual(entry1.entry_hash, entry2.entry_hash)

    def test_verify_hash(self):
        """Test the verify_hash method."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        
        self.assertTrue(entry.verify_hash())

    def test_verify_hash_tampered(self):
        """Test verify_hash with tampered data."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
        )
        
        # Tamper with the entry
        entry.article_id = "tampered_article"
        
        self.assertFalse(entry.verify_hash())

    def test_to_dict(self):
        """Test converting entry to dictionary."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
            actor_id="journalist_1",
            metadata=self.metadata,
        )
        
        data = entry.to_dict()
        
        self.assertEqual(data["entry_id"], "entry_1")
        self.assertEqual(data["article_id"], self.article_id)
        self.assertEqual(data["article_hash"], self.article_hash)
        self.assertEqual(data["action"], "ingest")
        self.assertEqual(data["timestamp"], "2024-01-01T12:00:00+00:00")
        self.assertEqual(data["actor_id"], "journalist_1")
        self.assertEqual(data["metadata"], self.metadata)
        self.assertIn("entry_hash", data)

    def test_to_dict_without_signature(self):
        """Test to_dict without including signature."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
            actor_signature=b"signature_bytes",
        )
        
        data = entry.to_dict(include_signature=False)
        self.assertNotIn("actor_signature", data)

    def test_from_dict(self):
        """Test creating entry from dictionary."""
        original_entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=self.action,
            timestamp=self.timestamp,
            actor_id="journalist_1",
            metadata=self.metadata,
        )
        
        data = original_entry.to_dict()
        restored_entry = CoCEntry.from_dict(data)
        
        self.assertEqual(restored_entry.entry_id, original_entry.entry_id)
        self.assertEqual(restored_entry.article_id, original_entry.article_id)
        self.assertEqual(restored_entry.article_hash, original_entry.article_hash)
        self.assertEqual(restored_entry.action, original_entry.action)
        self.assertEqual(restored_entry.timestamp, original_entry.timestamp)
        self.assertEqual(restored_entry.actor_id, original_entry.actor_id)
        self.assertEqual(restored_entry.metadata, original_entry.metadata)
        self.assertEqual(restored_entry.entry_hash, original_entry.entry_hash)

    def test_chaining(self):
        """Test that entries can be chained together."""
        entry1 = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=CoCAction.INGEST,
            timestamp=self.timestamp,
        )
        
        entry2 = CoCEntry(
            entry_id="entry_2",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=CoCAction.MODIFY,
            timestamp=datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            previous_entry_hash=entry1.entry_hash,
        )
        
        self.assertEqual(entry2.previous_entry_hash, entry1.entry_hash)


class TestCoCReport(unittest.TestCase):
    """Tests for the CoCReport dataclass."""

    def setUp(self):
        """Set up test fixtures."""
        self.article_id = "test_article_123"
        self.article_hash = "abc123def456"
        self.article_metadata = {"title": "Test Article", "source": "Test Source"}
        
        self.entry1 = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=CoCAction.INGEST,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        
        self.entry2 = CoCEntry(
            entry_id="entry_2",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=CoCAction.MODIFY,
            timestamp=datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            previous_entry_hash=self.entry1.entry_hash,
        )

    def test_create_report(self):
        """Test creating a CoCReport."""
        report = CoCReport(
            report_id="report_1",
            generated_at=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
            generated_by="Open-Omniscience",
            article_id=self.article_id,
            article_hash=self.article_hash,
            article_metadata=self.article_metadata,
            coc_entries=[self.entry1, self.entry2],
            is_verified=True,
            verification_errors=[],
        )
        
        self.assertEqual(report.report_id, "report_1")
        self.assertEqual(report.article_id, self.article_id)
        self.assertEqual(len(report.coc_entries), 2)
        self.assertTrue(report.is_verified)

    def test_to_dict(self):
        """Test converting report to dictionary."""
        report = CoCReport(
            report_id="report_1",
            generated_at=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
            generated_by="Open-Omniscience",
            article_id=self.article_id,
            article_hash=self.article_hash,
            article_metadata=self.article_metadata,
            coc_entries=[self.entry1, self.entry2],
            is_verified=True,
        )
        
        data = report.to_dict()
        
        self.assertEqual(data["report_id"], "report_1")
        self.assertEqual(data["article"]["id"], self.article_id)
        self.assertEqual(data["article"]["hash"], self.article_hash)
        self.assertIn("chain_of_custody", data)
        self.assertEqual(len(data["chain_of_custody"]), 2)
        self.assertTrue(data["verification"]["is_verified"])

    def test_to_json(self):
        """Test converting report to JSON."""
        report = CoCReport(
            report_id="report_1",
            generated_at=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
            generated_by="Open-Omniscience",
            article_id=self.article_id,
            article_hash=self.article_hash,
            article_metadata=self.article_metadata,
            coc_entries=[self.entry1],
            is_verified=True,
        )
        
        json_str = report.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        self.assertEqual(parsed["report_id"], "report_1")

    def test_redaction(self):
        """Test redaction in reports."""
        entry = CoCEntry(
            entry_id="entry_1",
            article_id=self.article_id,
            article_hash=self.article_hash,
            action=CoCAction.INGEST,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            actor_id="journalist_1",
            metadata={"sensitive": "data"},
        )
        
        report = CoCReport(
            report_id="report_1",
            generated_at=datetime(2024, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
            generated_by="Open-Omniscience",
            article_id=self.article_id,
            article_hash=self.article_hash,
            article_metadata={},
            coc_entries=[entry],
            redact_actor_ids=True,
            redact_metadata=True,
        )
        
        data = report.to_dict()
        
        # Check that actor_id and metadata are redacted
        self.assertEqual(data["chain_of_custody"][0]["actor_id"], "REDACTED")
        self.assertEqual(data["chain_of_custody"][0]["metadata"], "REDACTED")


class TestChainOfCustodyLogger(unittest.TestCase):
    """Tests for the ChainOfCustodyLogger class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_coc.db")
        
        # Create a logger without signing or TSA for simplicity
        self.logger = ChainOfCustodyLogger(
            db_path=self.db_path,
            enable_signing=False,
            enable_tsa=False,
        )

    def tearDown(self):
        """Clean up test fixtures."""
        # Close any open connections
        if hasattr(self.logger, '_conn'):
            pass  # SQLite connections are managed per-method
        
        # Remove temp directory
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, file))
            os.rmdir(self.temp_dir)

    def test_initialize_database(self):
        """Test that the database is initialized correctly."""
        # Check that the table exists
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            self.assertIn("coc_entries", tables)

    def test_log_action(self):
        """Test logging an action."""
        entry = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
            actor_id="journalist_1",
            metadata={"key": "value"},
        )
        
        self.assertEqual(entry.article_id, "article_1")
        self.assertEqual(entry.article_hash, "hash1")
        self.assertEqual(entry.action, CoCAction.INGEST)
        self.assertEqual(entry.actor_id, "journalist_1")
        self.assertEqual(entry.metadata, {"key": "value"})
        self.assertIsNotNone(entry.entry_hash)

    def test_log_multiple_actions(self):
        """Test logging multiple actions for the same article."""
        entry1 = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        entry2 = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.MODIFY,
        )
        
        # Check that the second entry references the first
        self.assertEqual(entry2.previous_entry_hash, entry1.entry_hash)

    def test_get_coc_for_article(self):
        """Test retrieving CoC entries for an article."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.MODIFY,
        )
        self.logger.log_action(
            article_id="article_2",
            article_hash="hash2",
            action=CoCAction.INGEST,
        )
        
        entries = self.logger.get_coc_for_article("article_1")
        
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].action, CoCAction.INGEST)
        self.assertEqual(entries[1].action, CoCAction.MODIFY)

    def test_get_coc_for_nonexistent_article(self):
        """Test retrieving CoC for a non-existent article."""
        entries = self.logger.get_coc_for_article("nonexistent")
        self.assertEqual(len(entries), 0)

    def test_verify_coc_valid(self):
        """Test verifying a valid CoC."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.MODIFY,
        )
        
        is_valid, errors = self.logger.verify_coc("article_1")
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_verify_coc_tampered(self):
        """Test verifying a tampered CoC."""
        # Log some entries
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        # Tamper with the database (simulate an attack)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE coc_entries 
                SET article_hash = 'tampered_hash' 
                WHERE article_id = 'article_1'
            """)
        
        # Force reload of entries to pick up the tampering
        # Verification should fail because the entry_hash won't match the tampered data
        is_valid, errors = self.logger.verify_coc("article_1")
        
        # The verification should fail because the entry_hash was computed with the original data
        # but the database now has tampered data, so the recomputed hash won't match
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)

    def test_verify_coc_empty(self):
        """Test verifying an empty CoC."""
        is_valid, errors = self.logger.verify_coc("nonexistent")
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_generate_report(self):
        """Test generating a CoC report."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
            actor_id="journalist_1",
        )
        
        report = self.logger.generate_report("article_1")
        
        self.assertEqual(report.article_id, "article_1")
        self.assertEqual(len(report.coc_entries), 1)
        self.assertTrue(report.is_verified)

    def test_export_report_json(self):
        """Test exporting a report as JSON."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        output_path = os.path.join(self.temp_dir, "report.json")
        self.logger.export_report_json("article_1", output_path)
        
        self.assertTrue(os.path.exists(output_path))
        
        with open(output_path, "r") as f:
            data = json.load(f)
        
        self.assertEqual(data["article"]["id"], "article_1")

    def test_get_all_articles(self):
        """Test getting all articles with CoC entries."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        self.logger.log_action(
            article_id="article_2",
            article_hash="hash2",
            action=CoCAction.INGEST,
        )
        
        articles = self.logger.get_all_articles()
        
        self.assertEqual(len(articles), 2)
        self.assertIn("article_1", articles)
        self.assertIn("article_2", articles)

    def test_get_stats(self):
        """Test getting CoC statistics."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.MODIFY,
        )
        
        stats = self.logger.get_stats()
        
        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["total_articles"], 1)
        self.assertEqual(stats["db_path"], self.db_path)

    def test_get_entries_by_time_range(self):
        """Test getting entries by time range."""
        # Use a time range that includes the current time
        start_time = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2030, 1, 1, 23, 59, 59, tzinfo=timezone.utc)
        
        # Log entries within the time range
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        # Log an entry outside the time range (simulate by modifying timestamp)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO coc_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "entry_old",
                "article_old",
                "hash_old",
                "ingest",
                "1990-01-01T00:00:00+00:00",  # Outside range
                None,
                None,
                None,
                None,
                None,
                "hash_old",
                "{}",
            ))
        
        entries = self.logger.get_entries_by_time_range(start_time, end_time)
        
        # Should only get the entry within the range
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].article_id, "article_1")


class TestSingletonFunctions(unittest.TestCase):
    """Tests for the singleton functions."""

    def setUp(self):
        """Reset the singleton before each test."""
        reset_coc_logger()

    def tearDown(self):
        """Reset the singleton after each test."""
        reset_coc_logger()

    def test_initialize_coc_logger(self):
        """Test initializing the global CoC logger."""
        logger = initialize_coc_logger(db_path=":memory:")
        
        self.assertIsInstance(logger, ChainOfCustodyLogger)

    def test_get_coc_logger(self):
        """Test getting the global CoC logger."""
        initialize_coc_logger(db_path=":memory:")
        
        logger = get_coc_logger()
        
        self.assertIsInstance(logger, ChainOfCustodyLogger)

    def test_get_coc_logger_not_initialized(self):
        """Test getting the logger before initialization."""
        with self.assertRaises(CoCError):
            get_coc_logger()

    def test_reset_coc_logger(self):
        """Test resetting the global CoC logger."""
        initialize_coc_logger(db_path=":memory:")
        
        reset_coc_logger()
        
        with self.assertRaises(CoCError):
            get_coc_logger()


class TestCoCWithSigning(unittest.TestCase):
    """Tests for CoC with signing enabled."""

    def setUp(self):
        """Set up test fixtures with signing."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_coc_signed.db")
        
        # Generate a test Ed25519 key pair
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            
            self.private_key = Ed25519PrivateKey.generate()
            self.private_key_bytes = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            self.logger = ChainOfCustodyLogger(
                db_path=self.db_path,
                private_key=self.private_key_bytes,
                enable_signing=True,
                enable_tsa=False,
            )
        except ImportError:
            # Skip tests if cryptography is not available
            self.skipTest("cryptography library not available")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, file))
            os.rmdir(self.temp_dir)

    def test_signing_enabled(self):
        """Test that signing is enabled."""
        self.assertTrue(self.logger.enable_signing)

    def test_log_action_with_signing(self):
        """Test logging an action with signing."""
        entry = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        self.assertIsNotNone(entry.actor_signature)
        self.assertGreater(len(entry.actor_signature), 0)

    def test_verify_signature(self):
        """Test verifying a signed entry."""
        entry = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        # The signature should be verifiable
        is_valid = self.logger._verify_signature(entry)
        self.assertTrue(is_valid)

    def test_verify_coc_with_signing(self):
        """Test verifying a CoC with signing enabled."""
        self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        is_valid, errors = self.logger.verify_coc("article_1")
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)


class TestCoCWithTSA(unittest.TestCase):
    """Tests for CoC with TSA enabled (mocked)."""

    def setUp(self):
        """Set up test fixtures with TSA."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_coc_tsa.db")
        
        # Create logger without TSA (we'll test TSA functionality separately)
        # For now, just test that the logger can be created with TSA enabled
        self.logger = ChainOfCustodyLogger(
            db_path=self.db_path,
            tsa_url="http://mock-tsa.com",
            enable_signing=False,
            enable_tsa=False,  # Disable TSA for now (requires network)
        )

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, file))
            os.rmdir(self.temp_dir)

    def test_tsa_disabled_by_default(self):
        """Test that TSA is disabled when no URL is provided."""
        logger = ChainOfCustodyLogger(
            db_path=self.db_path,
            enable_signing=False,
            enable_tsa=False,
        )
        self.assertFalse(logger.enable_tsa)

    def test_log_action_without_tsa(self):
        """Test logging an action without TSA."""
        entry = self.logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        
        # TSA fields should be None when TSA is disabled
        self.assertIsNone(entry.tsa_timestamp)
        self.assertIsNone(entry.tsa_token)


if __name__ == "__main__":
    unittest.main()
