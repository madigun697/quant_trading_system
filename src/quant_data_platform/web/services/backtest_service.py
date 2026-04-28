from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from typing import Any

import psycopg
from quant_data_platform.web.presets import (
    TRANSACTION_COST_BPS,
    StrategyPresetId,
    TransactionCostPreset,
    get_strategy_preset,
    list_cost_options,
    list_preset_options,
)
from quant_data_platform.web.repositories.backtest_repo import BacktestRepository, ReadinessStatus
from quant_data_platform.web.schemas import (
    BacktestFormInput,
    BacktestPageContext,
    EquityCurvePoint,
    PageState,
    SummaryMetric,
    TradeLogDetailRow,
    TradeLogSummaryRow,
    WarningMessage,
    form_values_from_model,
)
from quant_data_platform.web.services.engine import (
    SimulationResult,
    execution_schedule,
    month_end_signal_dates,
    select_top_candidates,
    simulate_backtest,
)


def _format_currency(value: Decimal | float | int) -> str:
    amount = Decimal(value)
    return f"${amount:,.2f}"


def _format_percent(value: Decimal | float | int) -> str:
    amount = Decimal(value) * Decimal("100")
    return f"{amount:,.2f}%"


def _format_decimal(value: Decimal | float | int, digits: int = 2) -> str:
    amount = Decimal(value)
    return f"{amount:,.{digits}f}"


def build_equity_curve_svg(points: list[EquityCurvePoint]) -> str | None:
    if len(points) < 2:
        return None
    width = 960
    height = 320
    padding_x = 48
    padding_y = 24
    usable_width = width - padding_x * 2
    usable_height = height - padding_y * 2

    gross_values = [point.gross_equity for point in points]
    net_values = [point.net_equity for point in points]
    min_value = float(min(min(gross_values), min(net_values)))
    max_value = float(max(max(gross_values), max(net_values)))
    if max_value == min_value:
        max_value += 1.0

    def path_for(values: list[float]) -> str:
        commands: list[str] = []
        for index, value in enumerate(values):
            x = padding_x + (usable_width * index / max(len(values) - 1, 1))
            y_ratio = (value - min_value) / (max_value - min_value)
            y = height - padding_y - (usable_height * y_ratio)
            commands.append(f"{'M' if index == 0 else 'L'} {x:.2f} {y:.2f}")
        return " ".join(commands)

    gross_path = path_for([float(value) for value in gross_values])
    net_path = path_for([float(value) for value in net_values])
    start_label = escape(points[0].date)
    end_label = escape(points[-1].date)
    return f"""
<svg viewBox="0 0 {width} {height}" class="equity-chart" role="img" aria-labelledby="equity-chart-title equity-chart-desc">
  <title id="equity-chart-title">Gross vs Net 누적 자산 곡선</title>
  <desc id="equity-chart-desc">백테스트 기간 동안 거래비용 전후 자산 변화를 비교하는 차트입니다.</desc>
  <rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="rgba(247, 243, 233, 0.72)"></rect>
  <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="#8d8778" stroke-width="1.2"></line>
  <line x1="{padding_x}" y1="{padding_y}" x2="{padding_x}" y2="{height - padding_y}" stroke="#8d8778" stroke-width="1.2"></line>
  <path d="{gross_path}" fill="none" stroke="#4b7f52" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></path>
  <path d="{net_path}" fill="none" stroke="#102f3f" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"></path>
  <text x="{padding_x}" y="{padding_y - 6}" fill="#6b6658" font-size="12">시작 {start_label}</text>
  <text x="{width - padding_x}" y="{padding_y - 6}" fill="#6b6658" font-size="12" text-anchor="end">종료 {end_label}</text>
  <g transform="translate({padding_x}, {height - 8})">
    <rect x="0" y="-12" width="12" height="3" rx="1.5" fill="#4b7f52"></rect>
    <text x="18" y="-8" fill="#254031" font-size="12">Gross</text>
    <rect x="90" y="-12" width="12" height="3" rx="1.5" fill="#102f3f"></rect>
    <text x="108" y="-8" fill="#102f3f" font-size="12">Net</text>
  </g>
</svg>
""".strip()


class SimpleLruCache:
    def __init__(self, max_size: int = 24) -> None:
        self.max_size = max_size
        self._store: OrderedDict[tuple[str, ...], BacktestPageContext] = OrderedDict()

    def get(self, key: tuple[str, ...]) -> BacktestPageContext | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: tuple[str, ...], value: BacktestPageContext) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)


class BacktestPageService:
    def __init__(self, repository: BacktestRepository) -> None:
        self.repository = repository
        self._cache = SimpleLruCache()

    def readiness_status(self) -> ReadinessStatus:
        return self.repository.check_readiness(StrategyPresetId.VALUE_QUALITY)

    def empty_context(self, today: date | None = None) -> BacktestPageContext:
        default_form = BacktestFormInput(
            strategy_preset=StrategyPresetId.VALUE_QUALITY,
            start_date=(today or date.today()) - timedelta(days=365 * 5),
            end_date=today or date.today(),
            initial_capital=Decimal("100000"),
            top_n=10,
            transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
        )
        return BacktestPageContext(
            state=PageState.EMPTY,
            form_values=form_values_from_model(default_form),
            preset_options=list_preset_options(),
            transaction_cost_options=list_cost_options(),
        )

    def error_context(
        self,
        form: BacktestFormInput | None,
        message: str,
        field_errors: dict[str, str] | None = None,
        http_status_code: int = 400,
    ) -> BacktestPageContext:
        base_form = form_values_from_model(form) if form else self.empty_context().form_values
        return BacktestPageContext(
            state=PageState.ERROR,
            form_values=base_form,
            preset_options=list_preset_options(),
            transaction_cost_options=list_cost_options(),
            error_message=message,
            field_errors=field_errors or {},
            http_status_code=http_status_code,
        )

    def build_context(self, form: BacktestFormInput) -> BacktestPageContext:
        readiness = self.repository.check_readiness(form.strategy_preset)
        if not readiness.ok:
            return self._dependency_error_context(form, readiness)
        try:
            freshness_token = self.repository.fetch_freshness_token(form.strategy_preset)
            cache_key = (
                form.strategy_preset.value,
                form.start_date.isoformat(),
                form.end_date.isoformat(),
                str(form.initial_capital),
                str(form.top_n),
                form.transaction_cost_preset.value,
                freshness_token,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

            calendar_start = form.start_date
            calendar_end = form.end_date + timedelta(days=7)
            spy_calendar = self.repository.fetch_spy_calendar(calendar_start, calendar_end)
            signal_dates = month_end_signal_dates(spy_calendar, form.start_date, form.end_date)
            factor_rows = self.repository.fetch_factor_rows(form.strategy_preset, signal_dates)
            all_factor_symbols = sorted({row.symbol for row in factor_rows})
            execution_dates = [
                spy_calendar[index + 1]
                for index, current_date in enumerate(spy_calendar[:-1])
                if current_date in signal_dates and spy_calendar[index + 1] <= form.end_date
            ]
            execution_price_rows = self.repository.fetch_execution_prices(all_factor_symbols, execution_dates)
            earliest_available = self.repository.fetch_earliest_available_trade_date(form.strategy_preset)
            selected_symbols = self._selected_symbols_for_daily_closes(form, spy_calendar, factor_rows, execution_price_rows)
            daily_close_rows = self.repository.fetch_daily_closes(selected_symbols, form.start_date, form.end_date)
            simulation = simulate_backtest(
                input_data=form,
                calendar_dates=spy_calendar,
                factor_rows=factor_rows,
                execution_price_rows=execution_price_rows,
                daily_close_rows=daily_close_rows,
                earliest_available_trade_date=earliest_available,
                transaction_cost_rate=Decimal(str(TRANSACTION_COST_BPS[form.transaction_cost_preset])),
            )
        except psycopg.Error as exc:
            return self._dependency_error_context(form, self.repository.classify_error(exc, form.strategy_preset))
        context = self._context_from_simulation(form, simulation)
        self._cache.set(cache_key, context)
        return context

    def _selected_symbols_for_daily_closes(
        self,
        form: BacktestFormInput,
        spy_calendar: list[date],
        factor_rows: list[Any],
        execution_price_rows: list[Any],
    ) -> list[str]:
        preset = get_strategy_preset(form.strategy_preset)
        signal_dates = month_end_signal_dates(spy_calendar, form.start_date, form.end_date)
        schedule = execution_schedule(spy_calendar, signal_dates, form.end_date)
        factor_rows_by_signal: dict[date, list[Any]] = defaultdict(list)
        for row in factor_rows:
            factor_rows_by_signal[row.trade_date].append(row)
        execution_open_map = {
            (row.symbol, row.trade_date): Decimal(row.adjusted_open) if row.adjusted_open is not None else None
            for row in execution_price_rows
        }
        selected_symbols: set[str] = set()
        for signal_date in signal_dates:
            execution_date = schedule.get(signal_date)
            if execution_date is None:
                continue
            selected_rows, _excluded = select_top_candidates(
                factor_rows_by_signal.get(signal_date, []),
                preset,
                form.top_n,
                execution_open_map,
                execution_date,
            )
            selected_symbols.update(row.symbol for row in selected_rows)
        return sorted(selected_symbols)

    def _dependency_error_context(self, form: BacktestFormInput, readiness: ReadinessStatus) -> BacktestPageContext:
        return self.error_context(
            form=form,
            message=self._dependency_error_message(readiness),
            http_status_code=503 if readiness.code != "database_error" else 500,
        )

    def _dependency_error_message(self, readiness: ReadinessStatus) -> str:
        if readiness.code == "database_unreachable":
            return (
                "백테스트 데이터베이스에 연결하지 못했습니다. "
                "Docker 경로라면 `docker compose up -d postgres backtest-web`로 서비스를 띄워 주세요. "
                "로컬 `uv run` 경로라면 `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432`를 지정해 compose Postgres에 연결해야 합니다."
            )
        if readiness.code in {"missing_schema", "missing_relation", "unqueryable_relation"}:
            return (
                "데이터베이스 연결은 되었지만 백테스트용 mart/stg 데이터가 아직 준비되지 않았습니다. "
                "Airflow 적재와 dbt 모델 실행이 끝났는지 확인해 주세요."
            )
        return "백테스트 쿼리 실행 중 데이터베이스 오류가 발생했습니다. 연결 상태와 서버 로그를 함께 확인해 주세요."

    def _context_from_simulation(self, form: BacktestFormInput, simulation: SimulationResult) -> BacktestPageContext:
        if simulation.state in {PageState.NO_DATA, PageState.INSUFFICIENT_HISTORY, PageState.ERROR}:
            return BacktestPageContext(
                state=simulation.state,
                form_values=form_values_from_model(form),
                preset_options=list_preset_options(),
                transaction_cost_options=list_cost_options(),
                warnings=[WarningMessage(title=warning.title, body=warning.body, tone=warning.tone) for warning in simulation.warnings],
                data_quality_flags=simulation.data_quality_flags,
                error_message=simulation.error_message,
                http_status_code=400 if simulation.state == PageState.ERROR else 200,
            )

        summary_metrics = self._build_summary_metrics(simulation.summary_metrics)
        equity_points = [
            EquityCurvePoint(
                date=point.date.isoformat(),
                gross_equity=float(point.gross_equity),
                net_equity=float(point.net_equity),
            )
            for point in simulation.equity_curve
        ]
        summary_rows = [
            TradeLogSummaryRow(
                signal_date=row.signal_date.isoformat(),
                execution_date=row.execution_date.isoformat(),
                selected_count=row.selected_count,
                sold_count=row.sold_count,
                buy_notional=_format_currency(row.buy_notional),
                sell_notional=_format_currency(row.sell_notional),
                fees=_format_currency(row.fees),
                turnover=_format_percent(row.turnover),
                notes=row.notes,
            )
            for row in simulation.summary_rows
        ]
        detail_rows = [
            TradeLogDetailRow(
                execution_date=row.execution_date.isoformat(),
                signal_date=row.signal_date.isoformat(),
                symbol=row.symbol,
                action=row.action,
                shares=_format_decimal(row.shares, 4),
                execution_price=_format_currency(row.execution_price),
                fees=_format_currency(row.fees),
                net_cash_flow=_format_currency(row.net_cash_flow),
                realized_pnl=_format_currency(row.realized_pnl) if row.realized_pnl is not None else None,
                holding_days=f"{row.holding_days}일" if row.holding_days is not None else None,
            )
            for row in simulation.fill_rows
        ]
        context = BacktestPageContext(
            state=simulation.state,
            form_values=form_values_from_model(form),
            preset_options=list_preset_options(),
            transaction_cost_options=list_cost_options(),
            summary_metrics=summary_metrics,
            equity_curve=equity_points,
            trade_log_summary=summary_rows,
            trade_log_rows=detail_rows,
            warnings=[WarningMessage(title=warning.title, body=warning.body, tone=warning.tone) for warning in simulation.warnings],
            data_quality_flags=simulation.data_quality_flags,
            equity_curve_svg=build_equity_curve_svg(equity_points),
        )
        return context

    def _build_summary_metrics(self, metrics: dict[str, Any]) -> list[SummaryMetric]:
        return [
            SummaryMetric(key="gross_total_return", label="총수익률", value=_format_percent(metrics["gross_total_return"]), tooltip="거래비용을 반영하기 전 성과입니다."),
            SummaryMetric(key="net_total_return", label="순수익률", value=_format_percent(metrics["net_total_return"]), tooltip="거래비용을 차감한 실제 체감 수익률입니다."),
            SummaryMetric(key="gross_cagr", label="Gross CAGR", value=_format_percent(metrics["gross_cagr"]), tooltip="연환산 복리 수익률입니다."),
            SummaryMetric(key="net_cagr", label="Net CAGR", value=_format_percent(metrics["net_cagr"]), tooltip="거래비용 반영 후 연환산 복리 수익률입니다."),
            SummaryMetric(key="max_drawdown_net", label="MDD", value=_format_percent(metrics["max_drawdown_net"]), tooltip="고점 대비 최저점 하락폭입니다."),
            SummaryMetric(key="sharpe", label="Sharpe", value=_format_decimal(metrics["sharpe"], 2), tooltip="변동성 대비 얼마나 효율적으로 수익을 냈는지 보여줍니다."),
            SummaryMetric(key="trade_count", label="거래 수", value=str(metrics["trade_count"]), tooltip="BUY와 SELL 상세 체결 건수를 합산한 값입니다."),
            SummaryMetric(key="win_rate", label="승률", value=_format_percent(metrics["win_rate"]), tooltip="실현 손익 기준으로 이긴 거래 비중입니다."),
            SummaryMetric(key="expected_value", label="기대값(EV)", value=_format_currency(metrics["expected_value"]), tooltip="실현 거래 1건당 평균 손익입니다."),
            SummaryMetric(key="turnover", label="회전율", value=_format_percent(metrics["turnover"]), tooltip="누적 거래대금을 초기 자본으로 나눈 값입니다."),
            SummaryMetric(key="total_fees", label="총 거래비용", value=_format_currency(metrics["total_fees"]), tooltip="매수와 매도에서 차감된 총비용입니다."),
            SummaryMetric(key="average_holding_period", label="평균 보유기간", value=f"{Decimal(metrics['average_holding_period']):.1f}일", tooltip="실현 매도 기준 평균 보유 일수입니다."),
        ]
