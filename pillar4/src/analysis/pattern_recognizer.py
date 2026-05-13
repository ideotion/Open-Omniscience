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
Pillar 4: Real-Time Monitoring & Alerting System - Pattern Recognizer

Detects repeating patterns, coordination, and campaign fingerprints in data streams.
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set
from enum import Enum
from collections import defaultdict, deque
import hashlib
import re


class PatternType(Enum):
    REPEATING = "repeating"
    COORDINATED = "coordinated"
    CAMPAIGN = "campaign"
    BEHAVIORAL = "behavioral"


class PatternStatus(Enum):
    NONE = "none"
    POTENTIAL = "potential"
    CONFIRMED = "confirmed"


@dataclass
class Pattern:
    """Represents a detected pattern."""
    type: PatternType
    status: PatternStatus
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    description: str
    first_seen: float
    last_seen: float
    occurrences: int
    elements: List[Any]  # List of elements that form the pattern
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "description": self.description,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrences": self.occurrences,
            "elements": [str(e) for e in self.elements],
            "metadata": self.metadata,
        }


class PatternRecognizer:
    """
    Detects patterns in data streams including:
    - Repeating content or behaviors
    - Coordinated activities (multiple sources posting similar content)
    - Campaign fingerprints
    - Behavioral patterns
    """

    def __init__(
        self,
        pattern_window: int = 50,
        similarity_threshold: float = 0.85,
        min_occurrences: int = 3,
    ):
        """
        Initialize the pattern recognizer.

        Args:
            pattern_window: Size of the window for pattern detection.
            similarity_threshold: Threshold for considering items similar.
            min_occurrences: Minimum occurrences to consider a pattern.
        """
        self.pattern_window = pattern_window
        self.similarity_threshold = similarity_threshold
        self.min_occurrences = min_occurrences

        # Pattern storage
        self.patterns: Dict[str, Pattern] = {}
        self.recent_data: deque = deque(maxlen=pattern_window)
        self.recent_timestamps: deque = deque(maxlen=pattern_window)

        # For coordination detection
        self.source_content: Dict[str, List[Tuple[float, str]]] = defaultdict(list)

    def add_data_point(self, content: str, source: Optional[str] = None, timestamp: Optional[float] = None) -> None:
        """Add a new data point to the recognizer."""
        if timestamp is None:
            timestamp = time.time()
        self.recent_data.append(content)
        self.recent_timestamps.append(timestamp)

        if source:
            self.source_content[source].append((timestamp, content))
            # Keep only recent content per source
            if len(self.source_content[source]) > self.pattern_window:
                self.source_content[source] = self.source_content[source][-self.pattern_window:]

    def detect_repeating_patterns(self) -> List[Pattern]:
        """
        Detect repeating patterns in the recent data.

        Returns:
            List of detected repeating patterns.
        """
        patterns = []
        if len(self.recent_data) < self.min_occurrences:
            return patterns

        # Simple approach: look for exact duplicates
        content_counts: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
        for i, (content, ts) in enumerate(zip(self.recent_data, self.recent_timestamps)):
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            content_counts[content_hash].append((i, ts))

        for content_hash, occurrences in content_counts.items():
            if len(occurrences) >= self.min_occurrences:
                first_idx, first_ts = occurrences[0]
                last_idx, last_ts = occurrences[-1]
                content = self.recent_data[first_idx]

                pattern = Pattern(
                    type=PatternType.REPEATING,
                    status=PatternStatus.CONFIRMED if len(occurrences) >= self.min_occurrences * 2 else PatternStatus.POTENTIAL,
                    score=min(1.0, len(occurrences) / self.pattern_window),
                    confidence=0.9,
                    description=f"Repeating content detected ({len(occurrences)} occurrences)",
                    first_seen=first_ts,
                    last_seen=last_ts,
                    occurrences=len(occurrences),
                    elements=[content],
                    metadata={
                        "content_hash": content_hash,
                        "content_length": len(content),
                    },
                )
                patterns.append(pattern)

        return patterns

    def detect_coordinated_patterns(self) -> List[Pattern]:
        """
        Detect coordinated patterns (multiple sources posting similar content).

        Returns:
            List of detected coordinated patterns.
        """
        patterns = []

        if len(self.source_content) < 2:
            return patterns

        # Get all recent content from all sources
        all_content = []
        for source, content_list in self.source_content.items():
            for ts, content in content_list:
                all_content.append((source, ts, content))

        if len(all_content) < self.min_occurrences:
            return patterns

        # Group content by similarity (simple approach: exact matches)
        content_groups: Dict[str, List[Tuple[str, float, str]]] = defaultdict(list)
        for source, ts, content in all_content:
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            content_groups[content_hash].append((source, ts, content))

        # Also check for similar content (using simple text similarity)
        # This is a simplified version - in production, use TF-IDF or embeddings
        for i, (source1, ts1, content1) in enumerate(all_content):
            for j, (source2, ts2, content2) in enumerate(all_content):
                if i >= j:
                    continue
                if source1 == source2:
                    continue

                # Simple similarity check
                similarity = self._text_similarity(content1, content2)
                if similarity >= self.similarity_threshold:
                    combined_hash = hashlib.sha256(f"{content1[:100]}-{content2[:100]}".encode()).hexdigest()[:16]
                    content_groups[combined_hash].append((source1, ts1, content1))
                    content_groups[combined_hash].append((source2, ts2, content2))

        for content_hash, group in content_groups.items():
            if len(group) >= self.min_occurrences:
                sources = set(s for s, _, _ in group)
                if len(sources) >= 2:  # At least 2 different sources
                    first_ts = min(ts for _, ts, _ in group)
                    last_ts = max(ts for _, ts, _ in group)
                    unique_content = list(set(c for _, _, c in group))

                    pattern = Pattern(
                        type=PatternType.COORDINATED,
                        status=PatternStatus.CONFIRMED if len(sources) >= 3 else PatternStatus.POTENTIAL,
                        score=min(1.0, len(sources) * 0.3 + len(group) * 0.1),
                        confidence=0.85,
                        description=f"Coordinated content from {len(sources)} sources",
                        first_seen=first_ts,
                        last_seen=last_ts,
                        occurrences=len(group),
                        elements=unique_content[:3],  # Limit to first 3 for brevity
                        metadata={
                            "sources": list(sources),
                            "content_hash": content_hash,
                        },
                    )
                    patterns.append(pattern)

        return patterns

    def detect_campaign_fingerprints(self, campaign_indicators: Optional[Dict[str, Any]] = None) -> List[Pattern]:
        """
        Detect campaign fingerprints based on known indicators.

        Args:
            campaign_indicators: Dictionary of known campaign indicators.

        Returns:
            List of detected campaign patterns.
        """
        patterns = []

        if campaign_indicators is None:
            # Default indicators (can be loaded from config)
            campaign_indicators = {
                "hashtag_spam": {
                    "pattern": r"#\w+",
                    "min_count": 5,
                    "description": "Excessive hashtag usage",
                },
                "url_shortener": {
                    "pattern": r"(bit\.ly|goo\.gl|t\.co|tinyurl\.com)",
                    "min_count": 3,
                    "description": "Multiple URL shorteners",
                },
                "repeated_phrases": {
                    "pattern": None,  # Special handling
                    "min_count": 3,
                    "description": "Repeated phrases across messages",
                },
            }

        # Check each indicator
        for indicator_name, config in campaign_indicators.items():
            if indicator_name == "repeated_phrases":
                # Special handling for repeated phrases
                phrase_counts: Dict[str, int] = defaultdict(int)
                for content in self.recent_data:
                    # Extract phrases (simplified: split by sentences)
                    sentences = re.split(r"[.!?]", content)
                    for sentence in sentences:
                        if len(sentence.strip()) > 10:  # Only consider longer phrases
                            phrase_counts[sentence.strip().lower()] += 1

                for phrase, count in phrase_counts.items():
                    if count >= config["min_count"]:
                        pattern = Pattern(
                            type=PatternType.CAMPAIGN,
                            status=PatternStatus.CONFIRMED,
                            score=min(1.0, count * 0.2),
                            confidence=0.8,
                            description=f"Repeated phrase: '{phrase[:50]}...' ({count} times)",
                            first_seen=self.recent_timestamps[0],
                            last_seen=self.recent_timestamps[-1],
                            occurrences=count,
                            elements=[phrase],
                            metadata={
                                "indicator": indicator_name,
                                "phrase_length": len(phrase),
                            },
                        )
                        patterns.append(pattern)
            else:
                # Regular regex pattern matching
                pattern_regex = re.compile(config["pattern"], re.IGNORECASE)
                match_counts: Dict[str, List[Tuple[int, float]]] = defaultdict(list)

                for i, (content, ts) in enumerate(zip(self.recent_data, self.recent_timestamps)):
                    matches = pattern_regex.findall(content)
                    for match in matches:
                        match_counts[match].append((i, ts))

                for match, occurrences in match_counts.items():
                    if len(occurrences) >= config["min_count"]:
                        first_idx, first_ts = occurrences[0]
                        last_idx, last_ts = occurrences[-1]

                        pattern = Pattern(
                            type=PatternType.CAMPAIGN,
                            status=PatternStatus.CONFIRMED if len(occurrences) >= config["min_count"] * 2 else PatternStatus.POTENTIAL,
                            score=min(1.0, len(occurrences) * 0.2),
                            confidence=0.75,
                            description=f"{config['description']}: '{match}' ({len(occurrences)} times)",
                            first_seen=first_ts,
                            last_seen=last_ts,
                            occurrences=len(occurrences),
                            elements=[match],
                            metadata={
                                "indicator": indicator_name,
                                "regex_pattern": config["pattern"],
                            },
                        )
                        patterns.append(pattern)

        return patterns

    def detect_behavioral_patterns(self) -> List[Pattern]:
        """
        Detect behavioral patterns (e.g., posting frequency, time patterns).

        Returns:
            List of detected behavioral patterns.
        """
        patterns = []

        # Check posting frequency per source
        for source, content_list in self.source_content.items():
            if len(content_list) < self.min_occurrences:
                continue

            timestamps = [ts for ts, _ in content_list]
            time_diffs = np.diff(timestamps)

            if len(time_diffs) > 0:
                mean_diff = np.mean(time_diffs)
                std_diff = np.std(time_diffs)

                # Check for regular posting intervals
                if std_diff < mean_diff * 0.2:  # Low variance in posting times
                    pattern = Pattern(
                        type=PatternType.BEHAVIORAL,
                        status=PatternStatus.CONFIRMED,
                        score=0.8,
                        confidence=0.85,
                        description=f"Regular posting pattern from {source} (interval: {mean_diff:.1f}s)",
                        first_seen=timestamps[0],
                        last_seen=timestamps[-1],
                        occurrences=len(content_list),
                        elements=[source],
                        metadata={
                            "mean_interval": float(mean_diff),
                            "std_interval": float(std_diff),
                        },
                    )
                    patterns.append(pattern)

                # Check for bursts of activity
                burst_threshold = mean_diff * 0.5 if mean_diff > 0 else 10.0
                bursts = np.where(time_diffs < burst_threshold)[0]
                if len(bursts) >= 3:
                    pattern = Pattern(
                        type=PatternType.BEHAVIORAL,
                        status=PatternStatus.POTENTIAL,
                        score=0.7,
                        confidence=0.7,
                        description=f"Burst activity detected from {source} ({len(bursts)} rapid posts)",
                        first_seen=timestamps[0],
                        last_seen=timestamps[-1],
                        occurrences=len(bursts),
                        elements=[source],
                        metadata={
                            "burst_threshold": float(burst_threshold),
                            "burst_count": len(bursts),
                        },
                    )
                    patterns.append(pattern)

        return patterns

    def detect_all(self) -> List[Pattern]:
        """Run all pattern detection methods."""
        patterns = []
        patterns.extend(self.detect_repeating_patterns())
        patterns.extend(self.detect_coordinated_patterns())
        patterns.extend(self.detect_campaign_fingerprints())
        patterns.extend(self.detect_behavioral_patterns())
        # Sort by last seen timestamp
        patterns.sort(key=lambda x: x.last_seen, reverse=True)
        return patterns

    def _text_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate simple text similarity (Jaccard similarity on words).

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        words1 = set(re.findall(r"\w+", text1.lower()))
        words2 = set(re.findall(r"\w+", text2.lower()))

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0

    def reset(self) -> None:
        """Reset the recognizer's state."""
        self.recent_data.clear()
        self.recent_timestamps.clear()
        self.source_content.clear()
        self.patterns.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            "total_data_points": len(self.recent_data),
            "unique_sources": len(self.source_content),
            "detected_patterns": len(self.patterns),
        }
