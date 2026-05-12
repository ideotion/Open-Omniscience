"""Consensus Scoring Module for Open-Omniscience - Phase 2.2"""
from typing import Dict, Any, List
from dataclasses import dataclass
import numpy as np
from .peer_review import PeerReviewSession, ReviewResult, ReviewDecision


@dataclass
class ConsensusResult:
    agreement_score: float
    average_score: float
    average_confidence: float
    decision_distribution: Dict[str, int]
    score_std_dev: float
    consensus_decision: ReviewDecision
    disagreements: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agreement_score": self.agreement_score,
            "average_score": self.average_score,
            "average_confidence": self.average_confidence,
            "decision_distribution": self.decision_distribution,
            "score_std_dev": self.score_std_dev,
            "consensus_decision": self.consensus_decision.value,
            "disagreements": self.disagreements
        }


class ConsensusCalculator:
    def __init__(self, agreement_threshold: float = 0.7):
        self.agreement_threshold = agreement_threshold
    
    def calculate_consensus(self, session: PeerReviewSession) -> ConsensusResult:
        if not session.reviews:
            return ConsensusResult(
                agreement_score=0.0,
                average_score=0.0,
                average_confidence=0.0,
                decision_distribution={},
                score_std_dev=0.0,
                consensus_decision=ReviewDecision.REJECT,
                disagreements=[]
            )
        
        scores = [r.score for r in session.reviews]
        decisions = [r.decision for r in session.reviews]
        confidences = [r.confidence for r in session.reviews]
        
        avg_score = float(np.mean(scores))
        avg_confidence = float(np.mean(confidences))
        score_std = float(np.std(scores)) if len(scores) > 1 else 0.0
        
        decision_counts = {}
        for decision in decisions:
            decision_counts[decision.value] = decision_counts.get(decision.value, 0) + 1
        
        if len(scores) > 1:
            normalized_std = score_std / 100.0
            agreement_score = max(0.0, 1.0 - normalized_std)
        else:
            agreement_score = 1.0
        
        consensus_decision_val = max(decision_counts.items(), key=lambda x: x[1])[0]
        consensus_decision = ReviewDecision(consensus_decision_val)
        
        disagreements = []
        for review in session.reviews:
            if review.decision != consensus_decision:
                disagreements.append({
                    "model": review.model_name,
                    "decision": review.decision.value,
                    "score": review.score,
                    "confidence": review.confidence
                })
        
        return ConsensusResult(
            agreement_score=agreement_score,
            average_score=avg_score,
            average_confidence=avg_confidence,
            decision_distribution=decision_counts,
            score_std_dev=score_std,
            consensus_decision=consensus_decision,
            disagreements=disagreements
        )
    
    def has_consensus(self, session: PeerReviewSession) -> bool:
        result = self.calculate_consensus(session)
        return result.agreement_score >= self.agreement_threshold
    
    def get_consensus_summary(self, session: PeerReviewSession) -> Dict[str, Any]:
        result = self.calculate_consensus(session)
        return {
            "has_consensus": self.has_consensus(session),
            "agreement_score": result.agreement_score,
            "consensus_decision": result.consensus_decision.value,
            "average_score": result.average_score,
            "num_disagreements": len(result.disagreements),
            "decision_distribution": result.decision_distribution
        }
    
    def calculate_pairwise_agreement(self, reviews: List[ReviewResult]) -> float:
        if len(reviews) < 2:
            return 1.0
        agreements = 0
        total = 0
        for i in range(len(reviews)):
            for j in range(i + 1, len(reviews)):
                if reviews[i].decision == reviews[j].decision:
                    agreements += 1
                total += 1
        return agreements / total if total > 0 else 1.0
    
    def calculate_weighted_consensus(self, session: PeerReviewSession) -> ConsensusResult:
        if not session.reviews:
            return self.calculate_consensus(session)
        weighted_scores = [r.score * r.confidence for r in session.reviews]
        total_weight = sum(r.confidence for r in session.reviews)
        if total_weight == 0:
            total_weight = 1
        avg_weighted_score = sum(weighted_scores) / total_weight
        simple_result = self.calculate_consensus(session)
        return ConsensusResult(
            agreement_score=simple_result.agreement_score,
            average_score=avg_weighted_score,
            average_confidence=simple_result.average_confidence,
            decision_distribution=simple_result.decision_distribution,
            score_std_dev=simple_result.score_std_dev,
            consensus_decision=simple_result.consensus_decision,
            disagreements=simple_result.disagreements
        )
