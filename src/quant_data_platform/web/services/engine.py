from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import sqrt
from statistics import mean, pstdev

from quant_data_platform.web.presets import StrategyPreset, StrategyPresetId, TransactionCostPreset, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow
from quant_data_platform.web.schemas import BacktestFormInput, PageState


@dataclass
class Position:
    shares: Decimal
    entry_price: Decimal
    entry_date: date
    entry_fee: Decimal


@dataclass(frozen=True)
class EquityPoint:
    date: date
    gross_equity: Decimal
    net_equity: Decimal


@dataclass(frozen=True)
class RebalanceSummary:
    signal_date: date
    execution_date: date
    selected_count: int
    sold_count: int
    buy_notional: Decimal
    sell_notional: Decimal
    fees: Decimal
    turnover: Decimal
    notes: str | None = None


@dataclass(frozen=True)
class FillEvent:
    execution_date: date
    signal_date: date
    symbol: str
    action: str
    shares: Decimal
    execution_price: Decimal
    fees: Decimal
    net_cash_flow: Decimal
    realized_pnl: Decimal | None = None
    holding_days: int | None = None


@dataclass(frozen=True)
class WarningEvent:
    title: str
    body: str
    tone: str = "warning"


@dataclass(frozen=True)
class SimulationResult:
    state: PageState
    equity_curve: list[EquityPoint]
    summary_rows: list[RebalanceSummary]
    fill_rows: list[FillEvent]
    warnings: list[WarningEvent]
    data_quality_flags: list[str]
    summary_metrics: dict[str, Decimal | float | int]
    error_message: str | None = None


def month_end_signal_dates(calendar_dates: list[date], start_date: date, end_date: date) -> list[date]:
    filtered = [calendar_date for calendar_date in calendar_dates if start_date <= calendar_date <= end_date]
    if not filtered:
        return []
    signal_dates: list[date] = []
    current_month = (filtered[0].year, filtered[0].month)
    month_last = filtered[0]
    for calendar_date in filtered[1:]:
        month_key = (calendar_date.year, calendar_date.month)
        if month_key != current_month:
            signal_dates.append(month_last)
            current_month = month_key
        month_last = calendar_date
    signal_dates.append(month_last)
    return signal_dates


def execution_schedule(calendar_dates: list[date], signal_dates: list[date], end_date: date) -> dict[date, date]:
    schedule: dict[date, date] = {}
    index_by_date = {calendar_date: index for index, calendar_date in enumerate(calendar_dates)}
    for signal_date in signal_dates:
        index = index_by_date.get(signal_date)
        if index is None or index + 1 >= len(calendar_dates):
            continue
        execution_date = calendar_dates[index + 1]
        if execution_date <= end_date:
            schedule[signal_date] = execution_date
    return schedule


def percentile_scores(rows: list[FactorSnapshotRow], column: str, higher_is_better: bool) -> dict[str, float]:
    if not rows:
        return {}
    value_groups: dict[Decimal, list[str]] = defaultdict(list)
    for row in rows:
        value = row.factors[column]
        if value is not None:
            value_groups[Decimal(value)].append(row.symbol)
    sorted_values = sorted(value_groups.keys(), reverse=higher_is_better)
    population = sum(len(symbols) for symbols in value_groups.values())
    if population <= 1:
        return {symbols[0]: 1.0 for symbols in value_groups.values() for _ in [0]}
    scores: dict[str, float] = {}
    rank_cursor = 0
    for value in sorted_values:
        symbols = sorted(value_groups[value])
        average_position = rank_cursor + (len(symbols) - 1) / 2
        score = 1.0 - (average_position / (population - 1))
        for symbol in symbols:
            scores[symbol] = score
        rank_cursor += len(symbols)
    return scores


def select_top_candidates(
    rows: list[FactorSnapshotRow],
    preset: StrategyPreset,
    top_n: int,
    execution_opens: dict[tuple[str, date], Decimal],
    execution_date: date,
) -> tuple[list[FactorSnapshotRow], dict[str, int]]:
    eligible_rows: list[FactorSnapshotRow] = []
    excluded_counts = {"missing_factors": 0, "missing_execution_open": 0}
    for row in rows:
        if any(row.factors[factor.column] is None for factor in preset.factor_specs):
            excluded_counts["missing_factors"] += 1
            continue
        if execution_opens.get((row.symbol, execution_date)) is None:
            excluded_counts["missing_execution_open"] += 1
            continue
        eligible_rows.append(row)

    if not eligible_rows:
        return [], excluded_counts

    composite_scores: dict[str, float] = defaultdict(float)
    for factor in preset.factor_specs:
        factor_scores = percentile_scores(eligible_rows, factor.column, factor.higher_is_better)
        for symbol, score in factor_scores.items():
            composite_scores[symbol] += score

    divisor = len(preset.factor_specs)
    ranked = sorted(
        eligible_rows,
        key=lambda row: (
            -(composite_scores[row.symbol] / divisor),
            row.liquidity_rank,
            row.symbol,
        ),
    )
    return ranked[:top_n], excluded_counts


def _fallback_close_price(
    close_map: dict[tuple[str, date], Decimal],
    last_known_closes: dict[str, Decimal],
    symbol: str,
    current_date: date,
    execution_open_map: dict[tuple[str, date], Decimal],
    quality_flags: set[str],
) -> Decimal | None:
    close_value = close_map.get((symbol, current_date))
    if close_value is not None:
        last_known_closes[symbol] = close_value
        return close_value

    if symbol in last_known_closes:
        quality_flags.add("일부 종목은 종가가 비어 있어 직전 사용 가능 가격으로 평가했습니다.")
        return last_known_closes[symbol]

    execution_open = execution_open_map.get((symbol, current_date))
    if execution_open is not None:
        quality_flags.add("일부 종목은 체결일 종가가 비어 있어 시가로 평가했습니다.")
        last_known_closes[symbol] = execution_open
        return execution_open
    return None


def _build_warning_events(
    input_data: BacktestFormInput,
    gross_total_return: Decimal,
    net_total_return: Decimal,
    month_shortfalls: list[str],
    missing_execution_open_count: int,
    insufficient_history: bool,
) -> list[WarningEvent]:
    warnings: list[WarningEvent] = [
        WarningEvent(
            title="실전형 결과 기준",
            body="이 화면은 거래비용을 차감한 순성과를 기본으로 보여주며, 월말 신호와 익영업일 체결을 전제로 합니다.",
            tone="info",
        )
    ]
    cost_drag = gross_total_return - net_total_return
    warnings.append(
        WarningEvent(
            title="거래비용 영향",
            body=f"총수익 대비 순수익이 {cost_drag:.2%}만큼 낮아졌습니다. 비용이 큰 전략은 실제 체감 수익이 빠르게 줄 수 있습니다.",
        )
    )
    if (input_data.end_date - input_data.start_date).days < 365:
        warnings.append(
            WarningEvent(
                title="표본 기간이 짧습니다",
                body="1년 미만 구간은 우연한 성과를 크게 반영할 수 있습니다. 더 긴 기간으로 다시 확인해 보세요.",
            )
        )
    if month_shortfalls:
        warnings.append(
            WarningEvent(
                title="일부 월은 후보가 부족했습니다",
                body=" / ".join(month_shortfalls[:3]) + (" ..." if len(month_shortfalls) > 3 else ""),
            )
        )
    if missing_execution_open_count:
        warnings.append(
            WarningEvent(
                title="실행 가격이 없는 종목을 제외했습니다",
                body=f"익영업일 시가가 비어 있는 종목 {missing_execution_open_count}개를 후보에서 제외했습니다.",
            )
        )
    if insufficient_history:
        warnings.append(
            WarningEvent(
                title="초기 구간은 과거 이력이 부족했습니다",
                body="선택한 기간 초반에는 전략 계산에 필요한 과거 데이터가 부족해 일부 월이 자동 제외됐습니다.",
            )
        )
    warnings.append(
        WarningEvent(
            title="PIT / 데이터 품질 유의",
            body="현재 레포의 mart와 staging 데이터를 그대로 읽으며, 원천 데이터 품질과 기업행동 반영 상태에 따라 결과가 달라질 수 있습니다.",
        )
    )
    return warnings


def _calculate_summary_metrics(
    initial_capital: Decimal,
    equity_curve: list[EquityPoint],
    fill_rows: list[FillEvent],
    total_fees: Decimal,
    total_turnover_notional: Decimal,
) -> dict[str, Decimal | float | int]:
    if not equity_curve:
        return {
            "gross_total_return": Decimal("0"),
            "net_total_return": Decimal("0"),
            "gross_cagr": Decimal("0"),
            "net_cagr": Decimal("0"),
            "max_drawdown_net": Decimal("0"),
            "sharpe": 0.0,
            "trade_count": 0,
            "win_rate": 0.0,
            "expected_value": Decimal("0"),
            "turnover": Decimal("0"),
            "total_fees": total_fees,
            "average_holding_period": Decimal("0"),
        }

    gross_end = equity_curve[-1].gross_equity
    net_end = equity_curve[-1].net_equity
    gross_total_return = (gross_end / initial_capital) - Decimal("1")
    net_total_return = (net_end / initial_capital) - Decimal("1")
    total_days = max((equity_curve[-1].date - equity_curve[0].date).days, 1)
    years = Decimal(total_days) / Decimal("365.25")
    gross_cagr = (gross_end / initial_capital) ** (Decimal("1") / years) - Decimal("1") if years > 0 else Decimal("0")
    net_cagr = (net_end / initial_capital) ** (Decimal("1") / years) - Decimal("1") if years > 0 else Decimal("0")

    peak = equity_curve[0].net_equity
    max_drawdown = Decimal("0")
    daily_returns: list[float] = []
    previous_net = equity_curve[0].net_equity
    for point in equity_curve[1:]:
        peak = max(peak, point.net_equity)
        if peak > 0:
            drawdown = (point.net_equity / peak) - Decimal("1")
            max_drawdown = min(max_drawdown, drawdown)
        if previous_net > 0:
            daily_returns.append(float((point.net_equity / previous_net) - Decimal("1")))
        previous_net = point.net_equity

    sharpe = 0.0
    if len(daily_returns) > 1:
        volatility = pstdev(daily_returns)
        if volatility > 0:
            sharpe = (mean(daily_returns) / volatility) * sqrt(252)

    realized_sell_rows = [row for row in fill_rows if row.action == "SELL" and row.realized_pnl is not None]
    trade_count = len(fill_rows)
    win_rate = (
        sum(1 for row in realized_sell_rows if row.realized_pnl and row.realized_pnl > 0) / len(realized_sell_rows)
        if realized_sell_rows
        else 0.0
    )
    expected_value = (
        sum((row.realized_pnl or Decimal("0")) for row in realized_sell_rows) / Decimal(len(realized_sell_rows))
        if realized_sell_rows
        else Decimal("0")
    )
    average_holding_period = (
        sum(Decimal(row.holding_days or 0) for row in realized_sell_rows) / Decimal(len(realized_sell_rows))
        if realized_sell_rows
        else Decimal("0")
    )
    turnover = total_turnover_notional / initial_capital if initial_capital > 0 else Decimal("0")

    return {
        "gross_total_return": gross_total_return,
        "net_total_return": net_total_return,
        "gross_cagr": gross_cagr,
        "net_cagr": net_cagr,
        "max_drawdown_net": max_drawdown,
        "sharpe": sharpe,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "expected_value": expected_value,
        "turnover": turnover,
        "total_fees": total_fees,
        "average_holding_period": average_holding_period,
    }


def simulate_backtest(
    input_data: BacktestFormInput,
    calendar_dates: list[date],
    factor_rows: list[FactorSnapshotRow],
    execution_price_rows: list[ExecutionPriceRow],
    daily_close_rows: list[DailyCloseRow],
    earliest_available_trade_date: date | None,
    transaction_cost_rate: Decimal,
) -> SimulationResult:
    preset = get_strategy_preset(input_data.strategy_preset)
    signal_dates = month_end_signal_dates(calendar_dates, input_data.start_date, input_data.end_date)
    if not signal_dates:
        return SimulationResult(
            state=PageState.NO_DATA,
            equity_curve=[],
            summary_rows=[],
            fill_rows=[],
            warnings=[],
            data_quality_flags=[],
            summary_metrics={},
            error_message="선택한 기간에 SPY 거래일이 없어 백테스트를 실행할 수 없습니다.",
        )

    schedule = execution_schedule(calendar_dates, signal_dates, input_data.end_date)
    if not schedule:
        return SimulationResult(
            state=PageState.NO_DATA,
            equity_curve=[],
            summary_rows=[],
            fill_rows=[],
            warnings=[],
            data_quality_flags=[],
            summary_metrics={},
            error_message="선택한 기간 안에 실행 가능한 리밸런스가 없습니다.",
        )

    factor_rows_by_signal: dict[date, list[FactorSnapshotRow]] = defaultdict(list)
    for row in factor_rows:
        factor_rows_by_signal[row.trade_date].append(row)

    execution_open_map = {
        (row.symbol, row.trade_date): Decimal(row.adjusted_open) if row.adjusted_open is not None else None
        for row in execution_price_rows
    }
    missing_execution_open_count = 0
    selected_by_signal: dict[date, list[FactorSnapshotRow]] = {}
    shortfall_notes: list[str] = []
    insufficient_history = False

    for signal_date in signal_dates:
        execution_date = schedule.get(signal_date)
        if execution_date is None:
            continue
        monthly_rows = factor_rows_by_signal.get(signal_date, [])
        if not monthly_rows:
            if earliest_available_trade_date and signal_date < earliest_available_trade_date:
                insufficient_history = True
            continue
        all_factors_blank = all(
            all(row.factors[factor.column] is None for factor in preset.factor_specs)
            for row in monthly_rows
        )
        selected_rows, excluded_counts = select_top_candidates(
            monthly_rows,
            preset,
            input_data.top_n,
            execution_open_map,
            execution_date,
        )
        missing_execution_open_count += excluded_counts["missing_execution_open"]
        if not selected_rows:
            if all_factors_blank:
                insufficient_history = True
            shortfall_notes.append(f"{signal_date.isoformat()} 신호는 체결 가능한 종목이 없어 건너뛰었습니다.")
            continue
        if len(selected_rows) < input_data.top_n:
            shortfall_notes.append(
                f"{signal_date.isoformat()} 신호는 후보 {len(selected_rows)}개만 확보되어 축소 포트폴리오로 실행했습니다."
            )
        selected_by_signal[signal_date] = selected_rows

    if not selected_by_signal:
        state = PageState.INSUFFICIENT_HISTORY if insufficient_history else PageState.NO_DATA
        message = (
            "선택한 기간에는 전략 계산에 필요한 과거 이력이 부족합니다."
            if state == PageState.INSUFFICIENT_HISTORY
            else "선택한 기간과 조건에서 체결 가능한 후보를 찾지 못했습니다."
        )
        return SimulationResult(
            state=state,
            equity_curve=[],
            summary_rows=[],
            fill_rows=[],
            warnings=[],
            data_quality_flags=[],
            summary_metrics={},
            error_message=message,
        )

    symbols_for_daily_prices = sorted({row.symbol for rows in selected_by_signal.values() for row in rows})
    close_map = {
        (row.symbol, row.trade_date): Decimal(row.adjusted_close) if row.adjusted_close is not None else None
        for row in daily_close_rows
    }

    gross_cash = Decimal(input_data.initial_capital)
    net_cash = Decimal(input_data.initial_capital)
    gross_positions: dict[str, Position] = {}
    net_positions: dict[str, Position] = {}
    fill_rows: list[FillEvent] = []
    summary_rows: list[RebalanceSummary] = []
    equity_curve: list[EquityPoint] = []
    quality_flags: set[str] = set()
    last_known_closes: dict[str, Decimal] = {}
    total_fees = Decimal("0")
    total_turnover_notional = Decimal("0")

    signal_by_execution = {execution_date: signal_date for signal_date, execution_date in schedule.items() if signal_date in selected_by_signal}
    calendar_in_range = [calendar_date for calendar_date in calendar_dates if input_data.start_date <= calendar_date <= input_data.end_date]

    for current_date in calendar_in_range:
        signal_date = signal_by_execution.get(current_date)
        if signal_date is not None:
            selected_rows = selected_by_signal[signal_date]
            selected_symbols = [row.symbol for row in selected_rows]

            sold_count = len(net_positions)
            rebalance_sell_notional = Decimal("0")
            rebalance_buy_notional = Decimal("0")
            rebalance_fees = Decimal("0")

            if gross_positions:
                for symbol, position in list(gross_positions.items()):
                    execution_open = execution_open_map.get((symbol, current_date))
                    if execution_open is None:
                        return SimulationResult(
                            state=PageState.ERROR,
                            equity_curve=[],
                            summary_rows=[],
                            fill_rows=[],
                            warnings=[],
                            data_quality_flags=[],
                            summary_metrics={},
                            error_message=f"{current_date.isoformat()} 체결일에 {symbol}의 실행 가격이 없어 리밸런스를 계속할 수 없습니다.",
                        )
                    gross_cash += position.shares * execution_open
                    del gross_positions[symbol]

            if net_positions:
                for symbol, position in list(net_positions.items()):
                    execution_open = execution_open_map.get((symbol, current_date))
                    if execution_open is None:
                        return SimulationResult(
                            state=PageState.ERROR,
                            equity_curve=[],
                            summary_rows=[],
                            fill_rows=[],
                            warnings=[],
                            data_quality_flags=[],
                            summary_metrics={},
                            error_message=f"{current_date.isoformat()} 체결일에 {symbol}의 실행 가격이 없어 리밸런스를 계속할 수 없습니다.",
                        )
                    sell_notional = position.shares * execution_open
                    sell_fee = sell_notional * transaction_cost_rate
                    net_cash += sell_notional - sell_fee
                    realized_pnl = sell_notional - sell_fee - (position.shares * position.entry_price) - position.entry_fee
                    holding_days = (current_date - position.entry_date).days
                    fill_rows.append(
                        FillEvent(
                            execution_date=current_date,
                            signal_date=signal_date,
                            symbol=symbol,
                            action="SELL",
                            shares=position.shares,
                            execution_price=execution_open,
                            fees=sell_fee,
                            net_cash_flow=sell_notional - sell_fee,
                            realized_pnl=realized_pnl,
                            holding_days=holding_days,
                        )
                    )
                    total_fees += sell_fee
                    rebalance_sell_notional += sell_notional
                    rebalance_fees += sell_fee
                    total_turnover_notional += sell_notional
                    del net_positions[symbol]

            if selected_symbols:
                gross_allocation = gross_cash / Decimal(len(selected_symbols))
                net_allocation = net_cash / (Decimal(len(selected_symbols)) * (Decimal("1") + transaction_cost_rate))
                for symbol in selected_symbols:
                    execution_open = execution_open_map[(symbol, current_date)]
                    if execution_open is None:
                        continue
                    gross_shares = gross_allocation / execution_open
                    gross_notional = gross_shares * execution_open
                    gross_cash -= gross_notional
                    gross_positions[symbol] = Position(
                        shares=gross_shares,
                        entry_price=execution_open,
                        entry_date=current_date,
                        entry_fee=Decimal("0"),
                    )

                    net_shares = net_allocation / execution_open
                    buy_notional = net_shares * execution_open
                    buy_fee = buy_notional * transaction_cost_rate
                    net_cash -= buy_notional + buy_fee
                    net_positions[symbol] = Position(
                        shares=net_shares,
                        entry_price=execution_open,
                        entry_date=current_date,
                        entry_fee=buy_fee,
                    )
                    fill_rows.append(
                        FillEvent(
                            execution_date=current_date,
                            signal_date=signal_date,
                            symbol=symbol,
                            action="BUY",
                            shares=net_shares,
                            execution_price=execution_open,
                            fees=buy_fee,
                            net_cash_flow=-(buy_notional + buy_fee),
                        )
                    )
                    total_fees += buy_fee
                    rebalance_buy_notional += buy_notional
                    rebalance_fees += buy_fee
                    total_turnover_notional += buy_notional

            turnover = (rebalance_buy_notional + rebalance_sell_notional) / Decimal(input_data.initial_capital)
            summary_rows.append(
                RebalanceSummary(
                    signal_date=signal_date,
                    execution_date=current_date,
                    selected_count=len(selected_symbols),
                    sold_count=sold_count,
                    buy_notional=rebalance_buy_notional,
                    sell_notional=rebalance_sell_notional,
                    fees=rebalance_fees,
                    turnover=turnover,
                    notes=(
                        "축소 포트폴리오"
                        if len(selected_symbols) < input_data.top_n
                        else None
                    ),
                )
            )

        gross_equity = gross_cash
        net_equity = net_cash
        for symbol, position in gross_positions.items():
            close_value = _fallback_close_price(close_map, last_known_closes, symbol, current_date, execution_open_map, quality_flags)
            if close_value is not None:
                gross_equity += position.shares * close_value
        for symbol, position in net_positions.items():
            close_value = _fallback_close_price(close_map, last_known_closes, symbol, current_date, execution_open_map, quality_flags)
            if close_value is not None:
                net_equity += position.shares * close_value
        equity_curve.append(EquityPoint(date=current_date, gross_equity=gross_equity, net_equity=net_equity))

    summary_metrics = _calculate_summary_metrics(
        Decimal(input_data.initial_capital),
        equity_curve,
        fill_rows,
        total_fees,
        total_turnover_notional,
    )
    warning_events = _build_warning_events(
        input_data,
        Decimal(summary_metrics["gross_total_return"]),
        Decimal(summary_metrics["net_total_return"]),
        shortfall_notes,
        missing_execution_open_count,
        insufficient_history,
    )
    return SimulationResult(
        state=PageState.SUCCESS,
        equity_curve=equity_curve,
        summary_rows=summary_rows,
        fill_rows=fill_rows,
        warnings=warning_events,
        data_quality_flags=sorted(quality_flags),
        summary_metrics=summary_metrics,
        error_message=None,
    )
