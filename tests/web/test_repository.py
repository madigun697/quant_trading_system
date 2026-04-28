from __future__ import annotations

from datetime import date

from quant_data_platform.web.presets import StrategyPresetId, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import BacktestRepository


def test_factor_query_uses_correct_mart_table() -> None:
    repo = BacktestRepository()
    preset = get_strategy_preset(StrategyPresetId.VALUE_MOMENTUM)
    query = repo.factor_query(preset)
    assert "from mart.mart_value_momentum_inputs" in query
    assert "momentum_12_1" in query


def test_calendar_query_uses_spy_benchmark_series() -> None:
    repo = BacktestRepository()
    query = repo.calendar_query()
    assert "from stg.stg_benchmark_series" in query
    assert "benchmark_name = 'SPY'" in query


def test_execution_price_query_reads_stg_daily_prices() -> None:
    repo = BacktestRepository()
    query = repo.execution_price_query()
    assert "from stg.stg_daily_prices" in query
    assert "coalesce(adjusted_open, open)" in query


def test_compute_factor_buffer_start_matches_preset_needs() -> None:
    repo = BacktestRepository()
    start_date = date(2024, 6, 15)
    assert repo.compute_factor_buffer_start(StrategyPresetId.VALUE_QUALITY, start_date) == date(2024, 6, 1)
    assert repo.compute_factor_buffer_start(StrategyPresetId.VALUE_MOMENTUM, start_date) < start_date
    assert repo.compute_factor_buffer_start(StrategyPresetId.QUALITY_LOWVOL, start_date) < start_date
