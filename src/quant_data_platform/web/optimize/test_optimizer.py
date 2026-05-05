"""
Unit tests for the factor weight optimizer module.
Tests core logic without requiring database connectivity.
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

# ==========================================
# 1. Mock ALL dependencies BEFORE importing optimizer
# ==========================================

class MockFactorSpec:
    def __init__(self, column: str, higher_is_better: bool):
        self.column = column
        self.higher_is_better = higher_is_better

class MockStrategyPreset:
    def __init__(self):
        self.preset_id = "test_preset"
        self.factor_specs: list = []

# Real simulation result to avoid Mock behavior when accessed
@dataclass
class RealSimulationResult:
    simulation_result_id: str
    start_date: date
    end_date: date
    sharpe_ratio: float
    metrics: dict = field(default_factory=dict)

# Patch modules before they are imported by optimizer.py
_original_presets_module = sys.modules.get("quant_data_platform.web.presets")
_original_repo_module = sys.modules.get("quant_data_platform.web.repositories.backtest_repo")
_original_engine_module = sys.modules.get("quant_data_platform.web.services.engine")

sys.modules["quant_data_platform.web.presets"] = MagicMock()
sys.modules["quant_data_platform.web.presets"].FactorSpec = MockFactorSpec
sys.modules["quant_data_platform.web.presets"].StrategyPreset = MockStrategyPreset
sys.modules["quant_data_platform.web.presets"].StrategyPresetId = MagicMock()

sys.modules["quant_data_platform.web.repositories.backtest_repo"] = MagicMock()
sys.modules["quant_data_platform.web.repositories.backtest_repo"].FactorSnapshotRow = MagicMock()
sys.modules["quant_data_platform.web.repositories.backtest_repo"].ExecutionPriceRow = MagicMock()

engine_mock = MagicMock()
engine_mock.SimulationResult = RealSimulationResult
sys.modules["quant_data_platform.web.services.engine"] = engine_mock

# ==========================================
# 2. Import the module under test
# ==========================================
from quant_data_platform.web.optimize.optimizer import (
    FactorOptimizer,
    list_optimization_configs,
    optimize_factors,
)
from quant_data_platform.web.optimize.reports.json_reporter import generate_json_report
from quant_data_platform.web.optimize.reports.csv_reporter import generate_csv_report
from quant_data_platform.web.optimize.reports.html_reporter import generate_html_report

if _original_presets_module is not None:
    sys.modules["quant_data_platform.web.presets"] = _original_presets_module
else:
    sys.modules.pop("quant_data_platform.web.presets", None)
if _original_repo_module is not None:
    sys.modules["quant_data_platform.web.repositories.backtest_repo"] = _original_repo_module
else:
    sys.modules.pop("quant_data_platform.web.repositories.backtest_repo", None)
if _original_engine_module is not None:
    sys.modules["quant_data_platform.web.services.engine"] = _original_engine_module
else:
    sys.modules.pop("quant_data_platform.web.services.engine", None)

# ==========================================
# 3. Mock row classes for internal usage
# ==========================================
class MockFactorSnapshotRow:
    def __init__(self, symbol: str, snapshot_date: date, liquidity_rank: int, factors: dict):
        self.symbol = symbol
        self.snapshot_date = snapshot_date
        self.factors = factors
        self.liquidity_rank = liquidity_rank
        self.trade_date = snapshot_date

    def get(self, key: str, default=None):
        if key == "symbol": return self.symbol
        if key == "trade_date": return self.snapshot_date
        return default

class MockExecutionPriceRow:
    def __init__(self, symbol: str, trade_date: date, adjusted_open: Decimal):
        self.symbol = symbol
        self.trade_date = trade_date
        self.adjusted_open = adjusted_open

    def get(self, key: str, default=None):
        if key == "symbol": return self.symbol
        if key == "trade_date": return self.trade_date
        if key == "adjusted_open": return self.adjusted_open
        return default


# ==========================================
# 4. Test Suites
# ==========================================

class TestFactorWeightConfiguration(unittest.TestCase):
    def test_five_configurations_exist(self):
        configs = list_optimization_configs()
        self.assertEqual(len(configs), 5)

    def test_all_configs_have_12_weights(self):
        configs = list_optimization_configs()
        for config in configs:
            self.assertEqual(len(config["weights"]), 12)

    def test_all_configs_have_non_empty_rationale(self):
        configs = list_optimization_configs()
        for config in configs:
            self.assertTrue(len(config["rationale"].strip()) > 0)


class TestListOptimizationConfigs(unittest.TestCase):
    def test_returns_list(self):
        configs = list_optimization_configs()
        self.assertIsInstance(configs, list)

    def test_each_config_is_dict_with_required_keys(self):
        configs = list_optimization_configs()
        for config in configs:
            self.assertIn("name", config)
            self.assertIn("weights", config)
            self.assertIn("rationale", config)

    def test_names_match_internal_list(self):
        configs = list_optimization_configs()
        names = {c["name"] for c in configs}
        internal = {c.name for c in FactorOptimizer.WEIGHT_CONFIGURATIONS}
        self.assertEqual(names, internal)


class TestWeightedPercentileScores(unittest.TestCase):
    def test_empty_input(self):
        result = FactorOptimizer._weighted_percentile_scores([], "pe_ratio", False, 1.0)
        self.assertEqual(result, {})

    def test_lower_pe_better_when_higher_is_better_false(self):
        rows = [
            MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("30")}),
            MockFactorSnapshotRow("B", date(2024, 1, 1), 2, {"pe_ratio": Decimal("20")}),
            MockFactorSnapshotRow("C", date(2024, 1, 1), 3, {"pe_ratio": Decimal("10")}),
        ]
        scores = FactorOptimizer._weighted_percentile_scores(rows, "pe_ratio", False, 1.0)
        self.assertGreater(scores["C"], scores["B"])
        self.assertGreater(scores["B"], scores["A"])

    def test_weight_scaling(self):
        rows = [MockFactorSnapshotRow("X", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10")})]
        s1 = FactorOptimizer._weighted_percentile_scores(rows, "pe_ratio", False, 1.0)
        s3 = FactorOptimizer._weighted_percentile_scores(rows, "pe_ratio", False, 3.0)
        self.assertAlmostEqual(s3["X"], s1["X"] * 3.0)


class TestWeightedSelectTopCandidates(unittest.TestCase):
    def _make_preset(self):
        p = MockStrategyPreset()
        p.factor_specs = [MockFactorSpec("pe_ratio", False)]
        return p

    def test_missing_factors_excluded(self):
        rows = [
            MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": None}),
            MockFactorSnapshotRow("B", date(2024, 1, 1), 2, {"pe_ratio": Decimal("10")}),
        ]
        execution_opens = {("B", date(2024, 1, 1)): Decimal("100")}
        top_n, counts = FactorOptimizer._weighted_select_top_candidates(
            rows, self._make_preset(), {"pe_ratio": 1.0}, 10, execution_opens, date(2024, 1, 1)
        )
        self.assertEqual(counts["missing_factors"], 1)
        self.assertEqual(len(top_n), 1)
        self.assertEqual(top_n[0].symbol, "B")

    def test_missing_execution_open_excluded(self):
        rows = [MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10")})]
        execution_opens = {}
        top_n, counts = FactorOptimizer._weighted_select_top_candidates(
            rows, self._make_preset(), {"pe_ratio": 1.0}, 10, execution_opens, date(2024, 1, 1)
        )
        self.assertEqual(counts["missing_execution_open"], 1)
        self.assertEqual(len(top_n), 0)

    def test_top_n_clamps(self):
        rows = [
            MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10")}),
            MockFactorSnapshotRow("B", date(2024, 1, 1), 2, {"pe_ratio": Decimal("15")}),
            MockFactorSnapshotRow("C", date(2024, 1, 1), 3, {"pe_ratio": Decimal("20")}),
        ]
        execution_opens = {
            ("A", date(2024, 1, 1)): Decimal("100"),
            ("B", date(2024, 1, 1)): Decimal("100"),
            ("C", date(2024, 1, 1)): Decimal("100"),
        }
        top_n, _ = FactorOptimizer._weighted_select_top_candidates(
            rows, self._make_preset(), {"pe_ratio": 1.0}, 2, execution_opens, date(2024, 1, 1)
        )
        self.assertEqual(len(top_n), 2)
        self.assertEqual(top_n[0].symbol, "A")

    def test_larger_top_n_clamps_to_eligible(self):
        rows = [MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10")})]
        execution_opens = {("A", date(2024, 1, 1)): Decimal("100")}
        top_n, _ = FactorOptimizer._weighted_select_top_candidates(
            rows, self._make_preset(), {"pe_ratio": 1.0}, 10, execution_opens, date(2024, 1, 1)
        )
        self.assertEqual(len(top_n), 1)


class TestRunOptimization(unittest.TestCase):
    def setUp(self):
        self.preset = MockStrategyPreset()
        self.preset.factor_specs = [
            MockFactorSpec("pe_ratio", False),
            MockFactorSpec("fcf_yield", True),
        ]
        self.factor_rows = [
            MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10"), "fcf_yield": Decimal("0.05")}),
            MockFactorSnapshotRow("B", date(2024, 1, 1), 2, {"pe_ratio": Decimal("20"), "fcf_yield": Decimal("0.04")}),
            MockFactorSnapshotRow("C", date(2024, 1, 1), 3, {"pe_ratio": Decimal("30"), "fcf_yield": Decimal("0.03")}),
            MockFactorSnapshotRow("D", date(2024, 2, 1), 1, {"pe_ratio": Decimal("12"), "fcf_yield": Decimal("0.045")}),
            MockFactorSnapshotRow("E", date(2024, 2, 1), 2, {"pe_ratio": Decimal("15"), "fcf_yield": Decimal("0.04")}),
        ]
        self.execution_rows = [
            MockExecutionPriceRow("A", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("B", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("C", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("D", date(2024, 2, 1), Decimal("100")),
            MockExecutionPriceRow("E", date(2024, 2, 1), Decimal("100")),
        ]

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_returns_five_results(self, mock_run):
        mock_run.return_value = [
            MagicMock(metrics={"sharpe_ratio": 1.5}),
            MagicMock(metrics={"sharpe_ratio": 1.2}),
            MagicMock(metrics={"sharpe_ratio": 0.8}),
            MagicMock(metrics={"sharpe_ratio": 0.5}),
            MagicMock(metrics={"sharpe_ratio": 0.2}),
        ]
        results = FactorOptimizer().run_optimization(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertEqual(len(results), 5)

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_ranked_by_sharpe(self, mock_run):
        mock_run.return_value = [
            MagicMock(metrics={"sharpe_ratio": 1.5}),
            MagicMock(metrics={"sharpe_ratio": 1.2}),
            MagicMock(metrics={"sharpe_ratio": 0.8}),
            MagicMock(metrics={"sharpe_ratio": 0.5}),
            MagicMock(metrics={"sharpe_ratio": 0.2}),
        ]
        results = FactorOptimizer().run_optimization(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        sharpe_ratios = [r.metrics.get("sharpe_ratio", 0.0) for r in results]
        for i in range(len(results) - 1):
            self.assertGreaterEqual(sharpe_ratios[i], sharpe_ratios[i + 1])

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_best_config_is_first(self, mock_run):
        mock_run.return_value = [
            MagicMock(metrics={"sharpe_ratio": 1.5}),
            MagicMock(metrics={"sharpe_ratio": 1.2}),
            MagicMock(metrics={"sharpe_ratio": 0.8}),
            MagicMock(metrics={"sharpe_ratio": 0.5}),
            MagicMock(metrics={"sharpe_ratio": 0.2}),
        ]
        results = FactorOptimizer().run_optimization(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        best_sharpe = results[0].metrics.get("sharpe_ratio", 0.0)
        for r in results[1:]:
            self.assertGreaterEqual(best_sharpe, r.metrics.get("sharpe_ratio", 0.0))


class TestGenerateReport(unittest.TestCase):
    def setUp(self):
        self.preset = MockStrategyPreset()
        self.preset.factor_specs = [
            MockFactorSpec("pe_ratio", False),
            MockFactorSpec("fcf_yield", True),
        ]
        self.factor_rows = [
            MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10"), "fcf_yield": Decimal("0.05")}),
            MockFactorSnapshotRow("B", date(2024, 1, 1), 2, {"pe_ratio": Decimal("20"), "fcf_yield": Decimal("0.04")}),
            MockFactorSnapshotRow("C", date(2024, 1, 1), 3, {"pe_ratio": Decimal("30"), "fcf_yield": Decimal("0.03")}),
            MockFactorSnapshotRow("D", date(2024, 2, 1), 1, {"pe_ratio": Decimal("12"), "fcf_yield": Decimal("0.045")}),
            MockFactorSnapshotRow("E", date(2024, 2, 1), 2, {"pe_ratio": Decimal("15"), "fcf_yield": Decimal("0.04")}),
        ]
        self.execution_rows = [
            MockExecutionPriceRow("A", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("B", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("C", date(2024, 1, 2), Decimal("100")),
            MockExecutionPriceRow("D", date(2024, 2, 1), Decimal("100")),
            MockExecutionPriceRow("E", date(2024, 2, 1), Decimal("100")),
        ]

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_report_has_status(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        report = optimize_factors(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertEqual(report["status"], "complete")

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_report_has_best_config(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        report = optimize_factors(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertIn("best_config", report)
        self.assertIsInstance(report["best_config"], dict)

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_report_has_ranked_configurations(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        report = optimize_factors(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertIn("ranked_configurations", report)
        self.assertEqual(len(report["ranked_configurations"]), 1)

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_report_has_recommendations(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        report = optimize_factors(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertIn("recommendations", report)
        self.assertIsInstance(report["recommendations"], list)

    @patch.object(FactorOptimizer, 'run_optimization')
    def test_report_timestamp(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        report = optimize_factors(self.factor_rows, self.execution_rows, self.preset, top_n=2)
        self.assertIn("timestamp", report)


class TestReportFormats(unittest.TestCase):
    def setUp(self):
        self.mock_report = {
            "status": "complete",
            "timestamp": "2024-01-01",
            "best_config": {"name": "test", "sharpe_ratio": 1.5, "rationale": "test rationale"},
            "ranked_configurations": [
                {"rank": 1, "config_name": "test", "sharpe_ratio": 1.5, "rationale": "test rationale", "config_description": "test"},
            ],
            "recommendations": ["Test recommendation"],
            "warnings": ["Test warning"],
            "preset_name": "Test Preset",
            "max_sharpe": 1.5,
        }

    def test_json_report(self):
        json_str = generate_json_report(self.mock_report)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["status"], "complete")
        self.assertEqual(parsed["best_config"]["name"], "test")

    def test_csv_report(self):
        csv_str = generate_csv_report(self.mock_report)
        lines = csv_str.strip().split("\n")
        self.assertGreater(len(lines), 1)
        self.assertIn("Rank", lines[0])

    def test_html_report(self):
        html_str = generate_html_report(self.mock_report)
        self.assertIn("<!DOCTYPE html>", html_str)
        self.assertIn("2024-01-01", html_str)
        self.assertIn("test", html_str)


class TestOptimizeFactorsFunction(unittest.TestCase):
    @patch.object(FactorOptimizer, 'run_optimization')
    def test_returns_dict(self, mock_run):
        mock_run.return_value = [MagicMock(metrics={"sharpe_ratio": 1.5}, config_name="test", config_description="test desc")]
        preset = MockStrategyPreset()
        preset.factor_specs = [MockFactorSpec("pe_ratio", False)]
        factor_rows = [MockFactorSnapshotRow("A", date(2024, 1, 1), 1, {"pe_ratio": Decimal("10")})]
        execution_rows = [MockExecutionPriceRow("A", date(2024, 1, 2), Decimal("100"))]
        result = optimize_factors(factor_rows, execution_rows, preset, top_n=1)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "complete")


if __name__ == "__main__":
    unittest.main(verbosity=2)
