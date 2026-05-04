from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Any

import psycopg
from quant_data_platform.web.presets import (
    TRANSACTION_COST_BPS,
    MarketTimingOverlayId,
    StrategyPresetId,
    TransactionCostPreset,
    get_market_timing_overlay,
    get_strategy_preset,
    list_cost_options,
    list_overlay_options,
    list_preset_options,
    list_safe_asset_options,
)
from quant_data_platform.web.repositories.backtest_repo import BacktestRepository, ReadinessStatus
from quant_data_platform.web.schemas import (
    BacktestFormInput,
    BacktestPageContext,
    CostDetail,
    EquityCurvePoint,
    OverlayDetail,
    PageState,
    PresetDetail,
    SafeAssetAllocationDetail,
    SummaryMetric,
    TradeLogDetailRow,
    TradeLogSummaryRow,
    UnavailableReason,
    WarningMessage,
    form_values_from_model,
)
from quant_data_platform.web.services.backtest_result_writer import BacktestResultWriter, DEFAULT_BACKTEST_RESULT_DIR
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
    benchmark_values = [point.benchmark_equity for point in points if point.benchmark_equity is not None]
    all_values = [*gross_values, *net_values, *benchmark_values]
    min_value = float(min(all_values))
    max_value = float(max(all_values))
    if max_value == min_value:
        max_value += 1.0

    def path_for(values: list[float | None]) -> str:
        commands: list[str] = []
        drawing = False
        for index, value in enumerate(values):
            if value is None:
                drawing = False
                continue
            x = padding_x + (usable_width * index / max(len(values) - 1, 1))
            y_ratio = (value - min_value) / (max_value - min_value)
            y = height - padding_y - (usable_height * y_ratio)
            commands.append(f"{'M' if not drawing else 'L'} {x:.2f} {y:.2f}")
            drawing = True
        return " ".join(commands)

    gross_path = path_for([float(value) for value in gross_values])
    net_path = path_for([float(value) for value in net_values])
    benchmark_path = path_for([float(value) if value is not None else None for value in (point.benchmark_equity for point in points)])
    start_label = escape(points[0].date)
    end_label = escape(points[-1].date)
    benchmark_path_markup = (
        f'<path d="{benchmark_path}" fill="none" stroke="#b86830" stroke-width="2.4" '
        'stroke-dasharray="8 6" stroke-linejoin="round" stroke-linecap="round"></path>'
        if benchmark_values and benchmark_path
        else ""
    )
    benchmark_legend_markup = (
        '<rect x="180" y="-12" width="12" height="3" rx="1.5" fill="#b86830"></rect>'
        '<text x="198" y="-8" fill="#7c4a24" font-size="12">SPY</text>'
        if benchmark_values
        else ""
    )
    return f"""
<svg viewBox="0 0 {width} {height}" class="equity-chart" role="img" aria-labelledby="equity-chart-title equity-chart-desc">
  <title id="equity-chart-title">Net, SPY, Gross 누적 자산 곡선</title>
  <desc id="equity-chart-desc">전략 순성과와 SPY 비교선, 거래비용 전 성과를 함께 보여 주는 차트입니다.</desc>
  <rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="rgba(247, 243, 233, 0.72)"></rect>
  <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}" stroke="#8d8778" stroke-width="1.2"></line>
  <line x1="{padding_x}" y1="{padding_y}" x2="{padding_x}" y2="{height - padding_y}" stroke="#8d8778" stroke-width="1.2"></line>
  <path d="{gross_path}" fill="none" stroke="#8fa59b" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></path>
  {benchmark_path_markup}
  <path d="{net_path}" fill="none" stroke="#102f3f" stroke-width="3.4" stroke-linejoin="round" stroke-linecap="round"></path>
  <text x="{padding_x}" y="{padding_y - 6}" fill="#6b6658" font-size="12">시작 {start_label}</text>
  <text x="{width - padding_x}" y="{padding_y - 6}" fill="#6b6658" font-size="12" text-anchor="end">종료 {end_label}</text>
  <g transform="translate({padding_x}, {height - 8})">
    <rect x="0" y="-12" width="12" height="3" rx="1.5" fill="#102f3f"></rect>
    <text x="18" y="-8" fill="#102f3f" font-size="12">Net</text>
    <rect x="90" y="-12" width="12" height="3" rx="1.5" fill="#8fa59b"></rect>
    <text x="108" y="-8" fill="#496057" font-size="12">Gross</text>
    {benchmark_legend_markup}
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
    def __init__(
        self,
        repository: BacktestRepository,
        result_writer: BacktestResultWriter | None = None,
    ) -> None:
        self.repository = repository
        self._cache = SimpleLruCache()
        self.result_writer = result_writer or BacktestResultWriter(DEFAULT_BACKTEST_RESULT_DIR)

    def readiness_status(self) -> ReadinessStatus:
        return self.repository.check_readiness(StrategyPresetId.VALUE_QUALITY)

    def empty_context(self, today: date | None = None) -> BacktestPageContext:
        default_form = BacktestFormInput(
            strategy_preset=StrategyPresetId.VALUE_QUALITY,
            market_timing_overlay=MarketTimingOverlayId.NONE,
            start_date=(today or date.today()) - timedelta(days=365 * 5),
            end_date=today or date.today(),
            initial_capital=Decimal("100000"),
            top_n=10,
            transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
        )
        form_values = form_values_from_model(default_form)
        return BacktestPageContext(
            state=PageState.EMPTY,
            form_values=form_values,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            transaction_cost_options=list_cost_options(),
            selected_preset_detail=self._selected_preset_detail(form_values["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(form_values["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(form_values),
            selected_safe_asset_summary=self._selected_safe_asset_summary(form_values),
            selected_cost_detail=self._selected_cost_detail(form_values["transaction_cost_preset"]),
        )

    def error_context(
        self,
        form: BacktestFormInput | None,
        message: str,
        field_errors: dict[str, str] | None = None,
        http_status_code: int = 400,
        unavailable_reasons: list[UnavailableReason] | None = None,
        form_values: dict[str, str] | None = None,
    ) -> BacktestPageContext:
        base_form = form_values or (form_values_from_model(form) if form else self.empty_context().form_values)
        return BacktestPageContext(
            state=PageState.ERROR,
            form_values=base_form,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            transaction_cost_options=list_cost_options(),
            selected_preset_detail=self._selected_preset_detail(base_form["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(base_form["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(base_form),
            selected_safe_asset_summary=self._selected_safe_asset_summary(base_form),
            selected_cost_detail=self._selected_cost_detail(base_form["transaction_cost_preset"]),
            error_message=message,
            field_errors=field_errors or {},
            unavailable_reasons=unavailable_reasons or [],
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
                form.market_timing_overlay.value,
                form.safe_asset_summary(),
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
            simulation = self._run_simulation(form)
        except psycopg.Error as exc:
            return self._dependency_error_context(form, self.repository.classify_error(exc, form.strategy_preset))
        context = self._context_from_simulation(form, simulation)
        self._cache.set(cache_key, context)
        return context

    def save_context(self, form: BacktestFormInput, saved_at: datetime | None = None) -> BacktestPageContext:
        readiness = self.repository.check_readiness(form.strategy_preset)
        if not readiness.ok:
            context = self._dependency_error_context(form, readiness)
            context.save_error_message = "저장용 백테스트를 다시 실행하지 못했습니다."
            return context
        try:
            simulation = self._run_simulation(form)
        except psycopg.Error as exc:
            context = self._dependency_error_context(form, self.repository.classify_error(exc, form.strategy_preset))
            context.save_error_message = "저장용 백테스트를 다시 실행하지 못했습니다."
            return context

        context = self._context_from_simulation(form, simulation)
        if simulation.state != PageState.SUCCESS:
            reason = simulation.error_message or "현재 조건에서는 저장 가능한 결과를 만들지 못했습니다."
            context.save_error_message = f"결과 저장을 완료하지 못했습니다. {reason}"
            return context

        try:
            saved_directory = self.result_writer.write(
                form=form,
                context=context,
                simulation=simulation,
                saved_at=saved_at,
            )
        except OSError as exc:
            context.save_error_message = f"결과 파일 저장 중 오류가 발생했습니다. {exc}"
            context.http_status_code = 500
            return context

        context.save_directory = str(saved_directory)
        context.save_success_message = f"백테스트 결과를 저장했습니다: {saved_directory}"
        return context

    def _run_simulation(self, form: BacktestFormInput) -> SimulationResult:
        calendar_start = form.start_date
        calendar_end = form.end_date + timedelta(days=7)
        spy_calendar = self.repository.fetch_spy_calendar(calendar_start, calendar_end)
        signal_dates = month_end_signal_dates(spy_calendar, form.start_date, form.end_date)
        factor_rows = self.repository.fetch_factor_rows(form.strategy_preset, signal_dates)
        monthly_execution_dates = [
            spy_calendar[index + 1]
            for index, current_date in enumerate(spy_calendar[:-1])
            if current_date in signal_dates and spy_calendar[index + 1] <= form.end_date
        ]
        all_factor_symbols = sorted({row.symbol for row in factor_rows} | {"SPY"})
        monthly_execution_price_rows = self.repository.fetch_execution_prices(all_factor_symbols, monthly_execution_dates)
        earliest_available = self.repository.fetch_earliest_available_trade_date(form.strategy_preset)
        selected_symbols = self._selected_symbols_for_daily_closes(form, spy_calendar, factor_rows, monthly_execution_price_rows)
        configured_safe_assets = {symbol.value for symbol, _weight in form.safe_asset_allocations()}
        support_symbols = sorted(set(selected_symbols) | {"SPY", "VT", "IEF", *configured_safe_assets})
        calendar_trade_dates = [calendar_date for calendar_date in spy_calendar if form.start_date <= calendar_date <= form.end_date]
        support_execution_price_rows = self.repository.fetch_execution_prices(support_symbols, calendar_trade_dates)
        execution_price_rows = self._merge_execution_rows(monthly_execution_price_rows, support_execution_price_rows)
        price_buffer_start = self._price_buffer_start(form)
        daily_close_rows = self.repository.fetch_daily_closes(support_symbols, price_buffer_start, form.end_date)
        benchmark_rows = self.repository.fetch_spy_benchmark_values(form.start_date, form.end_date)
        return simulate_backtest(
            input_data=form,
            calendar_dates=spy_calendar,
            factor_rows=factor_rows,
            execution_price_rows=execution_price_rows,
            daily_close_rows=daily_close_rows,
            benchmark_rows=benchmark_rows,
            earliest_available_trade_date=earliest_available,
            transaction_cost_rate=Decimal(str(TRANSACTION_COST_BPS[form.transaction_cost_preset])),
        )

    def _merge_execution_rows(self, *groups: list[Any]) -> list[Any]:
        merged: dict[tuple[str, date], Any] = {}
        for group in groups:
            for row in group:
                merged[(row.symbol, row.trade_date)] = row
        return list(merged.values())

    def _price_buffer_start(self, form: BacktestFormInput) -> date:
        factor_buffer = self.repository.compute_factor_buffer_start(form.strategy_preset, form.start_date)
        overlay_buffer = get_market_timing_overlay(form.market_timing_overlay).lookback_days
        overlay_start = form.start_date - timedelta(days=overlay_buffer)
        return min(factor_buffer, overlay_start)

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
            unavailable_reasons=[
                UnavailableReason(
                    code=readiness.code,
                    title="실행 전 확인이 필요합니다",
                    detail=self._dependency_error_message(readiness),
                    facts=[f"점검 대상: {relation}" for relation in readiness.checked_relations[:3]],
                    suggestions=self._dependency_error_suggestions(readiness),
                )
            ],
            http_status_code=503 if readiness.code != "database_error" else 500,
        )

    def _dependency_error_message(self, readiness: ReadinessStatus) -> str:
        if readiness.code == "database_unreachable":
            return (
                "백테스트 데이터베이스에 연결하지 못했습니다. "
                "Docker 경로라면 `docker compose up -d postgres backtest-web`로 서비스를 띄워 주세요. "
                "로컬 `uv run` 경로라면 `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432`를 지정해 compose Postgres에 연결해야 합니다."
            )
        if readiness.code in {"missing_schema", "missing_relation", "unqueryable_relation", "missing_support_symbol_data"}:
            return (
                "데이터베이스 연결은 되었지만 백테스트용 mart/stg 또는 지원 심볼 데이터가 아직 준비되지 않았습니다. "
                "Airflow 적재와 dbt 모델 실행이 끝났는지 확인해 주세요."
            )
        return "백테스트 쿼리 실행 중 데이터베이스 오류가 발생했습니다. 연결 상태와 서버 로그를 함께 확인해 주세요."

    def _dependency_error_suggestions(self, readiness: ReadinessStatus) -> list[str]:
        if readiness.code == "database_unreachable":
            return [
                "Docker 서비스가 꺼져 있다면 postgres와 backtest-web을 함께 실행해 주세요.",
                "로컬 실행이라면 POSTGRES_HOST와 POSTGRES_PORT가 compose Postgres를 가리키는지 확인해 주세요.",
            ]
        if readiness.code in {"missing_schema", "missing_relation", "unqueryable_relation"}:
            return [
                "stg와 mart 적재가 끝났는지 확인해 주세요.",
                "최근 dbt 실행이 실패하지 않았는지 서버 로그를 확인해 주세요.",
            ]
        if readiness.code == "missing_support_symbol_data":
            return [
                "SPY, VT, IEF, SGOV, JPST, TLT, GLD, XLE 지원 심볼의 시장 데이터 백필이 끝났는지 확인해 주세요.",
                "support symbol 적재 후 stg와 int 모델을 다시 실행해 주세요.",
            ]
        return ["데이터베이스 로그와 애플리케이션 로그를 함께 확인해 주세요."]

    def _context_from_simulation(self, form: BacktestFormInput, simulation: SimulationResult) -> BacktestPageContext:
        form_values = form_values_from_model(form)
        if simulation.state in {PageState.NO_DATA, PageState.INSUFFICIENT_HISTORY, PageState.ERROR}:
            return BacktestPageContext(
                state=simulation.state,
                form_values=form_values,
                preset_options=list_preset_options(),
                overlay_options=list_overlay_options(),
                safe_asset_options=list_safe_asset_options(),
                transaction_cost_options=list_cost_options(),
                selected_preset_detail=self._selected_preset_detail(form_values["strategy_preset"]),
                selected_overlay_detail=self._selected_overlay_detail(form_values["market_timing_overlay"]),
                selected_safe_asset_allocations=self._selected_safe_asset_allocations(form_values),
                selected_safe_asset_summary=self._selected_safe_asset_summary(form_values),
                selected_cost_detail=self._selected_cost_detail(form_values["transaction_cost_preset"]),
                warnings=[WarningMessage(title=warning.title, body=warning.body, tone=warning.tone) for warning in simulation.warnings],
                data_quality_flags=simulation.data_quality_flags,
                unavailable_reasons=[
                    UnavailableReason(
                        code=reason.code,
                        title=reason.title,
                        detail=reason.detail,
                        facts=reason.facts,
                        suggestions=reason.suggestions,
                    )
                    for reason in simulation.unavailable_reasons
                ],
                error_message=simulation.error_message,
                http_status_code=400 if simulation.state == PageState.ERROR else 200,
            )

        summary_metrics = self._build_summary_metrics(simulation.summary_metrics)
        equity_points = [
            EquityCurvePoint(
                date=point.date.isoformat(),
                gross_equity=float(point.gross_equity),
                net_equity=float(point.net_equity),
                benchmark_equity=float(point.benchmark_equity) if point.benchmark_equity is not None else None,
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
        return BacktestPageContext(
            state=simulation.state,
            form_values=form_values,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            transaction_cost_options=list_cost_options(),
            selected_preset_detail=self._selected_preset_detail(form_values["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(form_values["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(form_values),
            selected_safe_asset_summary=self._selected_safe_asset_summary(form_values),
            selected_cost_detail=self._selected_cost_detail(form_values["transaction_cost_preset"]),
            summary_metrics=summary_metrics,
            equity_curve=equity_points,
            trade_log_summary=summary_rows,
            trade_log_rows=detail_rows,
            warnings=[WarningMessage(title=warning.title, body=warning.body, tone=warning.tone) for warning in simulation.warnings],
            data_quality_flags=simulation.data_quality_flags,
            unavailable_reasons=[],
            benchmark_available=any(point.benchmark_equity is not None for point in equity_points),
            equity_curve_svg=build_equity_curve_svg(equity_points),
        )

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
            SummaryMetric(key="turnover", label="누적 거래대금 / 초기자본", value=_format_percent(metrics["turnover"]), tooltip="전체 기간 동안 실제로 거래한 총금액을 초기 자본과 비교한 값입니다."),
            SummaryMetric(key="total_fees", label="총 거래비용", value=_format_currency(metrics["total_fees"]), tooltip="매수와 매도에서 차감된 총비용입니다."),
            SummaryMetric(key="average_holding_period", label="평균 보유기간", value=f"{Decimal(metrics['average_holding_period']):.1f}일", tooltip="실현 매도 기준 평균 보유 일수입니다."),
        ]

    def _selected_preset_detail(self, preset_id: str) -> PresetDetail | None:
        for option in list_preset_options():
            if option["id"] == preset_id:
                return PresetDetail.model_validate(option)
        return None

    def _selected_overlay_detail(self, overlay_id: str) -> OverlayDetail | None:
        for option in list_overlay_options():
            if option["id"] == overlay_id:
                return OverlayDetail.model_validate(option)
        return None

    def _selected_safe_asset_allocations(self, form_values: dict[str, Any]) -> list[SafeAssetAllocationDetail]:
        allocations: list[SafeAssetAllocationDetail] = []
        for option in list_safe_asset_options():
            raw_weight = str(form_values.get(option["weight_field"], "0")).strip() or "0"
            try:
                weight = Decimal(raw_weight)
            except Exception:
                continue
            if weight <= 0:
                continue
            allocations.append(
                SafeAssetAllocationDetail.model_validate(
                    {
                        **option,
                        "weight_percent": f"{_format_decimal(weight, 1).rstrip('0').rstrip('.')}%",
                    }
                )
            )
        return allocations

    def _selected_safe_asset_summary(self, form_values: dict[str, Any]) -> str:
        allocations = self._selected_safe_asset_allocations(form_values)
        return " / ".join(f"{asset.label} {asset.weight_percent}" for asset in allocations)

    def _selected_cost_detail(self, cost_id: str) -> CostDetail | None:
        for option in list_cost_options():
            if option["id"] == cost_id:
                return CostDetail.model_validate(option)
        return None
