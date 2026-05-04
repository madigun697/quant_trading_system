from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import sqrt
from statistics import mean, pstdev

from quant_data_platform.web.presets import (
    MarketTimingOverlayId,
    StrategyPreset,
    get_market_timing_overlay,
    get_strategy_preset,
)
from quant_data_platform.web.repositories.backtest_repo import BenchmarkValueRow, DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow
from quant_data_platform.web.schemas import BacktestFormInput, PageState


@dataclass
class Position:
    shares: Decimal
    cost_basis: Decimal
    entry_mass: Decimal

    def buy(self, shares: Decimal, total_cost: Decimal, trade_date: date) -> None:
        self.shares += shares
        self.cost_basis += total_cost
        self.entry_mass += shares * Decimal(trade_date.toordinal())

    def sell(self, shares: Decimal, trade_date: date) -> tuple[Decimal, int]:
        ratio = shares / self.shares
        cost_basis_sold = self.cost_basis * ratio
        entry_mass_sold = self.entry_mass * ratio
        average_entry_ordinal = int(entry_mass_sold / shares) if shares > 0 else trade_date.toordinal()
        holding_days = max(trade_date.toordinal() - average_entry_ordinal, 0)
        self.shares -= shares
        self.cost_basis -= cost_basis_sold
        self.entry_mass -= entry_mass_sold
        return cost_basis_sold, holding_days


@dataclass(frozen=True)
class EquityPoint:
    date: date
    gross_equity: Decimal
    net_equity: Decimal
    benchmark_equity: Decimal | None = None


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
class UnavailableReasonEvent:
    code: str
    title: str
    detail: str
    facts: list[str]
    suggestions: list[str]


@dataclass(frozen=True)
class SimulationResult:
    state: PageState
    equity_curve: list[EquityPoint]
    summary_rows: list[RebalanceSummary]
    fill_rows: list[FillEvent]
    warnings: list[WarningEvent]
    data_quality_flags: list[str]
    summary_metrics: dict[str, Decimal | float | int]
    unavailable_reasons: list[UnavailableReasonEvent]
    error_message: str | None = None


@dataclass(frozen=True)
class OverlaySignal:
    risk_on: bool | None
    facts: list[str]
    strategy_weight: Decimal | None = None


@dataclass(frozen=True)
class TargetAllocation:
    symbol: str
    target_weight: Decimal


@dataclass(frozen=True)
class PendingAction:
    action_type: str
    signal_date: date
    execution_date: date
    target_allocations: tuple[TargetAllocation, ...]
    note: str
    resulting_state: str
    allow_missing_target_hold: bool = False


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
    execution_opens: dict[tuple[str, date], Decimal | None],
    execution_date: date,
    factor_weights: dict[str, float] | None = None,
) -> tuple[list[FactorSnapshotRow], dict[str, int]]:
    ranked_rows, excluded_counts = rank_factor_candidates(rows, preset, factor_weights)
    if not ranked_rows:
        excluded_counts["missing_execution_open"] = 0
        return [], excluded_counts

    selected_rows: list[FactorSnapshotRow] = []
    missing_execution_open = 0
    for row in ranked_rows:
        if execution_opens.get((row.symbol, execution_date)) is None:
            missing_execution_open += 1
            continue
        selected_rows.append(row)
        if len(selected_rows) >= top_n:
            break
    excluded_counts["missing_execution_open"] = missing_execution_open
    return selected_rows, excluded_counts


def rank_factor_candidates(
    rows: list[FactorSnapshotRow],
    preset: StrategyPreset,
    factor_weights: dict[str, float] | None = None,
) -> tuple[list[FactorSnapshotRow], dict[str, int]]:
    eligible_rows: list[FactorSnapshotRow] = []
    excluded_counts = {"missing_factors": 0}
    for row in rows:
        if any(row.factors[factor.column] is None for factor in preset.factor_specs):
            excluded_counts["missing_factors"] += 1
            continue
        eligible_rows.append(row)

    if not eligible_rows:
        return [], excluded_counts

    composite_scores: dict[str, float] = defaultdict(float)
    weights = factor_weights if factor_weights is not None else {}
    for factor in preset.factor_specs:
        weight = weights.get(factor.column, 1.0)
        factor_scores = percentile_scores(eligible_rows, factor.column, factor.higher_is_better)
        for symbol, score in factor_scores.items():
            composite_scores[symbol] += score * weight

    divisor = len(preset.factor_specs)
    ranked = sorted(
        eligible_rows,
        key=lambda row: (
            -(composite_scores[row.symbol] / divisor),
            row.liquidity_rank,
            row.symbol,
        ),
    )
    return ranked, excluded_counts


def select_top_candidates_by_close(
    rows: list[FactorSnapshotRow],
    preset: StrategyPreset,
    top_n: int,
    close_map: dict[tuple[str, date], Decimal | None],
    reference_date: date,
    factor_weights: dict[str, float] | None = None,
) -> tuple[list[FactorSnapshotRow], dict[str, int]]:
    ranked_rows, excluded_counts = rank_factor_candidates(rows, preset, factor_weights)
    if not ranked_rows:
        excluded_counts["missing_reference_close"] = 0
        return [], excluded_counts

    selected_rows: list[FactorSnapshotRow] = []
    missing_reference_close = 0
    for row in ranked_rows:
        if close_map.get((row.symbol, reference_date)) is None:
            missing_reference_close += 1
            continue
        selected_rows.append(row)
        if len(selected_rows) >= top_n:
            break
    excluded_counts["missing_reference_close"] = missing_reference_close
    return selected_rows, excluded_counts


def _fallback_close_price(
    close_map: dict[tuple[str, date], Decimal | None],
    last_known_closes: dict[str, Decimal],
    symbol: str,
    current_date: date,
    execution_open_map: dict[tuple[str, date], Decimal | None],
    quality_flags: set[str],
) -> Decimal | None:
    close_value = close_map.get((symbol, current_date))
    if close_value is not None:
        last_known_closes[symbol] = close_value
        return close_value

    if symbol in last_known_closes:
        quality_flags.add("일부 자산은 종가가 비어 있어 직전 사용 가능 가격으로 평가했습니다.")
        return last_known_closes[symbol]

    execution_open = execution_open_map.get((symbol, current_date))
    if execution_open is not None:
        quality_flags.add("일부 자산은 체결일 종가가 비어 있어 시가로 평가했습니다.")
        last_known_closes[symbol] = execution_open
        return execution_open
    return None


def _build_unavailable_reason(
    *,
    code: str,
    title: str,
    detail: str,
    facts: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> UnavailableReasonEvent:
    return UnavailableReasonEvent(
        code=code,
        title=title,
        detail=detail,
        facts=facts or [],
        suggestions=suggestions or [],
    )


def _solve_fee_aware_target_notionals(
    pre_trade_value: Decimal,
    current_notionals: dict[str, Decimal],
    target_weights: dict[str, Decimal],
    transaction_cost_rate: Decimal,
) -> dict[str, Decimal]:
    if not target_weights:
        return {}

    high = pre_trade_value
    low = Decimal("0")
    all_symbols = sorted(set(current_notionals) | set(target_weights))

    def net_after_costs(target_total: Decimal) -> Decimal:
        traded_notional = Decimal("0")
        for symbol in all_symbols:
            current = current_notionals.get(symbol, Decimal("0"))
            target = target_total * target_weights.get(symbol, Decimal("0"))
            traded_notional += abs(target - current)
        return pre_trade_value - (transaction_cost_rate * traded_notional)

    for _ in range(60):
        mid = (low + high) / 2
        affordable_total = net_after_costs(mid)
        target_total = mid
        if target_total > affordable_total:
            high = mid
        else:
            low = mid
    return {
        symbol: low * weight
        for symbol, weight in target_weights.items()
    }


def _build_history_maps(
    daily_close_rows: list[DailyCloseRow],
) -> tuple[dict[str, list[tuple[date, Decimal]]], dict[str, dict[date, int]]]:
    history_map: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in daily_close_rows:
        if row.adjusted_close is not None:
            history_map[row.symbol].append((row.trade_date, Decimal(row.adjusted_close)))
    for symbol in history_map:
        history_map[symbol].sort(key=lambda item: item[0])
    index_map = {
        symbol: {trade_date: idx for idx, (trade_date, _value) in enumerate(rows)}
        for symbol, rows in history_map.items()
    }
    return history_map, index_map


def _close_for(symbol: str, current_date: date, history_map: dict[str, list[tuple[date, Decimal]]], index_map: dict[str, dict[date, int]]) -> Decimal | None:
    idx = index_map.get(symbol, {}).get(current_date)
    if idx is None:
        return None
    return history_map[symbol][idx][1]


def _sma_for(
    symbol: str,
    current_date: date,
    window: int,
    history_map: dict[str, list[tuple[date, Decimal]]],
    index_map: dict[str, dict[date, int]],
) -> Decimal | None:
    idx = index_map.get(symbol, {}).get(current_date)
    if idx is None or idx + 1 < window:
        return None
    values = [price for _trade_date, price in history_map[symbol][idx - window + 1 : idx + 1]]
    return sum(values, start=Decimal("0")) / Decimal(window)


def _is_below_sma_for_consecutive_trading_days(
    symbol: str,
    current_date: date,
    *,
    window: int,
    consecutive_days: int,
    history_map: dict[str, list[tuple[date, Decimal]]],
    index_map: dict[str, dict[date, int]],
) -> bool | None:
    idx = index_map.get(symbol, {}).get(current_date)
    if idx is None:
        return None
    start_idx = idx - consecutive_days + 1
    if start_idx < 0:
        return None
    for offset in range(start_idx, idx + 1):
        trade_date, close_value = history_map[symbol][offset]
        sma_value = _sma_for(symbol, trade_date, window, history_map, index_map)
        if sma_value is None:
            return None
        if close_value >= sma_value:
            return False
    return True


def _return_for(
    symbol: str,
    current_date: date,
    lookback_days: int,
    history_map: dict[str, list[tuple[date, Decimal]]],
    index_map: dict[str, dict[date, int]],
) -> Decimal | None:
    idx = index_map.get(symbol, {}).get(current_date)
    if idx is None or idx < lookback_days:
        return None
    current_price = history_map[symbol][idx][1]
    prior_price = history_map[symbol][idx - lookback_days][1]
    if prior_price <= 0:
        return None
    return (current_price / prior_price) - Decimal("1")


def _evaluate_month_end_overlay_signal(
    overlay_id: MarketTimingOverlayId,
    current_date: date,
    history_map: dict[str, list[tuple[date, Decimal]]],
    index_map: dict[str, dict[date, int]],
) -> OverlaySignal:
    if overlay_id == MarketTimingOverlayId.NONE:
        return OverlaySignal(risk_on=True, facts=[])

    if overlay_id == MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC:
        close_value = _close_for("SPY", current_date, history_map, index_map)
        sma200 = _sma_for("SPY", current_date, 200, history_map, index_map)
        ret20 = _return_for("SPY", current_date, 20, history_map, index_map)
        facts: list[str] = []
        if close_value is None:
            facts.append("SPY 종가가 없습니다.")
        if sma200 is None:
            facts.append("SPY 200일선 계산 이력이 부족합니다.")
        if ret20 is None:
            facts.append("SPY 20거래일 수익률 계산 이력이 부족합니다.")
        if facts:
            return OverlaySignal(risk_on=None, facts=facts)
        return OverlaySignal(risk_on=bool(close_value > sma200 and ret20 > 0), facts=[])

    if overlay_id == MarketTimingOverlayId.CANARY_ASSET_SIGNAL:
        vt_return = _return_for("VT", current_date, 84, history_map, index_map)
        ief_return = _return_for("IEF", current_date, 84, history_map, index_map)
        facts = []
        if vt_return is None:
            facts.append("VT 84거래일 수익률 계산 이력이 부족합니다.")
        if ief_return is None:
            facts.append("IEF 84거래일 수익률 계산 이력이 부족합니다.")
        if facts:
            return OverlaySignal(risk_on=None, facts=facts)
        return OverlaySignal(risk_on=bool(vt_return > ief_return), facts=[])

    if overlay_id == MarketTimingOverlayId.GRADUATED_POSITION_SIZING:
        close_value = _close_for("SPY", current_date, history_map, index_map)
        sma200 = _sma_for("SPY", current_date, 200, history_map, index_map)
        facts = []
        if close_value is None:
            facts.append("SPY 종가가 없습니다.")
        if sma200 is None:
            facts.append("SPY 200일선 계산 이력이 부족합니다.")
        if facts:
            return OverlaySignal(risk_on=None, facts=facts)
        upper_bound = sma200 * Decimal("1.02")
        lower_bound = sma200 * Decimal("0.98")
        if close_value > upper_bound:
            return OverlaySignal(risk_on=True, facts=[], strategy_weight=Decimal("1"))
        if close_value > sma200:
            return OverlaySignal(risk_on=False, facts=[], strategy_weight=Decimal("0.7"))
        if close_value >= lower_bound:
            return OverlaySignal(risk_on=False, facts=[], strategy_weight=Decimal("0.5"))
        return OverlaySignal(risk_on=False, facts=[], strategy_weight=Decimal("0"))

    return OverlaySignal(risk_on=True, facts=[])


def _evaluate_daily_risk_off(
    overlay_id: MarketTimingOverlayId,
    current_date: date,
    history_map: dict[str, list[tuple[date, Decimal]]],
    index_map: dict[str, dict[date, int]],
) -> OverlaySignal:
    if overlay_id in {MarketTimingOverlayId.NONE}:
        return OverlaySignal(risk_on=True, facts=[])

    if overlay_id in {
        MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        MarketTimingOverlayId.GRADUATED_POSITION_SIZING,
    }:
        close_value = _close_for("SPY", current_date, history_map, index_map)
        sma50 = _sma_for("SPY", current_date, 50, history_map, index_map)
        below_sma_for_3_days = _is_below_sma_for_consecutive_trading_days(
            "SPY",
            current_date,
            window=50,
            consecutive_days=3,
            history_map=history_map,
            index_map=index_map,
        )
        facts: list[str] = []
        if close_value is None:
            facts.append("SPY 종가가 없습니다.")
        if sma50 is None:
            facts.append("SPY 50일선 계산 이력이 부족합니다.")
        if close_value is not None and sma50 is not None and below_sma_for_3_days is None:
            facts.append("SPY 50일선 3거래일 연속 이탈 여부를 계산할 이력이 부족합니다.")
        if facts:
            return OverlaySignal(risk_on=None, facts=facts)
        if bool(below_sma_for_3_days):
            if overlay_id == MarketTimingOverlayId.GRADUATED_POSITION_SIZING:
                return OverlaySignal(risk_on=False, facts=[], strategy_weight=Decimal("0.7"))
            return OverlaySignal(risk_on=False, facts=[])
        return OverlaySignal(risk_on=True, facts=[])

    return _evaluate_month_end_overlay_signal(overlay_id, current_date, history_map, index_map)


def evaluate_daily_overlay_signal(
    overlay_id: MarketTimingOverlayId,
    current_date: date,
    daily_close_rows: list[DailyCloseRow],
) -> OverlaySignal:
    history_map, index_map = _build_history_maps(daily_close_rows)
    return _evaluate_daily_risk_off(overlay_id, current_date, history_map, index_map)


def _format_percent(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _allocation_summary(allocations: tuple[TargetAllocation, ...], *, as_percent: bool = False) -> str:
    if not allocations:
        return ""
    if as_percent:
        return " / ".join(f"{allocation.symbol} {_format_percent(allocation.target_weight * Decimal('100'))}%" for allocation in allocations)
    return " / ".join(f"{allocation.symbol} {_format_percent(allocation.target_weight)}" for allocation in allocations)


def _equal_weight_allocations(symbols: list[str]) -> tuple[TargetAllocation, ...]:
    if not symbols:
        return tuple()
    weight = Decimal("1") / Decimal(len(symbols))
    return tuple(TargetAllocation(symbol=symbol, target_weight=weight) for symbol in symbols)


def _safe_asset_allocations(input_data: BacktestFormInput) -> tuple[TargetAllocation, ...]:
    return tuple(
        TargetAllocation(symbol=symbol.value, target_weight=weight / Decimal("100"))
        for symbol, weight in input_data.safe_asset_allocations()
    )


def _build_blended_allocations(
    factor_symbols: list[str],
    safe_asset_allocations: tuple[TargetAllocation, ...],
    strategy_weight: Decimal,
) -> tuple[TargetAllocation, ...]:
    """전략자산과 안전자산을 strategy_weight 비율로 혼합한 TargetAllocation을 생성합니다.

    strategy_weight=1.0 → 100% 전략자산
    strategy_weight=0.7 → 70% 전략자산 + 30% 안전자산
    strategy_weight=0.0 → 100% 안전자산
    """
    allocations: list[TargetAllocation] = []
    if strategy_weight > 0 and factor_symbols:
        factor_weight_each = strategy_weight / Decimal(len(factor_symbols))
        for symbol in factor_symbols:
            allocations.append(TargetAllocation(symbol=symbol, target_weight=factor_weight_each))
    safe_weight = Decimal("1") - strategy_weight
    if safe_weight > 0:
        for sa in safe_asset_allocations:
            allocations.append(TargetAllocation(symbol=sa.symbol, target_weight=sa.target_weight * safe_weight))
    return tuple(allocations)


def _build_warning_events(
    input_data: BacktestFormInput,
    gross_total_return: Decimal,
    net_total_return: Decimal,
    month_shortfalls: list[str],
    missing_execution_open_count: int,
    insufficient_history: bool,
) -> list[WarningEvent]:
    overlay = get_market_timing_overlay(input_data.market_timing_overlay)
    safe_asset_summary = input_data.safe_asset_summary()
    warnings: list[WarningEvent] = [
        WarningEvent(
            title="실전형 결과 기준",
            body="이 화면은 거래비용을 반영한 Net 성과를 먼저 보여 주고, 같은 시작점의 SPY 비교선을 함께 제공합니다.",
            tone="info",
        )
    ]
    if input_data.market_timing_overlay != MarketTimingOverlayId.NONE:
        warnings.append(
            WarningEvent(
                title="마켓타이밍 오버레이 활성화",
                body=f"{overlay.label} 오버레이가 켜져 있으며 risk-off 시 {safe_asset_summary}로 이동합니다.",
                tone="info",
            )
        )
    cost_drag = gross_total_return - net_total_return
    warnings.append(
        WarningEvent(
            title="거래비용 영향",
            body=f"총수익 대비 순수익이 {cost_drag:.2%}만큼 낮아졌습니다. Gross 선은 비용이 결과를 얼마나 깎았는지 확인하는 보조선입니다.",
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
                body="선택한 기간 초반에는 전략 계산에 필요한 가격 또는 신호 데이터가 부족해 일부 월이 자동 제외됐습니다.",
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
    benchmark_rows: list[BenchmarkValueRow],
    earliest_available_trade_date: date | None,
    transaction_cost_rate: Decimal,
    factor_weights: dict[str, float] | None = None,
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
            unavailable_reasons=[
                _build_unavailable_reason(
                    code="no_spy_calendar",
                    title="선택한 기간에 SPY 거래일이 없습니다",
                    detail="차트 기준이 되는 SPY 거래일을 찾지 못해 백테스트를 실행할 수 없습니다.",
                    suggestions=["시작일과 종료일을 더 최근 구간으로 조정해 보세요."],
                )
            ],
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
            unavailable_reasons=[
                _build_unavailable_reason(
                    code="no_executable_rebalance",
                    title="실행 가능한 리밸런스가 없습니다",
                    detail="선택한 기간 안에 월말 신호 다음 거래일까지 포함된 구간이 없습니다.",
                    facts=["종료일이 월말 신호 바로 뒤 거래일까지 포함되어야 실제 체결을 계산할 수 있습니다."],
                    suggestions=["종료일을 조금 더 뒤로 늘려 보세요."],
                )
            ],
            error_message="선택한 기간 안에 실행 가능한 리밸런스가 없습니다.",
        )

    factor_rows_by_signal: dict[date, list[FactorSnapshotRow]] = defaultdict(list)
    for row in factor_rows:
        factor_rows_by_signal[row.trade_date].append(row)

    execution_open_map = {
        (row.symbol, row.trade_date): Decimal(row.adjusted_open) if row.adjusted_open is not None else None
        for row in execution_price_rows
    }
    close_map = {
        (row.symbol, row.trade_date): Decimal(row.adjusted_close) if row.adjusted_close is not None else None
        for row in daily_close_rows
    }
    benchmark_map = {
        row.observation_date: Decimal(row.value)
        for row in benchmark_rows
        if row.value is not None
    }
    history_map, index_map = _build_history_maps(daily_close_rows)

    missing_execution_open_count = 0
    selected_by_signal: dict[date, list[FactorSnapshotRow]] = {}
    shortfall_notes: list[str] = []
    unavailable_reasons: list[UnavailableReasonEvent] = []
    insufficient_history = False
    blank_factor_month_count = 0
    missing_snapshot_month_count = 0
    zero_candidate_facts: list[str] = []

    for signal_date in signal_dates:
        execution_date = schedule.get(signal_date)
        if execution_date is None:
            continue
        monthly_rows = factor_rows_by_signal.get(signal_date, [])
        if not monthly_rows:
            if earliest_available_trade_date and signal_date < earliest_available_trade_date:
                insufficient_history = True
                missing_snapshot_month_count += 1
            else:
                zero_candidate_facts.append(f"{signal_date.isoformat()} 신호에는 사용할 팩터 스냅샷이 없습니다.")
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
            factor_weights,
        )
        missing_execution_open_count += excluded_counts["missing_execution_open"]
        if not selected_rows:
            if all_factors_blank:
                insufficient_history = True
                blank_factor_month_count += 1
            zero_candidate_facts.append(
                f"{signal_date.isoformat()} 신호: 후보 0 / 목표 {input_data.top_n}, "
                f"팩터 누락 {excluded_counts['missing_factors']}개, 실행가 누락 {excluded_counts['missing_execution_open']}개"
            )
            shortfall_notes.append(f"{signal_date.isoformat()} 신호는 체결 가능한 종목이 없어 건너뛰었습니다.")
            continue
        if len(selected_rows) < input_data.top_n:
            shortfall_notes.append(
                f"{signal_date.isoformat()} 신호는 후보 {len(selected_rows)}개만 확보되어 축소 포트폴리오로 실행했습니다."
            )
        selected_by_signal[signal_date] = selected_rows

    if not selected_by_signal and input_data.market_timing_overlay == MarketTimingOverlayId.NONE:
        if insufficient_history:
            facts: list[str] = [f"전략 데이터 시작 시점: {earliest_available_trade_date.isoformat()}"] if earliest_available_trade_date else []
            if blank_factor_month_count:
                facts.append(f"팩터가 전부 비어 있던 월: {blank_factor_month_count}개")
            if missing_snapshot_month_count:
                facts.append(f"전략 룩백 부족으로 제외된 월: {missing_snapshot_month_count}개")
            facts.append(f"필요 이력: {preset.lookback_label}")
            unavailable_reasons.append(
                _build_unavailable_reason(
                    code="insufficient_history",
                    title="선택한 기간에 과거 이력이 충분하지 않습니다",
                    detail="이 프리셋을 계산하는 데 필요한 가격 또는 팩터 이력이 초반 구간에 부족했습니다.",
                    facts=facts,
                    suggestions=["시작일을 더 뒤로 늦추거나, 룩백이 짧은 프리셋으로 바꿔 보세요."],
                )
            )
        if zero_candidate_facts:
            unavailable_reasons.append(
                _build_unavailable_reason(
                    code="no_eligible_candidates",
                    title="체결 가능한 후보를 찾지 못했습니다",
                    detail="선택한 월 신호들에서 필요한 팩터와 실행 가격을 모두 갖춘 종목이 없었습니다.",
                    facts=zero_candidate_facts[:4],
                    suggestions=["기간을 넓히거나 거래비용은 유지한 채 다른 프리셋을 선택해 보세요."],
                )
            )
        return SimulationResult(
            state=PageState.INSUFFICIENT_HISTORY if insufficient_history else PageState.NO_DATA,
            equity_curve=[],
            summary_rows=[],
            fill_rows=[],
            warnings=[],
            data_quality_flags=[],
            summary_metrics={},
            unavailable_reasons=unavailable_reasons,
            error_message="선택한 기간과 조건에서 체결 가능한 후보를 찾지 못했습니다.",
        )

    gross_cash = Decimal(input_data.initial_capital)
    net_cash = Decimal(input_data.initial_capital)
    gross_positions: dict[str, Decimal] = {}
    net_positions: dict[str, Position] = {}
    fill_rows: list[FillEvent] = []
    summary_rows: list[RebalanceSummary] = []
    equity_curve: list[EquityPoint] = []
    quality_flags: set[str] = set()
    last_known_closes: dict[str, Decimal] = {}
    total_fees = Decimal("0")
    total_turnover_notional = Decimal("0")
    portfolio_state = "pre_start"
    safe_asset_allocations = _safe_asset_allocations(input_data)
    safe_asset_summary = _allocation_summary(safe_asset_allocations, as_percent=True)
    first_execution_date = min(schedule.values()) if schedule else None
    benchmark_shares: Decimal | None = None
    benchmark_last_value: Decimal | None = None
    calendar_in_range = [calendar_date for calendar_date in calendar_dates if input_data.start_date <= calendar_date <= input_data.end_date]
    next_date_by_date = {
        current: calendar_in_range[index + 1]
        for index, current in enumerate(calendar_in_range[:-1])
    }
    pending_action: PendingAction | None = None
    overlay_unavailable_facts: list[str] = []

    def execute_target_portfolio(
        *,
        current_date: date,
        signal_date: date,
        target_allocations: tuple[TargetAllocation, ...],
        note: str,
        resulting_state: str,
        allow_missing_target_hold: bool = False,
    ) -> tuple[UnavailableReasonEvent | None, bool]:
        nonlocal gross_cash, net_cash, total_fees, total_turnover_notional, portfolio_state
        rebalance_sell_notional = Decimal("0")
        rebalance_buy_notional = Decimal("0")
        rebalance_fees = Decimal("0")
        sold_count = 0

        target_weights = {allocation.symbol: allocation.target_weight for allocation in target_allocations}
        current_open_prices = {
            symbol: execution_open_map.get((symbol, current_date))
            for symbol in sorted(set(gross_positions) | set(net_positions) | set(target_weights))
        }
        missing_symbols = [
            symbol
            for symbol, price in current_open_prices.items()
            if price is None and symbol in set(gross_positions) | set(net_positions)
        ]
        if missing_symbols:
            symbol_list = ", ".join(missing_symbols[:3])
            return (
                _build_unavailable_reason(
                    code="missing_rebalance_price",
                    title="보유 자산의 체결 가격이 비어 있습니다",
                    detail=f"{current_date.isoformat()} 체결일에 {symbol_list}의 실행 가격이 없어 리밸런스를 계속할 수 없습니다.",
                    facts=[f"누락 종목 수: {len(missing_symbols)}"],
                    suggestions=["해당 기간을 피하거나 데이터 적재 상태를 확인해 주세요."],
                ),
                False,
            )

        target_missing = [symbol for symbol in target_weights if current_open_prices.get(symbol) is None]
        if target_missing and allow_missing_target_hold:
            quality_flags.add(f"{', '.join(target_missing[:2])} 시가가 없어 기존 자산을 유지했습니다.")
            summary_rows.append(
                RebalanceSummary(
                    signal_date=signal_date,
                    execution_date=current_date,
                    selected_count=len(target_allocations),
                    sold_count=0,
                    buy_notional=Decimal("0"),
                    sell_notional=Decimal("0"),
                    fees=Decimal("0"),
                    turnover=Decimal("0"),
                    notes=f"{note} (시가 누락으로 유지)",
                )
            )
            return None, False
        if target_missing:
            symbol_list = ", ".join(target_missing[:3])
            return (
                _build_unavailable_reason(
                    code="missing_target_open",
                    title="목표 자산의 체결 가격이 비어 있습니다",
                    detail=f"{current_date.isoformat()} 체결일에 {symbol_list} 시가가 없어 목표 포트폴리오를 만들 수 없습니다.",
                    facts=[f"누락 종목 수: {len(target_missing)}"],
                    suggestions=["해당 기간을 피하거나 데이터 적재 상태를 확인해 주세요."],
                ),
                False,
            )

        gross_current_notionals = {
            symbol: shares * current_open_prices[symbol]
            for symbol, shares in gross_positions.items()
            if current_open_prices[symbol] is not None
        }
        net_current_notionals = {
            symbol: position.shares * current_open_prices[symbol]
            for symbol, position in net_positions.items()
            if current_open_prices[symbol] is not None
        }
        gross_pre_trade_value = gross_cash + sum(gross_current_notionals.values(), start=Decimal("0"))
        net_pre_trade_value = net_cash + sum(net_current_notionals.values(), start=Decimal("0"))

        gross_target_notionals = {
            symbol: gross_pre_trade_value * target_weight
            for symbol, target_weight in target_weights.items()
        }
        net_target_notionals = _solve_fee_aware_target_notionals(
            net_pre_trade_value,
            net_current_notionals,
            target_weights,
            transaction_cost_rate,
        )

        all_symbols = sorted(set(gross_positions) | set(net_positions) | set(target_weights))
        gross_deltas: dict[str, Decimal] = {}
        net_deltas: dict[str, Decimal] = {}
        for symbol in all_symbols:
            gross_current = gross_current_notionals.get(symbol, Decimal("0"))
            net_current = net_current_notionals.get(symbol, Decimal("0"))
            gross_target = gross_target_notionals.get(symbol, Decimal("0"))
            gross_deltas[symbol] = gross_target - gross_current
            net_target = net_target_notionals.get(symbol, Decimal("0"))
            net_deltas[symbol] = net_target - net_current

        for symbol in all_symbols:
            execution_open = current_open_prices[symbol]
            if execution_open is None:
                continue

            gross_delta = gross_deltas[symbol]
            if gross_delta < 0:
                sell_shares = (-gross_delta) / execution_open
                gross_cash += -gross_delta
                remaining_shares = gross_positions.get(symbol, Decimal("0")) - sell_shares
                if remaining_shares <= Decimal("0.0000000001"):
                    gross_positions.pop(symbol, None)
                else:
                    gross_positions[symbol] = remaining_shares

            net_delta = net_deltas[symbol]
            if net_delta < 0:
                position = net_positions.get(symbol)
                if position is None:
                    continue
                sell_notional = -net_delta
                sell_shares = sell_notional / execution_open
                sell_fee = sell_notional * transaction_cost_rate
                cost_basis_sold, holding_days = position.sell(sell_shares, current_date)
                net_cash += sell_notional - sell_fee
                realized_pnl = (sell_notional - sell_fee) - cost_basis_sold
                fill_rows.append(
                    FillEvent(
                        execution_date=current_date,
                        signal_date=signal_date,
                        symbol=symbol,
                        action="SELL",
                        shares=sell_shares,
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
                sold_count += 1
                if position.shares <= Decimal("0.0000000001"):
                    net_positions.pop(symbol, None)

        for symbol in all_symbols:
            execution_open = current_open_prices[symbol]
            if execution_open is None:
                continue

            gross_delta = gross_deltas[symbol]
            if gross_delta > 0:
                buy_shares = gross_delta / execution_open
                gross_cash -= gross_delta
                gross_positions[symbol] = gross_positions.get(symbol, Decimal("0")) + buy_shares

            net_delta = net_deltas[symbol]
            if net_delta > 0:
                buy_shares = net_delta / execution_open
                buy_fee = net_delta * transaction_cost_rate
                net_cash -= net_delta + buy_fee
                position = net_positions.get(symbol)
                if position is None:
                    net_positions[symbol] = Position(shares=Decimal("0"), cost_basis=Decimal("0"), entry_mass=Decimal("0"))
                    position = net_positions[symbol]
                position.buy(buy_shares, net_delta + buy_fee, current_date)
                fill_rows.append(
                    FillEvent(
                        execution_date=current_date,
                        signal_date=signal_date,
                        symbol=symbol,
                        action="BUY",
                        shares=buy_shares,
                        execution_price=execution_open,
                        fees=buy_fee,
                        net_cash_flow=-(net_delta + buy_fee),
                    )
                )
                total_fees += buy_fee
                rebalance_buy_notional += net_delta
                rebalance_fees += buy_fee
                total_turnover_notional += net_delta

        turnover = (
            (rebalance_buy_notional + rebalance_sell_notional) / net_pre_trade_value
            if net_pre_trade_value > 0
            else Decimal("0")
        )
        summary_rows.append(
            RebalanceSummary(
                signal_date=signal_date,
                execution_date=current_date,
                selected_count=len(target_allocations),
                sold_count=sold_count,
                buy_notional=rebalance_buy_notional,
                sell_notional=rebalance_sell_notional,
                fees=rebalance_fees,
                turnover=turnover,
                notes=note,
            )
        )
        portfolio_state = resulting_state
        return None, True

    for current_date in calendar_in_range:
        if pending_action and pending_action.execution_date == current_date:
            if pending_action.action_type == "target":
                error_reason, changed = execute_target_portfolio(
                    current_date=current_date,
                    signal_date=pending_action.signal_date,
                    target_allocations=pending_action.target_allocations,
                    note=pending_action.note,
                    resulting_state=pending_action.resulting_state,
                    allow_missing_target_hold=pending_action.allow_missing_target_hold,
                )
                if error_reason is not None:
                    return SimulationResult(
                        state=PageState.ERROR,
                        equity_curve=[],
                        summary_rows=[],
                        fill_rows=[],
                        warnings=[],
                        data_quality_flags=[],
                        summary_metrics={},
                        unavailable_reasons=[error_reason],
                        error_message=error_reason.detail,
                    )
            elif pending_action.action_type == "hold":
                summary_rows.append(
                    RebalanceSummary(
                        signal_date=pending_action.signal_date,
                        execution_date=current_date,
                        selected_count=len(pending_action.target_allocations),
                        sold_count=0,
                        buy_notional=Decimal("0"),
                        sell_notional=Decimal("0"),
                        fees=Decimal("0"),
                        turnover=Decimal("0"),
                        notes=pending_action.note,
                    )
                )
                portfolio_state = pending_action.resulting_state
            pending_action = None

            if benchmark_shares is None and first_execution_date == current_date:
                benchmark_entry_price = execution_open_map.get(("SPY", current_date))
                if benchmark_entry_price is None:
                    benchmark_entry_price = benchmark_map.get(current_date)
                    if benchmark_entry_price is not None:
                        quality_flags.add("SPY 시작 시가가 없어 첫 체결일 종가로 비교선을 시작했습니다.")
                if benchmark_entry_price is not None and benchmark_entry_price > 0:
                    benchmark_shares = Decimal(input_data.initial_capital) / (
                        benchmark_entry_price * (Decimal("1") + transaction_cost_rate)
                    )

        gross_equity = gross_cash
        net_equity = net_cash
        for symbol, shares in gross_positions.items():
            close_value = _fallback_close_price(close_map, last_known_closes, symbol, current_date, execution_open_map, quality_flags)
            if close_value is not None:
                gross_equity += shares * close_value
        for symbol, position in net_positions.items():
            close_value = _fallback_close_price(close_map, last_known_closes, symbol, current_date, execution_open_map, quality_flags)
            if close_value is not None:
                net_equity += position.shares * close_value

        benchmark_equity: Decimal | None = None
        if benchmark_shares is not None and first_execution_date is not None and current_date >= first_execution_date:
            benchmark_value = benchmark_map.get(current_date)
            if benchmark_value is not None:
                benchmark_last_value = benchmark_value
            elif benchmark_last_value is not None:
                benchmark_value = benchmark_last_value
                quality_flags.add("일부 SPY 기준값이 비어 있어 직전 사용 가능 가격으로 비교선을 이어 그렸습니다.")
            if benchmark_value is not None:
                benchmark_equity = benchmark_shares * benchmark_value

        equity_curve.append(
            EquityPoint(
                date=current_date,
                gross_equity=gross_equity,
                net_equity=net_equity,
                benchmark_equity=benchmark_equity,
            )
        )

        if current_date in signal_dates:
            execution_date = schedule.get(current_date)
            month_signal = _evaluate_month_end_overlay_signal(input_data.market_timing_overlay, current_date, history_map, index_map)
            if month_signal.risk_on is None:
                overlay_unavailable_facts.extend(f"{current_date.isoformat()} 월말: {fact}" for fact in month_signal.facts)
            if execution_date is None:
                continue
            selected_rows = selected_by_signal.get(current_date, [])

            if input_data.market_timing_overlay == MarketTimingOverlayId.NONE:
                if selected_rows:
                    pending_action = PendingAction(
                        action_type="target",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=_equal_weight_allocations([row.symbol for row in selected_rows]),
                        note="month-end risk_on: factor rebalance",
                        resulting_state="invested_in_factor",
                    )
                elif portfolio_state == "invested_in_factor":
                    pending_action = PendingAction(
                        action_type="hold",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=tuple(),
                        note="month-end risk_on: factor hold (no executable basket)",
                        resulting_state="invested_in_factor",
                    )
                continue

            if input_data.market_timing_overlay == MarketTimingOverlayId.GRADUATED_POSITION_SIZING:
                sw = month_signal.strategy_weight
                if sw is not None and selected_rows:
                    factor_symbols = [row.symbol for row in selected_rows]
                    blended = _build_blended_allocations(factor_symbols, safe_asset_allocations, sw)
                    blended_summary = _allocation_summary(blended, as_percent=True)
                    if sw == Decimal("1"):
                        pending_action = PendingAction(
                            action_type="target",
                            signal_date=current_date,
                            execution_date=execution_date,
                            target_allocations=blended,
                            note="month-end graduated: 100% factor",
                            resulting_state="invested_in_factor",
                        )
                    elif sw == Decimal("0"):
                        pending_action = PendingAction(
                            action_type="target",
                            signal_date=current_date,
                            execution_date=execution_date,
                            target_allocations=safe_asset_allocations,
                            note=f"month-end graduated: 100% safe -> {safe_asset_summary}",
                            resulting_state="parked_in_safe_asset",
                        )
                    else:
                        sw_pct = int(sw * 100)
                        safe_pct = 100 - sw_pct
                        pending_action = PendingAction(
                            action_type="target",
                            signal_date=current_date,
                            execution_date=execution_date,
                            target_allocations=blended,
                            note=f"month-end graduated: {sw_pct}% factor + {safe_pct}% safe",
                            resulting_state="partially_hedged",
                        )
                elif sw is not None and sw == Decimal("0"):
                    pending_action = PendingAction(
                        action_type="target",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=safe_asset_allocations,
                        note=f"month-end graduated: 100% safe -> {safe_asset_summary}",
                        resulting_state="parked_in_safe_asset",
                    )
                elif sw is not None and not selected_rows and portfolio_state in {"invested_in_factor", "partially_hedged"}:
                    quality_flags.add("월말 재진입 조건은 충족했지만 해당 월 실행 가능한 팩터 바스켓이 없어 기존 포지션을 유지했습니다.")
                    pending_action = PendingAction(
                        action_type="hold",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=tuple(),
                        note="month-end graduated: hold (no executable basket)",
                        resulting_state=portfolio_state,
                    )
                continue

            if portfolio_state == "parked_in_safe_asset":
                if month_signal.risk_on is True and selected_rows:
                    pending_action = PendingAction(
                        action_type="target",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=_equal_weight_allocations([row.symbol for row in selected_rows]),
                        note=f"month-end risk_on: {safe_asset_summary} -> factor basket",
                        resulting_state="invested_in_factor",
                    )
                else:
                    if month_signal.risk_on is True and not selected_rows:
                        quality_flags.add("월말 재진입 조건은 충족했지만 해당 월 실행 가능한 팩터 바스켓이 없어 안전자산을 유지했습니다.")
                    pending_action = PendingAction(
                        action_type="hold",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=safe_asset_allocations,
                        note="month-end risk_off: safe asset hold",
                        resulting_state="parked_in_safe_asset",
                    )
                continue

            if month_signal.risk_on is False:
                pending_action = PendingAction(
                    action_type="target",
                    signal_date=current_date,
                    execution_date=execution_date,
                    target_allocations=safe_asset_allocations,
                    note=f"month-end risk_off: factor basket -> {safe_asset_summary}",
                    resulting_state="parked_in_safe_asset",
                )
            elif selected_rows:
                pending_action = PendingAction(
                    action_type="target",
                    signal_date=current_date,
                    execution_date=execution_date,
                    target_allocations=_equal_weight_allocations([row.symbol for row in selected_rows]),
                    note="month-end risk_on: factor rebalance",
                    resulting_state="invested_in_factor",
                )
            elif portfolio_state == "invested_in_factor":
                    pending_action = PendingAction(
                        action_type="hold",
                        signal_date=current_date,
                        execution_date=execution_date,
                        target_allocations=tuple(),
                        note="month-end risk_on: factor hold (no executable basket)",
                        resulting_state="invested_in_factor",
                    )

        if (
            input_data.market_timing_overlay != MarketTimingOverlayId.NONE
            and portfolio_state in {"invested_in_factor", "partially_hedged"}
        ):
            daily_signal = _evaluate_daily_risk_off(input_data.market_timing_overlay, current_date, history_map, index_map)
            if daily_signal.risk_on is None:
                overlay_unavailable_facts.extend(f"{current_date.isoformat()} 일간: {fact}" for fact in daily_signal.facts)
            if daily_signal.risk_on is False:
                execution_date = next_date_by_date.get(current_date)
                if execution_date is not None:
                    if (
                        input_data.market_timing_overlay == MarketTimingOverlayId.GRADUATED_POSITION_SIZING
                        and daily_signal.strategy_weight is not None
                    ):
                        daily_sw = daily_signal.strategy_weight
                        daily_safe_pct = int((Decimal("1") - daily_sw) * 100)
                        if portfolio_state == "partially_hedged":
                            pass
                        else:
                            factor_symbols_for_daily = [
                                symbol for symbol in sorted(set(gross_positions) | set(net_positions))
                                if symbol not in {sa.symbol for sa in safe_asset_allocations}
                            ]
                            if factor_symbols_for_daily:
                                blended = _build_blended_allocations(factor_symbols_for_daily, safe_asset_allocations, daily_sw)
                                pending_action = PendingAction(
                                    action_type="target",
                                    signal_date=current_date,
                                    execution_date=execution_date,
                                    target_allocations=blended,
                                    note=f"daily risk_off graduated: {int(daily_sw * 100)}% factor + {daily_safe_pct}% safe",
                                    resulting_state="partially_hedged",
                                )
                    else:
                        pending_action = PendingAction(
                            action_type="target",
                            signal_date=current_date,
                            execution_date=execution_date,
                            target_allocations=safe_asset_allocations,
                            note=f"daily risk_off: factor basket -> {safe_asset_summary}",
                            resulting_state="parked_in_safe_asset",
                        )

    if first_execution_date is not None and not any(point.benchmark_equity is not None for point in equity_curve):
        quality_flags.add("SPY 첫 체결일 기준값이 없어 이번 실행에서는 비교선을 그리지 못했습니다.")

    if not summary_rows:
        if overlay_unavailable_facts:
            unavailable_reasons.append(
                _build_unavailable_reason(
                    code="overlay_history_unavailable",
                    title="오버레이 신호 계산 이력이 부족합니다",
                    detail="선택한 기간 초반에 마켓타이밍 신호를 계산할 가격 이력이 부족했습니다.",
                    facts=overlay_unavailable_facts[:6],
                    suggestions=["시작일을 더 뒤로 늦추거나 안전자산이 더 오래된 구간을 선택해 보세요."],
                )
            )
        return SimulationResult(
            state=PageState.INSUFFICIENT_HISTORY if overlay_unavailable_facts else PageState.NO_DATA,
            equity_curve=[],
            summary_rows=[],
            fill_rows=[],
            warnings=[],
            data_quality_flags=[],
            summary_metrics={},
            unavailable_reasons=unavailable_reasons or [
                _build_unavailable_reason(
                    code="no_executable_results",
                    title="실행 가능한 결과를 만들지 못했습니다",
                    detail="선택한 기간에는 팩터 바스켓과 오버레이를 함께 만족하는 실행 구간이 없었습니다.",
                    suggestions=["기간을 넓히거나 오버레이를 끄고 비교해 보세요."],
                )
            ],
            error_message="선택한 기간에는 실행 가능한 결과를 만들지 못했습니다.",
        )

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
        insufficient_history or bool(overlay_unavailable_facts),
    )
    if first_execution_date is not None and not any(point.benchmark_equity is not None for point in equity_curve):
        warning_events.append(
            WarningEvent(
                title="SPY 비교선 제외",
                body="첫 체결일에 SPY 시작 가격을 확보하지 못해 이번 실행에서는 SPY 기준 비교선을 그리지 못했습니다.",
            )
        )
    return SimulationResult(
        state=PageState.SUCCESS,
        equity_curve=equity_curve,
        summary_rows=summary_rows,
        fill_rows=fill_rows,
        warnings=warning_events,
        data_quality_flags=sorted(quality_flags),
        summary_metrics=summary_metrics,
        unavailable_reasons=[],
        error_message=None,
    )
