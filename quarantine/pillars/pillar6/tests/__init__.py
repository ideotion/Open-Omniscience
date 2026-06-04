"""
Pillar 6 Test Suite

Comprehensive tests for rare earth market intelligence system.
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure pytest markers
pytestmark = pytest.mark.pillar6
