"""
Tests for DeepfakeDetector module
"""

import pytest
import numpy as np
from PIL import Image
import tempfile
import os
from src.analysis.deepfake_detector import DeepfakeDetector, DeepfakeStatus


@pytest.fixture
def deepfake_detector():
    return DeepfakeDetector()


@pytest.fixture
def create_test_image():
    """Create a simple test image"""
    def _create_test_image(size=(100, 100), color='red'):
        img = Image.new('RGB', size, color)
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(temp_file.name)
        temp_file.close()
        return temp_file.name
    
    return _create_test_image


@pytest.fixture
def create_test_video():
    """Create a simple test video (placeholder - would need ffmpeg)"""
    def _create_test_video():
        # For now, just create a dummy file
        temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        temp_file.close()
        return temp_file.name
    
    return _create_test_video


class TestDeepfakeDetector:
    def test_initialization(self, deepfake_detector):
        assert deepfake_detector is not None
        assert hasattr(deepfake_detector, 'detect_image')
        assert hasattr(deepfake_detector, 'detect_video')
        assert hasattr(deepfake_detector, 'detect_audio')
        assert hasattr(deepfake_detector, 'check_dependencies')

    def test_check_dependencies(self, deepfake_detector):
        deps = deepfake_detector.check_dependencies()
        assert isinstance(deps, dict)

    def test_detect_with_nonexistent_file(self, deepfake_detector):
        result = deepfake_detector.detect_image("/nonexistent/file.png")
        assert result.status == DeepfakeStatus.UNKNOWN
        assert result.confidence == 0.0

    def test_detect_with_test_image(self, deepfake_detector, create_test_image):
        image_path = create_test_image()
        try:
            result = deepfake_detector.detect_image(image_path)
            assert result.status in [DeepfakeStatus.GENUINE, DeepfakeStatus.LOW, DeepfakeStatus.MEDIUM, DeepfakeStatus.HIGH, DeepfakeStatus.EXTREME]
            assert result.media_type == MediaType.IMAGE
            assert result.processing_time >= 0
        finally:
            os.unlink(image_path)

    def test_result_serialization(self, deepfake_detector, create_test_image):
        image_path = create_test_image()
        try:
            result = deepfake_detector.detect_image(image_path)
            result_dict = result.to_dict()
            assert "status" in result_dict
            assert "confidence" in result_dict
            assert "score" in result_dict
            assert "media_type" in result_dict
            
            result_json = result.to_json()
            assert isinstance(result_json, str)
            assert len(result_json) > 0
        finally:
            os.unlink(image_path)

    def test_get_artifact_analysis(self, deepfake_detector, create_test_image):
        image_path = create_test_image()
        try:
            artifacts = deepfake_detector._analyze_image_artifacts(image_path)
            assert isinstance(artifacts, dict)
        finally:
            os.unlink(image_path)

    def test__get_artifact_description(self, deepfake_detector):
        description = deepfake_detector._get_artifact_description("face_artifacts")
        assert isinstance(description, str)
        assert len(description) > 0
