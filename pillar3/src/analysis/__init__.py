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

STATUS (v0.4): The deepfake, propaganda, cognitive-bias, and bot detectors that
formerly lived here have been QUARANTINED to ``quarantine/pillar3_analysis/``
because their "detection" was fabricated -- e.g. the deepfake "CNN" loads ONNX
sessions but never runs inference and instead returns a blur/edge heuristic, and
the propaganda/bias detectors emit hardcoded confidence constants. Shipping them
as working forensics would be a serious liability for a journalism/legal tool.

What remains here still requires heavy optional dependencies and has NOT yet been
audited for honesty; treat as experimental until rebuilt. The genuinely useful,
honest piece to revive first is metadata/EXIF validation.

Lazy imports are retained to avoid importing heavy deps at module import time.
"""


__all__ = [
    "MultiModalAnalyzer",
    "MetadataValidator",
    "NetworkAnalyzer",
    # multimodal data classes / enums
    "MediaType",
    "MediaItem",
    "CrossModalResult",
    "MultiModalResult",
    "ConsistencyStatus",
    # metadata_validator data classes / enums
    "ValidationResult",
    "MetadataType",
    "ValidationStatus",
    # network_analyzer data classes / enums
    "NetworkAnalysisResult",
    "NetworkNode",
    "NetworkEdge",
    "Community",
    "NetworkStatus",
    "NetworkType",
]

# Names that were removed from this package in v0.4. Accessing them yields a clear
# explanation instead of an opaque AttributeError or, worse, a fabricated result.
_QUARANTINED = {
    "DeepfakeDetector",
    "DeepfakeResult",
    "DeepfakeStatus",
    "ArtifactType",
    "PropagandaDetector",
    "PropagandaResult",
    "PropagandaTechnique",
    "PropagandaStatus",
    "CognitiveBiasDetector",
    "CognitiveBiasResult",
    "CognitiveBias",
    "CognitiveBiasStatus",
    "BiasInstance",
    "BotDetector",
    "BotResult",
    "BotStatus",
    "BotDetectionMethod",
    "UserActivity",
    "BotIndicator",
}


def __getattr__(name):
    """Lazy import for the remaining (still-experimental) analysis modules."""
    if name in _QUARANTINED:
        raise AttributeError(
            f"{name!r} was quarantined in v0.4: its detection logic was fabricated "
            f"(see quarantine/pillar3_analysis/ and docs/SALVAGE_MAP.md). It must be "
            f"rebuilt with a real, evaluated model before it can be used again."
        )
    # MultiModalAnalyzer + multimodal data classes
    if name in {
        "MultiModalAnalyzer",
        "MediaType",
        "MediaItem",
        "CrossModalResult",
        "MultiModalResult",
        "ConsistencyStatus",
    }:
        import pillar3.src.analysis.multimodal as m
        return getattr(m, name)
    # MetadataValidator + data classes (the honest piece to revive first)
    if name in {"MetadataValidator", "ValidationResult", "MetadataType", "ValidationStatus"}:
        import pillar3.src.analysis.metadata_validator as m
        return getattr(m, name)
    # NetworkAnalyzer + data classes
    if name in {
        "NetworkAnalyzer",
        "NetworkAnalysisResult",
        "NetworkNode",
        "NetworkEdge",
        "Community",
        "NetworkStatus",
        "NetworkType",
    }:
        import pillar3.src.analysis.network_analyzer as m
        return getattr(m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
