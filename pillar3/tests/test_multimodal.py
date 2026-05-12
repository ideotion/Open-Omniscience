"""
Tests for Multimodal verification module
"""

import pytest
import tempfile
import os
from PIL import Image
from src.analysis.multimodal import (
    MultiModalAnalyzer, 
    ConsistencyStatus,
    MediaItem,
    MediaType
)


@pytest.fixture
def multimodal_verifier():
    return MultiModalAnalyzer()


@pytest.fixture
def create_test_image():
    """Create a simple test image"""
    def _create_test_image(size=(200, 200), color='blue'):
        img = Image.new('RGB', size, color)
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(temp_file.name)
        temp_file.close()
        return temp_file.name
    
    return _create_test_image


@pytest.fixture
def text_media_item():
    return MediaItem(
        file_path="test.txt",
        media_type=MediaType.TEXT,
        content="This is a test text content",
        metadata={"source": "test"}
    )


@pytest.fixture
def empty_media_items():
    return []


class TestMultiModalAnalyzer:
    def test_initialization(self, multimodal_verifier):
        assert multimodal_verifier is not None
        assert hasattr(multimodal_verifier, 'analyze')
        assert hasattr(multimodal_verifier, 'extract_text_from_image')
        assert hasattr(multimodal_verifier, 'check_dependencies')

    def test_empty_media_items(self, multimodal_verifier, empty_media_items):
        result = multimodal_verifier.analyze(empty_media_items)
        assert result.status == ConsistencyStatus.NONE
        assert result.score == 0.0

    def test_single_text_item(self, multimodal_verifier, text_media_item):
        result = multimodal_verifier.analyze([text_media_item])
        assert result.status in [ConsistencyStatus.NONE, ConsistencyStatus.LOW]
        assert result.media_item_count == 1

    def test_check_dependencies(self, multimodal_verifier):
        deps = multimodal_verifier.check_dependencies()
        assert isinstance(deps, dict) or isinstance(deps, list)

    def test_result_serialization(self, multimodal_verifier, text_media_item):
        result = multimodal_verifier.analyze([text_media_item])
        result_dict = result.to_dict()
        assert "status" in result_dict
        assert "score" in result_dict
        assert "confidence" in result_dict
        assert "media_item_count" in result_dict
        
        result_json = result.to_json()
        assert isinstance(result_json, str)
        assert len(result_json) > 0

    def test_extract_text_from_image(self, multimodal_verifier, create_test_image):
        image_path = create_test_image()
        try:
            # This will use OCR to extract text from the image
            # Since our test image is just a solid color, it should return empty or minimal text
            text = multimodal_verifier.extract_text_from_image(image_path)
            assert isinstance(text, str)
        finally:
            os.unlink(image_path)

    def testcheck_semantic_consistency(self, multimodal_verifier):
        texts = ["Hello world", "Good morning", "How are you"]
        consistency = multimodal_verifier.check_semantic_consistency(texts)
        assert isinstance(consistency, float)
        assert 0.0 <= consistency <= 1.0

    def test__get_technique_description(self, multimodal_verifier):
        description = multimodal_verifier._get_technique_description("semantic_analysis")
        assert isinstance(description, str)
        assert len(description) > 0
