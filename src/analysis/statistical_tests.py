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
Statistical Validation Engine for Open-Omniscience
Pillar 2: Scientific Rigor - Phase 2.1

Implements statistical tests using scipy.stats, statsmodels, and pingouin.
All functions are designed to work offline with 100% FOSS tools.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd

# Try to import all required libraries
try:
    import scipy.stats as stats
    from scipy.stats import (
        chi2,
        chi2_contingency,
        f_oneway,
        kruskal,
        linregress,
        norm,
        pearsonr,
        spearmanr,
        ttest_1samp,
        ttest_ind,
        ttest_rel,
    )
    from scipy.stats import t as t_dist
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
    from statsmodels.stats.multicomp import pairwise_tukeyhsd
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    import pingouin as pg
    HAS_PINGOUIN = True
except ImportError:
    HAS_PINGOUIN = False


@dataclass
class TestResult:
    """Container for statistical test results."""
    test_name: str
    statistic: float
    p_value: float
    degrees_of_freedom: float | None = None
    effect_size: float | None = None
    confidence_interval: tuple[float, float] | None = None
    sample_size: int | None = None
    notes: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            'test_name': self.test_name,
            'statistic': self.statistic,
            'p_value': self.p_value,
            'degrees_of_freedom': self.degrees_of_freedom,
            'effect_size': self.effect_size,
            'confidence_interval': self.confidence_interval,
            'sample_size': self.sample_size,
            'notes': self.notes
        }
    
    def __repr__(self) -> str:
        return (f"TestResult({self.test_name}: stat={self.statistic:.4f}, "
                f"p={self.p_value:.4f}, df={self.degrees_of_freedom})")


class StatisticalTests:
    """
    Comprehensive statistical testing engine.
    
    Implements:
    - T-tests (independent, paired, one-sample)
    - Chi-square tests (goodness of fit, independence)
    - ANOVA (one-way, two-way)
    - Regression (linear, logistic)
    - Non-parametric tests (Mann-Whitney, Kruskal-Wallis)
    - Correlation tests (Pearson, Spearman)
    """
    
    def __init__(self, alpha: float = 0.05):
        """
        Initialize the statistical tests engine.
        
        Args:
            alpha: Significance level (default: 0.05)
        """
        self.alpha = alpha
        self._validate_dependencies()
    
    def _validate_dependencies(self) -> None:
        """Check that required dependencies are available."""
        if not HAS_SCIPY:
            raise ImportError(
                "scipy is required for statistical tests. "
                "Install with: pip install scipy"
            )
    
    # ==================== T-TESTS ====================
    
    def t_test_independent(
        self,
        sample1: list | np.ndarray | pd.Series,
        sample2: list | np.ndarray | pd.Series,
        equal_var: bool = True,
        alternative: str = 'two-sided'
    ) -> TestResult:
        """
        Independent (two-sample) t-test.
        
        Tests whether the means of two independent samples are significantly different.
        
        Args:
            sample1: First sample data
            sample2: Second sample data
            equal_var: If True, assume equal variances (Student's t-test)
                      If False, use Welch's t-test (default: True)
            alternative: Alternative hypothesis ('two-sided', 'less', 'greater')
        
        Returns:
            TestResult with t-statistic, p-value, and degrees of freedom
        """
        # Convert inputs to numpy arrays
        arr1 = self._to_array(sample1)
        arr2 = self._to_array(sample2)
        
        # Perform t-test
        t_stat, p_value = ttest_ind(arr1, arr2, equal_var=equal_var, alternative=alternative)
        
        # Calculate degrees of freedom
        n1, n2 = len(arr1), len(arr2)
        if equal_var:
            df = n1 + n2 - 2
        else:
            # Welch-Satterthwaite equation
            var1, var2 = np.var(arr1, ddof=1), np.var(arr2, ddof=1)
            df = ((var1/n1 + var2/n2)**2) / ((var1/n1)**2/(n1-1) + (var2/n2)**2/(n2-1))
        
        # Calculate effect size (Cohen's d)
        pooled_std = np.sqrt(((n1-1)*np.var(arr1, ddof=1) + (n2-1)*np.var(arr2, ddof=1)) / (n1 + n2 - 2))
        effect_size = (np.mean(arr1) - np.mean(arr2)) / pooled_std if pooled_std > 0 else 0
        
        return TestResult(
            test_name='Independent t-test',
            statistic=t_stat,
            p_value=p_value,
            degrees_of_freedom=df,
            effect_size=abs(effect_size),
            sample_size=n1 + n2,
            notes=f'Equal variance: {equal_var}, Alternative: {alternative}'
        )
    
    def t_test_paired(
        self,
        sample1: list | np.ndarray | pd.Series,
        sample2: list | np.ndarray | pd.Series,
        alternative: str = 'two-sided'
    ) -> TestResult:
        """
        Paired (dependent) t-test.
        
        Tests whether the mean of the differences between paired observations is zero.
        
        Args:
            sample1: First set of observations
            sample2: Second set of observations (paired with sample1)
            alternative: Alternative hypothesis ('two-sided', 'less', 'greater')
        
        Returns:
            TestResult with t-statistic, p-value, and degrees of freedom
        """
        arr1 = self._to_array(sample1)
        arr2 = self._to_array(sample2)
        
        if len(arr1) != len(arr2):
            raise ValueError(f"Samples must have equal length. Got {len(arr1)} and {len(arr2)}")
        
        t_stat, p_value = ttest_rel(arr1, arr2, alternative=alternative)
        df = len(arr1) - 1
        
        # Calculate effect size (Cohen's d for paired samples)
        diffs = arr1 - arr2
        effect_size = np.mean(diffs) / np.std(diffs, ddof=1) if np.std(diffs, ddof=1) > 0 else 0
        
        return TestResult(
            test_name='Paired t-test',
            statistic=t_stat,
            p_value=p_value,
            degrees_of_freedom=df,
            effect_size=abs(effect_size),
            sample_size=len(arr1),
            notes=f'Alternative: {alternative}'
        )
    
    def t_test_one_sample(
        self,
        sample: list | np.ndarray | pd.Series,
        popmean: float = 0.0,
        alternative: str = 'two-sided'
    ) -> TestResult:
        """
        One-sample t-test.
        
        Tests whether the mean of a sample is significantly different from a population mean.
        
        Args:
            sample: Sample data
            popmean: Population mean to test against (default: 0.0)
            alternative: Alternative hypothesis ('two-sided', 'less', 'greater')
        
        Returns:
            TestResult with t-statistic, p-value, and degrees of freedom
        """
        arr = self._to_array(sample)
        
        t_stat, p_value = ttest_1samp(arr, popmean, alternative=alternative)
        df = len(arr) - 1
        
        # Effect size (Cohen's d)
        effect_size = (np.mean(arr) - popmean) / np.std(arr, ddof=1) if np.std(arr, ddof=1) > 0 else 0
        
        return TestResult(
            test_name='One-sample t-test',
            statistic=t_stat,
            p_value=p_value,
            degrees_of_freedom=df,
            effect_size=abs(effect_size),
            sample_size=len(arr),
            notes=f'Population mean: {popmean}, Alternative: {alternative}'
        )
    
    # ==================== CHI-SQUARE TESTS ====================
    
    def chi_square_goodness_of_fit(
        self,
        observed: list | np.ndarray,
        expected: list | np.ndarray | str = 'uniform'
    ) -> TestResult:
        """
        Chi-square goodness of fit test.
        
        Tests whether observed frequencies match expected frequencies.
        
        Args:
            observed: Observed frequencies
            expected: Expected frequencies or 'uniform' for equal distribution
        
        Returns:
            TestResult with chi-square statistic and p-value
        """
        obs = self._to_array(observed)
        
        if isinstance(expected, str) and expected == 'uniform':
            exp = np.ones_like(obs) * (np.sum(obs) / len(obs))
        else:
            exp = self._to_array(expected)
        
        if len(obs) != len(exp):
            raise ValueError(f"Observed and expected must have same length. Got {len(obs)} and {len(exp)}")
        
        chi2_stat, p_value = chi2.sf(obs, exp)
        # Using chi2_contingency for goodness of fit
        chi2_stat, p_value = stats.chisquare(obs, f_exp=exp)
        df = len(obs) - 1
        
        return TestResult(
            test_name='Chi-square goodness of fit',
            statistic=chi2_stat,
            p_value=p_value,
            degrees_of_freedom=df,
            sample_size=int(np.sum(obs)),
            notes='Test of observed vs expected frequencies'
        )
    
    def chi_square_independence(
        self,
        contingency_table: list | np.ndarray | pd.DataFrame
    ) -> TestResult:
        """
        Chi-square test of independence.
        
        Tests whether two categorical variables are independent.
        
        Args:
            contingency_table: 2D array or DataFrame of observed frequencies
        
        Returns:
            TestResult with chi-square statistic and p-value
        """
        if isinstance(contingency_table, pd.DataFrame):
            table = contingency_table.values
        else:
            table = np.array(contingency_table)
        
        if table.ndim != 2:
            raise ValueError("Contingency table must be 2-dimensional")
        
        chi2_stat, p_value, df, expected = chi2_contingency(table)
        
        # Calculate effect size (Cramer's V)
        n = np.sum(table)
        phi2 = chi2_stat / n
        r, k = table.shape
        phi2corr = max(0, phi2 - ((r-1)*(k-1))/(n-1))
        r_corr = r - ((r-1)**2)/(n-1)
        k_corr = k - ((k-1)**2)/(n-1)
        effect_size = np.sqrt(phi2corr / min((k_corr-1), (r_corr-1)))
        
        return TestResult(
            test_name='Chi-square independence',
            statistic=chi2_stat,
            p_value=p_value,
            degrees_of_freedom=df,
            effect_size=effect_size,
            sample_size=int(n),
            notes=f'Contingency table shape: {table.shape}'
        )
    
    # ==================== ANOVA ====================
    
    def one_way_anova(
        self,
        *groups: list | np.ndarray | pd.Series,
        equal_var: bool = True
    ) -> TestResult:
        """
        One-way ANOVA.
        
        Tests whether the means of three or more groups are significantly different.
        
        Args:
            *groups: Two or more sample groups
            equal_var: If True, assume equal variances (use F-test)
                      If False, use Kruskal-Wallis test (non-parametric)
        
        Returns:
            TestResult with F-statistic (or H-statistic) and p-value
        """
        if len(groups) < 2:
            raise ValueError("ANOVA requires at least 2 groups")
        
        # Convert all groups to numpy arrays
        group_arrays = [self._to_array(g) for g in groups]
        
        if not equal_var:
            # Use Kruskal-Wallis (non-parametric)
            all_data = []
            all_groups = []
            for i, arr in enumerate(group_arrays):
                all_data.extend(arr.tolist())
                all_groups.extend([i] * len(arr))
            
            h_stat, p_value = kruskal(*group_arrays)
            df = len(groups) - 1
            
            return TestResult(
                test_name='Kruskal-Wallis H-test (non-parametric ANOVA)',
                statistic=h_stat,
                p_value=p_value,
                degrees_of_freedom=df,
                sample_size=len(all_data),
                notes='Non-parametric alternative to one-way ANOVA'
            )
        
        # Use F-test for parametric ANOVA
        f_stat, p_value = f_oneway(*group_arrays)
        
        # Calculate degrees of freedom
        n_total = sum(len(g) for g in group_arrays)
        k = len(group_arrays)
        df_between = k - 1
        df_within = n_total - k
        
        # Calculate effect size (eta-squared)
        grand_mean = np.mean([np.mean(g) for g in group_arrays])
        ss_between = sum(len(g) * (np.mean(g) - grand_mean)**2 for g in group_arrays)
        ss_total = sum(sum((x - grand_mean)**2 for x in g) for g in group_arrays)
        eta_squared = ss_between / ss_total if ss_total > 0 else 0
        
        return TestResult(
            test_name='One-way ANOVA',
            statistic=f_stat,
            p_value=p_value,
            degrees_of_freedom=(df_between, df_within),
            effect_size=eta_squared,
            sample_size=n_total,
            notes=f'Number of groups: {k}'
        )
    
    def two_way_anova(
        self,
        data: pd.DataFrame,
        formula: str
    ) -> dict[str, Any]:
        """
        Two-way ANOVA using statsmodels.
        
        Args:
            data: DataFrame containing the data
            formula: Formula string (e.g., 'y ~ factor1 + factor2 + factor1:factor2')
        
        Returns:
            Dictionary with ANOVA table and results
        """
        if not HAS_STATSMODELS:
            raise ImportError(
                "statsmodels is required for two-way ANOVA. "
                "Install with: pip install statsmodels"
            )
        
        model = ols(formula, data=data).fit()
        anova_table = sm.stats.anova_lm(model, typ=2)
        
        return {
            'model': model,
            'anova_table': anova_table,
            'summary': model.summary()
        }
    
    # ==================== REGRESSION ====================
    
    def linear_regression(
        self,
        x: list | np.ndarray | pd.Series,
        y: list | np.ndarray | pd.Series
    ) -> dict[str, Any]:
        """
        Simple linear regression.
        
        Args:
            x: Independent variable
            y: Dependent variable
        
        Returns:
            Dictionary with regression results
        """
        x_arr = self._to_array(x)
        y_arr = self._to_array(y)
        
        if len(x_arr) != len(y_arr):
            raise ValueError(f"x and y must have same length. Got {len(x_arr)} and {len(y_arr)}")
        
        # Perform linear regression
        slope, intercept, r_value, p_value, std_err = linregress(x_arr, y_arr)
        
        # Calculate R-squared
        r_squared = r_value ** 2
        
        # Calculate confidence intervals for slope and intercept
        n = len(x_arr)
        if n > 2:
            # Standard error of the estimate
            y_pred = intercept + slope * x_arr
            ss_res = np.sum((y_arr - y_pred) ** 2)
            ss_tot = np.sum((y_arr - np.mean(y_arr)) ** 2)
            
            # Standard error of slope and intercept
            x_mean = np.mean(x_arr)
            x_var = np.var(x_arr, ddof=1)
            se_slope = std_err
            se_intercept = std_err * np.sqrt(np.sum(x_arr**2) / (n * x_var))
            
            # t-critical value for 95% CI
            t_crit = t_dist.ppf(0.975, df=n-2)
            
            ci_slope = (slope - t_crit * se_slope, slope + t_crit * se_slope)
            ci_intercept = (intercept - t_crit * se_intercept, intercept + t_crit * se_intercept)
        else:
            ci_slope = (np.nan, np.nan)
            ci_intercept = (np.nan, np.nan)
        
        return {
            'slope': slope,
            'intercept': intercept,
            'r_value': r_value,
            'r_squared': r_squared,
            'p_value': p_value,
            'std_err': std_err,
            'confidence_interval_slope': ci_slope,
            'confidence_interval_intercept': ci_intercept,
            'n': n,
            'degrees_of_freedom': n - 2
        }
    
    def multiple_regression(
        self,
        data: pd.DataFrame,
        formula: str
    ) -> dict[str, Any]:
        """
        Multiple linear regression using statsmodels.
        
        Args:
            data: DataFrame containing the data
            formula: Formula string (e.g., 'y ~ x1 + x2 + x3')
        
        Returns:
            Dictionary with regression results
        """
        if not HAS_STATSMODELS:
            raise ImportError(
                "statsmodels is required for multiple regression. "
                "Install with: pip install statsmodels"
            )
        
        model = ols(formula, data=data).fit()
        
        return {
            'model': model,
            'summary': model.summary(),
            'parameters': model.params,
            'p_values': model.pvalues,
            'r_squared': model.rsquared,
            'r_squared_adj': model.rsquared_adj,
            'f_statistic': model.fvalue,
            'f_p_value': model.f_pvalue,
            'n_observations': model.nobs,
            'df_resid': model.df_resid,
            'df_model': model.df_model
        }
    
    # ==================== CORRELATION ====================
    
    def pearson_correlation(
        self,
        x: list | np.ndarray | pd.Series,
        y: list | np.ndarray | pd.Series
    ) -> TestResult:
        """
        Pearson correlation test.
        
        Tests for linear correlation between two variables.
        
        Args:
            x: First variable
            y: Second variable
        
        Returns:
            TestResult with correlation coefficient and p-value
        """
        x_arr = self._to_array(x)
        y_arr = self._to_array(y)
        
        r, p_value = pearsonr(x_arr, y_arr)
        
        return TestResult(
            test_name='Pearson correlation',
            statistic=r,
            p_value=p_value,
            degrees_of_freedom=len(x_arr) - 2,
            sample_size=len(x_arr),
            notes='Linear correlation test'
        )
    
    def spearman_correlation(
        self,
        x: list | np.ndarray | pd.Series,
        y: list | np.ndarray | pd.Series
    ) -> TestResult:
        """
        Spearman rank correlation test.
        
        Non-parametric test for monotonic correlation.
        
        Args:
            x: First variable
            y: Second variable
        
        Returns:
            TestResult with correlation coefficient and p-value
        """
        x_arr = self._to_array(x)
        y_arr = self._to_array(y)
        
        r, p_value = spearmanr(x_arr, y_arr)
        
        return TestResult(
            test_name='Spearman correlation',
            statistic=r,
            p_value=p_value,
            degrees_of_freedom=len(x_arr) - 2,
            sample_size=len(x_arr),
            notes='Non-parametric monotonic correlation test'
        )
    
    # ==================== NON-PARAMETRIC TESTS ====================
    
    def mann_whitney_u(
        self,
        sample1: list | np.ndarray | pd.Series,
        sample2: list | np.ndarray | pd.Series,
        alternative: str = 'two-sided'
    ) -> TestResult:
        """
        Mann-Whitney U test (non-parametric alternative to independent t-test).
        
        Args:
            sample1: First sample
            sample2: Second sample
            alternative: Alternative hypothesis ('two-sided', 'less', 'greater')
        
        Returns:
            TestResult with U-statistic and p-value
        """
        arr1 = self._to_array(sample1)
        arr2 = self._to_array(sample2)
        
        if HAS_SCIPY:
            u_stat, p_value = stats.mannwhitneyu(arr1, arr2, alternative=alternative)
        elif HAS_PINGOUIN:
            result = pg.mwu(arr1, arr2, alternative=alternative)
            u_stat = result['U-val'].values[0]
            p_value = result['p-val'].values[0]
        else:
            raise ImportError("Either scipy or pingouin is required for Mann-Whitney U test")
        
        # Calculate effect size (rank-biserial correlation)
        n1, n2 = len(arr1), len(arr2)
        ranks = stats.rankdata(np.concatenate([arr1, arr2]))
        r1 = np.mean(ranks[:n1])
        r2 = np.mean(ranks[n1:])
        effect_size = 1 - (2 * min(r1, r2) / (n1 + n2 + 1))
        
        return TestResult(
            test_name='Mann-Whitney U',
            statistic=u_stat,
            p_value=p_value,
            sample_size=n1 + n2,
            effect_size=effect_size,
            notes=f'Non-parametric test, Alternative: {alternative}'
        )
    
    def wilcoxon_signed_rank(
        self,
        sample1: list | np.ndarray | pd.Series,
        sample2: list | np.ndarray | pd.Series = None,
        alternative: str = 'two-sided'
    ) -> TestResult:
        """
        Wilcoxon signed-rank test (non-parametric alternative to paired t-test).
        
        Args:
            sample1: First sample or differences
            sample2: Second sample (optional, if paired)
            alternative: Alternative hypothesis ('two-sided', 'less', 'greater')
        
        Returns:
            TestResult with W-statistic and p-value
        """
        if sample2 is not None:
            arr1 = self._to_array(sample1)
            arr2 = self._to_array(sample2)
            if len(arr1) != len(arr2):
                raise ValueError(f"Samples must have equal length. Got {len(arr1)} and {len(arr2)}")
            diffs = arr1 - arr2
        else:
            diffs = self._to_array(sample1)
        
        w_stat, p_value = stats.wilcoxon(diffs, alternative=alternative)
        
        return TestResult(
            test_name='Wilcoxon signed-rank',
            statistic=w_stat,
            p_value=p_value,
            sample_size=len(diffs),
            notes=f'Non-parametric paired test, Alternative: {alternative}'
        )
    
    # ==================== POST-HOC TESTS ====================
    
    def tukey_hsd(
        self,
        data: list | np.ndarray | pd.Series,
        groups: list | np.ndarray | pd.Series
    ) -> dict[str, Any]:
        """
        Tukey's Honestly Significant Difference test for post-hoc ANOVA comparisons.
        
        Args:
            data: Response variable
            groups: Group labels
        
        Returns:
            Dictionary with pairwise comparison results
        """
        if not HAS_STATSMODELS:
            raise ImportError(
                "statsmodels is required for Tukey HSD test. "
                "Install with: pip install statsmodels"
            )
        
        result = pairwise_tukeyhsd(
            endog=data,
            groups=groups,
            alpha=self.alpha
        )
        
        return {
            'summary': result.summary(),
            'confidence_intervals': result.confint,
            'p_values': result.pvalues,
            'reject': result.reject
        }
    
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
    
    def summarize_results(self, results: TestResult | list) -> pd.DataFrame:
        """
        Convert test results to a summary DataFrame.
        
        Args:
            results: Single TestResult or list of TestResults
        
        Returns:
            DataFrame with summary of all results
        """
        if isinstance(results, TestResult):
            results = [results]
        
        data = [r.to_dict() for r in results]
        return pd.DataFrame(data)
    
    def is_significant(self, result: TestResult) -> bool:
        """
        Check if a test result is statistically significant.
        
        Args:
            result: TestResult to check
        
        Returns:
            True if p-value < alpha, False otherwise
        """
        return result.p_value < self.alpha


# ==================== MODULE-LEVEL FUNCTIONS ====================

# Create a default instance for convenience
_default_tests = StatisticalTests()


def t_test_independent(
    sample1: list | np.ndarray | pd.Series,
    sample2: list | np.ndarray | pd.Series,
    equal_var: bool = True,
    alternative: str = 'two-sided'
) -> TestResult:
    """Independent t-test (module-level function)."""
    return _default_tests.t_test_independent(sample1, sample2, equal_var, alternative)


def t_test_paired(
    sample1: list | np.ndarray | pd.Series,
    sample2: list | np.ndarray | pd.Series,
    alternative: str = 'two-sided'
) -> TestResult:
    """Paired t-test (module-level function)."""
    return _default_tests.t_test_paired(sample1, sample2, alternative)


def one_way_anova(
    *groups: list | np.ndarray | pd.Series,
    equal_var: bool = True
) -> TestResult:
    """One-way ANOVA (module-level function)."""
    return _default_tests.one_way_anova(*groups, equal_var=equal_var)


def chi_square_independence(
    contingency_table: list | np.ndarray | pd.DataFrame
) -> TestResult:
    """Chi-square test of independence (module-level function)."""
    return _default_tests.chi_square_independence(contingency_table)


def pearson_correlation(
    x: list | np.ndarray | pd.Series,
    y: list | np.ndarray | pd.Series
) -> TestResult:
    """Pearson correlation (module-level function)."""
    return _default_tests.pearson_correlation(x, y)


def linear_regression(
    x: list | np.ndarray | pd.Series,
    y: list | np.ndarray | pd.Series
) -> dict[str, Any]:
    """Linear regression (module-level function)."""
    return _default_tests.linear_regression(x, y)
