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
