"""
Tests for BotDetector module
"""

import pytest
from datetime import datetime, timedelta
from src.analysis.bot_detector import BotDetector, UserActivity, BotStatus, BotDetectionMethod


@pytest.fixture
def bot_detector():
    return BotDetector()


@pytest.fixture
def normal_activity():
    posts = []
    now = datetime.utcnow()
    for i in range(10):
        posts.append({
            "content": f"This is my post number {i}",
            "timestamp": (now - timedelta(hours=i)).isoformat() + 'Z',
            "is_retweet": False
        })
    return UserActivity(
        user_id="normal_user",
        posts=posts,
        followers=[f"follower_{i}" for i in range(100)],
        following=[f"following_{i}" for i in range(50)]
    )


@pytest.fixture
def bot_like_activity():
    posts = []
    now = datetime.utcnow()
    # Create posts with similar content and high frequency
    for i in range(100):
        posts.append({
            "content": "Buy this amazing product now! http://example.com/product #amazing #deal",
            "timestamp": (now - timedelta(minutes=i)).isoformat() + 'Z',
            "is_retweet": True
        })
    return UserActivity(
        user_id="bot_user",
        posts=posts,
        followers=[f"follower_{i}" for i in range(10)],
        following=[f"following_{i}" for i in range(1000)]
    )


@pytest.fixture
def empty_activity():
    return UserActivity(
        user_id="empty_user",
        posts=[],
        followers=[],
        following=[]
    )


class TestBotDetector:
    def test_initialization(self, bot_detector):
        assert bot_detector is not None
        assert hasattr(bot_detector, 'detect')
        assert hasattr(bot_detector, 'check_dependencies')

    def test_empty_activity(self, bot_detector, empty_activity):
        result = bot_detector.detect(empty_activity)
        assert result.status == BotStatus.NONE
        assert result.score == 0.0
        assert result.is_bot is False
        assert result.confidence == 0.0

    def test_normal_activity(self, bot_detector, normal_activity):
        result = bot_detector.detect(normal_activity)
        assert result.status in [BotStatus.NONE, BotStatus.LOW]
        assert result.is_bot is False
        assert result.score < 50

    def test_bot_like_activity(self, bot_detector, bot_like_activity):
        result = bot_detector.detect(bot_like_activity)
        assert result.status in [BotStatus.MEDIUM, BotStatus.HIGH, BotStatus.EXTREME]
        assert result.is_bot is True
        assert result.score >= 40

    def test_check_dependencies(self, bot_detector):
        deps = bot_detector.check_dependencies()
        assert "numpy" in deps
        assert "sklearn" in deps

    def test_indicator_descriptions(self, bot_detector):
        descriptions = bot_detector.get_indicator_description("high_post_frequency")
        assert isinstance(descriptions, str)
        assert len(descriptions) > 0

    def test_bot_probability(self, bot_detector, bot_like_activity):
        result = bot_detector.detect(bot_like_activity)
        assert 0.0 <= result.bot_probability <= 1.0

    def test_result_serialization(self, bot_detector, normal_activity):
        result = bot_detector.detect(normal_activity)
        result_dict = result.to_dict()
        assert "status" in result_dict
        assert "score" in result_dict
        assert "is_bot" in result_dict
        assert "indicators" in result_dict
        
        result_json = result.to_json()
        assert isinstance(result_json, str)
        assert len(result_json) > 0


class TestUserActivity:
    def test_post_count(self, normal_activity):
        assert normal_activity.post_count == 10

    def test_follower_count(self, normal_activity):
        assert normal_activity.follower_count == 100

    def test_following_count(self, normal_activity):
        assert normal_activity.following_count == 50
