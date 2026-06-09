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
Confidence Intervals Module for Open-Omniscience
Pillar 2: Scientific Rigor - Phase 2.1

Implements confidence interval calculations for various statistical measures
using scipy.stats, statsmodels, and numpy.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

# Try to import required libraries
try:
    import scipy.stats as stats
    from scipy.stats import chi2, norm, sem
    from scipy.stats import f as f_dist
    from scipy.stats import t as t_dist

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import statsmodels.api as sm
    from statsmodels.stats.proportion import proportion_confint
    from statsmodels.stats.weightstats import DescrStatsW

    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


class ConfidenceLevel(Enum):
    """Standard confidence levels."""

    CI_90 = 0.90
    CI_95 = 0.95
    CI_99 = 0.99


@dataclass
class ConfidenceInterval:
    """Container for confidence interval results."""

    estimate: float
    lower: float
    upper: float
    confidence_level: float
    method: str
    standard_error: float | None = None
    degrees_of_freedom: float | None = None
    sample_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "confidence_level": self.confidence_level,
            "method": self.method,
            "standard_error": self.standard_error,
            "degrees_of_freedom": self.degrees_of_freedom,
            "sample_size": self.sample_size,
            "margin_of_error": self.upper - self.estimate,
        }

    def width(self) -> float:
        """Calculate the width of the confidence interval."""
        return self.upper - self.lower

    def contains(self, value: float) -> bool:
        """Check if a value is within the confidence interval."""
        return self.lower <= value <= self.upper

    def __repr__(self) -> str:
        return (
            f"ConfidenceInterval({self.estimate:.4f} [{self.lower:.4f}, {self.upper:.4f}] "
            f"@ {self.confidence_level * 100:.0f}% CI, {self.method})"
        )


class ConfidenceIntervals:
    """
    Comprehensive confidence interval calculator.

    Implements confidence intervals for:
    - Means (normal and t-distribution)
    - Proportions (Wald, Wilson, Clopper-Pearson)
    - Variances
    - Differences between means
    - Regression coefficients
    - Odds ratios and relative risks
    """

    def __init__(self):
        """Initialize the confidence interval calculator."""
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        """Check that required dependencies are available."""
        if not HAS_SCIPY:
            raise ImportError(
                "scipy is required for confidence intervals. Install with: pip install scipy"
            )

    def _get_critical_value(
        self, distribution: str, confidence_level: float, df: float | None = None
    ) -> float:
        """
        Get critical value for a given distribution and confidence level.

        Args:
            distribution: 'normal', 't', 'chi2', or 'f'
            confidence_level: Confidence level (e.g., 0.95)
            df: Degrees of freedom (for t, chi2, f distributions)

        Returns:
            Critical value for two-tailed test
        """
        alpha = 1 - confidence_level

        if distribution == "normal":
            return norm.ppf(1 - alpha / 2)
        elif distribution == "t":
            if df is None:
                raise ValueError("Degrees of freedom required for t-distribution")
            return t_dist.ppf(1 - alpha / 2, df=df)
        elif distribution == "chi2":
            if df is None:
                raise ValueError("Degrees of freedom required for chi2-distribution")
            return chi2.ppf(1 - alpha / 2, df=df)
        elif distribution == "f":
            if df is None:
                raise ValueError("Degrees of freedom required for f-distribution")
            return f_dist.ppf(1 - alpha / 2, *df)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")

    # ==================== MEAN CONFIDENCE INTERVALS ====================

    def mean_ci(
        self,
        data: list | np.ndarray | pd.Series,
        confidence_level: float = 0.95,
        population_std: float | None = None,
    ) -> ConfidenceInterval:
        """
        Confidence interval for the population mean.

        Uses t-distribution if population standard deviation is unknown
        (which is almost always the case in practice).

        Args:
            data: Sample data
            confidence_level: Confidence level (default: 0.95)
            population_std: Known population standard deviation (optional)

        Returns:
            ConfidenceInterval for the mean
        """
        arr = self._to_array(data)
        n = len(arr)
        sample_mean = np.mean(arr)

        if population_std is not None:
            # Use normal distribution (z-test)
            std_err = population_std / np.sqrt(n)
            critical = self._get_critical_value("normal", confidence_level)
            method = "Normal (z)"
            df = None
        else:
            # Use t-distribution
            sample_std = np.std(arr, ddof=1)
            std_err = sample_std / np.sqrt(n)
            critical = self._get_critical_value("t", confidence_level, df=n - 1)
            method = "t-distribution"
            df = n - 1

        margin = critical * std_err

        return ConfidenceInterval(
            estimate=sample_mean,
            lower=sample_mean - margin,
            upper=sample_mean + margin,
            confidence_level=confidence_level,
            method=method,
            standard_error=std_err,
            degrees_of_freedom=df,
            sample_size=n,
        )

    def mean_ci_normal(
        self, data: list | np.ndarray | pd.Series, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for mean using normal distribution.

        Assumes population standard deviation is known or sample size is large.

        Args:
            data: Sample data
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the mean
        """
        return self.mean_ci(data, confidence_level, population_std=np.std(data, ddof=1))

    def mean_ci_t(
        self, data: list | np.ndarray | pd.Series, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for mean using t-distribution.

        For small samples or when population standard deviation is unknown.

        Args:
            data: Sample data
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the mean
        """
        return self.mean_ci(data, confidence_level, population_std=None)

    # ==================== PROPORTION CONFIDENCE INTERVALS ====================

    def proportion_ci_wald(
        self, successes: int, trials: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Wald confidence interval for a proportion.

        Simple and fast, but can be inaccurate for small samples or extreme proportions.

        Args:
            successes: Number of successes
            trials: Total number of trials
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the proportion
        """
        if not (0 <= successes <= trials):
            raise ValueError(f"successes ({successes}) must be between 0 and trials ({trials})")

        p_hat = successes / trials
        critical = self._get_critical_value("normal", confidence_level)

        # Standard error
        std_err = np.sqrt(p_hat * (1 - p_hat) / trials)

        # Margin of error
        margin = critical * std_err

        return ConfidenceInterval(
            estimate=p_hat,
            lower=max(0, p_hat - margin),
            upper=min(1, p_hat + margin),
            confidence_level=confidence_level,
            method="Wald",
            standard_error=std_err,
            sample_size=trials,
        )

    def proportion_ci_wilson(
        self, successes: int, trials: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Wilson score confidence interval for a proportion.

        More accurate than Wald, especially for small samples or extreme proportions.

        Args:
            successes: Number of successes
            trials: Total number of trials
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the proportion
        """
        if not (0 <= successes <= trials):
            raise ValueError(f"successes ({successes}) must be between 0 and trials ({trials})")

        p_hat = successes / trials
        critical = self._get_critical_value("normal", confidence_level)

        # Wilson score interval
        z2 = critical**2
        numerator = (
            p_hat
            + z2 / (2 * trials)
            - critical * np.sqrt((p_hat * (1 - p_hat) + z2 / (4 * trials)) / trials)
        )
        denominator = 1 + z2 / trials

        lower = numerator / denominator
        upper = (
            p_hat
            + z2 / (2 * trials)
            + critical * np.sqrt((p_hat * (1 - p_hat) + z2 / (4 * trials)) / trials)
        ) / denominator

        return ConfidenceInterval(
            estimate=p_hat,
            lower=max(0, lower),
            upper=min(1, upper),
            confidence_level=confidence_level,
            method="Wilson",
            sample_size=trials,
        )

    def proportion_ci_clopper_pearson(
        self, successes: int, trials: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Clopper-Pearson (exact) confidence interval for a proportion.

        Most accurate but computationally intensive. Uses beta distribution.

        Args:
            successes: Number of successes
            trials: Total number of trials
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the proportion
        """
        if not (0 <= successes <= trials):
            raise ValueError(f"successes ({successes}) must be between 0 and trials ({trials})")

        if HAS_STATSMODELS:
            lower, upper = proportion_confint(
                successes, trials, alpha=1 - confidence_level, method="beta"
            )
        else:
            # Fallback implementation using scipy
            alpha = 1 - confidence_level
            lower = stats.beta.ppf(alpha / 2, successes, trials - successes + 1)
            upper = stats.beta.ppf(1 - alpha / 2, successes + 1, trials - successes)

        p_hat = successes / trials if trials > 0 else 0

        return ConfidenceInterval(
            estimate=p_hat,
            lower=float(lower),
            upper=float(upper),
            confidence_level=confidence_level,
            method="Clopper-Pearson (exact)",
            sample_size=trials,
        )

    def proportion_ci_agresti_coull(
        self, successes: int, trials: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Agresti-Coull confidence interval for a proportion.

        Improved version of Wald that adds pseudo-observations.

        Args:
            successes: Number of successes
            trials: Total number of trials
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the proportion
        """
        if not (0 <= successes <= trials):
            raise ValueError(f"successes ({successes}) must be between 0 and trials ({trials})")

        critical = self._get_critical_value("normal", confidence_level)
        z2 = critical**2

        # Adjusted proportion
        p_tilde = (successes + z2 / 2) / (trials + z2)

        # Standard error
        std_err = np.sqrt(p_tilde * (1 - p_tilde) / (trials + z2))

        # Margin of error
        margin = critical * std_err

        return ConfidenceInterval(
            estimate=successes / trials if trials > 0 else 0,
            lower=max(0, p_tilde - margin),
            upper=min(1, p_tilde + margin),
            confidence_level=confidence_level,
            method="Agresti-Coull",
            standard_error=std_err,
            sample_size=trials,
        )

    # ==================== DIFFERENCE CONFIDENCE INTERVALS ====================

    def diff_means_ci(
        self,
        sample1: list | np.ndarray | pd.Series,
        sample2: list | np.ndarray | pd.Series,
        confidence_level: float = 0.95,
        equal_var: bool = True,
    ) -> ConfidenceInterval:
        """
        Confidence interval for the difference between two means.

        Args:
            sample1: First sample
            sample2: Second sample
            confidence_level: Confidence level (default: 0.95)
            equal_var: If True, assume equal variances (default: True)

        Returns:
            ConfidenceInterval for the difference in means
        """
        arr1 = self._to_array(sample1)
        arr2 = self._to_array(sample2)

        n1, n2 = len(arr1), len(arr2)
        mean1, mean2 = np.mean(arr1), np.mean(arr2)
        diff = mean1 - mean2

        if equal_var:
            # Pooled variance
            var1, var2 = np.var(arr1, ddof=1), np.var(arr2, ddof=1)
            pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
            std_err = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
            df = n1 + n2 - 2
        else:
            # Welch-Satterthwaite
            var1, var2 = np.var(arr1, ddof=1), np.var(arr2, ddof=1)
            std_err = np.sqrt(var1 / n1 + var2 / n2)
            # Degrees of freedom
            df = ((var1 / n1 + var2 / n2) ** 2) / (
                (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
            )

        critical = self._get_critical_value("t", confidence_level, df=df)
        margin = critical * std_err

        return ConfidenceInterval(
            estimate=diff,
            lower=diff - margin,
            upper=diff + margin,
            confidence_level=confidence_level,
            method="Difference of means (t)",
            standard_error=std_err,
            degrees_of_freedom=df,
            sample_size=n1 + n2,
        )

    def diff_proportions_ci(
        self,
        successes1: int,
        trials1: int,
        successes2: int,
        trials2: int,
        confidence_level: float = 0.95,
    ) -> ConfidenceInterval:
        """
        Confidence interval for the difference between two proportions.

        Uses Wald method for the difference.

        Args:
            successes1: Successes in first group
            trials1: Trials in first group
            successes2: Successes in second group
            trials2: Trials in second group
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the difference in proportions
        """
        p1 = successes1 / trials1
        p2 = successes2 / trials2
        diff = p1 - p2

        # Pooled proportion
        p_pooled = (successes1 + successes2) / (trials1 + trials2)

        # Standard error
        std_err = np.sqrt(p_pooled * (1 - p_pooled) * (1 / trials1 + 1 / trials2))

        critical = self._get_critical_value("normal", confidence_level)
        margin = critical * std_err

        return ConfidenceInterval(
            estimate=diff,
            lower=diff - margin,
            upper=diff + margin,
            confidence_level=confidence_level,
            method="Difference of proportions (Wald)",
            standard_error=std_err,
            sample_size=trials1 + trials2,
        )

    # ==================== VARIANCE CONFIDENCE INTERVALS ====================

    def variance_ci(
        self, data: list | np.ndarray | pd.Series, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for the population variance.

        Uses chi-square distribution.

        Args:
            data: Sample data
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the variance
        """
        arr = self._to_array(data)
        n = len(arr)
        sample_var = np.var(arr, ddof=1)

        alpha = 1 - confidence_level
        lower_crit = chi2.ppf(alpha / 2, df=n - 1)
        upper_crit = chi2.ppf(1 - alpha / 2, df=n - 1)

        lower = (n - 1) * sample_var / upper_crit
        upper = (n - 1) * sample_var / lower_crit

        return ConfidenceInterval(
            estimate=sample_var,
            lower=lower,
            upper=upper,
            confidence_level=confidence_level,
            method="Chi-square",
            degrees_of_freedom=n - 1,
            sample_size=n,
        )

    def std_dev_ci(
        self, data: list | np.ndarray | pd.Series, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for the population standard deviation.

        Args:
            data: Sample data
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the standard deviation
        """
        var_ci = self.variance_ci(data, confidence_level)

        return ConfidenceInterval(
            estimate=np.sqrt(var_ci.estimate),
            lower=np.sqrt(var_ci.lower),
            upper=np.sqrt(var_ci.upper),
            confidence_level=confidence_level,
            method="Chi-square (sqrt)",
            degrees_of_freedom=var_ci.degrees_of_freedom,
            sample_size=var_ci.sample_size,
        )

    # ==================== REGRESSION CONFIDENCE INTERVALS ====================

    def regression_slope_ci(
        self,
        x: list | np.ndarray | pd.Series,
        y: list | np.ndarray | pd.Series,
        confidence_level: float = 0.95,
    ) -> ConfidenceInterval:
        """
        Confidence interval for the slope in simple linear regression.

        Args:
            x: Independent variable
            y: Dependent variable
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the regression slope
        """
        x_arr = self._to_array(x)
        y_arr = self._to_array(y)

        n = len(x_arr)
        if n < 3:
            raise ValueError("At least 3 data points required for regression")

        # Calculate regression statistics
        x_mean = np.mean(x_arr)
        y_mean = np.mean(y_arr)

        ss_xx = np.sum((x_arr - x_mean) ** 2)
        ss_xy = np.sum((x_arr - x_mean) * (y_arr - y_mean))

        slope = ss_xy / ss_xx

        # Calculate standard error of slope
        y_pred = slope * (x_arr - x_mean) + y_mean
        residuals = y_arr - y_pred
        ss_res = np.sum(residuals**2)

        mse = ss_res / (n - 2)
        se_slope = np.sqrt(mse / ss_xx)

        # Critical value
        critical = self._get_critical_value("t", confidence_level, df=n - 2)
        margin = critical * se_slope

        return ConfidenceInterval(
            estimate=slope,
            lower=slope - margin,
            upper=slope + margin,
            confidence_level=confidence_level,
            method="Regression slope (t)",
            standard_error=se_slope,
            degrees_of_freedom=n - 2,
            sample_size=n,
        )

    def regression_prediction_ci(
        self,
        x: list | np.ndarray | pd.Series,
        y: list | np.ndarray | pd.Series,
        x_new: float,
        confidence_level: float = 0.95,
    ) -> ConfidenceInterval:
        """
        Confidence interval for a prediction from simple linear regression.

        Args:
            x: Independent variable (training data)
            y: Dependent variable (training data)
            x_new: New x value to predict at
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the predicted y value
        """
        x_arr = self._to_array(x)
        y_arr = self._to_array(y)

        n = len(x_arr)
        if n < 3:
            raise ValueError("At least 3 data points required for regression")

        # Calculate regression coefficients
        slope, intercept, _, _, std_err = stats.linregress(x_arr, y_arr)

        # Calculate mean of x
        x_mean = np.mean(x_arr)

        # Calculate standard error of prediction
        x_diff = x_new - x_mean
        ss_xx = np.sum((x_arr - x_mean) ** 2)

        se_pred = std_err * np.sqrt(1 + 1 / n + x_diff**2 / ss_xx)

        # Critical value
        critical = self._get_critical_value("t", confidence_level, df=n - 2)
        margin = critical * se_pred

        # Predicted value
        y_pred = intercept + slope * x_new

        return ConfidenceInterval(
            estimate=y_pred,
            lower=y_pred - margin,
            upper=y_pred + margin,
            confidence_level=confidence_level,
            method="Regression prediction (t)",
            standard_error=se_pred,
            degrees_of_freedom=n - 2,
            sample_size=n,
        )

    # ==================== ODDS RATIO AND RELATIVE RISK ====================

    def odds_ratio_ci(
        self, a: int, b: int, c: int, d: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for odds ratio (2x2 contingency table).

        Args:
            a: Number of exposed cases
            b: Number of exposed controls
            c: Number of unexposed cases
            d: Number of unexposed controls
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the odds ratio
        """
        # Haldane-Anscombe continuity correction: add 0.5 to all cells when any
        # cell is zero. Without it, 1/a + 1/b + 1/c + 1/d raises ZeroDivisionError
        # (and OR/SE are undefined) for the common zero-cell case.
        if min(a, b, c, d) == 0:
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5

        or_estimate = (a * d) / (b * c)
        se_log_or = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)

        # Critical value
        critical = self._get_critical_value("normal", confidence_level)

        # Confidence interval for log(OR)
        log_or = np.log(or_estimate) if or_estimate != float("inf") else float("inf")
        lower_log = log_or - critical * se_log_or
        upper_log = log_or + critical * se_log_or

        # Exponentiate to get OR confidence interval
        lower = np.exp(lower_log)
        upper = np.exp(upper_log)

        return ConfidenceInterval(
            estimate=or_estimate,
            lower=lower,
            upper=upper,
            confidence_level=confidence_level,
            method="Odds ratio (Wald)",
            sample_size=a + b + c + d,
        )

    def relative_risk_ci(
        self, a: int, b: int, c: int, d: int, confidence_level: float = 0.95
    ) -> ConfidenceInterval:
        """
        Confidence interval for relative risk (2x2 contingency table).

        Args:
            a: Number of exposed cases
            b: Number of exposed controls
            c: Number of unexposed cases
            d: Number of unexposed controls
            confidence_level: Confidence level (default: 0.95)

        Returns:
            ConfidenceInterval for the relative risk
        """
        # Continuity correction for zero cells (see odds_ratio_ci).
        if min(a, b, c, d) == 0:
            a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5

        rr_estimate = (a / (a + b)) / (c / (c + d))
        se_log_rr = np.sqrt((b / (a * (a + b))) + (d / (c * (c + d))))

        # Critical value
        critical = self._get_critical_value("normal", confidence_level)

        # Confidence interval for log(RR)
        log_rr = np.log(rr_estimate) if rr_estimate != float("inf") else float("inf")
        lower_log = log_rr - critical * se_log_rr
        upper_log = log_rr + critical * se_log_rr

        # Exponentiate to get RR confidence interval
        lower = np.exp(lower_log)
        upper = np.exp(upper_log)

        return ConfidenceInterval(
            estimate=rr_estimate,
            lower=lower,
            upper=upper,
            confidence_level=confidence_level,
            method="Relative risk (Wald)",
            sample_size=a + b + c + d,
        )

    # ==================== BATCH PROCESSING ====================

    def batch_mean_ci(
        self,
        data: list | np.ndarray | pd.Series,
        confidence_levels: tuple[float, ...] = (0.90, 0.95, 0.99),
    ) -> dict[float, ConfidenceInterval]:
        """
        Calculate mean confidence intervals for multiple confidence levels.

        Args:
            data: Sample data
            confidence_levels: List of confidence levels to calculate

        Returns:
            Dictionary mapping confidence levels to ConfidenceIntervals
        """
        return {cl: self.mean_ci(data, cl) for cl in confidence_levels}

    def batch_proportion_ci(
        self,
        successes: int,
        trials: int,
        confidence_levels: tuple[float, ...] = (0.90, 0.95, 0.99),
        method: str = "wilson",
    ) -> dict[float, ConfidenceInterval]:
        """
        Calculate proportion confidence intervals for multiple confidence levels.

        Args:
            successes: Number of successes
            trials: Total number of trials
            confidence_levels: List of confidence levels to calculate
            method: Method to use ('wald', 'wilson', 'clopper_pearson', 'agresti_coull')

        Returns:
            Dictionary mapping confidence levels to ConfidenceIntervals
        """
        method_map = {
            "wald": self.proportion_ci_wald,
            "wilson": self.proportion_ci_wilson,
            "clopper_pearson": self.proportion_ci_clopper_pearson,
            "agresti_coull": self.proportion_ci_agresti_coull,
        }

        if method not in method_map:
            raise ValueError(f"Unknown method: {method}. Choose from {list(method_map.keys())}")

        return {cl: method_map[method](successes, trials, cl) for cl in confidence_levels}

    # ==================== UTILITY METHODS ====================

    def _to_array(self, data: list | np.ndarray | pd.Series) -> np.ndarray:
        """Convert input to numpy array."""
        if isinstance(data, pd.Series):
            return data.values
        elif isinstance(data, np.ndarray):
            return data
        elif isinstance(data, list):
            return np.array(data)
        else:
            raise TypeError(f"Unsupported data type: {type(data)}")

    def summarize_ci(self, ci: ConfidenceInterval, decimal_places: int = 4) -> str:
        """
        Generate a human-readable summary of a confidence interval.

        Args:
            ci: ConfidenceInterval to summarize
            decimal_places: Number of decimal places (default: 4)

        Returns:
            Formatted string summary
        """
        fmt = f".{decimal_places}f"
        return (
            f"{ci.estimate:{fmt}} [{ci.lower:{fmt}}, {ci.upper:{fmt}}] "
            f"({ci.confidence_level * 100:.0f}% CI, {ci.method})"
        )
