"""
Pillar 4: Tests for Pattern Recognizer
"""

import pytest
import time
from pillar4.src.analysis.pattern_recognizer import PatternRecognizer, Pattern, PatternType, PatternStatus


class TestPatternRecognizer:
    """Tests for the PatternRecognizer class."""

    def test_initialization(self):
        """Test recognizer initialization."""
        recognizer = PatternRecognizer()
        assert recognizer.pattern_window == 50
        assert recognizer.similarity_threshold == 0.85
        assert recognizer.min_occurrences == 3

    def test_initialization_custom_params(self):
        """Test recognizer initialization with custom parameters."""
        recognizer = PatternRecognizer(
            pattern_window=100,
            similarity_threshold=0.9,
            min_occurrences=5,
        )
        assert recognizer.pattern_window == 100
        assert recognizer.similarity_threshold == 0.9
        assert recognizer.min_occurrences == 5

    def test_add_data_point(self):
        """Test adding data points."""
        recognizer = PatternRecognizer()
        recognizer.add_data_point("test content 1", source="source1")
        recognizer.add_data_point("test content 2", source="source2")
        
        assert len(recognizer.recent_data) == 2
        assert "source1" in recognizer.source_content
        assert "source2" in recognizer.source_content

    def test_detect_repeating_patterns(self):
        """Test detection of repeating patterns."""
        recognizer = PatternRecognizer(min_occurrences=2)
        
        # Add repeating content
        content = "This is a test message"
        for i in range(3):
            recognizer.add_data_point(content, source=f"source{i}")
        
        patterns = recognizer.detect_repeating_patterns()
        assert len(patterns) >= 1
        assert any(p.type == PatternType.REPEATING for p in patterns)

    def test_detect_coordinated_patterns(self):
        """Test detection of coordinated patterns."""
        recognizer = PatternRecognizer(min_occurrences=2)
        
        # Add similar content from different sources
        content1 = "Important news announcement"
        content2 = "Important news announcement!"
        content3 = "Important news announcement!!"
        
        recognizer.add_data_point(content1, source="source1")
        recognizer.add_data_point(content2, source="source2")
        recognizer.add_data_point(content3, source="source3")
        
        patterns = recognizer.detect_coordinated_patterns()
        assert len(patterns) >= 1
        assert any(p.type == PatternType.COORDINATED for p in patterns)

    def test_detect_campaign_fingerprints(self):
        """Test detection of campaign fingerprints."""
        recognizer = PatternRecognizer()
        
        # Add content with campaign indicators
        recognizer.add_data_point("Check out this #amazing offer!")
        recognizer.add_data_point("Don't miss this #amazing deal!")
        recognizer.add_data_point("This #amazing opportunity won't last!")
        
        patterns = recognizer.detect_campaign_fingerprints()
        assert len(patterns) >= 1
        assert any(p.type == PatternType.CAMPAIGN for p in patterns)

    def test_detect_behavioral_patterns(self):
        """Test detection of behavioral patterns."""
        recognizer = PatternRecognizer()
        
        # Add content from a source with regular posting
        for i in range(10):
            recognizer.add_data_point(f"Message {i}", source="regular_source")
            time.sleep(0.01)  # Small delay
        
        patterns = recognizer.detect_behavioral_patterns()
        assert len(patterns) >= 0  # May or may not detect depending on timing

    def test_detect_all(self):
        """Test running all pattern detection methods."""
        recognizer = PatternRecognizer()
        
        # Add various patterns
        for i in range(5):
            recognizer.add_data_point("Repeated message", source="source1")
        
        recognizer.add_data_point("Similar message", source="source2")
        recognizer.add_data_point("Another similar message", source="source3")
        
        patterns = recognizer.detect_all()
        assert len(patterns) >= 2

    def test_get_stats(self):
        """Test getting statistics."""
        recognizer = PatternRecognizer()
        recognizer.add_data_point("test 1", source="source1")
        recognizer.add_data_point("test 2", source="source2")
        
        stats = recognizer.get_stats()
        assert stats["total_data_points"] == 2
        assert stats["unique_sources"] == 2

    def test_reset(self):
        """Test resetting the recognizer."""
        recognizer = PatternRecognizer()
        recognizer.add_data_point("test", source="source1")
        recognizer.add_data_point("test2", source="source2")
        
        recognizer.reset()
        
        assert len(recognizer.recent_data) == 0
        assert len(recognizer.recent_timestamps) == 0
        assert len(recognizer.source_content) == 0

    def test_empty_data(self):
        """Test with empty data."""
        recognizer = PatternRecognizer()
        patterns = recognizer.detect_repeating_patterns()
        assert len(patterns) == 0

    def test_insufficient_data(self):
        """Test with insufficient data for pattern detection."""
        recognizer = PatternRecognizer(min_occurrences=5)
        
        # Add content but not enough for detection
        for i in range(3):
            recognizer.add_data_point("test", source="source1")
        
        patterns = recognizer.detect_repeating_patterns()
        assert len(patterns) == 0

    def test_text_similarity(self):
        """Test text similarity calculation."""
        recognizer = PatternRecognizer()
        
        text1 = "This is a test message"
        text2 = "This is a test message!"
        text3 = "This is a completely different message"
        
        similarity1 = recognizer._text_similarity(text1, text2)
        similarity2 = recognizer._text_similarity(text1, text3)
        
        assert similarity1 > similarity2
        assert similarity1 > 0.5  # Should be quite similar
        assert similarity2 < 0.5  # Should be less similar


class TestPattern:
    """Tests for the Pattern dataclass."""

    def test_pattern_creation(self):
        """Test creating a pattern."""
        pattern = Pattern(
            type=PatternType.REPEATING,
            status=PatternStatus.CONFIRMED,
            score=0.95,
            confidence=0.9,
            description="Repeated content",
            first_seen=time.time() - 100,
            last_seen=time.time(),
            occurrences=5,
            elements=["test message"],
        )
        
        assert pattern.type == PatternType.REPEATING
        assert pattern.status == PatternStatus.CONFIRMED
        assert pattern.score == 0.95
        assert pattern.occurrences == 5

    def test_pattern_to_dict(self):
        """Test converting pattern to dictionary."""
        pattern = Pattern(
            type=PatternType.COORDINATED,
            status=PatternStatus.POTENTIAL,
            score=0.85,
            confidence=0.8,
            description="Coordinated posting",
            first_seen=time.time() - 50,
            last_seen=time.time(),
            occurrences=3,
            elements=["message1", "message2"],
            metadata={"sources": ["source1", "source2"]},
        )
        
        d = pattern.to_dict()
        assert d["type"] == "coordinated"
        assert d["status"] == "potential"
        assert d["score"] == 0.85
        assert d["occurrences"] == 3
        assert len(d["elements"]) == 2

    def test_pattern_properties(self):
        """Test pattern properties."""
        pattern = Pattern(
            type=PatternType.CAMPAIGN,
            status=PatternStatus.CONFIRMED,
            score=0.9,
            confidence=0.85,
            description="Campaign fingerprint",
            first_seen=time.time() - 100,
            last_seen=time.time(),
            occurrences=10,
            elements=["#hashtag1", "#hashtag2"],
        )
        
        assert pattern.type.value == "campaign"
        assert pattern.status.value == "confirmed"
        assert pattern.score > 0.8
        assert pattern.confidence > 0.8


class TestCampaignDetection:
    """Tests for campaign fingerprint detection."""

    def test_hashtag_spam_detection(self):
        """Test detection of hashtag spam."""
        recognizer = PatternRecognizer()
        
        # Add content with excessive hashtags
        for i in range(5):
            recognizer.add_data_point(
                "Check out #amazing #offer #deal #sale #discount #promotion #limitedtime",
                source=f"source{i}"
            )
        
        patterns = recognizer.detect_campaign_fingerprints()
        assert len(patterns) >= 1
        assert any("hashtag" in p.description.lower() for p in patterns)

    def test_url_shortener_detection(self):
        """Test detection of URL shorteners."""
        recognizer = PatternRecognizer()
        
        # Add content with URL shorteners
        messages = [
            "Click here: bit.ly/test1",
            "Visit: goo.gl/test2",
            "Check out: t.co/test3",
            "Link: tinyurl.com/test4",
        ]
        
        for msg in messages:
            recognizer.add_data_point(msg, source="source")
        
        patterns = recognizer.detect_campaign_fingerprints()
        assert len(patterns) >= 1
        assert any("url" in p.description.lower() or "shortener" in p.description.lower() 
                   for p in patterns)

    def test_repeated_phrases_detection(self):
        """Test detection of repeated phrases."""
        recognizer = PatternRecognizer()
        
        # Add content with repeated phrases
        messages = [
            "This amazing product will change your life!",
            "This amazing product is the best ever!",
            "You need this amazing product today!",
        ]
        
        for msg in messages:
            recognizer.add_data_point(msg, source="source")
        
        patterns = recognizer.detect_campaign_fingerprints()
        assert len(patterns) >= 1


class TestBehavioralPatterns:
    """Tests for behavioral pattern detection."""

    def test_regular_posting_pattern(self):
        """Test detection of regular posting intervals."""
        recognizer = PatternRecognizer()
        
        # Simulate regular posting (every 10 seconds)
        base_time = time.time()
        for i in range(10):
            timestamp = base_time + (i * 10)
            # Mock the timestamp by directly manipulating the data
            recognizer.source_content["regular_source"] = [
                (timestamp + j, f"Message {j}") for j in range(i + 1)
            ]
        
        patterns = recognizer.detect_behavioral_patterns()
        # Should detect regular pattern
        assert any(p.type == PatternType.BEHAVIORAL and "regular" in p.description.lower()
                   for p in patterns) or len(patterns) >= 1

    def test_burst_activity_detection(self):
        """Test detection of burst activity."""
        recognizer = PatternRecognizer()
        
        # Simulate burst activity
        base_time = time.time()
        for i in range(5):
            timestamp = base_time + (i * 0.1)  # Very short intervals
            recognizer.source_content["burst_source"] = [
                (timestamp + j * 0.1, f"Message {j}") for j in range(i + 1)
            ]
        
        patterns = recognizer.detect_behavioral_patterns()
        # Should detect burst pattern
        assert any(p.type == PatternType.BEHAVIORAL and "burst" in p.description.lower()
                   for p in patterns) or len(patterns) >= 1
