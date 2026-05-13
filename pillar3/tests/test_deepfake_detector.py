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
            assert result.status in [DeepfakeStatus.GENUINE, DeepfakeStatus.SUSPICIOUS, DeepfakeStatus.FAKE, DeepfakeStatus.UNKNOWN]
            assert result.file_type == "image"
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
            assert "file_type" in result_dict
            
            # Convert to JSON using the dict
            import json
            result_json = json.dumps(result_dict)
            assert isinstance(result_json, str)
            assert len(result_json) > 0
        finally:
            os.unlink(image_path)

    def test_get_artifact_analysis(self, deepfake_detector, create_test_image):
        image_path = create_test_image()
        try:
            # Test the internal artifact detection method
            # Skip if OpenCV is not available
            try:
                import cv2
                img = cv2.imread(image_path)
                if img is not None:
                    artifacts = deepfake_detector._detect_image_artifacts(img)
                    assert isinstance(artifacts, list)
            except ImportError:
                pytest.skip("OpenCV not available")
        finally:
            os.unlink(image_path)

    def test__get_artifact_description(self, deepfake_detector):
        # Test artifact type descriptions
        from src.analysis.deepfake_detector import ArtifactType, Artifact
        # Check that artifact types have descriptions
        artifact = Artifact(
            artifact_type=ArtifactType.FACE_ARTIFACTS,
            location="test",
            severity=0.5,
            description="Test artifact",
            confidence=0.8
        )
        assert isinstance(artifact.description, str)
        assert len(artifact.description) > 0
