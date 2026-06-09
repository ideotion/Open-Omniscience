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
Tests for confidence_intervals.py module
Pillar 2: Scientific Rigor - Phase 2.1
"""

import numpy as np
import pandas as pd
import pytest

from src.analysis.confidence_intervals import (
    ConfidenceInterval,
    ConfidenceIntervals,
    ConfidenceLevel,
)


class TestConfidenceIntervals:
    """Test suite for ConfidenceIntervals class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ci_calc = ConfidenceIntervals()
        np.random.seed(42)

    def test_mean_ci_basic(self):
        """Test basic mean confidence interval."""
        data = np.random.normal(5, 1, 100)

        ci = self.ci_calc.mean_ci(data, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.confidence_level == 0.95
        assert ci.method == "t-distribution"
        assert ci.estimate == pytest.approx(np.mean(data), abs=0.01)
        assert ci.lower < ci.estimate < ci.upper
        assert ci.sample_size == 100
        assert ci.degrees_of_freedom == 99

    def test_mean_ci_normal(self):
        """Test mean CI with normal distribution."""
        data = np.random.normal(5, 1, 100)

        ci = self.ci_calc.mean_ci_normal(data, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Normal (z)"

    def test_mean_ci_t(self):
        """Test mean CI with t-distribution."""
        data = np.random.normal(5, 1, 30)  # Small sample

        ci = self.ci_calc.mean_ci_t(data, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "t-distribution"

    def test_mean_ci_with_population_std(self):
        """Test mean CI with known population standard deviation."""
        data = np.random.normal(5, 1, 100)

        ci = self.ci_calc.mean_ci(data, confidence_level=0.95, population_std=1.0)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Normal (z)"

    def test_proportion_ci_wald(self):
        """Test Wald confidence interval for proportion."""
        successes = 50
        trials = 100

        ci = self.ci_calc.proportion_ci_wald(successes, trials, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.estimate == 0.5
        assert ci.method == "Wald"
        assert 0 <= ci.lower <= ci.estimate <= ci.upper <= 1
        assert ci.sample_size == 100

    def test_proportion_ci_wilson(self):
        """Test Wilson confidence interval for proportion."""
        successes = 50
        trials = 100

        ci = self.ci_calc.proportion_ci_wilson(successes, trials, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.estimate == 0.5
        assert ci.method == "Wilson"
        assert 0 <= ci.lower <= ci.estimate <= ci.upper <= 1

    def test_proportion_ci_clopper_pearson(self):
        """Test Clopper-Pearson confidence interval for proportion."""
        successes = 50
        trials = 100

        ci = self.ci_calc.proportion_ci_clopper_pearson(successes, trials, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.estimate == 0.5
        assert ci.method == "Clopper-Pearson (exact)"
        assert 0 <= ci.lower <= ci.estimate <= ci.upper <= 1

    def test_proportion_ci_agresti_coull(self):
        """Test Agresti-Coull confidence interval for proportion."""
        successes = 50
        trials = 100

        ci = self.ci_calc.proportion_ci_agresti_coull(successes, trials, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.estimate == 0.5
        assert ci.method == "Agresti-Coull"
        assert 0 <= ci.lower <= ci.estimate <= ci.upper <= 1

    def test_proportion_ci_edge_cases(self):
        """Test proportion CI with edge cases."""
        # Test with 0 successes
        ci_zero = self.ci_calc.proportion_ci_wald(0, 100, confidence_level=0.95)
        assert ci_zero.estimate == 0
        assert ci_zero.lower == 0

        # Test with all successes
        ci_all = self.ci_calc.proportion_ci_wald(100, 100, confidence_level=0.95)
        assert ci_all.estimate == 1
        assert ci_all.upper == 1

    def test_proportion_ci_invalid_input(self):
        """Test that invalid inputs raise errors."""
        with pytest.raises(ValueError, match="successes .* must be between 0 and trials"):
            self.ci_calc.proportion_ci_wald(101, 100)

        with pytest.raises(ValueError, match="successes .* must be between 0 and trials"):
            self.ci_calc.proportion_ci_wald(-1, 100)

    def test_diff_means_ci(self):
        """Test confidence interval for difference between means."""
        sample1 = np.random.normal(5, 1, 100)
        sample2 = np.random.normal(6, 1, 100)

        ci = self.ci_calc.diff_means_ci(sample1, sample2, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Difference of means (t)"
        assert ci.estimate == pytest.approx(np.mean(sample1) - np.mean(sample2), abs=0.1)
        assert ci.sample_size == 200

    def test_diff_means_ci_unequal_var(self):
        """Test difference of means CI with unequal variances."""
        sample1 = np.random.normal(5, 1, 50)
        sample2 = np.random.normal(6, 2, 50)

        ci = self.ci_calc.diff_means_ci(sample1, sample2, confidence_level=0.95, equal_var=False)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Difference of means (t)"

    def test_diff_proportions_ci(self):
        """Test confidence interval for difference between proportions."""
        successes1 = 60
        trials1 = 100
        successes2 = 40
        trials2 = 100

        ci = self.ci_calc.diff_proportions_ci(
            successes1, trials1, successes2, trials2, confidence_level=0.95
        )

        assert isinstance(ci, ConfidenceInterval)
        assert ci.estimate == pytest.approx(0.2, abs=0.0001)  # 0.6 - 0.4
        assert ci.method == "Difference of proportions (Wald)"
        assert ci.sample_size == 200

    def test_variance_ci(self):
        """Test confidence interval for variance."""
        data = np.random.normal(5, 2, 100)

        ci = self.ci_calc.variance_ci(data, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Chi-square"
        assert ci.estimate == pytest.approx(np.var(data, ddof=1), abs=0.1)
        assert ci.degrees_of_freedom == 99

    def test_std_dev_ci(self):
        """Test confidence interval for standard deviation."""
        data = np.random.normal(5, 2, 100)

        ci = self.ci_calc.std_dev_ci(data, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Chi-square (sqrt)"
        assert ci.estimate == pytest.approx(np.std(data, ddof=1), abs=0.1)

    def test_regression_slope_ci(self):
        """Test confidence interval for regression slope."""
        x = np.random.normal(0, 1, 100)
        y = 2 * x + 3 + np.random.normal(0, 0.5, 100)

        ci = self.ci_calc.regression_slope_ci(x, y, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Regression slope (t)"
        assert ci.estimate == pytest.approx(2, abs=0.5)
        assert ci.degrees_of_freedom == 98

    def test_regression_slope_ci_too_few_points(self):
        """Test that regression slope CI raises error with too few points."""
        x = [1, 2]
        y = [1, 2]

        with pytest.raises(ValueError, match="At least 3 data points required"):
            self.ci_calc.regression_slope_ci(x, y)

    def test_regression_prediction_ci(self):
        """Test confidence interval for regression prediction."""
        x = np.random.normal(0, 1, 100)
        y = 2 * x + 3 + np.random.normal(0, 0.5, 100)

        ci = self.ci_calc.regression_prediction_ci(x, y, x_new=0, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Regression prediction (t)"
        assert ci.degrees_of_freedom == 98

    def test_odds_ratio_ci(self):
        """Test confidence interval for odds ratio."""
        # 2x2 table: a=exposed cases, b=exposed controls, c=unexposed cases, d=unexposed controls
        a, b, c, d = 10, 20, 5, 30

        ci = self.ci_calc.odds_ratio_ci(a, b, c, d, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Odds ratio (Wald)"
        # OR = (10*30)/(20*5) = 3
        assert ci.estimate == 3.0
        assert ci.sample_size == 65

    def test_relative_risk_ci(self):
        """Test confidence interval for relative risk."""
        # 2x2 table
        a, b, c, d = 10, 20, 5, 30

        ci = self.ci_calc.relative_risk_ci(a, b, c, d, confidence_level=0.95)

        assert isinstance(ci, ConfidenceInterval)
        assert ci.method == "Relative risk (Wald)"
        # RR = (10/30)/(5/35) = (1/3)/(1/7) = 7/3 ≈ 2.333
        assert ci.estimate == pytest.approx(7 / 3, abs=0.01)
        assert ci.sample_size == 65

    def test_batch_mean_ci(self):
        """Test batch processing of mean confidence intervals."""
        data = np.random.normal(5, 1, 100)

        results = self.ci_calc.batch_mean_ci(data, [0.90, 0.95, 0.99])

        assert isinstance(results, dict)
        assert len(results) == 3
        assert 0.90 in results
        assert 0.95 in results
        assert 0.99 in results

        for cl, ci in results.items():
            assert isinstance(ci, ConfidenceInterval)
            assert ci.confidence_level == cl

    def test_batch_proportion_ci(self):
        """Test batch processing of proportion confidence intervals."""
        successes = 50
        trials = 100

        results = self.ci_calc.batch_proportion_ci(
            successes, trials, [0.90, 0.95, 0.99], method="wilson"
        )

        assert isinstance(results, dict)
        assert len(results) == 3

        for cl, ci in results.items():
            assert isinstance(ci, ConfidenceInterval)
            assert ci.confidence_level == cl
            assert ci.method == "Wilson"

    def test_batch_proportion_ci_invalid_method(self):
        """Test that invalid method raises error."""
        with pytest.raises(ValueError, match="Unknown method"):
            self.ci_calc.batch_proportion_ci(50, 100, [0.95], method="invalid")


class TestConfidenceInterval:
    """Test suite for ConfidenceInterval dataclass."""

    def test_width(self):
        """Test width calculation."""
        ci = ConfidenceInterval(
            estimate=5.0, lower=4.0, upper=6.0, confidence_level=0.95, method="Test"
        )

        assert ci.width() == 2.0

    def test_contains(self):
        """Test contains method."""
        ci = ConfidenceInterval(
            estimate=5.0, lower=4.0, upper=6.0, confidence_level=0.95, method="Test"
        )

        assert ci.contains(5.0) is True
        assert ci.contains(4.5) is True
        assert ci.contains(4.0) is True
        assert ci.contains(6.0) is True
        assert ci.contains(3.9) is False
        assert ci.contains(6.1) is False

    def test_to_dict(self):
        """Test to_dict method."""
        ci = ConfidenceInterval(
            estimate=5.0,
            lower=4.0,
            upper=6.0,
            confidence_level=0.95,
            method="Test",
            standard_error=0.5,
            degrees_of_freedom=10,
            sample_size=100,
        )

        d = ci.to_dict()

        assert isinstance(d, dict)
        assert d["estimate"] == 5.0
        assert d["lower"] == 4.0
        assert d["upper"] == 6.0
        assert d["confidence_level"] == 0.95
        assert d["method"] == "Test"
        assert d["standard_error"] == 0.5
        assert d["degrees_of_freedom"] == 10
        assert d["sample_size"] == 100
        assert "margin_of_error" in d

    def test_repr(self):
        """Test repr method."""
        ci = ConfidenceInterval(
            estimate=5.0, lower=4.0, upper=6.0, confidence_level=0.95, method="Test"
        )

        repr_str = repr(ci)

        assert "5.0" in repr_str
        assert "4.0" in repr_str
        assert "6.0" in repr_str
        assert "95%" in repr_str
        assert "Test" in repr_str


class TestConfidenceLevel:
    """Test suite for ConfidenceLevel enum."""

    def test_ci_90(self):
        """Test 90% confidence level."""
        assert ConfidenceLevel.CI_90.value == 0.90

    def test_ci_95(self):
        """Test 95% confidence level."""
        assert ConfidenceLevel.CI_95.value == 0.95

    def test_ci_99(self):
        """Test 99% confidence level."""
        assert ConfidenceLevel.CI_99.value == 0.99


class TestInputTypes:
    """Test that functions accept various input types."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ci_calc = ConfidenceIntervals()

    def test_list_input(self):
        """Test with list inputs."""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        ci = self.ci_calc.mean_ci(data)
        assert isinstance(ci, ConfidenceInterval)

    def test_numpy_array_input(self):
        """Test with numpy array inputs."""
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

        ci = self.ci_calc.mean_ci(data)
        assert isinstance(ci, ConfidenceInterval)

    def test_pandas_series_input(self):
        """Test with pandas Series inputs."""
        data = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

        ci = self.ci_calc.mean_ci(data)
        assert isinstance(ci, ConfidenceInterval)


class TestSummarizeCI:
    """Test the summarize_ci method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ci_calc = ConfidenceIntervals()

    def test_summarize_ci(self):
        """Test CI summarization."""
        ci = ConfidenceInterval(
            estimate=5.0, lower=4.5, upper=5.5, confidence_level=0.95, method="Test"
        )

        summary = self.ci_calc.summarize_ci(ci, decimal_places=2)

        assert isinstance(summary, str)
        assert "5.00" in summary
        assert "4.50" in summary
        assert "5.50" in summary
        assert "95%" in summary
        assert "Test" in summary
