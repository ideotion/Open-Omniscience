"""Peer-Review Simulation Module for Open-Omniscience - Phase 2.2"""
import hashlib, time, re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

class ReviewStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class ReviewDecision(Enum):
    ACCEPT = "accept"
    MINOR_REVISIONS = "minor_revisions"
    MAJOR_REVISIONS = "major_revisions"
    REJECT = "reject"

@dataclass
class ReviewResult:
    model_name: str
    model_id: str
    review_text: str
    score: float
    decision: ReviewDecision
    confidence: float
    review_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_id": self.model_id,
            "review_text": self.review_text,
            "score": self.score,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "review_time": self.review_time,
            "metadata": self.metadata
        }

@dataclass
class BlindReview:
    review_id: str
    content_hash: str
    review_text: str
    score: float
    decision: ReviewDecision
    confidence: float
    timestamp: float

@dataclass
class PeerReviewSession:
    id: str
    content: str
    content_hash: str
    reviews: List[ReviewResult] = field(default_factory=list)
    blind_reviews: List[BlindReview] = field(default_factory=list)
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_review(self, review):
        self.reviews.append(review)
    
    def add_blind_review(self, blind_review):
        self.blind_reviews.append(blind_review)
    
    def mark_completed(self):
        self.status = ReviewStatus.COMPLETED
        self.completed_at = time.time()
    
    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "content_hash": self.content_hash,
            "reviews": [r.to_dict() for r in self.reviews],
            "blind_reviews": [r.to_dict() for r in self.blind_reviews],
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata
        }
    
    def get_average_score(self):
        if not self.reviews:
            return 0.0
        return float(np.mean([r.score for r in self.reviews]))
    
    def get_average_confidence(self):
        if not self.reviews:
            return 0.0
        return float(np.mean([r.confidence for r in self.reviews]))


class PeerReviewSimulator:
    def __init__(self, ollama_base_url="http://localhost:11434", default_models=None, timeout=120):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.default_models = default_models or ["llama3.2:3b", "mistral:7b"]
        self.timeout = timeout

    def _generate_hash(self, content):
        return hashlib.sha256(content.encode()).hexdigest()

    def _generate_id(self, prefix=""):
        return hashlib.sha256((prefix + str(time.time()) + str(np.random.randint(0, 1000000))).encode()).hexdigest()[:16]

    def _call_ollama(self, model, prompt, system=None):
        import requests
        payload = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        response = requests.post(f"{self.ollama_base_url}/api/generate", json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _extract_score(self, text):
        for pattern in [r"Score:\s*(\d+(?:\.\d+)?)", r"score:\s*(\d+(?:\.\d+)?)", r"(\d+(?:\.\d+)?)\s*/\s*100"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    s = float(match.group(1))
                    if 0 <= s <= 100:
                        return s
                except:
                    pass
        return 75.0

    def _extract_decision(self, text):
        text = text.lower()
        if any(w in text for w in ["accept", "excellent", "perfect", "publish"]):
            return ReviewDecision.ACCEPT
        if any(w in text for w in ["reject", "not acceptable", "poor"]):
            return ReviewDecision.REJECT
        if any(w in text for w in ["major revision", "major changes"]):
            return ReviewDecision.MAJOR_REVISIONS
        return ReviewDecision.MINOR_REVISIONS

    def _extract_confidence(self, text):
        for pattern in [r"Confidence:\s*(\d+(?:\.\d+)?)", r"confidence:\s*(\d+(?:\.\d+)?)"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    c = float(match.group(1))
                    if 0 <= c <= 1:
                        return c
                    if 0 <= c <= 100:
                        return c / 100.0
                except:
                    pass
        return 0.8

    def create_session(self, content, models=None):
        models = models or self.default_models
        return PeerReviewSession(
            id=self._generate_id("session"),
            content=content,
            content_hash=self._generate_hash(content),
            metadata={"models": models}
        )

    def conduct_review(self, session, model):
        start = time.time()
        prompt = self._generate_review_prompt(session.content)
        system_prompt = self._generate_system_prompt()
        try:
            resp = self._call_ollama(model, prompt, system_prompt)
            text = resp.get("response", "")
            score = self._extract_score(text)
            decision = self._extract_decision(text)
            confidence = self._extract_confidence(text)
            return ReviewResult(
                model_name=model,
                model_id=self._generate_id(f"{model}_review"),
                review_text=text,
                score=score,
                decision=decision,
                confidence=confidence,
                review_time=time.time() - start,
                metadata={"model": model}
            )
        except Exception as e:
            return ReviewResult(
                model_name=model,
                model_id=self._generate_id(f"{model}_failed"),
                review_text=f"Review failed: {str(e)}",
                score=0.0,
                decision=ReviewDecision.REJECT,
                confidence=0.0,
                review_time=time.time() - start,
                metadata={"error": str(e)}
            )

    def conduct_multi_model_review(self, content, models=None):
        models = models or self.default_models
        session = self.create_session(content, models)
        session.status = ReviewStatus.IN_PROGRESS
        for model in models:
            try:
                session.add_review(self.conduct_review(session, model))
            except Exception as e:
                print(f"Warning: Failed review from {model}: {e}")
        session.mark_completed()
        return session

    def create_blind_review(self, content, model):
        content_hash = self._generate_hash(content)
        prompt = self._generate_blind_prompt(content)
        system_prompt = self._generate_system_prompt()
        try:
            resp = self._call_ollama(model, prompt, system_prompt)
            text = resp.get("response", "")
            score = self._extract_score(text)
            decision = self._extract_decision(text)
            confidence = self._extract_confidence(text)
            return BlindReview(
                review_id=self._generate_id("blind"),
                content_hash=content_hash,
                review_text=text,
                score=score,
                decision=decision,
                confidence=confidence,
                timestamp=time.time()
            )
        except Exception as e:
            return BlindReview(
                review_id=self._generate_id("blind_failed"),
                content_hash=content_hash,
                review_text=f"Blind review failed: {str(e)}",
                score=0.0,
                decision=ReviewDecision.REJECT,
                confidence=0.0,
                timestamp=time.time()
            )

    def _generate_review_prompt(self, content):
        return f"Review this content:\n{content}\n\nProvide: Assessment, Strengths, Weaknesses, Suggestions.\nFinal: Score (0-100), Decision (accept/minor_revisions/major_revisions/reject), Confidence (0-1)"

    def _generate_blind_prompt(self, content):
        return f"Review ANONYMIZED content (ignore metadata):\n{content}\n\nProvide: Assessment, Strengths, Weaknesses, Suggestions.\nFinal: Score (0-100), Decision, Confidence (0-1)"

    def _generate_system_prompt(self):
        return "You are an expert peer reviewer. Be thorough, critical, and professional. Consider: Scientific Rigor, Clarity, Originality, Reproducibility, Significance."
