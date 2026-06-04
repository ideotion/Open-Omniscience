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
"""Tests for peer_review.py module - Phase 2.2"""
import pytest
from src.analysis.peer_review import (
    PeerReviewSimulator,
    PeerReviewSession,
    ReviewResult,
    BlindReview,
    ReviewStatus,
    ReviewDecision
)


class TestPeerReviewDataClasses:
    def test_review_result_creation(self):
        result = ReviewResult(
            model_name="test_model",
            model_id="test_id",
            review_text="Test review",
            score=85.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.9,
            review_time=10.5
        )
        assert result.model_name == "test_model"
        assert result.score == 85.0
        assert result.decision == ReviewDecision.ACCEPT
        assert result.to_dict()["model_name"] == "test_model"
    
    def test_blind_review_creation(self):
        review = BlindReview(
            review_id="blind_001",
            content_hash="abc123",
            review_text="Blind review text",
            score=75.0,
            decision=ReviewDecision.MINOR_REVISIONS,
            confidence=0.8,
            timestamp=1234567890.0
        )
        assert review.review_id == "blind_001"
        assert review.content_hash == "abc123"
        assert review.decision == ReviewDecision.MINOR_REVISIONS
    
    def test_peer_review_session_creation(self):
        session = PeerReviewSession(
            id="session_001",
            content="Test content",
            content_hash="def456",
            status=ReviewStatus.PENDING
        )
        assert session.id == "session_001"
        assert session.content == "Test content"
        assert session.status == ReviewStatus.PENDING
    
    def test_session_methods(self):
        session = PeerReviewSession(
            id="session_001",
            content="Test",
            content_hash="abc"
        )
        
        review = ReviewResult(
            model_name="model1",
            model_id="r1",
            review_text="Review 1",
            score=80.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.85,
            review_time=5.0
        )
        
        session.add_review(review)
        assert len(session.reviews) == 1
        assert session.get_average_score() == 80.0
        assert session.get_average_confidence() == 0.85
        
        session.mark_completed()
        assert session.status == ReviewStatus.COMPLETED
        assert session.completed_at is not None


class TestPeerReviewSimulator:
    def test_simulator_initialization(self):
        simulator = PeerReviewSimulator()
        assert simulator.ollama_base_url == "http://localhost:11434"
        assert len(simulator.default_models) > 0
    
    def test_simulator_with_custom_url(self):
        simulator = PeerReviewSimulator(ollama_base_url="http://custom:1234")
        assert simulator.ollama_base_url == "http://custom:1234"
    
    def test_generate_hash(self):
        simulator = PeerReviewSimulator()
        hash1 = simulator._generate_hash("test content")
        hash2 = simulator._generate_hash("test content")
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hash length
    
    def test_generate_id(self):
        simulator = PeerReviewSimulator()
        id1 = simulator._generate_id("test")
        id2 = simulator._generate_id("test")
        assert id1 != id2  # Should be different due to timestamp
        assert len(id1) == 16
    
    def test_extract_score(self):
        simulator = PeerReviewSimulator()
        assert simulator._extract_score("Score: 85") == 85.0
        assert simulator._extract_score("score: 92.5") == 92.5
        assert simulator._extract_score("80/100") == 80.0
        assert simulator._extract_score("No score here") == 75.0
    
    def test_extract_decision(self):
        simulator = PeerReviewSimulator()
        assert simulator._extract_decision("accept this") == ReviewDecision.ACCEPT
        assert simulator._extract_decision("REJECT") == ReviewDecision.REJECT
        assert simulator._extract_decision("major revision needed") == ReviewDecision.MAJOR_REVISIONS
        assert simulator._extract_decision("some text") == ReviewDecision.MINOR_REVISIONS
    
    def test_extract_confidence(self):
        simulator = PeerReviewSimulator()
        assert simulator._extract_confidence("Confidence: 0.9") == 0.9
        assert simulator._extract_confidence("confidence: 85") == 0.85
        assert simulator._extract_confidence("No confidence") == 0.8
    
    def test_create_session(self):
        simulator = PeerReviewSimulator()
        session = simulator.create_session("Test content", ["model1", "model2"])
        assert session.id is not None
        assert session.content == "Test content"
        assert session.content_hash is not None
        assert session.metadata["models"] == ["model1", "model2"]
    
    def test_generate_prompts(self):
        simulator = PeerReviewSimulator()
        content = "Test research content"
        
        review_prompt = simulator._generate_review_prompt(content)
        assert "Test research content" in review_prompt
        assert "Score" in review_prompt
        assert "Decision" in review_prompt
        
        blind_prompt = simulator._generate_blind_prompt(content)
        assert "ANONYMIZED" in blind_prompt
        assert "ignore metadata" in blind_prompt
        
        system_prompt = simulator._generate_system_prompt()
        assert "expert peer reviewer" in system_prompt
