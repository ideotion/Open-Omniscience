"""
Statistical Analysis Module for Open-Omniscience
Pillar 2: Scientific Rigor

This module provides comprehensive statistical validation capabilities including:
- Statistical tests (t-tests, chi-square, ANOVA, regression)
- Confidence intervals (means, proportions, variances, regression coefficients)
- Peer-review simulation (Ollama-based)
- Consensus scoring
- Reproducibility scoring

All functions work offline with 100% FOSS tools.
"""

from .statistical_tests import (
    StatisticalTests,
    TestResult,
    t_test_independent,
    t_test_paired,
    one_way_anova,
    chi_square_independence,
    pearson_correlation,
    linear_regression,
)

from .confidence_intervals import (
    ConfidenceIntervals,
    ConfidenceInterval,
    ConfidenceLevel,
)

# Phase 2.2: Peer-Review Simulation
from .peer_review import (
    PeerReviewSimulator,
    PeerReviewSession,
    ReviewResult,
    BlindReview,
    ReviewStatus,
    ReviewDecision,
)

# Phase 2.2: Consensus Scoring
from .consensus import (
    ConsensusCalculator,
    ConsensusResult,
)

# Phase 2.3: Reproducibility Scoring
from .reproducibility import (
    ReproducibilityCalculator,
    ReproducibilityScore,
    DataLineageTracker,
    DataLineage,
    DataSourceType,
)

__version__ = "0.2.0"
__author__ = "Open-Omniscience"
