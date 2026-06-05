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
#!/usr/bin/env python3
"""
Statistical Validation Engine Demo
Open-Omniscience - Pillar 2: Scientific Rigor - Phase 2.1

This script demonstrates the usage of the statistical validation engine.
"""

import numpy as np
import pandas as pd
from pillar2.src.analysis.statistical_tests import StatisticalTests, t_test_independent
from pillar2.src.analysis.confidence_intervals import ConfidenceIntervals


def main():
    print("=" * 80)
    print("Open-Omniscience - Statistical Validation Engine Demo")
    print("Pillar 2: Scientific Rigor - Phase 2.1")
    print("=" * 80)
    print()
    
    # Set random seed for reproducibility
    np.random.seed(42)
    
    # ==================== STATISTICAL TESTS ====================
    print("1. STATISTICAL TESTS")
    print("-" * 80)
    
    # Create sample data
    print("\nGenerating sample data...")
    group_a = np.random.normal(5.0, 1.0, 100)
    group_b = np.random.normal(5.5, 1.0, 100)
    group_c = np.random.normal(6.0, 1.0, 100)
    
    # Initialize statistical tests engine
    stats_engine = StatisticalTests(alpha=0.05)
    
    # Independent t-test
    print("\n1.1 Independent t-test (Group A vs Group B)")
    t_result = stats_engine.t_test_independent(group_a, group_b)
    print(f"   Test: {t_result.test_name}")
    print(f"   Statistic: {t_result.statistic:.4f}")
    print(f"   p-value: {t_result.p_value:.4f}")
    print(f"   Degrees of freedom: {t_result.degrees_of_freedom}")
    print(f"   Effect size (Cohen's d): {t_result.effect_size:.4f}")
    print(f"   Sample size: {t_result.sample_size}")
    print(f"   Significant: {stats_engine.is_significant(t_result)}")
    
    # Paired t-test
    print("\n1.2 Paired t-test (Before vs After)")
    before = np.random.normal(5.0, 1.0, 50)
    after = before + np.random.normal(0.3, 0.5, 50)
    paired_result = stats_engine.t_test_paired(before, after)
    print(f"   Test: {paired_result.test_name}")
    print(f"   Statistic: {paired_result.statistic:.4f}")
    print(f"   p-value: {paired_result.p_value:.4f}")
    print(f"   Degrees of freedom: {paired_result.degrees_of_freedom}")
    print(f"   Effect size: {paired_result.effect_size:.4f}")
    print(f"   Significant: {stats_engine.is_significant(paired_result)}")
    
    # One-way ANOVA
    print("\n1.3 One-way ANOVA (Groups A, B, C)")
    anova_result = stats_engine.one_way_anova(group_a, group_b, group_c)
    print(f"   Test: {anova_result.test_name}")
    print(f"   F-statistic: {anova_result.statistic:.4f}")
    print(f"   p-value: {anova_result.p_value:.4f}")
    print(f"   Degrees of freedom: {anova_result.degrees_of_freedom}")
    print(f"   Effect size (eta-squared): {anova_result.effect_size:.4f}")
    print(f"   Sample size: {anova_result.sample_size}")
    print(f"   Significant: {stats_engine.is_significant(anova_result)}")
    
    # Chi-square test
    print("\n1.4 Chi-square test of independence")
    contingency_table = [[50, 30, 20],
                         [40, 40, 20]]
    chi2_result = stats_engine.chi_square_independence(contingency_table)
    print(f"   Test: {chi2_result.test_name}")
    print(f"   Statistic: {chi2_result.statistic:.4f}")
    print(f"   p-value: {chi2_result.p_value:.4f}")
    print(f"   Degrees of freedom: {chi2_result.degrees_of_freedom}")
    print(f"   Effect size (Cramer's V): {chi2_result.effect_size:.4f}")
    print(f"   Significant: {stats_engine.is_significant(chi2_result)}")
    
    # Correlation
    print("\n1.5 Pearson correlation")
    x = np.random.normal(0, 1, 100)
    y = 0.8 * x + np.random.normal(0, 0.5, 100)
    corr_result = stats_engine.pearson_correlation(x, y)
    print(f"   Test: {corr_result.test_name}")
    print(f"   Correlation coefficient: {corr_result.statistic:.4f}")
    print(f"   p-value: {corr_result.p_value:.4f}")
    print(f"   Degrees of freedom: {corr_result.degrees_of_freedom}")
    print(f"   Significant: {stats_engine.is_significant(corr_result)}")
    
    # Linear regression
    print("\n1.6 Simple linear regression")
    reg_result = stats_engine.linear_regression(x, y)
    print(f"   Slope: {reg_result['slope']:.4f}")
    print(f"   Intercept: {reg_result['intercept']:.4f}")
    print(f"   R-squared: {reg_result['r_squared']:.4f}")
    print(f"   p-value: {reg_result['p_value']:.4f}")
    print(f"   Slope 95% CI: ({reg_result['confidence_interval_slope'][0]:.4f}, {reg_result['confidence_interval_slope'][1]:.4f})")
    
    # ==================== CONFIDENCE INTERVALS ====================
    print("\n\n2. CONFIDENCE INTERVALS")
    print("-" * 80)
    
    # Initialize confidence interval calculator
    ci_calc = ConfidenceIntervals()
    
    # Mean confidence interval
    print("\n2.1 Mean confidence interval")
    data = np.random.normal(5.0, 1.0, 100)
    mean_ci = ci_calc.mean_ci(data, confidence_level=0.95)
    print(f"   Estimate: {mean_ci.estimate:.4f}")
    print(f"   95% CI: [{mean_ci.lower:.4f}, {mean_ci.upper:.4f}]")
    print(f"   Method: {mean_ci.method}")
    print(f"   Standard error: {mean_ci.standard_error:.4f}")
    print(f"   Width: {mean_ci.width():.4f}")
    
    # Proportion confidence interval
    print("\n2.2 Proportion confidence interval (Wilson method)")
    successes = 65
    trials = 100
    prop_ci = ci_calc.proportion_ci_wilson(successes, trials, confidence_level=0.95)
    print(f"   Estimate: {prop_ci.estimate:.4f}")
    print(f"   95% CI: [{prop_ci.lower:.4f}, {prop_ci.upper:.4f}]")
    print(f"   Method: {prop_ci.method}")
    print(f"   Contains 0.65: {prop_ci.contains(0.65)}")
    
    # Difference of means
    print("\n2.3 Difference of means confidence interval")
    diff_ci = ci_calc.diff_means_ci(group_a, group_b, confidence_level=0.95)
    print(f"   Estimate: {diff_ci.estimate:.4f}")
    print(f"   95% CI: [{diff_ci.lower:.4f}, {diff_ci.upper:.4f}]")
    print(f"   Method: {diff_ci.method}")
    print(f"   Contains 0: {diff_ci.contains(0)}")
    
    # Variance confidence interval
    print("\n2.4 Variance confidence interval")
    var_ci = ci_calc.variance_ci(data, confidence_level=0.95)
    print(f"   Estimate: {var_ci.estimate:.4f}")
    print(f"   95% CI: [{var_ci.lower:.4f}, {var_ci.upper:.4f}]")
    print(f"   Method: {var_ci.method}")
    
    # Regression slope confidence interval
    print("\n2.5 Regression slope confidence interval")
    slope_ci = ci_calc.regression_slope_ci(x, y, confidence_level=0.95)
    print(f"   Estimate: {slope_ci.estimate:.4f}")
    print(f"   95% CI: [{slope_ci.lower:.4f}, {slope_ci.upper:.4f}]")
    print(f"   Method: {slope_ci.method}")
    
    # Odds ratio confidence interval
    print("\n2.6 Odds ratio confidence interval")
    # 2x2 table: a=exposed cases, b=exposed controls, c=unexposed cases, d=unexposed controls
    a, b, c, d = 20, 30, 10, 40
    or_ci = ci_calc.odds_ratio_ci(a, b, c, d, confidence_level=0.95)
    print(f"   Estimate: {or_ci.estimate:.4f}")
    print(f"   95% CI: [{or_ci.lower:.4f}, {or_ci.upper:.4f}]")
    print(f"   Method: {or_ci.method}")
    
    # Batch processing
    print("\n2.7 Batch processing - Mean CIs at multiple confidence levels")
    batch_results = ci_calc.batch_mean_ci(data, [0.90, 0.95, 0.99])
    for cl, ci in batch_results.items():
        print(f"   {cl*100:.0f}% CI: [{ci.lower:.4f}, {ci.upper:.4f}]")
    
    # ==================== SUMMARY ====================
    print("\n\n3. SUMMARY")
    print("-" * 80)
    
    # Summarize multiple test results
    results = [t_result, paired_result, anova_result, chi2_result, corr_result]
    summary_df = stats_engine.summarize_results(results)
    print("\nTest Results Summary:")
    print(summary_df.to_string(index=False))
    
    print("\n" + "=" * 80)
    print("Demo completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
