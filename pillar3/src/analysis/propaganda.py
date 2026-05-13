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
Propaganda Detection Module

Detects propaganda techniques and manipulative language patterns in text content
using 100% FOSS NLP libraries. Works completely offline.

Features:
- 15+ propaganda technique detection
- Emotional language analysis
- Loaded language detection
- Logical fallacy identification
- Source credibility assessment
- Confidence scoring
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

import numpy as np

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
except ImportError:
    HAS_VADER = False


class PropagandaStatus(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class PropagandaTechnique(Enum):
    APPEAL_TO_EMOTION = "appeal_to_emotion"
    BANDWAGON = "bandwagon"
    BLACK_AND_WHITE_FALLACY = "black_and_white_fallacy"
    CIRCULAR_REASONING = "circular_reasoning"
    FALSE_CAUSE = "false_cause"
    HASTY_GENERALIZATION = "hasty_generalization"
    RED_HERRING = "red_herring"
    STRAW_MAN = "straw_man"
    AD_HOMINEM = "ad_hominem"
    APPEAL_TO_AUTHORITY = "appeal_to_authority"
    LOADED_LANGUAGE = "loaded_language"
    REPETITION = "repetition"
    SLOGANS = "slogans"
    TESTIMONIALS = "testimonials"
    FEAR_MONGERING = "fear_mongering"


@dataclass
class PropagandaInstance:
    technique: PropagandaTechnique
    text: str
    start: int
    end: int
    confidence: float
    explanation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "technique": self.technique.value,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


@dataclass
class PropagandaResult:
    status: PropagandaStatus
    confidence: float
    score: float
    techniques: List[PropagandaTechnique] = field(default_factory=list)
    instances: List[PropagandaInstance] = field(default_factory=list)
    emotional_score: float = 0.0
    credibility_score: float = 1.0
    loaded_terms: List[str] = field(default_factory=list)
    logical_fallacies: List[str] = field(default_factory=list)
    processing_time: float = 0.0
    timestamp: str = ""
    text_length: int = 0
    model_version: str = "1.0.0"
    
    @property
    def has_propaganda(self) -> bool:
        return self.status != PropagandaStatus.NONE
    
    @property
    def technique_count(self) -> int:
        return len(set(self.techniques))
    
    @property
    def instance_count(self) -> int:
        return len(self.instances)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "score": self.score,
            "techniques": [t.value for t in self.techniques],
            "instances": [i.to_dict() for i in self.instances],
            "emotional_score": self.emotional_score,
            "credibility_score": self.credibility_score,
            "loaded_terms": self.loaded_terms,
            "logical_fallacies": self.logical_fallacies,
            "processing_time": self.processing_time,
            "timestamp": self.timestamp,
            "text_length": self.text_length,
            "has_propaganda": self.has_propaganda,
            "technique_count": self.technique_count,
            "instance_count": self.instance_count,
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class PropagandaDetector:
    """
    Detects propaganda techniques in text content.
    
    Example usage:
        detector = PropagandaDetector()
        text = "Everyone knows that this amazing product will change your life!"
        result = detector.detect(text)
        print(f"Propaganda status: {result.status}")
        print(f"Score: {result.score:.1f}/100")
    """
    
    def __init__(self):
        self._initialize_patterns()
        self._initialize_sentiment()
    
    def _initialize_patterns(self) -> None:
        self.emotional_patterns = [
            r'\b(terrible|horrible|awful|disgusting|outrageous|shocking)\b',
            r'\b(amazing|incredible|fantastic|wonderful|perfect|miraculous)\b',
            r'\b(hate|love|adore|despise|worship)\b',
            r'\b(fear|terror|horror|dread)\b',
            r'\b(urgent|critical|desperate|emergency)\b',
        ]
        
        self.loaded_terms = [
            'miracle', 'revolutionary', 'groundbreaking', 'unprecedented',
            'life-changing', 'world-class', 'elite', 'premium', 'exclusive',
            'guaranteed', 'proven', 'scientific', 'natural', 'organic',
            'disaster', 'catastrophe', 'tragedy', 'scandal', 'outrage',
            'corrupt', 'evil', 'dangerous', 'toxic', 'deadly',
            'shameful', 'disgraceful', 'unacceptable', 'horrific',
        ]
        
        self.bandwagon_patterns = [
            r'\b(everyone|everybody|all|most people|the majority)\b.*\b(knows?|agrees?|believes?|thinks?)\b',
            r'\b(join|be part of|get on board with)\b',
        ]
        
        self.false_dilemma_patterns = [
            r'\b(either\b.*\bor\b.*\b|only two choices|no other option)',
        ]
        
        self.authority_patterns = [
            r'\b(according to|as stated by|as proven by)\b.*\b(experts?|scientists?|doctors?|studies?|research)\b',
        ]
        
        self.ad_hominem_patterns = [
            r'\b(you|they|he|she|it)\b.*\b(stupid|idiot|moron|fool|dumb|ignorant)\b',
        ]
        
        self.straw_man_patterns = [
            r'\b(they|you|opponents?|critics?)\b.*\b(want to|believe that|think that)\b.*\b(ridiculous|absurd|crazy|stupid)\b',
        ]
        
        self.fear_patterns = [
            r'\b(be afraid|be very afraid|fear|terrified|scared)\b',
            r'\b(danger|threat|risk|warning|alert)\b',
        ]
        
        self.repetition_patterns = [
            r'\b(\w+)\b.*\1.*\1',
        ]
    
    def _initialize_sentiment(self) -> None:
        self.sentiment_analyzer = None
        if HAS_VADER:
            self.sentiment_analyzer = SentimentIntensityAnalyzer()
    
    def _get_timestamp(self) -> str:
        return datetime.utcnow().isoformat() + 'Z'
    
    def detect(self, text: str) -> PropagandaResult:
        import time
        start_time = time.time()
        
        if not text or not text.strip():
            return PropagandaResult(
                status=PropagandaStatus.NONE,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                text_length=0,
            )
        
        text = str(text)
        text_length = len(text)
        
        instances = []
        detected_techniques = []
        
        # Detect techniques
        for pattern_list, technique in [
            (self.emotional_patterns, PropagandaTechnique.APPEAL_TO_EMOTION),
            (self.bandwagon_patterns, PropagandaTechnique.BANDWAGON),
            (self.false_dilemma_patterns, PropagandaTechnique.BLACK_AND_WHITE_FALLACY),
            (self.authority_patterns, PropagandaTechnique.APPEAL_TO_AUTHORITY),
            (self.ad_hominem_patterns, PropagandaTechnique.AD_HOMINEM),
            (self.straw_man_patterns, PropagandaTechnique.STRAW_MAN),
            (self.fear_patterns, PropagandaTechnique.FEAR_MONGERING),
            (self.repetition_patterns, PropagandaTechnique.REPETITION),
        ]:
            instances_found = self._detect_with_patterns(text, pattern_list, technique)
            instances.extend(instances_found)
            if instances_found:
                detected_techniques.append(technique)
        
        # Detect loaded language
        loaded_instances = self._detect_loaded_language(text)
        instances.extend(loaded_instances)
        if loaded_instances:
            detected_techniques.append(PropagandaTechnique.LOADED_LANGUAGE)
        
        # Calculate scores
        emotional_score = self._calculate_emotional_score(text)
        credibility_score = self._calculate_credibility_score(text, detected_techniques)
        
        # Calculate confidence and score
        confidence = self._calculate_confidence(instances, text_length)
        score = confidence * 100.0
        
        # Determine status
        if score >= 80:
            status = PropagandaStatus.EXTREME
        elif score >= 60:
            status = PropagandaStatus.HIGH
        elif score >= 40:
            status = PropagandaStatus.MEDIUM
        elif score >= 20:
            status = PropagandaStatus.LOW
        else:
            status = PropagandaStatus.NONE
        
        # Extract loaded terms and fallacies
        loaded_terms = self._extract_loaded_terms(text)
        logical_fallacies = self._extract_logical_fallacies(text)
        
        processing_time = time.time() - start_time
        
        return PropagandaResult(
            status=status,
            confidence=confidence,
            score=score,
            techniques=detected_techniques,
            instances=instances,
            emotional_score=emotional_score,
            credibility_score=credibility_score,
            loaded_terms=loaded_terms,
            logical_fallacies=logical_fallacies,
            processing_time=processing_time,
            timestamp=self._get_timestamp(),
            text_length=text_length,
        )
    
    def _detect_with_patterns(self, text: str, patterns: List[str], technique: PropagandaTechnique) -> List[PropagandaInstance]:
        instances = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                instances.append(PropagandaInstance(
                    technique=technique,
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.8,
                    explanation=f"{technique.value.replace('_', ' ').title()} detected",
                ))
        return instances
    
    def _detect_loaded_language(self, text: str) -> List[PropagandaInstance]:
        instances = []
        for term in self.loaded_terms:
            pattern = r'\b' + re.escape(term) + r'\b'
            for match in re.finditer(pattern, text, re.IGNORECASE):
                instances.append(PropagandaInstance(
                    technique=PropagandaTechnique.LOADED_LANGUAGE,
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                    explanation=f"Loaded term: {term}",
                ))
        return instances
    
    def _calculate_emotional_score(self, text: str) -> float:
        if not HAS_VADER:
            emotional_words = [
                'terrible', 'horrible', 'awful', 'disgusting', 'outrageous', 'shocking',
                'amazing', 'incredible', 'fantastic', 'wonderful', 'perfect', 'miraculous',
                'hate', 'love', 'adore', 'despise', 'worship',
                'fear', 'terror', 'horror', 'dread',
                'urgent', 'critical', 'desperate', 'emergency',
            ]
            text_lower = text.lower()
            count = sum(1 for word in emotional_words if word in text_lower)
            word_count = len(text.split())
            return min(1.0, count / word_count * 5.0) if word_count > 0 else 0.0
        
        try:
            sentiment = self.sentiment_analyzer.polarity_scores(text)
            emotional_intensity = abs(sentiment['pos'] - sentiment['neg'])
            return min(1.0, emotional_intensity * 2.0)
        except Exception:
            return 0.0
    
    def _calculate_credibility_score(self, text: str, detected_techniques: List[PropagandaTechnique]) -> float:
        credibility = 1.0
        
        technique_penalties = {
            PropagandaTechnique.APPEAL_TO_EMOTION: 0.1,
            PropagandaTechnique.BANDWAGON: 0.15,
            PropagandaTechnique.BLACK_AND_WHITE_FALLACY: 0.2,
            PropagandaTechnique.CIRCULAR_REASONING: 0.2,
            PropagandaTechnique.FALSE_CAUSE: 0.2,
            PropagandaTechnique.HASTY_GENERALIZATION: 0.15,
            PropagandaTechnique.RED_HERRING: 0.15,
            PropagandaTechnique.STRAW_MAN: 0.2,
            PropagandaTechnique.AD_HOMINEM: 0.25,
            PropagandaTechnique.APPEAL_TO_AUTHORITY: 0.15,
            PropagandaTechnique.LOADED_LANGUAGE: 0.1,
            PropagandaTechnique.REPETITION: 0.05,
            PropagandaTechnique.SLOGANS: 0.05,
            PropagandaTechnique.TESTIMONIALS: 0.1,
            PropagandaTechnique.FEAR_MONGERING: 0.2,
        }
        
        for technique in detected_techniques:
            credibility -= technique_penalties.get(technique, 0.1)
        
        if re.search(r'\[\d+\]|\d+\.|according to|source|cite|reference', text, re.IGNORECASE):
            credibility = min(1.0, credibility + 0.1)
        
        if self._has_balanced_language(text):
            credibility = min(1.0, credibility + 0.1)
        
        return max(0.0, credibility)
    
    def _has_balanced_language(self, text: str) -> bool:
        balanced_words = ['however', 'but', 'although', 'though', 'on the other hand', 'some', 'many']
        text_lower = text.lower()
        return sum(1 for word in balanced_words if word in text_lower) >= 2
    
    def _calculate_confidence(self, instances: List[PropagandaInstance], text_length: int) -> float:
        if not instances:
            return 0.0
        avg_confidence = np.mean([i.confidence for i in instances])
        instance_density = len(instances) / max(1, text_length / 100)
        return min(1.0, avg_confidence * min(1.0, instance_density * 0.5))
    
    def _extract_loaded_terms(self, text: str) -> List[str]:
        found_terms = []
        text_lower = text.lower()
        for term in self.loaded_terms:
            if term in text_lower:
                found_terms.append(term)
        return found_terms
    
    def _extract_logical_fallacies(self, text: str) -> List[str]:
        fallacies = []
        if re.search(r'\b(because|since|after)\b.*\b(therefore|so|thus)\b', text, re.IGNORECASE):
            fallacies.append("False Cause")
        if re.search(r'\b(every|all|always|never)\b', text, re.IGNORECASE):
            fallacies.append("Hasty Generalization")
        if re.search(r'\b(because|since)\b.*\b(it is|we know|obviously)\b', text, re.IGNORECASE):
            fallacies.append("Circular Reasoning")
        return fallacies
    
    def get_detected_techniques(self, text: str) -> List[PropagandaTechnique]:
        result = self.detect(text)
        return result.techniques
    
    def get_propaganda_score(self, text: str) -> float:
        result = self.detect(text)
        return result.score
    
    def has_propaganda(self, text: str) -> bool:
        result = self.detect(text)
        return result.has_propaganda
    
    def check_dependencies(self) -> Dict[str, bool]:
        return {"VADER": HAS_VADER}
    
    def get_technique_description(self, technique: PropagandaTechnique) -> str:
        descriptions = {
            PropagandaTechnique.APPEAL_TO_EMOTION: "Manipulating emotions to influence opinions",
            PropagandaTechnique.BANDWAGON: "Encouraging people because everyone else is doing it",
            PropagandaTechnique.BLACK_AND_WHITE_FALLACY: "Presenting only two options when more exist",
            PropagandaTechnique.CIRCULAR_REASONING: "Using conclusion as premise",
            PropagandaTechnique.FALSE_CAUSE: "Assuming correlation implies causation",
            PropagandaTechnique.HASTY_GENERALIZATION: "Making broad claims based on insufficient evidence",
            PropagandaTechnique.RED_HERRING: "Introducing irrelevant information to distract",
            PropagandaTechnique.STRAW_MAN: "Misrepresenting opponent's argument",
            PropagandaTechnique.AD_HOMINEM: "Attacking the person instead of the argument",
            PropagandaTechnique.APPEAL_TO_AUTHORITY: "Using authority figures to support claims",
            PropagandaTechnique.LOADED_LANGUAGE: "Using emotionally charged words to influence opinions",
            PropagandaTechnique.REPETITION: "Repeating a message to make it more believable",
            PropagandaTechnique.SLOGANS: "Using catchy phrases to promote a message",
            PropagandaTechnique.TESTIMONIALS: "Using celebrity or expert endorsements",
            PropagandaTechnique.FEAR_MONGERING: "Creating fear to influence opinions",
        }
        return descriptions.get(technique, "Unknown propaganda technique")
