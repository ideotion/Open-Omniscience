"""
Pillar 3: Deception Defense (FOSS)

A comprehensive deception defense system for detecting deepfakes, propaganda,
and cognitive biases using 100% open-source models that work offline.

This package provides:
- Multi-modal verification (images, video, audio, text)
- Deepfake detection using FOSS models
- Propaganda and cognitive bias detection
- Disinformation campaign tracking

All functionality works offline with no cloud dependencies.
"""

__version__ = "0.1.0"
__author__ = "Open-Omniscience Team"
__license__ = "AGPL-3.0"
__all__ = [
    "analysis",
    "models", 
    "utils",
]

# Import submodules for easier access
from . import analysis, models, utils

__doc__ = f"""
Open-Omniscience Pillar 3: Deception Defense v{__version__}

100% FOSS deception detection system with offline capability.

Available modules:
- analysis: Core detection modules
- models: Model loading and management
- utils: Utility functions and preprocessing

Example usage:
    from pillar3.analysis import DeepfakeDetector
    detector = DeepfakeDetector()
    # result = detector.detect_image("path/to/image.jpg")
    # print(f"Deepfake confidence: {{result.confidence:.2%}}")
"""
