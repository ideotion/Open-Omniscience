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
Tests for statistical_tests.py module
Pillar 2: Scientific Rigor - Phase 2.1
"""

import pytest
import numpy as np
import pandas as pd
from src.analysis.statistical_tests import (
    StatisticalTests,
    TestResult,
    t_test_independent,
    t_test_paired,
    one_way_anova,
)


class TestStatisticalTests:
    """Test suite for StatisticalTests class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tests = StatisticalTests(alpha=0.05)
        # Set random seed for reproducibility
        np.random.seed(42)
    
    def test_t_test_independent_basic(self):
        """Test independent t-test with known different means."""
        # Create two samples with different means
        sample1 = np.random.normal(5, 1, 100)
        sample2 = np.random.normal(6, 1, 100)
        
        result = self.tests.t_test_independent(sample1, sample2)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Independent t-test'
        assert result.statistic is not None
        assert 0 <= result.p_value <= 1
        assert result.degrees_of_freedom == 198  # n1 + n2 - 2
        assert result.sample_size == 200
        assert result.effect_size is not None
    
    def test_t_test_independent_equal_var_false(self):
        """Test independent t-test with Welch's correction."""
        sample1 = np.random.normal(5, 1, 50)
        sample2 = np.random.normal(6, 2, 50)
        
        result = self.tests.t_test_independent(sample1, sample2, equal_var=False)
        
        assert isinstance(result, TestResult)
        assert 'Equal variance: False' in result.notes
        # Degrees of freedom will be fractional with Welch's correction
        assert result.degrees_of_freedom < 98  # Less than n1 + n2 - 2
    
    def test_t_test_paired(self):
        """Test paired t-test."""
        # Create paired data
        before = np.random.normal(5, 1, 100)
        after = before + np.random.normal(0.5, 0.5, 100)
        
        result = self.tests.t_test_paired(before, after)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Paired t-test'
        assert result.degrees_of_freedom == 99  # n - 1
        assert result.sample_size == 100
    
    def test_t_test_paired_unequal_length(self):
        """Test that paired t-test raises error for unequal sample sizes."""
        sample1 = [1, 2, 3, 4, 5]
        sample2 = [1, 2, 3]
        
        with pytest.raises(ValueError, match="Samples must have equal length"):
            self.tests.t_test_paired(sample1, sample2)
    
    def test_t_test_one_sample(self):
        """Test one-sample t-test."""
        sample = np.random.normal(5, 1, 100)
        
        result = self.tests.t_test_one_sample(sample, popmean=5)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'One-sample t-test'
        assert result.degrees_of_freedom == 99
        assert result.sample_size == 100
        assert 'Population mean: 5' in result.notes
    
    def test_chi_square_independence(self):
        """Test chi-square test of independence."""
        # Create a contingency table
        table = [[10, 20, 30],
                 [6, 9, 17]]
        
        result = self.tests.chi_square_independence(table)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Chi-square independence'
        assert result.statistic is not None
        assert 0 <= result.p_value <= 1
        assert result.degrees_of_freedom == 2  # (2-1)*(3-1)
        assert result.effect_size is not None  # Cramer's V
    
    def test_chi_square_independence_dataframe(self):
        """Test chi-square test with pandas DataFrame."""
        df = pd.DataFrame({
            'A': [10, 20, 30],
            'B': [6, 9, 17]
        })
        
        result = self.tests.chi_square_independence(df)
        
        assert isinstance(result, TestResult)
        assert result.sample_size == 10 + 20 + 30 + 6 + 9 + 17
    
    def test_one_way_anova(self):
        """Test one-way ANOVA."""
        # Create three groups with different means
        group1 = np.random.normal(5, 1, 50)
        group2 = np.random.normal(6, 1, 50)
        group3 = np.random.normal(7, 1, 50)
        
        result = self.tests.one_way_anova(group1, group2, group3)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'One-way ANOVA'
        assert result.statistic is not None  # F-statistic
        assert 0 <= result.p_value <= 1
        assert result.degrees_of_freedom == (2, 147)  # (k-1, n-k)
        assert result.effect_size is not None  # eta-squared
        assert result.sample_size == 150
    
    def test_one_way_anova_non_parametric(self):
        """Test non-parametric ANOVA (Kruskal-Wallis)."""
        group1 = np.random.normal(5, 1, 50)
        group2 = np.random.normal(6, 1, 50)
        group3 = np.random.normal(7, 1, 50)
        
        result = self.tests.one_way_anova(group1, group2, group3, equal_var=False)
        
        assert isinstance(result, TestResult)
        assert 'Kruskal-Wallis' in result.test_name
    
    def test_one_way_anova_too_few_groups(self):
        """Test that ANOVA raises error with too few groups."""
        group1 = [1, 2, 3, 4, 5]
        
        with pytest.raises(ValueError, match="ANOVA requires at least 2 groups"):
            self.tests.one_way_anova(group1)
    
    def test_pearson_correlation(self):
        """Test Pearson correlation."""
        x = np.random.normal(0, 1, 100)
        y = x + np.random.normal(0, 0.5, 100)
        
        result = self.tests.pearson_correlation(x, y)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Pearson correlation'
        assert -1 <= result.statistic <= 1
        assert 0 <= result.p_value <= 1
        assert result.degrees_of_freedom == 98  # n - 2
    
    def test_spearman_correlation(self):
        """Test Spearman correlation."""
        x = np.random.normal(0, 1, 100)
        y = x + np.random.normal(0, 0.5, 100)
        
        result = self.tests.spearman_correlation(x, y)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Spearman correlation'
        assert -1 <= result.statistic <= 1
    
    def test_linear_regression(self):
        """Test simple linear regression."""
        x = np.random.normal(0, 1, 100)
        y = 2 * x + 3 + np.random.normal(0, 0.5, 100)
        
        result = self.tests.linear_regression(x, y)
        
        assert isinstance(result, dict)
        assert 'slope' in result
        assert 'intercept' in result
        assert 'r_value' in result
        assert 'r_squared' in result
        assert 'p_value' in result
        assert 'confidence_interval_slope' in result
        assert 'confidence_interval_intercept' in result
        
        # Check that slope is close to 2
        assert abs(result['slope'] - 2) < 0.5
        # Check that intercept is close to 3
        assert abs(result['intercept'] - 3) < 0.5
    
    def test_linear_regression_unequal_length(self):
        """Test that linear regression raises error for unequal lengths."""
        x = [1, 2, 3, 4, 5]
        y = [1, 2, 3]
        
        with pytest.raises(ValueError, match="x and y must have same length"):
            self.tests.linear_regression(x, y)
    
    def test_mann_whitney_u(self):
        """Test Mann-Whitney U test."""
        sample1 = np.random.normal(5, 1, 50)
        sample2 = np.random.normal(6, 1, 50)
        
        result = self.tests.mann_whitney_u(sample1, sample2)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Mann-Whitney U'
        assert result.statistic is not None
        assert 0 <= result.p_value <= 1
        assert result.effect_size is not None
    
    def test_wilcoxon_signed_rank(self):
        """Test Wilcoxon signed-rank test."""
        before = np.random.normal(5, 1, 50)
        after = before + np.random.normal(0.5, 0.5, 50)
        
        result = self.tests.wilcoxon_signed_rank(before, after)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Wilcoxon signed-rank'
        assert result.statistic is not None
        assert 0 <= result.p_value <= 1
    
    def test_is_significant(self):
        """Test significance checking."""
        # Create a result with p-value < alpha
        result_significant = TestResult(
            test_name='Test',
            statistic=5.0,
            p_value=0.01,
            degrees_of_freedom=10
        )
        
        # Create a result with p-value > alpha
        result_not_significant = TestResult(
            test_name='Test',
            statistic=1.0,
            p_value=0.30,
            degrees_of_freedom=10
        )
        
        assert self.tests.is_significant(result_significant) is True
        assert self.tests.is_significant(result_not_significant) is False
    
    def test_summarize_results(self):
        """Test result summarization."""
        result1 = TestResult(
            test_name='Test 1',
            statistic=2.5,
            p_value=0.01,
            degrees_of_freedom=10
        )
        result2 = TestResult(
            test_name='Test 2',
            statistic=1.5,
            p_value=0.15,
            degrees_of_freedom=15
        )
        
        df = self.tests.summarize_results([result1, result2])
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert 'test_name' in df.columns
        assert 'statistic' in df.columns
        assert 'p_value' in df.columns
    
    def test_to_dict(self):
        """Test TestResult to_dict method."""
        result = TestResult(
            test_name='Test',
            statistic=2.5,
            p_value=0.01,
            degrees_of_freedom=10,
            effect_size=0.5,
            sample_size=100,
            notes='Test note'
        )
        
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert d['test_name'] == 'Test'
        assert d['statistic'] == 2.5
        assert d['p_value'] == 0.01
        assert d['degrees_of_freedom'] == 10
        assert d['effect_size'] == 0.5
        assert d['sample_size'] == 100
        assert d['notes'] == 'Test note'
    
    def test_repr(self):
        """Test TestResult repr method."""
        result = TestResult(
            test_name='Test',
            statistic=2.5,
            p_value=0.01,
            degrees_of_freedom=10
        )
        
        repr_str = repr(result)
        
        assert 'Test' in repr_str
        assert '2.5' in repr_str
        assert '0.01' in repr_str


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""
    
    def test_t_test_independent_function(self):
        """Test module-level t_test_independent function."""
        sample1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        sample2 = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        
        result = t_test_independent(sample1, sample2)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Independent t-test'
    
    def test_t_test_paired_function(self):
        """Test module-level t_test_paired function."""
        before = [1, 2, 3, 4, 5]
        after = [2, 3, 4, 5, 6]
        
        result = t_test_paired(before, after)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'Paired t-test'
    
    def test_one_way_anova_function(self):
        """Test module-level one_way_anova function."""
        group1 = [1, 2, 3, 4, 5]
        group2 = [2, 3, 4, 5, 6]
        group3 = [3, 4, 5, 6, 7]
        
        result = one_way_anova(group1, group2, group3)
        
        assert isinstance(result, TestResult)
        assert result.test_name == 'One-way ANOVA'


class TestInputTypes:
    """Test that functions accept various input types."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tests = StatisticalTests()
    
    def test_list_input(self):
        """Test with list inputs."""
        sample1 = [1, 2, 3, 4, 5]
        sample2 = [2, 3, 4, 5, 6]
        
        result = self.tests.t_test_independent(sample1, sample2)
        assert isinstance(result, TestResult)
    
    def test_numpy_array_input(self):
        """Test with numpy array inputs."""
        sample1 = np.array([1, 2, 3, 4, 5])
        sample2 = np.array([2, 3, 4, 5, 6])
        
        result = self.tests.t_test_independent(sample1, sample2)
        assert isinstance(result, TestResult)
    
    def test_pandas_series_input(self):
        """Test with pandas Series inputs."""
        sample1 = pd.Series([1, 2, 3, 4, 5])
        sample2 = pd.Series([2, 3, 4, 5, 6])
        
        result = self.tests.t_test_independent(sample1, sample2)
        assert isinstance(result, TestResult)
