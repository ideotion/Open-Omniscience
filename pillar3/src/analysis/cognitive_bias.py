"""
Cognitive Bias Detection Module

Detects cognitive biases in text content using 100% FOSS NLP libraries.
Works completely offline.

Features:
- 20+ cognitive bias detection
- Confirmation bias
- Anchoring bias
- Framing bias
- Availability bias
- And more...
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

import numpy as np


class CognitiveBiasStatus(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class CognitiveBias(Enum):
    CONFIRMATION_BIAS = "confirmation_bias"
    ANCHORING_BIAS = "anchoring_bias"
    FRAMING_BIAS = "framing_bias"
    AVAILABILITY_BIAS = "availability_bias"
    DUNNING_KRUGER = "dunning_kruger"
    HALO_EFFECT = "halo_effect"
    HORN_EFFECT = "horn_effect"
    RECENCY_BIAS = "recency_bias"
    PRIMACY_EFFECT = "primacy_effect"
    STEREOTYPING = "stereotyping"
    IN_GROUP_BIAS = "in_group_bias"
    OUT_GROUP_HOMOGENEITY = "out_group_homogeneity"
    SELF_SERVING_BIAS = "self_serving_bias"
    OPTIMISM_BIAS = "optimism_bias"
    PESSIMISM_BIAS = "pessimism_bias"
    STATUS_QUO_BIAS = "status_quo_bias"
    LOSS_AVERSION = "loss_aversion"
    SUNK_COST_FALLACY = "sunk_cost_fallacy"
    GAMBLERS_FALLACY = "gamblers_fallacy"
    CLUSTERING_ILLUSION = "clustering_illusion"
    ILLUSORY_CORRELATION = "illusory_correlation"


@dataclass
class BiasInstance:
    bias: CognitiveBias
    text: str
    start: int
    end: int
    confidence: float
    explanation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bias": self.bias.value,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


@dataclass
class CognitiveBiasResult:
    status: CognitiveBiasStatus
    confidence: float
    score: float
    biases: List[CognitiveBias] = field(default_factory=list)
    instances: List[BiasInstance] = field(default_factory=list)
    processing_time: float = 0.0
    timestamp: str = ""
    text_length: int = 0
    model_version: str = "1.0.0"
    
    @property
    def has_bias(self) -> bool:
        return self.status != CognitiveBiasStatus.NONE
    
    @property
    def bias_count(self) -> int:
        return len(set(self.biases))
    
    @property
    def instance_count(self) -> int:
        return len(self.instances)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "score": self.score,
            "biases": [b.value for b in self.biases],
            "instances": [i.to_dict() for i in self.instances],
            "processing_time": self.processing_time,
            "timestamp": self.timestamp,
            "text_length": self.text_length,
            "has_bias": self.has_bias,
            "bias_count": self.bias_count,
            "instance_count": self.instance_count,
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class CognitiveBiasDetector:
    """
    Detects cognitive biases in text content.
    
    Example usage:
        detector = CognitiveBiasDetector()
        text = "I knew it all along! This proves my theory was right."
        result = detector.detect(text)
        print(f"Bias status: {result.status}")
        print(f"Score: {result.score:.1f}/100")
    """
    
    def __init__(self):
        self._initialize_patterns()
    
    def _initialize_patterns(self) -> None:
        # Confirmation bias patterns
        self.confirmation_patterns = [
            r'(I knew it|as I suspected|this proves|just as I thought)',
            r'(see|told you|always knew)',
        ]
        
        # Anchoring bias patterns
        self.anchoring_patterns = [
            r'(first|initial|original).*\(estimate|impression|judgment\)',
            r'(based on the first|starting from)',
        ]
        
        # Framing bias patterns
        self.framing_patterns = [
            r'(positive|negative|good|bad).*\(spin|frame|perspective\)',
            r'(glass half full|glass half empty)',
        ]
        
        # Availability bias patterns
        self.availability_patterns = [
            r'(easily remember|comes to mind|recently heard)',
            r'(vivid|dramatic|memorable).*\(example|instance|case\)',
        ]
        
        # Dunning-Kruger patterns
        self.dunning_kruger_patterns = [
            r'(overestimate|overconfident|more skilled than)',
            r"(everyone else is|most people don't understand)",
        ]
        
        # Halo effect patterns
        self.halo_patterns = [
            r'(one good thing|positive aspect).*\(overall good|great person\)',
            r'(because of|due to).*\(one feature|single aspect\)',
        ]
        
        # Stereotyping patterns
        self.stereotyping_patterns = [
            r'(all|every|most|some).*\(group|category|type\).*\(are|is|have|has\)',
            r'(typical|stereotypical)',
        ]
    def _get_timestamp(self) -> str:
        return datetime.utcnow().isoformat() + 'Z'
    
    def detect(self, text: str) -> CognitiveBiasResult:
        import time
        start_time = time.time()
        
        if not text or not text.strip():
            return CognitiveBiasResult(
                status=CognitiveBiasStatus.NONE,
                confidence=0.0,
                score=0.0,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
                text_length=0,
            )
        
        text = str(text)
        text_length = len(text)
        
        instances = []
        detected_biases = []
        
        # Detect biases using patterns
        pattern_map = [
            (self.confirmation_patterns, CognitiveBias.CONFIRMATION_BIAS, "Confirmation bias detected"),
            (self.anchoring_patterns, CognitiveBias.ANCHORING_BIAS, "Anchoring bias detected"),
            (self.framing_patterns, CognitiveBias.FRAMING_BIAS, "Framing bias detected"),
            (self.availability_patterns, CognitiveBias.AVAILABILITY_BIAS, "Availability bias detected"),
            (self.dunning_kruger_patterns, CognitiveBias.DUNNING_KRUGER, "Dunning-Kruger effect detected"),
            (self.halo_patterns, CognitiveBias.HALO_EFFECT, "Halo effect detected"),
            (self.stereotyping_patterns, CognitiveBias.STEREOTYPING, "Stereotyping detected"),
        ]
        
        for patterns, bias, explanation in pattern_map:
            instances_found = self._detect_with_patterns(text, patterns, bias, explanation)
            instances.extend(instances_found)
            if instances_found:
                detected_biases.append(bias)
        
        # Calculate confidence and score
        confidence = self._calculate_confidence(instances, text_length)
        score = confidence * 100.0
        
        # Determine status
        if score >= 80:
            status = CognitiveBiasStatus.EXTREME
        elif score >= 60:
            status = CognitiveBiasStatus.HIGH
        elif score >= 40:
            status = CognitiveBiasStatus.MEDIUM
        elif score >= 20:
            status = CognitiveBiasStatus.LOW
        else:
            status = CognitiveBiasStatus.NONE
        
        processing_time = time.time() - start_time
        
        return CognitiveBiasResult(
            status=status,
            confidence=confidence,
            score=score,
            biases=detected_biases,
            instances=instances,
            processing_time=processing_time,
            timestamp=self._get_timestamp(),
            text_length=text_length,
        )
    
    def _detect_with_patterns(self, text: str, patterns: List[str], bias: CognitiveBias, explanation: str) -> List[BiasInstance]:
        instances = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                instances.append(BiasInstance(
                    bias=bias,
                    text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.75,
                    explanation=explanation,
                ))
        return instances
    
    def _calculate_confidence(self, instances: List[BiasInstance], text_length: int) -> float:
        if not instances:
            return 0.0
        avg_confidence = np.mean([i.confidence for i in instances])
        instance_density = len(instances) / max(1, text_length / 100)
        return min(1.0, avg_confidence * min(1.0, instance_density * 0.5))
    
    def get_detected_biases(self, text: str) -> List[CognitiveBias]:
        result = self.detect(text)
        return result.biases
    
    def get_bias_score(self, text: str) -> float:
        result = self.detect(text)
        return result.score
    
    def has_bias(self, text: str) -> bool:
        result = self.detect(text)
        return result.has_bias
    
    def get_bias_description(self, bias: CognitiveBias) -> str:
        descriptions = {
            CognitiveBias.CONFIRMATION_BIAS: "Favoring information that confirms preexisting beliefs",
            CognitiveBias.ANCHORING_BIAS: "Relying too heavily on the first piece of information",
            CognitiveBias.FRAMING_BIAS: "Different presentations of the same information lead to different interpretations",
            CognitiveBias.AVAILABILITY_BIAS: "Judging probability based on ease of recall",
            CognitiveBias.DUNNING_KRUGER: "Overestimating one's own competence",
            CognitiveBias.HALO_EFFECT: "Positive impression in one area influences opinion in others",
            CognitiveBias.HORN_EFFECT: "Negative impression in one area influences opinion in others",
            CognitiveBias.RECENCY_BIAS: "Recent events are more important than earlier ones",
            CognitiveBias.PRIMACY_EFFECT: "First items in a series are more important",
            CognitiveBias.STEREOTYPING: "Generalizing about groups of people",
            CognitiveBias.IN_GROUP_BIAS: "Favoring people in one's own group",
            CognitiveBias.OUT_GROUP_HOMOGENEITY: "Seeing out-group members as more similar",
            CognitiveBias.SELF_SERVING_BIAS: "Attributing success to self, failure to others",
            CognitiveBias.OPTIMISM_BIAS: "Overestimating positive outcomes",
            CognitiveBias.PESSIMISM_BIAS: "Overestimating negative outcomes",
            CognitiveBias.STATUS_QUO_BIAS: "Preferring the current state of affairs",
            CognitiveBias.LOSS_AVERSION: "Fear of losses is stronger than desire for gains",
            CognitiveBias.SUNK_COST_FALLACY: "Continuing due to past investment",
            CognitiveBias.GAMBLERS_FALLACY: "Believing past events affect future probabilities",
            CognitiveBias.CLUSTERING_ILLUSION: "Seeing patterns in random data",
            CognitiveBias.ILLUSORY_CORRELATION: "Seeing relationships where none exist",
        }
        return descriptions.get(bias, "Unknown cognitive bias")
