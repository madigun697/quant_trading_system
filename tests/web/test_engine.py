from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_data_platform.web.presets import StrategyPresetId, TransactionCostPreset, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import BenchmarkValueRow, DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow
from quant_data_platform.web.schemas import BacktestFormInput, PageState
from quant_data_platform.web.services.engine import (
    execution_schedule,
    month_end_signal_dates,
    select_top_candidates,
    simulate_backtest,
)


def make_form(**overrides) -> BacktestFormInput:
    payload = {
        "strategy_preset": StrategyPresetId.VALUE_QUALITY,
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 3, 1),
        "initial_capital": Decimal("1000"),
        "top_n": 10,
        "transaction_cost_preset": TransactionCostPreset.CONSERVATIVE,
    }
    payload.update(overrides)
    return BacktestFormInput(**payload)


def test_month_end_signal_dates_uses_last_trading_day_per_month() -> None:
    calendar = [
        date(2024, 1, 30),
        date(2024, 1, 31),
        date(2024, 2, 28),
        date(2024, 2, 29),
        date(2024, 3, 28),
    ]
    assert month_end_signal_dates(calendar, date(2024, 1, 1), date(2024, 3, 31)) == [
        date(2024, 1, 31),
        date(2024, 2, 29),
        date(2024, 3, 28),
    ]


def test_execution_schedule_uses_next_trading_day_within_range() -> None:
    calendar = [
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    schedule = execution_schedule(calendar, [date(2024, 1, 31), date(2024, 2, 29)], date(2024, 3, 1))
    assert schedule == {
        date(2024, 1, 31): date(2024, 2, 1),
        date(2024, 2, 29): date(2024, 3, 1),
    }


def test_select_top_candidates_uses_liquidity_then_symbol_as_tie_breaker() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    rows = [
        FactorSnapshotRow("BBB", date(2024, 1, 31), 2, {factor.column: Decimal("1") for factor in preset.factor_specs}),
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, {factor.column: Decimal("1") for factor in preset.factor_specs}),
    ]
    selected, excluded = select_top_candidates(
        rows,
        preset,
        1,
        {("AAA", date(2024, 2, 1)): Decimal("10"), ("BBB", date(2024, 2, 1)): Decimal("10")},
        date(2024, 2, 1),
    )
    assert excluded == {"missing_factors": 0, "missing_execution_open": 0}
    assert [row.symbol for row in selected] == ["AAA"]


def test_simulate_backtest_runs_buy_sell_sequence_and_costs() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    calendar = [
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    base_factors = {factor.column: Decimal("1") for factor in preset.factor_specs}
    stronger_factors = {factor.column: Decimal("2") for factor in preset.factor_specs}
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, stronger_factors),
        FactorSnapshotRow("BBB", date(2024, 1, 31), 2, {**base_factors, "pe_ratio": None}),
        FactorSnapshotRow("AAA", date(2024, 2, 29), 2, {**base_factors, "pe_ratio": None}),
        FactorSnapshotRow("BBB", date(2024, 2, 29), 1, stronger_factors),
    ]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("BBB", date(2024, 2, 1), Decimal("20")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("AAA", date(2024, 3, 1), Decimal("11")),
        ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("25")),
        ExecutionPriceRow("SPY", date(2024, 3, 1), Decimal("105")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 29), Decimal("11")),
        DailyCloseRow("AAA", date(2024, 3, 1), Decimal("11")),
        DailyCloseRow("BBB", date(2024, 2, 1), Decimal("20")),
        DailyCloseRow("BBB", date(2024, 2, 29), Decimal("24")),
        DailyCloseRow("BBB", date(2024, 3, 1), Decimal("25")),
    ]
    benchmark_rows = [
        BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
        BenchmarkValueRow(date(2024, 2, 29), Decimal("104")),
        BenchmarkValueRow(date(2024, 3, 1), Decimal("105")),
    ]
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=benchmark_rows,
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )

    assert result.state == PageState.SUCCESS
    assert [row.action for row in result.fill_rows[:3]] == ["BUY", "SELL", "BUY"]
    assert result.summary_metrics["trade_count"] == 3
    assert result.summary_metrics["total_fees"] > 0
    assert result.summary_rows[0].selected_count == 1
    assert result.summary_rows[1].sold_count == 1
    assert result.equity_curve[-1].benchmark_equity is not None


def test_simulate_backtest_excludes_missing_factor_rows() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    rows = [
        FactorSnapshotRow(
            "AAA",
            date(2024, 1, 31),
            1,
            {**{factor.column: Decimal("1") for factor in preset.factor_specs}, "pe_ratio": None},
        )
    ]
    result = simulate_backtest(
        input_data=form,
        calendar_dates=[date(2024, 1, 31), date(2024, 2, 1)],
        factor_rows=rows,
        execution_price_rows=[ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10"))],
        daily_close_rows=[DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10"))],
        benchmark_rows=[BenchmarkValueRow(date(2024, 2, 1), Decimal("100"))],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.NO_DATA
    assert result.unavailable_reasons


def test_simulate_backtest_returns_insufficient_history_when_all_signals_precede_data() -> None:
    result = simulate_backtest(
        input_data=make_form(),
        calendar_dates=[date(2024, 1, 31), date(2024, 2, 1)],
        factor_rows=[],
        execution_price_rows=[],
        daily_close_rows=[],
        benchmark_rows=[BenchmarkValueRow(date(2024, 2, 1), Decimal("100"))],
        earliest_available_trade_date=date(2024, 5, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.INSUFFICIENT_HISTORY
    assert result.unavailable_reasons[0].code == "insufficient_history"


def test_simulate_backtest_marks_all_null_factor_month_as_insufficient_history() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    all_null_factors = {factor.column: None for factor in preset.factor_specs}
    result = simulate_backtest(
        input_data=form,
        calendar_dates=[date(2024, 1, 31), date(2024, 2, 1)],
        factor_rows=[FactorSnapshotRow("AAA", date(2024, 1, 31), 1, all_null_factors)],
        execution_price_rows=[ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10"))],
        daily_close_rows=[DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10"))],
        benchmark_rows=[BenchmarkValueRow(date(2024, 2, 1), Decimal("100"))],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.INSUFFICIENT_HISTORY


def test_simulate_backtest_returns_error_when_sell_execution_price_is_missing() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    stronger_factors = {factor.column: Decimal("2") for factor in preset.factor_specs}
    weaker_factors = {factor.column: Decimal("1") for factor in preset.factor_specs}
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, stronger_factors),
        FactorSnapshotRow("AAA", date(2024, 2, 29), 2, weaker_factors),
        FactorSnapshotRow("BBB", date(2024, 2, 29), 1, stronger_factors),
    ]
    result = simulate_backtest(
        input_data=form,
        calendar_dates=[date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 29), date(2024, 3, 1)],
        factor_rows=factor_rows,
        execution_price_rows=[
            ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
            ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("12")),
        ],
        daily_close_rows=[
            DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
            DailyCloseRow("BBB", date(2024, 3, 1), Decimal("12")),
        ],
        benchmark_rows=[BenchmarkValueRow(date(2024, 2, 1), Decimal("100")), BenchmarkValueRow(date(2024, 3, 1), Decimal("105"))],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.ERROR
    assert result.unavailable_reasons[0].code == "missing_rebalance_price"


def test_simulate_backtest_rebalances_only_delta_for_overlapping_holdings() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    medium = {factor.column: Decimal("1.5") for factor in preset.factor_specs}
    weak = {factor.column: Decimal("1") for factor in preset.factor_specs}
    calendar = [
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong),
        FactorSnapshotRow("BBB", date(2024, 1, 31), 2, medium),
        FactorSnapshotRow("AAA", date(2024, 2, 29), 1, strong),
        FactorSnapshotRow("CCC", date(2024, 2, 29), 2, weak),
    ]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("BBB", date(2024, 2, 1), Decimal("20")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("AAA", date(2024, 3, 1), Decimal("12")),
        ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("18")),
        ExecutionPriceRow("CCC", date(2024, 3, 1), Decimal("15")),
        ExecutionPriceRow("SPY", date(2024, 3, 1), Decimal("101")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("BBB", date(2024, 2, 1), Decimal("20")),
        DailyCloseRow("AAA", date(2024, 2, 29), Decimal("11")),
        DailyCloseRow("BBB", date(2024, 2, 29), Decimal("19")),
        DailyCloseRow("AAA", date(2024, 3, 1), Decimal("12")),
        DailyCloseRow("BBB", date(2024, 3, 1), Decimal("18")),
        DailyCloseRow("CCC", date(2024, 3, 1), Decimal("15")),
    ]
    result = simulate_backtest(
        input_data=make_form(),
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[BenchmarkValueRow(date(2024, 2, 1), Decimal("100")), BenchmarkValueRow(date(2024, 2, 29), Decimal("100")), BenchmarkValueRow(date(2024, 3, 1), Decimal("101"))],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    sell_symbols = [row.symbol for row in result.fill_rows if row.action == "SELL"]
    buy_symbols = [row.symbol for row in result.fill_rows if row.action == "BUY"]
    assert result.state == PageState.SUCCESS
    assert sell_symbols.count("AAA") == 1
    assert sell_symbols.count("BBB") == 1
    assert buy_symbols.count("AAA") == 1
    assert buy_symbols.count("CCC") == 1
    assert result.summary_rows[-1].turnover < Decimal("2")


def test_simulate_backtest_warns_when_benchmark_anchor_is_missing() -> None:
    form = make_form()
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    result = simulate_backtest(
        input_data=form,
        calendar_dates=[date(2024, 1, 31), date(2024, 2, 1)],
        factor_rows=[FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong)],
        execution_price_rows=[ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10"))],
        daily_close_rows=[DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10"))],
        benchmark_rows=[],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert all(point.benchmark_equity is None for point in result.equity_curve)
    assert any(warning.title == "SPY 비교선 제외" for warning in result.warnings)
