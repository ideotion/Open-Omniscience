"""
Tests for Metadata Validator Module
"""

import os
import tempfile
import pytest
from pathlib import Path

from pillar3.src.analysis.metadata_validator import (
    MetadataValidator,
    MetadataType,
    ValidationStatus,
    ValidationResult,
    ValidationIssue,
)


@pytest.fixture
def validator():
    """Create a MetadataValidator instance."""
    return MetadataValidator()


@pytest.fixture
def temp_image():
    """Create a temporary image file for testing."""
    try:
        from PIL import Image
        import numpy as np
        
        # Create a simple test image
        img_array = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp.name)
            yield tmp.name
            
        # Clean up
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    except ImportError:
        # If PIL is not available, create a dummy file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(b'dummy image data')
            yield tmp.name
        
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


@pytest.fixture
def temp_text_file():
    """Create a temporary text file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w') as tmp:
        tmp.write("This is a test file.")
        yield tmp.name
    
    if os.path.exists(tmp.name):
        os.unlink(tmp.name)


class TestMetadataValidator:
    """Test cases for MetadataValidator class."""
    
    def test_initialization(self, validator):
        """Test that validator initializes correctly."""
        assert validator is not None
        assert hasattr(validator, 'validate_image')
        assert hasattr(validator, 'validate_audio')
        assert hasattr(validator, 'validate_video')
    
    def test_validate_nonexistent_file(self, validator):
        """Test validation of non-existent file."""
        result = validator.validate_image("/nonexistent/path/image.jpg")
        
        assert result.status == ValidationStatus.INVALID
        assert result.metadata_type == MetadataType.IMAGE
        assert len(result.issues) > 0
        assert result.issues[0].issue_type == "file_not_found"
        assert result.issues[0].severity == "critical"
    
    def test_validate_image_file(self, validator, temp_image):
        """Test validation of an image file."""
        result = validator.validate_image(temp_image)
        
        assert result is not None
        assert result.metadata_type == MetadataType.IMAGE
        assert result.file_path == temp_image
        assert result.file_size > 0
        assert result.file_hash != ""
        assert result.timestamp != ""
        assert result.processing_time >= 0
    
    def test_validate_text_file(self, validator, temp_text_file):
        """Test validation of a text file (should be treated as unknown)."""
        result = validator.validate_image(temp_text_file)
        
        assert result is not None
        assert result.metadata_type == MetadataType.IMAGE
        assert result.file_path == temp_text_file
    
    def test_validation_result_properties(self, validator, temp_image):
        """Test properties of ValidationResult."""
        result = validator.validate_image(temp_image)
        
        # Test is_valid property
        assert isinstance(result.is_valid, bool)
        
        # Test has_issues property
        assert isinstance(result.has_issues, bool)
        
        # Test score property
        assert 0 <= result.score <= 100
        
        # Test to_dict method
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert "status" in result_dict
        assert "metadata_type" in result_dict
        assert "file_path" in result_dict
        assert "score" in result_dict
    
    def test_validation_result_to_json(self, validator, temp_image):
        """Test JSON serialization of ValidationResult."""
        result = validator.validate_image(temp_image)
        json_str = result.to_json()
        
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    def test_get_supported_formats(self, validator):
        """Test getting supported formats."""
        formats = validator.get_supported_formats()
        
        assert isinstance(formats, dict)
        assert MetadataType.IMAGE in formats
        assert MetadataType.AUDIO in formats
        assert MetadataType.VIDEO in formats
        assert len(formats[MetadataType.IMAGE]) > 0
        assert len(formats[MetadataType.AUDIO]) > 0
        assert len(formats[MetadataType.VIDEO]) > 0
    
    def test_check_dependencies(self, validator):
        """Test checking dependencies."""
        deps = validator.check_dependencies()
        
        assert isinstance(deps, dict)
        assert "Pillow" in deps
        assert "pydub" in deps
        assert "OpenCV" in deps
        assert "Tesseract" in deps


class TestValidationIssue:
    """Test cases for ValidationIssue class."""
    
    def test_validation_issue_creation(self):
        """Test creating a ValidationIssue."""
        issue = ValidationIssue(
            issue_type="test_issue",
            severity="high",
            description="Test description",
            field="test_field",
        )
        
        assert issue.issue_type == "test_issue"
        assert issue.severity == "high"
        assert issue.description == "Test description"
        assert issue.field == "test_field"
        assert issue.confidence == 1.0
    
    def test_validation_issue_to_dict(self):
        """Test converting ValidationIssue to dict."""
        issue = ValidationIssue(
            issue_type="test_issue",
            severity="medium",
            description="Test description",
            field="test_field",
            expected="expected_value",
            actual="actual_value",
            confidence=0.8,
        )
        
        issue_dict = issue.to_dict()
        
        assert isinstance(issue_dict, dict)
        assert issue_dict["issue_type"] == "test_issue"
        assert issue_dict["severity"] == "medium"
        assert issue_dict["confidence"] == 0.8


class TestValidationStatus:
    """Test cases for ValidationStatus enum."""
    
    def test_validation_status_values(self):
        """Test ValidationStatus enum values."""
        assert ValidationStatus.VALID.value == "valid"
        assert ValidationStatus.SUSPICIOUS.value == "suspicious"
        assert ValidationStatus.INVALID.value == "invalid"
        assert ValidationStatus.TAMPERED.value == "tampered"
        assert ValidationStatus.MISSING.value == "missing"


class TestMetadataType:
    """Test cases for MetadataType enum."""
    
    def test_metadata_type_values(self):
        """Test MetadataType enum values."""
        assert MetadataType.IMAGE.value == "image"
        assert MetadataType.AUDIO.value == "audio"
        assert MetadataType.VIDEO.value == "video"
        assert MetadataType.TEXT.value == "text"
        assert MetadataType.UNKNOWN.value == "unknown"
