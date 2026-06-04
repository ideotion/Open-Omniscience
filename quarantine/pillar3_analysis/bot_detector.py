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
Bot Detection Module

Detects bot-like behavior in social media accounts and content
using 100% FOSS libraries. Works completely offline.

Features:
- Behavioral analysis
- Content similarity detection
- Posting pattern analysis
- Network-based bot detection
- Confidence scoring
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class BotStatus(Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class BotDetectionMethod(Enum):
    BEHAVIORAL = "behavioral"
    CONTENT = "content"
    TEMPORAL = "temporal"
    NETWORK = "network"
    COMBINED = "combined"


@dataclass
class BotIndicator:
    indicator_type: str
    method: BotDetectionMethod
    value: float
    threshold: float
    description: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "indicator_type": self.indicator_type,
            "method": self.method.value,
            "value": self.value,
            "threshold": self.threshold,
            "description": self.description,
            "confidence": self.confidence,
        }


@dataclass
class BotResult:
    status: BotStatus
    confidence: float
    score: float
    is_bot: bool
    indicators: List[BotIndicator] = field(default_factory=list)
    behavioral_score: float = 0.0
    content_score: float = 0.0
    temporal_score: float = 0.0
    network_score: float = 0.0
    processing_time: float = 0.0
    timestamp: str = ""
    model_version: str = "1.0.0"
    
    @property
    def bot_probability(self) -> float:
        return self.score / 100.0
    
    @property
    def indicator_count(self) -> int:
        return len(self.indicators)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": self.confidence,
            "score": self.score,
            "is_bot": self.is_bot,
            "indicators": [i.to_dict() for i in self.indicators],
            "behavioral_score": self.behavioral_score,
            "content_score": self.content_score,
            "temporal_score": self.temporal_score,
            "network_score": self.network_score,
            "processing_time": self.processing_time,
            "timestamp": self.timestamp,
            "bot_probability": self.bot_probability,
            "indicator_count": self.indicator_count,
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class UserActivity:
    user_id: str
    posts: List[Dict[str, Any]]
    followers: List[str]
    following: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def post_count(self) -> int:
        return len(self.posts)
    
    @property
    def follower_count(self) -> int:
        return len(self.followers)
    
    @property
    def following_count(self) -> int:
        return len(self.following)


class BotDetector:
    """
    Detects bot-like behavior in user activity.
    
    Example usage:
        detector = BotDetector()
        activity = UserActivity(
            user_id="user123",
            posts=[{"content": "Hello world", "timestamp": "2024-01-01T12:00:00Z"}],
            followers=["user456"],
            following=["user789"]
        )
        result = detector.detect(activity)
        print(f"Bot status: {result.status}")
        print(f"Bot probability: {result.bot_probability:.2%}")
    """
    
    def __init__(self):
        self._initialize_thresholds()
    
    def _initialize_thresholds(self) -> None:
        # Behavioral thresholds
        self.post_frequency_threshold = 10.0  # posts per hour
        self.follower_ratio_threshold = 10.0  # following/follower ratio
        self.retweet_ratio_threshold = 0.8  # retweet/original content ratio
        
        # Content thresholds
        self.similarity_threshold = 0.9  # content similarity threshold
        self.url_ratio_threshold = 0.5  # URL-containing posts ratio
        self.hashtag_ratio_threshold = 0.3  # hashtag-containing posts ratio
        
        # Temporal thresholds
        self.regularity_threshold = 0.1  # standard deviation of posting intervals
        self.burstiness_threshold = 5.0  # posts in short time periods
        
        # Network thresholds
        self.community_ratio_threshold = 0.1  # connections outside main community
    
    def _get_timestamp(self) -> str:
        return datetime.utcnow().isoformat() + 'Z'
    
    def detect(self, activity: UserActivity) -> BotResult:
        import time
        start_time = time.time()
        
        if not activity or not activity.posts:
            return BotResult(
                status=BotStatus.NONE,
                confidence=0.0,
                score=0.0,
                is_bot=False,
                processing_time=time.time() - start_time,
                timestamp=self._get_timestamp(),
            )
        
        indicators = []
        
        # Behavioral analysis
        behavioral_score, behavioral_indicators = self._analyze_behavior(activity)
        indicators.extend(behavioral_indicators)
        
        # Content analysis
        content_score, content_indicators = self._analyze_content(activity)
        indicators.extend(content_indicators)
        
        # Temporal analysis
        temporal_score, temporal_indicators = self._analyze_temporal(activity)
        indicators.extend(temporal_indicators)
        
        # Network analysis
        network_score, network_indicators = self._analyze_network(activity)
        indicators.extend(network_indicators)
        
        # Calculate overall score
        score = self._calculate_score(behavioral_score, content_score, temporal_score, network_score)
        confidence = self._calculate_confidence(indicators)
        
        # Determine status and is_bot
        if score >= 80:
            status = BotStatus.EXTREME
            is_bot = True
        elif score >= 60:
            status = BotStatus.HIGH
            is_bot = True
        elif score >= 40:
            status = BotStatus.MEDIUM
            is_bot = True
        elif score >= 20:
            status = BotStatus.LOW
            is_bot = False
        else:
            status = BotStatus.NONE
            is_bot = False
        
        processing_time = time.time() - start_time
        
        return BotResult(
            status=status,
            confidence=confidence,
            score=score,
            is_bot=is_bot,
            indicators=indicators,
            behavioral_score=behavioral_score,
            content_score=content_score,
            temporal_score=temporal_score,
            network_score=network_score,
            processing_time=processing_time,
            timestamp=self._get_timestamp(),
        )
    
    def _analyze_behavior(self, activity: UserActivity) -> Tuple[float, List[BotIndicator]]:
        indicators = []
        score = 0.0
        
        # Post frequency analysis
        if activity.post_count > 0:
            time_range = self._calculate_time_range(activity)
            if time_range > 0:
                post_frequency = activity.post_count / (time_range / 3600)  # posts per hour
                if post_frequency > self.post_frequency_threshold:
                    confidence = min(1.0, post_frequency / self.post_frequency_threshold / 2)
                    indicators.append(BotIndicator(
                        indicator_type="high_post_frequency",
                        method=BotDetectionMethod.BEHAVIORAL,
                        value=post_frequency,
                        threshold=self.post_frequency_threshold,
                        description=f"High posting frequency: {post_frequency:.1f} posts/hour",
                        confidence=confidence
                    ))
                    score += 25 * confidence
        
        # Follower ratio analysis
        if activity.following_count > 0 and activity.follower_count > 0:
            follower_ratio = activity.following_count / activity.follower_count
            if follower_ratio > self.follower_ratio_threshold:
                confidence = min(1.0, follower_ratio / self.follower_ratio_threshold / 2)
                indicators.append(BotIndicator(
                    indicator_type="high_follower_ratio",
                    method=BotDetectionMethod.BEHAVIORAL,
                    value=follower_ratio,
                    threshold=self.follower_ratio_threshold,
                    description=f"High following/follower ratio: {follower_ratio:.1f}",
                    confidence=confidence
                ))
                score += 20 * confidence
        
        # Retweet ratio analysis
        retweet_count = sum(1 for post in activity.posts if post.get("is_retweet", False))
        if activity.post_count > 0:
            retweet_ratio = retweet_count / activity.post_count
            if retweet_ratio > self.retweet_ratio_threshold:
                confidence = min(1.0, (retweet_ratio - self.retweet_ratio_threshold) / (1 - self.retweet_ratio_threshold))
                indicators.append(BotIndicator(
                    indicator_type="high_retweet_ratio",
                    method=BotDetectionMethod.BEHAVIORAL,
                    value=retweet_ratio,
                    threshold=self.retweet_ratio_threshold,
                    description=f"High retweet ratio: {retweet_ratio:.1%}",
                    confidence=confidence
                ))
                score += 15 * confidence
        
        return min(100.0, score), indicators
    
    def _analyze_content(self, activity: UserActivity) -> Tuple[float, List[BotIndicator]]:
        indicators = []
        score = 0.0
        
        if not activity.posts:
            return 0.0, indicators
        
        # Content similarity analysis
        if HAS_SKLEARN and len(activity.posts) >= 3:
            try:
                texts = [post.get("content", "") for post in activity.posts]
                vectorizer = TfidfVectorizer(max_features=100)
                tfidf_matrix = vectorizer.fit_transform(texts)
                similarity_matrix = cosine_similarity(tfidf_matrix)
                
                avg_similarity = np.mean(similarity_matrix[np.triu_indices_from(similarity_matrix, k=1)])
                if avg_similarity > self.similarity_threshold:
                    confidence = min(1.0, (avg_similarity - self.similarity_threshold) / (1 - self.similarity_threshold))
                    indicators.append(BotIndicator(
                        indicator_type="high_content_similarity",
                        method=BotDetectionMethod.CONTENT,
                        value=avg_similarity,
                        threshold=self.similarity_threshold,
                        description=f"High content similarity: {avg_similarity:.2%}",
                        confidence=confidence
                    ))
                    score += 25 * confidence
            except Exception:
                pass
        
        # URL ratio analysis
        url_count = sum(1 for post in activity.posts if "http://" in post.get("content", "") or "https://" in post.get("content", ""))
        url_ratio = url_count / len(activity.posts) if activity.posts else 0
        if url_ratio > self.url_ratio_threshold:
            confidence = min(1.0, (url_ratio - self.url_ratio_threshold) / (1 - self.url_ratio_threshold))
            indicators.append(BotIndicator(
                indicator_type="high_url_ratio",
                method=BotDetectionMethod.CONTENT,
                value=url_ratio,
                threshold=self.url_ratio_threshold,
                description=f"High URL ratio: {url_ratio:.1%}",
                confidence=confidence
            ))
            score += 20 * confidence
        
        # Hashtag ratio analysis
        hashtag_count = sum(1 for post in activity.posts if "#" in post.get("content", ""))
        hashtag_ratio = hashtag_count / len(activity.posts) if activity.posts else 0
        if hashtag_ratio > self.hashtag_ratio_threshold:
            confidence = min(1.0, (hashtag_ratio - self.hashtag_ratio_threshold) / (1 - self.hashtag_ratio_threshold))
            indicators.append(BotIndicator(
                indicator_type="high_hashtag_ratio",
                method=BotDetectionMethod.CONTENT,
                value=hashtag_ratio,
                threshold=self.hashtag_ratio_threshold,
                description=f"High hashtag ratio: {hashtag_ratio:.1%}",
                confidence=confidence
            ))
            score += 15 * confidence
        
        return min(100.0, score), indicators
    
    def _analyze_temporal(self, activity: UserActivity) -> Tuple[float, List[BotIndicator]]:
        indicators = []
        score = 0.0
        
        if not activity.posts or len(activity.posts) < 2:
            return 0.0, indicators
        
        # Extract timestamps
        timestamps = []
        for post in activity.posts:
            ts = post.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    timestamps.append(dt.timestamp())
                except Exception:
                    pass
        
        if len(timestamps) < 2:
            return 0.0, indicators
        
        timestamps.sort()
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        
        if not intervals:
            return 0.0, indicators
        
        # Regularity analysis
        if HAS_NUMPY:
            std_dev = np.std(intervals)
            mean_interval = np.mean(intervals)
            if mean_interval > 0:
                regularity = std_dev / mean_interval
                if regularity < self.regularity_threshold:
                    confidence = min(1.0, (self.regularity_threshold - regularity) / self.regularity_threshold)
                    indicators.append(BotIndicator(
                        indicator_type="high_regularity",
                        method=BotDetectionMethod.TEMPORAL,
                        value=regularity,
                        threshold=self.regularity_threshold,
                        description=f"High posting regularity (std_dev/mean: {regularity:.3f})",
                        confidence=confidence
                    ))
                    score += 20 * confidence
        
        # Burstiness analysis
        short_intervals = [i for i in intervals if i < 60]  # intervals less than 1 minute
        if len(short_intervals) >= self.burstiness_threshold:
            confidence = min(1.0, len(short_intervals) / self.burstiness_threshold)
            indicators.append(BotIndicator(
                indicator_type="burst_posting",
                method=BotDetectionMethod.TEMPORAL,
                value=len(short_intervals),
                threshold=self.burstiness_threshold,
                description=f"Burst posting: {len(short_intervals)} posts in short intervals",
                confidence=confidence
            ))
            score += 25 * confidence
        
        return min(100.0, score), indicators
    
    def _analyze_network(self, activity: UserActivity) -> Tuple[float, List[BotIndicator]]:
        indicators = []
        score = 0.0
        
        if not activity.followers and not activity.following:
            return 0.0, indicators
        
        # Community ratio analysis (simplified - would need network analysis for full implementation)
        if activity.followers and activity.following:
            # This is a placeholder - in a real implementation, you'd analyze the network structure
            # For now, we'll use a simple heuristic
            total_connections = len(activity.followers) + len(activity.following)
            if total_connections > 1000:  # Arbitrary threshold for "mass" following
                confidence = min(1.0, total_connections / 10000)
                indicators.append(BotIndicator(
                    indicator_type="mass_connections",
                    method=BotDetectionMethod.NETWORK,
                    value=total_connections,
                    threshold=1000,
                    description=f"Mass connections: {total_connections} total",
                    confidence=confidence
                ))
                score += 20 * confidence
        
        return min(100.0, score), indicators
    
    def _calculate_time_range(self, activity: UserActivity) -> float:
        if not activity.posts:
            return 0.0
        
        timestamps = []
        for post in activity.posts:
            ts = post.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    timestamps.append(dt.timestamp())
                except Exception:
                    pass
        
        if len(timestamps) < 2:
            return 0.0
        
        return max(timestamps) - min(timestamps)
    
    def _calculate_score(
        self,
        behavioral: float,
        content: float,
        temporal: float,
        network: float
    ) -> float:
        # Weighted average
        weights = {
            "behavioral": 0.35,
            "content": 0.25,
            "temporal": 0.25,
            "network": 0.15
        }
        
        score = (
            behavioral * weights["behavioral"] +
            content * weights["content"] +
            temporal * weights["temporal"] +
            network * weights["network"]
        )
        
        return min(100.0, score)
    
    def _calculate_confidence(self, indicators: List[BotIndicator]) -> float:
        if not indicators:
            return 0.0
        
        total_confidence = sum(indicator.confidence for indicator in indicators)
        return min(1.0, total_confidence / len(indicators))
    
    def check_dependencies(self) -> Dict[str, bool]:
        return {
            "numpy": HAS_NUMPY,
            "sklearn": HAS_SKLEARN,
        }
    
    def get_indicator_description(self, indicator_type: str) -> str:
        descriptions = {
            "high_post_frequency": "Posts at an unusually high frequency",
            "high_follower_ratio": "Follows many more users than follow back",
            "high_retweet_ratio": "Mostly retweets rather than original content",
            "high_content_similarity": "Posts very similar content repeatedly",
            "high_url_ratio": "Posts contain many URLs",
            "high_hashtag_ratio": "Posts contain many hashtags",
            "high_regularity": "Posts at very regular intervals",
            "burst_posting": "Posts many messages in short time periods",
            "mass_connections": "Has an unusually large number of connections",
        }
        return descriptions.get(indicator_type, "Unknown bot indicator")
