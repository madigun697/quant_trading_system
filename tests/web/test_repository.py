from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg
from quant_data_platform.web.presets import TRANSACTION_COST_BPS, StrategyPresetId, TransactionCostPreset, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import BacktestRepository


def test_factor_query_uses_correct_mart_table() -> None:
    repo = BacktestRepository()
    preset = get_strategy_preset(StrategyPresetId.VALUE_MOMENTUM)
    query = repo.factor_query(preset)
    assert "from mart.mart_value_momentum_inputs" in query
    assert "momentum_12_1" in query
    assert "liquidity_rank nulls last" in query


def test_calendar_query_uses_spy_benchmark_series() -> None:
    repo = BacktestRepository()
    query = repo.calendar_query()
    assert "from stg.stg_benchmark_series" in query
    assert "benchmark_name = 'SPY'" in query


def test_benchmark_value_query_reads_spy_series_value() -> None:
    repo = BacktestRepository()
    query = repo.benchmark_value_query()
    assert "select observation_date, value" in query
    assert "from stg.stg_benchmark_series" in query


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


def test_required_relations_include_selected_mart_and_staging_tables() -> None:
    repo = BacktestRepository()
    relations = repo.required_relations(StrategyPresetId.VALUE_QUALITY)
    assert relations == (
        "stg.stg_daily_prices",
        "stg.stg_benchmark_series",
        "mart.mart_value_quality_inputs",
    )


def test_classify_error_marks_operational_failures_as_database_unreachable() -> None:
    repo = BacktestRepository()
    readiness = repo.classify_error(psycopg.OperationalError("failed to resolve host 'postgres'"), StrategyPresetId.VALUE_QUALITY)
    assert readiness.ok is False
    assert readiness.code == "database_unreachable"


def test_normalize_liquidity_rank_pushes_nulls_to_the_back() -> None:
    repo = BacktestRepository()
    assert repo.normalize_liquidity_rank(None) == repo.NULL_LIQUIDITY_RANK
    assert repo.normalize_liquidity_rank("7") == 7


def test_transaction_cost_presets_are_stored_as_round_trip_totals() -> None:
    assert TRANSACTION_COST_BPS[TransactionCostPreset.LOW] == 0.0005
    assert TRANSACTION_COST_BPS[TransactionCostPreset.BASE] == 0.00125
    assert TRANSACTION_COST_BPS[TransactionCostPreset.CONSERVATIVE] == 0.0025


def test_backtest_result_tables_use_mart_schema() -> None:
    repo = BacktestRepository()
    ddl = "\n".join(repo.BACKTEST_RESULT_TABLE_SQL)
    assert "create table if not exists mart.backtest_run_summary" in ddl
    assert "create table if not exists mart.backtest_equity_curve" in ddl
    assert "create table if not exists mart.backtest_rebalance_summary" in ddl
    assert "create table if not exists mart.backtest_fill_log" in ddl
    assert "references mart.backtest_run_summary(run_id) on delete cascade" in ddl
    assert "create table if not exists stg." not in ddl
    assert "create table if not exists raw." not in ddl


def test_saved_run_id_matches_swing_timestamp_format() -> None:
    run_id = BacktestRepository.generate_run_id(datetime(2024, 4, 1, 9, 30, 0, 123456, tzinfo=timezone.utc))
    assert run_id == "bt-20240401T093000123456Z"


def test_backtest_repository_exposes_result_persistence_methods() -> None:
    repo = BacktestRepository()
    assert callable(repo.ensure_backtest_result_tables)
    assert callable(repo.save_simulation_result)
    assert callable(repo.list_recent_runs)
    assert callable(repo.fetch_saved_run)
