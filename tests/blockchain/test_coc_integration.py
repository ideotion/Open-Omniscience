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
Integration Tests for Chain of Custody (CoC) Module

Tests the integration of CoC with:
- main_pipeline.py
- hash_chain.py
- anchor_service.py
- API endpoints

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

from src.blockchain.core.coc import (
    CoCAction,
    CoCEntry,
    CoCReport,
    ChainOfCustodyLogger,
    get_coc_logger,
    initialize_coc_logger,
    reset_coc_logger,
)
from src.blockchain.core.hash_chain import LocalHashChain
from src.blockchain.core.anchor_service import AnchorService


class TestCoCWithHashChain(unittest.TestCase):
    """Tests for CoC integration with LocalHashChain."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_hash_chain.db")
        self.coc_db_path = os.path.join(self.temp_dir, "test_coc.db")
        
        # Initialize CoC logger
        initialize_coc_logger(db_path=self.coc_db_path, enable_signing=False, enable_tsa=False)
        
        # Create hash chain
        self.hash_chain = LocalHashChain(db_path=self.db_path)

    def tearDown(self):
        """Clean up test fixtures."""
        reset_coc_logger()
        
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)

    def test_add_article_does_not_auto_log_coc(self):
        """Test that adding an article to hash chain does NOT auto-log CoC.
        
        CoC entries are logged separately via explicit calls to coc_logger.log_action().
        This test verifies that the hash chain and CoC are independent.
        """
        article_id = "test_article_1"
        content_hash = "abc123"
        metadata_hash = "def456"
        source_hash = "ghi789"
        
        # Add article to hash chain
        result = self.hash_chain.add_article(
            article_id=article_id,
            content_hash=content_hash,
            metadata_hash=metadata_hash,
            source_hash=source_hash,
        )
        
        # Check that NO CoC entry was auto-logged (CoC is separate)
        coc_logger = get_coc_logger()
        entries = coc_logger.get_coc_for_article(article_id)
        
        # Should have 0 entries (CoC is logged separately)
        self.assertEqual(len(entries), 0)
        
        # But we can manually log a CoC entry
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.INGEST,
        )
        
        # Now should have 1 entry
        entries = coc_logger.get_coc_for_article(article_id)
        self.assertEqual(len(entries), 1)

    def test_coc_entries_linked_to_articles(self):
        """Test that CoC entries are linked to articles in hash chain."""
        article_id = "test_article_1"
        content_hash = "abc123"
        metadata_hash = "def456"
        source_hash = "ghi789"
        
        # Add article to hash chain
        self.hash_chain.add_article(
            article_id=article_id,
            content_hash=content_hash,
            metadata_hash=metadata_hash,
            source_hash=source_hash,
        )
        
        # Get article hashes from hash chain
        article_hashes = self.hash_chain.get_article_hashes(article_id)
        self.assertIsNotNone(article_hashes)
        
        # Get CoC entries
        coc_logger = get_coc_logger()
        entries = coc_logger.get_coc_for_article(article_id)
        
        # Check that CoC entries reference the same article
        for entry in entries:
            self.assertEqual(entry.article_id, article_id)


class TestCoCWithAnchorService(unittest.TestCase):
    """Tests for CoC integration with AnchorService."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_anchor.db")
        self.coc_db_path = os.path.join(self.temp_dir, "test_coc.db")
        
        # Initialize CoC logger
        initialize_coc_logger(db_path=self.coc_db_path, enable_signing=False, enable_tsa=False)
        
        # Create hash chain
        hash_chain = LocalHashChain(db_path=self.db_path)
        
        # Create anchor service (without settings to disable anchoring)
        self.anchor_service = AnchorService(hash_chain, settings=None)

    def tearDown(self):
        """Clean up test fixtures."""
        reset_coc_logger()
        
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)

    def test_add_article_via_anchor_service(self):
        """Test that adding an article via AnchorService does NOT auto-log CoC.
        
        CoC entries are logged separately. The AnchorService.add_article() method
        delegates to hash_chain.add_article(), which does not auto-log CoC entries.
        """
        article_id = "test_article_1"
        content_hash = "abc123"
        metadata_hash = "def456"
        source_hash = "ghi789"
        
        # Add article via anchor service
        result = self.anchor_service.add_article(
            article_id=article_id,
            content_hash=content_hash,
            metadata_hash=metadata_hash,
            source_hash=source_hash,
        )
        
        # Check that NO CoC entry was auto-logged
        coc_logger = get_coc_logger()
        entries = coc_logger.get_coc_for_article(article_id)
        
        # Should have 0 entries (CoC is logged separately)
        self.assertEqual(len(entries), 0)
        
        # But we can manually log a CoC entry
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.INGEST,
        )
        
        # Now should have 1 entry
        entries = coc_logger.get_coc_for_article(article_id)
        self.assertEqual(len(entries), 1)


class TestCoCWithMainPipeline(unittest.TestCase):
    """Tests for CoC integration with main_pipeline.py."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.coc_db_path = os.path.join(self.temp_dir, "test_coc.db")
        
        # Initialize CoC logger
        initialize_coc_logger(db_path=self.coc_db_path, enable_signing=False, enable_tsa=False)

    def tearDown(self):
        """Clean up test fixtures."""
        reset_coc_logger()
        
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)

    def test_ingested_data_has_coc_metadata(self):
        """Test that IngestedData includes CoC metadata after ingestion."""
        from src.main_pipeline import IngestedData
        
        # Create ingested data
        ingested_data = IngestedData(
            url="https://example.com/article",
            content="Test content",
            raw_content=b"Test content",
            headers={"Content-Type": "text/html"},
        )
        
        # Check that content_hash, metadata_hash, source_hash are computed
        self.assertIsNotNone(ingested_data.content_hash)
        self.assertIsNotNone(ingested_data.metadata_hash)
        self.assertIsNotNone(ingested_data.source_hash)


class TestCoCEndToEnd(unittest.TestCase):
    """End-to-end tests for CoC workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_e2e.db")
        self.coc_db_path = os.path.join(self.temp_dir, "test_coc_e2e.db")
        
        # Initialize CoC logger
        initialize_coc_logger(db_path=self.coc_db_path, enable_signing=False, enable_tsa=False)
        
        # Create hash chain
        self.hash_chain = LocalHashChain(db_path=self.db_path)

    def tearDown(self):
        """Clean up test fixtures."""
        reset_coc_logger()
        
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)

    def test_full_workflow(self):
        """Test the full CoC workflow: ingest -> anchor -> verify."""
        article_id = "test_article_full"
        content_hash = "abc123"
        metadata_hash = "def456"
        source_hash = "ghi789"
        
        # Step 1: Add article to hash chain (simulates ingestion)
        self.hash_chain.add_article(
            article_id=article_id,
            content_hash=content_hash,
            metadata_hash=metadata_hash,
            source_hash=source_hash,
        )
        
        # Step 2: Log CoC entry for ingestion
        coc_logger = get_coc_logger()
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.INGEST,
            actor_id="test_user",
            metadata={"source": "test"},
        )
        
        # Step 3: Log CoC entry for verification
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.VERIFY,
            actor_id="test_user",
        )
        
        # Step 4: Get CoC report
        report = coc_logger.generate_report(article_id)
        
        # Verify report
        self.assertEqual(report.article_id, article_id)
        self.assertEqual(len(report.coc_entries), 2)
        self.assertTrue(report.is_verified)
        
        # Step 5: Verify CoC integrity
        is_valid, errors = coc_logger.verify_coc(article_id)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_tamper_detection(self):
        """Test that tampering with CoC entries is detected."""
        article_id = "test_article_tamper"
        content_hash = "abc123"
        
        # Log a CoC entry
        coc_logger = get_coc_logger()
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.INGEST,
        )
        
        # Verify CoC is valid
        is_valid, errors = coc_logger.verify_coc(article_id)
        self.assertTrue(is_valid)
        
        # Tamper with the database
        with sqlite3.connect(self.coc_db_path) as conn:
            conn.execute("""
                UPDATE coc_entries 
                SET article_hash = 'tampered_hash' 
                WHERE article_id = ?
            """, (article_id,))
        
        # Verify CoC detects tampering
        is_valid, errors = coc_logger.verify_coc(article_id)
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)

    def test_report_export(self):
        """Test exporting CoC reports."""
        article_id = "test_article_export"
        content_hash = "abc123"
        
        # Log some CoC entries
        coc_logger = get_coc_logger()
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.INGEST,
            actor_id="user1",
        )
        coc_logger.log_action(
            article_id=article_id,
            article_hash=content_hash,
            action=CoCAction.VERIFY,
            actor_id="user2",
        )
        
        # Export as JSON
        output_path = os.path.join(self.temp_dir, "coc_report.json")
        coc_logger.export_report_json(article_id, output_path)
        
        # Verify file exists and is valid JSON
        self.assertTrue(os.path.exists(output_path))
        with open(output_path, "r") as f:
            data = json.load(f)
        
        self.assertEqual(data["article"]["id"], article_id)
        self.assertEqual(len(data["chain_of_custody"]), 2)


class TestCoCStats(unittest.TestCase):
    """Tests for CoC statistics."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.coc_db_path = os.path.join(self.temp_dir, "test_stats.db")
        
        # Initialize CoC logger
        initialize_coc_logger(db_path=self.coc_db_path, enable_signing=False, enable_tsa=False)

    def tearDown(self):
        """Clean up test fixtures."""
        reset_coc_logger()
        
        if os.path.exists(self.temp_dir):
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(self.temp_dir)

    def test_stats_tracking(self):
        """Test that CoC statistics are tracked correctly."""
        coc_logger = get_coc_logger()
        
        # Initially, stats should be empty
        stats = coc_logger.get_stats()
        self.assertEqual(stats["total_entries"], 0)
        self.assertEqual(stats["total_articles"], 0)
        
        # Log some entries
        coc_logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.INGEST,
        )
        coc_logger.log_action(
            article_id="article_1",
            article_hash="hash1",
            action=CoCAction.MODIFY,
        )
        coc_logger.log_action(
            article_id="article_2",
            article_hash="hash2",
            action=CoCAction.INGEST,
        )
        
        # Check stats
        stats = coc_logger.get_stats()
        self.assertEqual(stats["total_entries"], 3)
        self.assertEqual(stats["total_articles"], 2)


if __name__ == "__main__":
    unittest.main()
