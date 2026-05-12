"""Tests for consensus.py module - Phase 2.2"""
import pytest
from src.analysis.consensus import ConsensusCalculator, ConsensusResult
from src.analysis.peer_review import PeerReviewSession, ReviewResult, ReviewDecision


class TestConsensusCalculator:
    def test_initialization(self):
        calculator = ConsensusCalculator()
        assert calculator.agreement_threshold == 0.7
    
    def test_custom_threshold(self):
        calculator = ConsensusCalculator(agreement_threshold=0.8)
        assert calculator.agreement_threshold == 0.8
    
    def test_calculate_consensus_empty(self):
        calculator = ConsensusCalculator()
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        result = calculator.calculate_consensus(session)
        assert result.agreement_score == 0.0
        assert result.average_score == 0.0
        assert result.consensus_decision == ReviewDecision.REJECT
    
    def test_calculate_consensus_single_review(self):
        calculator = ConsensusCalculator()
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        session.add_review(ReviewResult(
            model_name="model1",
            model_id="r1",
            review_text="Good",
            score=90.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.95,
            review_time=5.0
        ))
        result = calculator.calculate_consensus(session)
        assert result.agreement_score == 1.0
        assert result.average_score == 90.0
        assert result.average_confidence == 0.95
        assert result.consensus_decision == ReviewDecision.ACCEPT
    
    def test_calculate_consensus_multiple_reviews(self):
        calculator = ConsensusCalculator()
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        
        session.add_review(ReviewResult(
            model_name="model1",
            model_id="r1",
            review_text="Good",
            score=85.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.9,
            review_time=5.0
        ))
        session.add_review(ReviewResult(
            model_name="model2",
            model_id="r2",
            review_text="Very good",
            score=90.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.95,
            review_time=6.0
        ))
        
        result = calculator.calculate_consensus(session)
        assert result.agreement_score > 0.9
        assert result.average_score == 87.5
        assert result.consensus_decision == ReviewDecision.ACCEPT
        assert len(result.disagreements) == 0
    
    def test_calculate_consensus_with_disagreements(self):
        calculator = ConsensusCalculator()
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        
        session.add_review(ReviewResult(
            model_name="model1",
            model_id="r1",
            review_text="Accept",
            score=85.0,
            decision=ReviewDecision.ACCEPT,
            confidence=0.9,
            review_time=5.0
        ))
        session.add_review(ReviewResult(
            model_name="model2",
            model_id="r2",
            review_text="Reject",
            score=40.0,
            decision=ReviewDecision.REJECT,
            confidence=0.8,
            review_time=6.0
        ))
        
        result = calculator.calculate_consensus(session)
        assert result.agreement_score < 1.0
        assert result.consensus_decision in [ReviewDecision.ACCEPT, ReviewDecision.REJECT]
        assert len(result.disagreements) == 1
    
    def test_has_consensus(self):
        calculator = ConsensusCalculator(agreement_threshold=0.8)
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        
        # Add reviews with high agreement
        session.add_review(ReviewResult(
            model_name="model1", model_id="r1", review_text="Good",
            score=85.0, decision=ReviewDecision.ACCEPT, confidence=0.9, review_time=5.0
        ))
        session.add_review(ReviewResult(
            model_name="model2", model_id="r2", review_text="Good",
            score=88.0, decision=ReviewDecision.ACCEPT, confidence=0.95, review_time=6.0
        ))
        
        assert calculator.has_consensus(session) is True
    
    def test_no_consensus(self):
        calculator = ConsensusCalculator(agreement_threshold=0.9)
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        
        # Add reviews with low agreement
        session.add_review(ReviewResult(
            model_name="model1", model_id="r1", review_text="Accept",
            score=85.0, decision=ReviewDecision.ACCEPT, confidence=0.9, review_time=5.0
        ))
        session.add_review(ReviewResult(
            model_name="model2", model_id="r2", review_text="Reject",
            score=40.0, decision=ReviewDecision.REJECT, confidence=0.8, review_time=6.0
        ))
        
        assert calculator.has_consensus(session) is False
    
    def test_get_consensus_summary(self):
        calculator = ConsensusCalculator()
        session = PeerReviewSession(id="test", content="test", content_hash="abc")
        session.add_review(ReviewResult(
            model_name="model1", model_id="r1", review_text="Good",
            score=85.0, decision=ReviewDecision.ACCEPT, confidence=0.9, review_time=5.0
        ))
        
        summary = calculator.get_consensus_summary(session)
        assert "has_consensus" in summary
        assert "agreement_score" in summary
        assert "consensus_decision" in summary
        assert "average_score" in summary
    
    def test_pairwise_agreement(self):
        calculator = ConsensusCalculator()
        reviews = [
            ReviewResult("m1", "r1", "", 85, ReviewDecision.ACCEPT, 0.9, 5.0),
            ReviewResult("m2", "r2", "", 90, ReviewDecision.ACCEPT, 0.95, 6.0),
            ReviewResult("m3", "r3", "", 80, ReviewDecision.ACCEPT, 0.85, 7.0)
        ]
        agreement = calculator.calculate_pairwise_agreement(reviews)
        assert agreement == 1.0  # All agree
    
    def test_pairwise_agreement_mixed(self):
        calculator = ConsensusCalculator()
        reviews = [
            ReviewResult("m1", "r1", "", 85, ReviewDecision.ACCEPT, 0.9, 5.0),
            ReviewResult("m2", "r2", "", 90, ReviewDecision.ACCEPT, 0.95, 6.0),
            ReviewResult("m3", "r3", "", 80, ReviewDecision.REJECT, 0.85, 7.0)
        ]
        agreement = calculator.calculate_pairwise_agreement(reviews)
        assert abs(agreement - 1.0 / 3.0) < 0.0001  # 1 out of 3 pairs agree
    
    def test_to_dict(self):
        result = ConsensusResult(
            agreement_score=0.95,
            average_score=87.5,
            average_confidence=0.9,
            decision_distribution={"accept": 2, "reject": 1},
            score_std_dev=5.0,
            consensus_decision=ReviewDecision.ACCEPT,
            disagreements=[]
        )
        d = result.to_dict()
        assert d["agreement_score"] == 0.95
        assert d["average_score"] == 87.5
        assert d["consensus_decision"] == "accept"
