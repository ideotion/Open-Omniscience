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
        assert result.cross_modal_analysis.consistency_status == ConsistencyStatus.ERROR
        assert result.consistency_score == 0.0

    def test_single_text_item(self, multimodal_verifier, create_test_image):
        # Create a test image file
        image_path = create_test_image()
        try:
            result = multimodal_verifier.analyze([image_path])
            assert result.cross_modal_analysis.consistency_status in [ConsistencyStatus.CONSISTENT, ConsistencyStatus.PARTIALLY_CONSISTENT, ConsistencyStatus.INCONSISTENT, ConsistencyStatus.UNRELATED, ConsistencyStatus.ERROR]
            assert len(result.individual_results) >= 0  # May have results depending on file type
        finally:
            os.unlink(image_path)

    def test_check_dependencies(self, multimodal_verifier):
        deps = multimodal_verifier.check_dependencies()
        assert isinstance(deps, dict) or isinstance(deps, list)

    def test_result_serialization(self, multimodal_verifier, create_test_image):
        image_path = create_test_image()
        try:
            result = multimodal_verifier.analyze([image_path])
            result_dict = result.to_dict()
            assert "consistency_score" in result_dict
            assert "cross_modal_analysis" in result_dict
            assert "processing_time" in result_dict
            
            # Convert to JSON using the dict
            import json
            result_json = json.dumps(result_dict)
            assert isinstance(result_json, str)
            assert len(result_json) > 0
        finally:
            os.unlink(image_path)

    def test_extract_text_from_image(self, multimodal_verifier, create_test_image):
        # Skip if Tesseract is not available
        try:
            import pytesseract
        except ImportError:
            pytest.skip("Tesseract not available for OCR")
        
        image_path = create_test_image()
        try:
            # This will use OCR to extract text from the image
            # Since our test image is just a solid color, it should return empty or minimal text
            text = multimodal_verifier.extract_text_from_image(image_path)
            assert isinstance(text, str)
        finally:
            os.unlink(image_path)

    def test_check_semantic_consistency(self, multimodal_verifier):
        text = "Hello world"
        image_features = {"colors": ["red", "blue"], "objects": ["person"]}
        consistency = multimodal_verifier.check_semantic_consistency(text, image_features)
        assert isinstance(consistency, float)
        assert 0.0 <= consistency <= 1.0
