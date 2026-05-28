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

Note: Using lazy imports to avoid MemoryError with networkx in Python 3.12
"""


__all__ = [
    # Classes
    "MultiModalAnalyzer",
    "MetadataValidator",
    "DeepfakeDetector",
    "PropagandaDetector",
    "CognitiveBiasDetector",
    "NetworkAnalyzer",
    "BotDetector",
    # Data classes and enums from multimodal
    "MediaType",
    "MediaItem", 
    "CrossModalResult",
    "MultiModalResult",
    "ConsistencyStatus",
    # Data classes and enums from metadata_validator
    "ValidationResult",
    "MetadataType",
    "ValidationStatus",
    # Data classes and enums from deepfake_detector
    "DeepfakeResult",
    "DeepfakeStatus",
    "ArtifactType",
    # Data classes and enums from propaganda
    "PropagandaResult",
    "PropagandaTechnique",
    "PropagandaStatus",
    # Data classes and enums from cognitive_bias
    "CognitiveBiasResult",
    "CognitiveBias",
    "CognitiveBiasStatus",
    "BiasInstance",
    # Data classes and enums from network_analyzer
    "NetworkAnalysisResult",
    "NetworkNode",
    "NetworkEdge",
    "Community",
    "NetworkStatus",
    "NetworkType",
    # Data classes and enums from bot_detector
    "BotResult",
    "BotStatus",
    "BotDetectionMethod",
    "UserActivity",
    "BotIndicator",
]


def __getattr__(name):
    """Lazy import for analysis modules and data classes to avoid MemoryError."""
    # Classes
    if name == "MultiModalAnalyzer":
        from .multimodal import MultiModalAnalyzer
        return MultiModalAnalyzer
    elif name == "MetadataValidator":
        from .metadata_validator import MetadataValidator
        return MetadataValidator
    elif name == "DeepfakeDetector":
        from .deepfake_detector import DeepfakeDetector
        return DeepfakeDetector
    elif name == "PropagandaDetector":
        from .propaganda import PropagandaDetector
        return PropagandaDetector
    elif name == "CognitiveBiasDetector":
        from .cognitive_bias import CognitiveBiasDetector
        return CognitiveBiasDetector
    elif name == "NetworkAnalyzer":
        from .network_analyzer import NetworkAnalyzer
        return NetworkAnalyzer
    elif name == "BotDetector":
        from .bot_detector import BotDetector
        return BotDetector
    # Data classes and enums from multimodal
    elif name == "MediaType":
        from .multimodal import MediaType
        return MediaType
    elif name == "MediaItem":
        from .multimodal import MediaItem
        return MediaItem
    elif name == "CrossModalResult":
        from .multimodal import CrossModalResult
        return CrossModalResult
    elif name == "MultiModalResult":
        from .multimodal import MultiModalResult
        return MultiModalResult
    elif name == "ConsistencyStatus":
        from .multimodal import ConsistencyStatus
        return ConsistencyStatus
    # Data classes and enums from metadata_validator
    elif name == "ValidationResult":
        from .metadata_validator import ValidationResult
        return ValidationResult
    elif name == "MetadataType":
        from .metadata_validator import MetadataType
        return MetadataType
    elif name == "ValidationStatus":
        from .metadata_validator import ValidationStatus
        return ValidationStatus
    # Data classes and enums from deepfake_detector
    elif name == "DeepfakeResult":
        from .deepfake_detector import DeepfakeResult
        return DeepfakeResult
    elif name == "DeepfakeStatus":
        from .deepfake_detector import DeepfakeStatus
        return DeepfakeStatus
    elif name == "ArtifactType":
        from .deepfake_detector import ArtifactType
        return ArtifactType
    # Data classes and enums from propaganda
    elif name == "PropagandaResult":
        from .propaganda import PropagandaResult
        return PropagandaResult
    elif name == "PropagandaTechnique":
        from .propaganda import PropagandaTechnique
        return PropagandaTechnique
    elif name == "PropagandaStatus":
        from .propaganda import PropagandaStatus
        return PropagandaStatus
    # Data classes and enums from cognitive_bias
    elif name == "CognitiveBiasResult":
        from .cognitive_bias import CognitiveBiasResult
        return CognitiveBiasResult
    elif name == "CognitiveBias":
        from .cognitive_bias import CognitiveBias
        return CognitiveBias
    elif name == "CognitiveBiasStatus":
        from .cognitive_bias import CognitiveBiasStatus
        return CognitiveBiasStatus
    elif name == "BiasInstance":
        from .cognitive_bias import BiasInstance
        return BiasInstance
    # Data classes and enums from network_analyzer
    elif name == "NetworkAnalysisResult":
        from .network_analyzer import NetworkAnalysisResult
        return NetworkAnalysisResult
    elif name == "NetworkNode":
        from .network_analyzer import NetworkNode
        return NetworkNode
    elif name == "NetworkEdge":
        from .network_analyzer import NetworkEdge
        return NetworkEdge
    elif name == "Community":
        from .network_analyzer import Community
        return Community
    elif name == "NetworkStatus":
        from .network_analyzer import NetworkStatus
        return NetworkStatus
    elif name == "NetworkType":
        from .network_analyzer import NetworkType
        return NetworkType
    # Data classes and enums from bot_detector
    elif name == "BotResult":
        from .bot_detector import BotResult
        return BotResult
    elif name == "BotStatus":
        from .bot_detector import BotStatus
        return BotStatus
    elif name == "BotDetectionMethod":
        from .bot_detector import BotDetectionMethod
        return BotDetectionMethod
    elif name == "UserActivity":
        from .bot_detector import UserActivity
        return UserActivity
    elif name == "BotIndicator":
        from .bot_detector import BotIndicator
        return BotIndicator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
