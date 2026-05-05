"""
Factor weight optimization module for quantitative portfolio strategy.

This module provides tools to optimize factor weights in the backtest engine,
testing multiple configurations to identify which combinations deliver the best
out-of-sample performance.

The optimizer:
1. Defines several weight configurations (equal weight, value-heavy, quality-heavy, etc.)
2. Implements weighted composite scoring (without modifying the original engine code)
3. Runs backtests with different weight configurations
4. Compares results and generates reports

Available configurations:
- equal_weight: Equal weighting (baseline)
- quality_heavy: Quality-weighted (Novy-Marx tilted)
- value_heavy: Value-weighted (Fama-French tilted)
- cashflow_quality: Cash-flow quality focused
- orthogonal_diversified: Redundancy-reduced diversification

Usage:
    from quant_data_platform.web.optimize import optimize_factors, list_optimization_configs
    
    configs = list_optimization_configs()
    report = optimize_factors(factor_rows, execution_price_rows, preset, top_n=20)
"""

from .optimizer import FactorOptimizer, FactorWeightConfiguration, FactorOptimizationResult, list_optimization_configs, optimize_factors
from .reports import generate_html_report, generate_json_report, generate_csv_report

__all__ = [
    "FactorOptimizer",
    "FactorWeightConfiguration",
    "FactorOptimizationResult",
    "list_optimization_configs",
    "optimize_factors",
    "generate_html_report",
    "generate_json_report",
    "generate_csv_report",
]
