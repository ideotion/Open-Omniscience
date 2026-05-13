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
Analysis Module for Pillar 3: Deception Defense

This module contains all the core deception detection functionality:
- Multi-modal verification
- Metadata validation
- Deepfake detection
- Propaganda detection
- Cognitive bias detection
- Network analysis
- Bot detection
"""

from .multimodal import MultiModalAnalyzer
from .metadata_validator import MetadataValidator
from .deepfake_detector import DeepfakeDetector
from .propaganda import PropagandaDetector
from .cognitive_bias import CognitiveBiasDetector
from .network_analyzer import NetworkAnalyzer
from .bot_detector import BotDetector

# Data classes and enums
from .multimodal import (
    MediaType,
    MediaItem,
    CrossModalResult,
    MultiModalResult,
    ConsistencyStatus,
)
from .metadata_validator import (
    ValidationResult,
    MetadataType,
    ValidationStatus,
)
from .deepfake_detector import (
    DeepfakeResult,
    DeepfakeStatus,
    ArtifactType,
)
from .propaganda import (
    PropagandaResult,
    PropagandaTechnique,
    PropagandaStatus,
)
from .cognitive_bias import (
    CognitiveBiasResult,
    CognitiveBias,
    CognitiveBiasStatus,
    BiasInstance,
)
from .network_analyzer import (
    NetworkAnalysisResult,
    NetworkNode,
    NetworkEdge,
    Community,
    NetworkStatus,
    NetworkType,
)
from .bot_detector import (
    BotResult,
    BotStatus,
    BotDetectionMethod,
    UserActivity,
    BotIndicator,
)

__all__ = [
    # Classes
    "MultiModalAnalyzer",
    "MetadataValidator",
    "DeepfakeDetector",
    "PropagandaDetector",
    "CognitiveBiasDetector",
    "NetworkAnalyzer",
    "BotDetector",
    # Data classes and enums
    "MediaType",
    "MediaItem", 
    "CrossModalResult",
    "MultiModalResult",
    "ConsistencyStatus",
    "ValidationResult",
    "MetadataType",
    "ValidationStatus",
    "DeepfakeResult",
    "DeepfakeStatus",
    "ArtifactType",
    "PropagandaResult",
    "PropagandaTechnique",
    "PropagandaStatus",
    "CognitiveBiasResult",
    "CognitiveBias",
    "CognitiveBiasStatus",
    "BiasInstance",
    "NetworkAnalysisResult",
    "NetworkNode",
    "NetworkEdge",
    "Community",
    "NetworkStatus",
    "NetworkType",
    "BotResult",
    "BotStatus",
    "BotDetectionMethod",
    "UserActivity",
    "BotIndicator",
]
