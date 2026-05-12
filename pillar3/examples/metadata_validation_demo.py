#!/usr/bin/env python3
"""
Metadata Validation Demo

Demonstrates the metadata validation capabilities of Pillar 3: Deception Defense.
This example shows how to validate metadata from images, audio, and video files.
"""

import os
import sys
import tempfile

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pillar3.src.analysis.metadata_validator import (
    MetadataValidator,
    ValidationStatus,
)


def create_test_image():
    """Create a test image file."""
    try:
        from PIL import Image
        import numpy as np
        
        # Create a simple test image
        img_array = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)
        
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp.name)
            return tmp.name
    except ImportError:
        print("Pillow not available, creating dummy file")
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(b'dummy image data')
            return tmp.name


def create_test_text_file():
    """Create a test text file."""
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w') as tmp:
        tmp.write("This is a test text file for metadata validation.")
        return tmp.name


def cleanup_file(file_path):
    """Clean up a temporary file."""
    if os.path.exists(file_path):
        os.unlink(file_path)


def demo_image_validation():
    """Demonstrate image metadata validation."""
    print("=" * 60)
    print("IMAGE METADATA VALIDATION DEMO")
    print("=" * 60)
    
    validator = MetadataValidator()
    
    # Create test image
    image_path = create_test_image()
    
    try:
        print(f"\nValidating image: {image_path}")
        
        # Validate the image
        result = validator.validate_image(image_path)
        
        # Display results
        print(f"\nValidation Status: {result.status.value.upper()}")
        print(f"File Type: {result.file_type}")
        print(f"File Size: {result.file_size} bytes")
        print(f"File Hash: {result.file_hash[:16]}...")
        print(f"Processing Time: {result.processing_time:.4f} seconds")
        print(f"Validation Score: {result.score:.1f}/100")
        
        if result.has_issues:
            print(f"\nIssues Found: {len(result.issues)}")
            for i, issue in enumerate(result.issues, 1):
                print(f"  {i}. [{issue.severity.upper()}] {issue.issue_type}: {issue.description}")
        else:
            print("\nNo issues found - metadata appears valid!")
        
        # Display metadata
        if result.metadata:
            print(f"\nExtracted Metadata:")
            for key, value in result.metadata.items():
                if key == 'image_info':
                    print(f"  Image Info:")
                    for k, v in value.items():
                        print(f"    {k}: {v}")
                else:
                    print(f"  {key}: {value}")
        
    finally:
        cleanup_file(image_path)


def demo_file_not_found():
    """Demonstrate handling of non-existent files."""
    print("\n" + "=" * 60)
    print("FILE NOT FOUND DEMO")
    print("=" * 60)
    
    validator = MetadataValidator()
    
    # Try to validate a non-existent file
    result = validator.validate_image("/nonexistent/path/image.jpg")
    
    print(f"\nValidation Status: {result.status.value.upper()}")
    print(f"File Path: {result.file_path}")
    print(f"Issues Found: {len(result.issues)}")
    
    for issue in result.issues:
        print(f"  [{issue.severity.upper()}] {issue.issue_type}: {issue.description}")


def demo_dependency_check():
    """Demonstrate checking for required dependencies."""
    print("\n" + "=" * 60)
    print("DEPENDENCY CHECK DEMO")
    print("=" * 60)
    
    validator = MetadataValidator()
    dependencies = validator.check_dependencies()
    
    print("\nAvailable Dependencies:")
    for dep, available in dependencies.items():
        status = "✓ Available" if available else "✗ Not Available"
        print(f"  {dep}: {status}")


def demo_supported_formats():
    """Demonstrate getting supported formats."""
    print("\n" + "=" * 60)
    print("SUPPORTED FORMATS DEMO")
    print("=" * 60)
    
    validator = MetadataValidator()
    formats = validator.get_supported_formats()
    
    print("\nSupported Formats:")
    for media_type, extensions in formats.items():
        print(f"  {media_type.value.upper()}: {', '.join(extensions)}")


def main():
    """Run all demos."""
    print("Pillar 3: Deception Defense - Metadata Validation Demo")
    print("=" * 60)
    
    # Run demos
    demo_image_validation()
    demo_file_not_found()
    demo_dependency_check()
    demo_supported_formats()
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
