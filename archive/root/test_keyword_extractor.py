import pytest
from src.services.keyword_extractor import KeywordExtractor, keyword_extractor
from src.services.text_processor import TextProcessor, text_processor
from src.services.stopwords import StopwordsManager, stopwords_manager


class TestStopwordsManager:
    def test_initialization(self):
        manager = StopwordsManager()
        assert manager is not None
        assert len(manager.get_stopwords("en")) > 0

    def test_filter_stopwords(self):
        manager = StopwordsManager()
        words = ["the", "quick", "brown", "fox"]
        filtered = manager.filter_stopwords(words, "en")
        assert "the" not in filtered
        assert "quick" in filtered


class TestTextProcessor:
    def test_clean_text(self):
        processor = TextProcessor()
        text = "Hello <b>world</b>!"
        cleaned = processor.clean_text(text)
        assert "<b>" not in cleaned
        assert "!" not in cleaned

    def test_tokenize(self):
        processor = TextProcessor()
        text = "The quick brown fox"
        tokens = processor.tokenize(text)
        assert "the" in tokens
        assert "quick" in tokens


class TestKeywordExtractor:
    def test_extract_keywords(self):
        extractor = KeywordExtractor()
        text = "The quick brown fox jumps over the lazy dog."
        result = extractor.extract_keywords(text, "en")
        assert "keywords" in result
        assert "quick" in result["keywords"]

    def test_categorize_keywords(self):
        extractor = KeywordExtractor()
        keywords = ["politics", "technology", "health"]
        categories = extractor.categorize_keywords(keywords)
        assert "politics" in categories
        assert "technology" in categories


class TestGlobalInstances:
    def test_instances_exist(self):
        assert stopwords_manager is not None
        assert text_processor is not None
        assert keyword_extractor is not None
