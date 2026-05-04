from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from quant_data_platform.web.presets import MarketTimingOverlayId, StrategyPresetId, TransactionCostPreset, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import BenchmarkValueRow, DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow
from quant_data_platform.web.schemas import BacktestFormInput, PageState
from quant_data_platform.web.services.engine import (
    execution_schedule,
    evaluate_daily_overlay_signal,
    month_end_signal_dates,
    select_top_candidates,
    select_top_candidates_by_close,
    simulate_backtest,
)


def make_form(**overrides) -> BacktestFormInput:
    payload = {
        "strategy_preset": StrategyPresetId.VALUE_QUALITY,
        "market_timing_overlay": MarketTimingOverlayId.NONE,
        "safe_asset_weight_sgov": Decimal("100"),
        "safe_asset_weight_jpst": Decimal("0"),
        "safe_asset_weight_ief": Decimal("0"),
        "safe_asset_weight_tlt": Decimal("0"),
        "safe_asset_weight_gld": Decimal("0"),
        "safe_asset_weight_xle": Decimal("0"),
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


def test_select_top_candidates_by_close_uses_close_availability_after_ranking() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, {factor.column: Decimal("2") for factor in preset.factor_specs}),
        FactorSnapshotRow("BBB", date(2024, 1, 31), 2, {factor.column: Decimal("1") for factor in preset.factor_specs}),
    ]
    selected, excluded = select_top_candidates_by_close(
        rows,
        preset,
        1,
        {("AAA", date(2024, 1, 31)): None, ("BBB", date(2024, 1, 31)): Decimal("20")},
        date(2024, 1, 31),
    )
    assert excluded == {"missing_factors": 0, "missing_reference_close": 1}
    assert [row.symbol for row in selected] == ["BBB"]


def test_evaluate_daily_overlay_signal_can_return_risk_off() -> None:
    rows = [
        DailyCloseRow("SPY", date(2024, 1, 1) + timedelta(days=index), Decimal("100"))
        for index in range(50)
    ]
    rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 2, 20), Decimal("80")),
            DailyCloseRow("SPY", date(2024, 2, 21), Decimal("79")),
            DailyCloseRow("SPY", date(2024, 2, 22), Decimal("78")),
        ]
    )

    signal = evaluate_daily_overlay_signal(
        MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        date(2024, 2, 22),
        rows,
    )

    assert signal.risk_on is False


def test_evaluate_daily_overlay_signal_stays_risk_on_before_third_breach_day() -> None:
    rows = [
        DailyCloseRow("SPY", date(2024, 1, 1) + timedelta(days=index), Decimal("100"))
        for index in range(50)
    ]
    rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 2, 20), Decimal("80")),
            DailyCloseRow("SPY", date(2024, 2, 21), Decimal("79")),
        ]
    )

    signal = evaluate_daily_overlay_signal(
        MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        date(2024, 2, 21),
        rows,
    )

    assert signal.risk_on is True


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


def test_simulate_backtest_daily_emergency_brake_moves_to_selected_safe_asset() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        start_date=date(2024, 1, 31),
        end_date=date(2024, 2, 7),
    )
    calendar = [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2), date(2024, 2, 5), date(2024, 2, 6), date(2024, 2, 7)]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    factor_rows = [FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong)]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 7), Decimal("10")),
        ExecutionPriceRow("SGOV", date(2024, 2, 7), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 7), Decimal("88")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 2), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 5), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 6), Decimal("10")),
        DailyCloseRow("SGOV", date(2024, 2, 6), Decimal("100")),
        DailyCloseRow("SGOV", date(2024, 2, 7), Decimal("100")),
    ]
    for offset in range(90):
        trade_date = date(2023, 11, 15) + timedelta(days=offset)
        if trade_date.weekday() < 5 and trade_date < date(2024, 1, 31):
            daily_rows.append(DailyCloseRow("SPY", trade_date, Decimal("100")))
    daily_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 1, 31), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 2, 1), Decimal("101")),
            DailyCloseRow("SPY", date(2024, 2, 2), Decimal("90")),
            DailyCloseRow("SPY", date(2024, 2, 5), Decimal("89")),
            DailyCloseRow("SPY", date(2024, 2, 6), Decimal("88")),
            DailyCloseRow("SPY", date(2024, 2, 7), Decimal("87")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 2), Decimal("90")),
            BenchmarkValueRow(date(2024, 2, 5), Decimal("89")),
            BenchmarkValueRow(date(2024, 2, 6), Decimal("88")),
            BenchmarkValueRow(date(2024, 2, 7), Decimal("87")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert any(row.notes == "daily risk_off: factor basket -> SGOV 100%" for row in result.summary_rows)
    assert [row.symbol for row in result.fill_rows if row.execution_date == date(2024, 2, 7) and row.action == "BUY"] == ["SGOV"]


def test_simulate_backtest_waits_until_month_end_before_reentering_factor_basket() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        start_date=date(2024, 1, 31),
        end_date=date(2024, 3, 1),
    )
    calendar = [
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 2),
        date(2024, 2, 5),
        date(2024, 2, 6),
        date(2024, 2, 7),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    stronger = {factor.column: Decimal("3") for factor in preset.factor_specs}
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong),
        FactorSnapshotRow("BBB", date(2024, 2, 29), 1, stronger),
    ]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 7), Decimal("10")),
        ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("20")),
        ExecutionPriceRow("SGOV", date(2024, 2, 7), Decimal("100")),
        ExecutionPriceRow("SGOV", date(2024, 3, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 7), Decimal("87")),
        ExecutionPriceRow("SPY", date(2024, 3, 1), Decimal("110")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 2), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 5), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 6), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 7), Decimal("10")),
        DailyCloseRow("SGOV", date(2024, 2, 7), Decimal("100")),
        DailyCloseRow("SGOV", date(2024, 2, 29), Decimal("100.3")),
        DailyCloseRow("SGOV", date(2024, 3, 1), Decimal("100.4")),
    ]
    for offset in range(320):
        trade_date = date(2023, 1, 2) + timedelta(days=offset)
        if trade_date.weekday() < 5:
            daily_rows.append(DailyCloseRow("SPY", trade_date, Decimal("100")))
    daily_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 1, 31), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 2, 1), Decimal("101")),
            DailyCloseRow("SPY", date(2024, 2, 2), Decimal("90")),
            DailyCloseRow("SPY", date(2024, 2, 5), Decimal("89")),
            DailyCloseRow("SPY", date(2024, 2, 6), Decimal("88")),
            DailyCloseRow("SPY", date(2024, 2, 7), Decimal("87")),
            DailyCloseRow("SPY", date(2024, 2, 29), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 3, 1), Decimal("111")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 2), Decimal("90")),
            BenchmarkValueRow(date(2024, 2, 5), Decimal("89")),
            BenchmarkValueRow(date(2024, 2, 6), Decimal("88")),
            BenchmarkValueRow(date(2024, 2, 7), Decimal("87")),
            BenchmarkValueRow(date(2024, 2, 29), Decimal("110")),
            BenchmarkValueRow(date(2024, 3, 1), Decimal("111")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert any(row.notes == "daily risk_off: factor basket -> SGOV 100%" for row in result.summary_rows)
    assert any(row.notes == "month-end risk_on: SGOV 100% -> factor basket" for row in result.summary_rows)
    march_buys = [row.symbol for row in result.fill_rows if row.execution_date == date(2024, 3, 1) and row.action == "BUY"]
    assert march_buys == ["BBB"]


def test_simulate_backtest_daily_emergency_brake_overrides_month_end_reentry_on_third_breach_day() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        start_date=date(2024, 1, 31),
        end_date=date(2024, 3, 1),
    )
    calendar = [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 27), date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    stronger = {factor.column: Decimal("3") for factor in preset.factor_specs}
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong),
        FactorSnapshotRow("BBB", date(2024, 2, 29), 1, stronger),
    ]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 3, 1), Decimal("10")),
        ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("20")),
        ExecutionPriceRow("SGOV", date(2024, 3, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 3, 1), Decimal("100")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 1, 31), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 27), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 28), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 29), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 3, 1), Decimal("10")),
        DailyCloseRow("SGOV", date(2024, 3, 1), Decimal("100")),
    ]
    for offset in range(360):
        trade_date = date(2023, 4, 3) + timedelta(days=offset)
        if trade_date.weekday() >= 5 or trade_date >= date(2024, 2, 27):
            continue
        if trade_date < date(2024, 1, 1):
            close_value = Decimal("50")
        elif trade_date < date(2024, 1, 10):
            close_value = Decimal("60")
        elif trade_date < date(2024, 2, 1):
            close_value = Decimal("160")
        elif trade_date < date(2024, 2, 9):
            close_value = Decimal("80")
        else:
            close_value = Decimal("160")
        daily_rows.append(DailyCloseRow("SPY", trade_date, close_value))
    daily_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 2, 27), Decimal("100")),
            DailyCloseRow("SPY", date(2024, 2, 28), Decimal("99")),
            DailyCloseRow("SPY", date(2024, 2, 29), Decimal("98")),
            DailyCloseRow("SPY", date(2024, 3, 1), Decimal("97")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 27), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 28), Decimal("99")),
            BenchmarkValueRow(date(2024, 2, 29), Decimal("98")),
            BenchmarkValueRow(date(2024, 3, 1), Decimal("97")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert any(row.notes == "daily risk_off: factor basket -> SGOV 100%" for row in result.summary_rows)
    march_buys = [row.symbol for row in result.fill_rows if row.execution_date == date(2024, 3, 1) and row.action == "BUY"]
    assert march_buys == ["SGOV"]


def test_simulate_backtest_canary_signal_uses_ief_but_parks_in_jpst() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.CANARY_ASSET_SIGNAL,
        safe_asset_weight_sgov=Decimal("0"),
        safe_asset_weight_jpst=Decimal("100"),
        start_date=date(2024, 1, 31),
        end_date=date(2024, 2, 5),
    )
    calendar = [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2), date(2024, 2, 5)]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    factor_rows = [FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong)]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 5), Decimal("10")),
        ExecutionPriceRow("JPST", date(2024, 2, 5), Decimal("50")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 5), Decimal("99")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 2), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 5), Decimal("10")),
        DailyCloseRow("JPST", date(2024, 2, 5), Decimal("50")),
    ]
    for offset in range(140):
        trade_date = date(2023, 8, 1) + timedelta(days=offset)
        if trade_date.weekday() < 5:
            daily_rows.append(DailyCloseRow("VT", trade_date, Decimal("110")))
            daily_rows.append(DailyCloseRow("IEF", trade_date, Decimal("100")))
    daily_rows.extend(
        [
            DailyCloseRow("VT", date(2024, 1, 31), Decimal("120")),
            DailyCloseRow("VT", date(2024, 2, 1), Decimal("119")),
            DailyCloseRow("VT", date(2024, 2, 2), Decimal("88")),
            DailyCloseRow("VT", date(2024, 2, 5), Decimal("87")),
            DailyCloseRow("IEF", date(2024, 1, 31), Decimal("101")),
            DailyCloseRow("IEF", date(2024, 2, 1), Decimal("101.2")),
            DailyCloseRow("IEF", date(2024, 2, 2), Decimal("106")),
            DailyCloseRow("IEF", date(2024, 2, 5), Decimal("106.5")),
            DailyCloseRow("SPY", date(2024, 1, 31), Decimal("100")),
            DailyCloseRow("SPY", date(2024, 2, 1), Decimal("101")),
            DailyCloseRow("SPY", date(2024, 2, 2), Decimal("98")),
            DailyCloseRow("SPY", date(2024, 2, 5), Decimal("97")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("99")),
            BenchmarkValueRow(date(2024, 2, 2), Decimal("98")),
            BenchmarkValueRow(date(2024, 2, 5), Decimal("97")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert any(row.notes == "daily risk_off: factor basket -> JPST 100%" for row in result.summary_rows)
    assert [row.symbol for row in result.fill_rows if row.execution_date == date(2024, 2, 5) and row.action == "BUY"] == ["JPST"]


def test_simulate_backtest_daily_risk_off_respects_safe_asset_weights() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        safe_asset_weight_sgov=Decimal("60"),
        safe_asset_weight_ief=Decimal("40"),
        start_date=date(2024, 1, 31),
        end_date=date(2024, 2, 7),
    )
    calendar = [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2), date(2024, 2, 5), date(2024, 2, 6), date(2024, 2, 7)]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    factor_rows = [FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong)]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 7), Decimal("10")),
        ExecutionPriceRow("IEF", date(2024, 2, 7), Decimal("100")),
        ExecutionPriceRow("SGOV", date(2024, 2, 7), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 7), Decimal("87")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 2), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 5), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 6), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 7), Decimal("10")),
        DailyCloseRow("IEF", date(2024, 2, 7), Decimal("100")),
        DailyCloseRow("SGOV", date(2024, 2, 7), Decimal("100")),
    ]
    for offset in range(90):
        trade_date = date(2023, 11, 15) + timedelta(days=offset)
        if trade_date.weekday() < 5 and trade_date < date(2024, 1, 31):
            daily_rows.append(DailyCloseRow("SPY", trade_date, Decimal("100")))
    daily_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 1, 31), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 2, 1), Decimal("101")),
            DailyCloseRow("SPY", date(2024, 2, 2), Decimal("90")),
            DailyCloseRow("SPY", date(2024, 2, 5), Decimal("89")),
            DailyCloseRow("SPY", date(2024, 2, 6), Decimal("88")),
            DailyCloseRow("SPY", date(2024, 2, 7), Decimal("87")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 2), Decimal("90")),
            BenchmarkValueRow(date(2024, 2, 5), Decimal("89")),
            BenchmarkValueRow(date(2024, 2, 6), Decimal("88")),
            BenchmarkValueRow(date(2024, 2, 7), Decimal("87")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.SUCCESS
    assert any(row.notes == "daily risk_off: factor basket -> SGOV 60% / IEF 40%" for row in result.summary_rows)
    buy_rows = [row for row in result.fill_rows if row.execution_date == date(2024, 2, 7) and row.action == "BUY"]
    assert [row.symbol for row in buy_rows] == ["IEF", "SGOV"]
    buy_notionals = {row.symbol: row.shares * row.execution_price for row in buy_rows}
    total_buy = sum(buy_notionals.values(), start=Decimal("0"))
    assert total_buy > 0
    assert float(buy_notionals["IEF"] / total_buy) == pytest.approx(0.4, abs=1e-6)
    assert float(buy_notionals["SGOV"] / total_buy) == pytest.approx(0.6, abs=1e-6)


def test_simulate_backtest_returns_error_when_safe_asset_open_is_missing_on_risk_off_entry() -> None:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    form = make_form(
        market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        start_date=date(2024, 1, 31),
        end_date=date(2024, 3, 1),
    )
    calendar = [
        date(2024, 1, 31),
        date(2024, 2, 1),
        date(2024, 2, 2),
        date(2024, 2, 5),
        date(2024, 2, 6),
        date(2024, 2, 7),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    strong = {factor.column: Decimal("2") for factor in preset.factor_specs}
    stronger = {factor.column: Decimal("3") for factor in preset.factor_specs}
    factor_rows = [
        FactorSnapshotRow("AAA", date(2024, 1, 31), 1, strong),
        FactorSnapshotRow("BBB", date(2024, 2, 29), 1, stronger),
    ]
    execution_rows = [
        ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 7), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 2, 29), Decimal("10")),
        ExecutionPriceRow("AAA", date(2024, 3, 1), Decimal("10")),
        ExecutionPriceRow("BBB", date(2024, 3, 1), Decimal("20")),
        ExecutionPriceRow("SPY", date(2024, 2, 1), Decimal("100")),
        ExecutionPriceRow("SPY", date(2024, 2, 7), Decimal("87")),
        ExecutionPriceRow("SPY", date(2024, 3, 1), Decimal("110")),
    ]
    daily_rows = [
        DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 2), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 5), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 6), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 7), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 2, 29), Decimal("10")),
        DailyCloseRow("AAA", date(2024, 3, 1), Decimal("10")),
        DailyCloseRow("BBB", date(2024, 3, 1), Decimal("20")),
    ]
    for offset in range(320):
        trade_date = date(2023, 1, 2) + timedelta(days=offset)
        if trade_date.weekday() < 5:
            daily_rows.append(DailyCloseRow("SPY", trade_date, Decimal("100")))
    daily_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 1, 31), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 2, 1), Decimal("101")),
            DailyCloseRow("SPY", date(2024, 2, 2), Decimal("90")),
            DailyCloseRow("SPY", date(2024, 2, 5), Decimal("89")),
            DailyCloseRow("SPY", date(2024, 2, 6), Decimal("88")),
            DailyCloseRow("SPY", date(2024, 2, 7), Decimal("87")),
            DailyCloseRow("SPY", date(2024, 2, 29), Decimal("110")),
            DailyCloseRow("SPY", date(2024, 3, 1), Decimal("111")),
        ]
    )
    result = simulate_backtest(
        input_data=form,
        calendar_dates=calendar,
        factor_rows=factor_rows,
        execution_price_rows=execution_rows,
        daily_close_rows=daily_rows,
        benchmark_rows=[
            BenchmarkValueRow(date(2024, 2, 1), Decimal("100")),
            BenchmarkValueRow(date(2024, 2, 2), Decimal("90")),
            BenchmarkValueRow(date(2024, 2, 5), Decimal("89")),
            BenchmarkValueRow(date(2024, 2, 6), Decimal("88")),
            BenchmarkValueRow(date(2024, 2, 7), Decimal("87")),
            BenchmarkValueRow(date(2024, 2, 29), Decimal("110")),
            BenchmarkValueRow(date(2024, 3, 1), Decimal("111")),
        ],
        earliest_available_trade_date=date(2024, 1, 31),
        transaction_cost_rate=Decimal("0.005"),
    )
    assert result.state == PageState.ERROR
    assert result.error_message == "2024-02-07 체결일에 SGOV 시가가 없어 목표 포트폴리오를 만들 수 없습니다."
