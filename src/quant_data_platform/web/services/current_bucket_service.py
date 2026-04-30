from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable
from zoneinfo import ZoneInfo

import psycopg
from quant_data_platform.web.presets import (
    MarketTimingOverlayId,
    StrategyPresetId,
    get_market_timing_overlay,
    get_strategy_preset,
    list_overlay_options,
    list_preset_options,
    list_safe_asset_options,
)
from quant_data_platform.web.repositories.backtest_repo import BacktestRepository, ReadinessStatus
from quant_data_platform.web.schemas import (
    CurrentBucketFormInput,
    CurrentBucketPageContext,
    CurrentBucketRow,
    OverlayDetail,
    PageState,
    PresetDetail,
    SafeAssetAllocationDetail,
    UnavailableReason,
    WarningMessage,
    current_bucket_form_values_from_model,
)
from quant_data_platform.web.services.engine import (
    evaluate_daily_overlay_signal,
    month_end_signal_dates,
    select_top_candidates_by_close,
)


MARKET_TIMEZONE = ZoneInfo("America/New_York")
MARKET_CLOSE_TIME = time(hour=16, minute=0)
CALENDAR_LOOKBACK_DAYS = 500
OVERLAY_HISTORY_BUFFER_DAYS = 450


def _format_currency(value: Decimal | float | int) -> str:
    amount = Decimal(value)
    return f"${amount:,.2f}"


def _format_percent(value: Decimal | float | int) -> str:
    amount = Decimal(value) * Decimal("100")
    return f"{amount:,.2f}%"


class CurrentBucketPageService:
    def __init__(
        self,
        repository: BacktestRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(tz=MARKET_TIMEZONE))

    def readiness_status(self) -> ReadinessStatus:
        return self.repository.check_readiness(StrategyPresetId.VALUE_QUALITY)

    def empty_context(self) -> CurrentBucketPageContext:
        default_form = CurrentBucketFormInput(
            strategy_preset=StrategyPresetId.VALUE_QUALITY,
            market_timing_overlay=MarketTimingOverlayId.NONE,
            investable_capital=Decimal("100000"),
            top_n=10,
        )
        form_values = current_bucket_form_values_from_model(default_form)
        return CurrentBucketPageContext(
            state=PageState.EMPTY,
            form_values=form_values,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            selected_preset_detail=self._selected_preset_detail(form_values["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(form_values["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(form_values),
            selected_safe_asset_summary=self._selected_safe_asset_summary(form_values),
            safe_asset_summary=self._selected_safe_asset_summary(form_values),
        )

    def error_context(
        self,
        form: CurrentBucketFormInput | None,
        message: str,
        *,
        state: PageState = PageState.ERROR,
        field_errors: dict[str, str] | None = None,
        http_status_code: int = 400,
        unavailable_reasons: list[UnavailableReason] | None = None,
        form_values: dict[str, str] | None = None,
    ) -> CurrentBucketPageContext:
        base_form = form_values or (current_bucket_form_values_from_model(form) if form else self.empty_context().form_values)
        return CurrentBucketPageContext(
            state=state,
            form_values=base_form,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            selected_preset_detail=self._selected_preset_detail(base_form["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(base_form["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(base_form),
            selected_safe_asset_summary=self._selected_safe_asset_summary(base_form),
            safe_asset_summary=self._selected_safe_asset_summary(base_form),
            error_message=message,
            field_errors=field_errors or {},
            unavailable_reasons=unavailable_reasons or [],
            http_status_code=http_status_code,
        )

    def build_context(self, form: CurrentBucketFormInput) -> CurrentBucketPageContext:
        readiness = self.repository.check_readiness(form.strategy_preset)
        if not readiness.ok:
            return self._dependency_error_context(form, readiness)
        try:
            return self._build_context(form)
        except ValueError as exc:
            return self.error_context(
                form,
                str(exc),
                state=PageState.NO_DATA,
                unavailable_reasons=[
                    UnavailableReason(
                        code="invalid_reference_close",
                        title="기준 종가를 사용할 수 없습니다",
                        detail=str(exc),
                        suggestions=["해당 기준일의 stg.stg_daily_prices 적재 상태를 확인해 주세요."],
                    )
                ],
            )
        except psycopg.Error as exc:
            return self._dependency_error_context(form, self.repository.classify_error(exc, form.strategy_preset))

    def _build_context(self, form: CurrentBucketFormInput) -> CurrentBucketPageContext:
        now_et = self._market_now()
        calendar_end = now_et.date()
        calendar_start = calendar_end - timedelta(days=CALENDAR_LOOKBACK_DAYS)
        spy_calendar = self.repository.fetch_spy_calendar(calendar_start, calendar_end)
        as_of_date, price_basis_label = self._resolve_as_of_date(spy_calendar, now_et)
        if as_of_date is None:
            return self.error_context(
                form,
                "현재 기준일을 계산할 거래일 이력이 없습니다. SPY benchmark 캘린더 적재 상태를 확인해 주세요.",
                state=PageState.NO_DATA,
                unavailable_reasons=[
                    UnavailableReason(
                        code="missing_calendar",
                        title="거래일 캘린더가 비어 있습니다",
                        detail="SPY benchmark 시계열에서 현재 버킷 기준일을 고를 수 없었습니다.",
                        suggestions=["stg.stg_benchmark_series 적재 상태를 확인해 주세요."],
                    )
                ],
            )

        candidate_signal_dates = month_end_signal_dates(spy_calendar, spy_calendar[0], as_of_date)
        if not candidate_signal_dates:
            return self.error_context(
                form,
                "현재 기준일 이전에 사용할 수 있는 월말 시그널 날짜가 없습니다.",
                state=PageState.INSUFFICIENT_HISTORY,
            )

        factor_rows = self.repository.fetch_factor_rows(form.strategy_preset, candidate_signal_dates)
        if not factor_rows:
            return self.error_context(
                form,
                "선택한 전략의 최신 월말 스냅샷을 찾지 못했습니다.",
                state=PageState.NO_DATA,
            )
        signal_date = max(row.trade_date for row in factor_rows)
        factor_rows = [row for row in factor_rows if row.trade_date == signal_date]

        factor_symbols = sorted({row.symbol for row in factor_rows})
        support_symbols = sorted({"SPY", "VT", "IEF", *(symbol.value for symbol, _weight in form.safe_asset_allocations())})
        reference_close_rows = self.repository.fetch_daily_closes(sorted(set(factor_symbols) | set(support_symbols)), as_of_date, as_of_date)
        reference_close_map = {
            (row.symbol, row.trade_date): Decimal(row.adjusted_close) if row.adjusted_close is not None else None
            for row in reference_close_rows
        }

        preset = get_strategy_preset(form.strategy_preset)
        selected_rows, excluded_counts = select_top_candidates_by_close(
            factor_rows,
            preset,
            form.top_n,
            reference_close_map,
            as_of_date,
        )
        if len(selected_rows) < form.top_n:
            return self.error_context(
                form,
                "현 시점 종가 기준으로 필요한 수만큼의 투자 후보를 만들지 못했습니다.",
                state=PageState.NO_DATA,
                unavailable_reasons=[
                    UnavailableReason(
                        code="insufficient_current_bucket_candidates",
                        title="현재 버킷 후보가 부족합니다",
                        detail="요구한 Top-N 수를 기준일 종가까지 충족하는 종목이 부족했습니다.",
                        facts=[
                            f"요청한 Top-N: {form.top_n}",
                            f"선정된 후보 수: {len(selected_rows)}",
                            f"결측 팩터 제외 수: {excluded_counts.get('missing_factors', 0)}",
                            f"기준일 종가 결측 제외 수: {excluded_counts.get('missing_reference_close', 0)}",
                        ],
                        suggestions=[
                            "다른 전략 프리셋이나 더 작은 Top-N으로 다시 시도해 주세요.",
                            "해당 기준일의 stg.stg_daily_prices 종가 적재 상태를 확인해 주세요.",
                        ],
                    )
                ],
            )

        history_symbols = sorted(set(support_symbols))
        history_start = as_of_date - timedelta(days=OVERLAY_HISTORY_BUFFER_DAYS)
        history_rows = self.repository.fetch_daily_closes(history_symbols, history_start, as_of_date)
        overlay_signal = evaluate_daily_overlay_signal(form.market_timing_overlay, as_of_date, history_rows)
        if overlay_signal.risk_on is None:
            return self.error_context(
                form,
                "마켓타이밍 오버레이를 계산할 과거 가격 이력이 부족합니다.",
                state=PageState.INSUFFICIENT_HISTORY,
                unavailable_reasons=[
                    UnavailableReason(
                        code="insufficient_overlay_history",
                        title="오버레이 가격 이력이 부족합니다",
                        detail="선택한 기준일까지 risk-on / risk-off 판단에 필요한 이력이 충분하지 않았습니다.",
                        facts=overlay_signal.facts,
                        suggestions=["오버레이를 끄거나 더 뒤 시점의 데이터 적재 상태를 확인해 주세요."],
                    )
                ],
            )

        bucket_rows, cash_remainder = self._build_bucket_rows(
            selected_rows=selected_rows,
            as_of_date=as_of_date,
            reference_close_map=reference_close_map,
            investable_capital=form.investable_capital,
        )
        active_risk_state = "risk_on" if overlay_signal.risk_on else "risk_off"
        safe_asset_summary = form.safe_asset_summary()
        warnings = [
            WarningMessage(
                title="종가 기준 버킷",
                body="이 화면은 실시간 주문 실행이 아니라 최신 기준 종가로 계산한 투자 후보와 목표 수량을 보여 줍니다.",
                tone="info",
            )
        ]
        if form.market_timing_overlay != MarketTimingOverlayId.NONE:
            warnings.append(
                WarningMessage(
                    title="오버레이 상태 반영",
                    body=f"{get_market_timing_overlay(form.market_timing_overlay).label} 기준 현재 상태는 {active_risk_state.replace('_', '-')} 입니다.",
                    tone="info",
                )
            )
        risk_off_notice = None
        if overlay_signal.risk_on is False:
            risk_off_notice = f"현재 오버레이는 risk-off 상태입니다. 아래 표는 주식 후보 버킷이며, 실제 투자 바스켓은 {safe_asset_summary}입니다."
            warnings.append(
                WarningMessage(
                    title="현재는 안전자산 구간입니다",
                    body=risk_off_notice,
                    tone="warning",
                )
            )

        form_values = current_bucket_form_values_from_model(form)
        return CurrentBucketPageContext(
            state=PageState.SUCCESS,
            form_values=form_values,
            preset_options=list_preset_options(),
            overlay_options=list_overlay_options(),
            safe_asset_options=list_safe_asset_options(),
            selected_preset_detail=self._selected_preset_detail(form_values["strategy_preset"]),
            selected_overlay_detail=self._selected_overlay_detail(form_values["market_timing_overlay"]),
            selected_safe_asset_allocations=self._selected_safe_asset_allocations(form_values),
            selected_safe_asset_summary=self._selected_safe_asset_summary(form_values),
            safe_asset_summary=safe_asset_summary,
            stock_bucket_rows=bucket_rows,
            warnings=warnings,
            as_of_date=as_of_date.isoformat(),
            price_basis_label=price_basis_label,
            signal_date=signal_date.isoformat(),
            active_risk_state=active_risk_state,
            cash_remainder=_format_currency(cash_remainder),
            risk_off_notice=risk_off_notice,
        )

    def _market_now(self) -> datetime:
        current_time = self.clock()
        if current_time.tzinfo is None:
            return current_time.replace(tzinfo=MARKET_TIMEZONE)
        return current_time.astimezone(MARKET_TIMEZONE)

    def _resolve_as_of_date(self, spy_calendar: list[date], now_et: datetime) -> tuple[date | None, str]:
        if not spy_calendar:
            return None, ""
        today = now_et.date()
        calendar_set = set(spy_calendar)
        today_is_trading_day = today in calendar_set
        after_close = now_et.timetz().replace(tzinfo=None) >= MARKET_CLOSE_TIME

        if today_is_trading_day and after_close:
            eligible_dates = [calendar_date for calendar_date in spy_calendar if calendar_date <= today]
            return (max(eligible_dates) if eligible_dates else None, "오늘 장 종료 종가 기준")

        eligible_dates = [calendar_date for calendar_date in spy_calendar if calendar_date < today]
        return (max(eligible_dates) if eligible_dates else None, "직전 거래일 종가 기준")

    def _build_bucket_rows(
        self,
        *,
        selected_rows: list[Any],
        as_of_date: date,
        reference_close_map: dict[tuple[str, date], Decimal | None],
        investable_capital: Decimal,
    ) -> tuple[list[CurrentBucketRow], Decimal]:
        target_weight = Decimal("1") / Decimal(len(selected_rows))
        target_notional = investable_capital * target_weight
        quantized_target_notional = target_notional.quantize(Decimal("0.01"))
        bucket_rows: list[CurrentBucketRow] = []
        actual_total = Decimal("0")

        for row in selected_rows:
            reference_close = reference_close_map.get((row.symbol, as_of_date))
            if reference_close is None or reference_close <= 0:
                raise ValueError(f"{row.symbol} 기준 종가를 사용할 수 없습니다.")
            target_shares = (target_notional / reference_close).to_integral_value(rounding=ROUND_DOWN)
            actual_notional = (reference_close * target_shares).quantize(Decimal("0.01"))
            actual_total += actual_notional
            actual_weight = actual_notional / investable_capital if investable_capital > 0 else Decimal("0")
            bucket_rows.append(
                CurrentBucketRow(
                    symbol=row.symbol,
                    target_weight=_format_percent(target_weight),
                    reference_close=_format_currency(reference_close),
                    target_notional=_format_currency(quantized_target_notional),
                    target_shares=str(int(target_shares)),
                    actual_notional=_format_currency(actual_notional),
                    actual_weight=_format_percent(actual_weight),
                )
            )

        cash_remainder = (investable_capital - actual_total).quantize(Decimal("0.01"))
        return bucket_rows, cash_remainder

    def _dependency_error_context(self, form: CurrentBucketFormInput, readiness: ReadinessStatus) -> CurrentBucketPageContext:
        return self.error_context(
            form=form,
            message=self._dependency_error_message(readiness),
            http_status_code=503 if readiness.code != "database_error" else 500,
            unavailable_reasons=[
                UnavailableReason(
                    code=readiness.code,
                    title="실행 전 확인이 필요합니다",
                    detail=self._dependency_error_message(readiness),
                    facts=[f"점검 대상: {relation}" for relation in readiness.checked_relations[:3]],
                    suggestions=self._dependency_error_suggestions(readiness),
                )
            ],
        )

    def _dependency_error_message(self, readiness: ReadinessStatus) -> str:
        if readiness.code == "database_unreachable":
            return (
                "현재 버킷 데이터베이스에 연결하지 못했습니다. "
                "Docker 경로라면 `docker compose up -d postgres backtest-web`로 서비스를 띄워 주세요. "
                "로컬 `uv run` 경로라면 `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432`를 지정해 compose Postgres에 연결해야 합니다."
            )
        if readiness.code in {"missing_schema", "missing_relation", "unqueryable_relation", "missing_support_symbol_data"}:
            return (
                "데이터베이스 연결은 되었지만 현재 버킷용 mart/stg 또는 지원 심볼 데이터가 아직 준비되지 않았습니다. "
                "Airflow 적재와 dbt 모델 실행이 끝났는지 확인해 주세요."
            )
        return "현재 버킷 쿼리 실행 중 데이터베이스 오류가 발생했습니다. 연결 상태와 서버 로그를 함께 확인해 주세요."

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
                "SPY, VT, IEF, SGOV, JPST, TLT, GLD 지원 심볼의 시장 데이터 백필이 끝났는지 확인해 주세요.",
                "support symbol 적재 후 stg와 int 모델을 다시 실행해 주세요.",
            ]
        return ["데이터베이스 로그와 애플리케이션 로그를 함께 확인해 주세요."]

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

    def _selected_safe_asset_allocations(self, form_values: dict[str, str]) -> list[SafeAssetAllocationDetail]:
        allocations: list[SafeAssetAllocationDetail] = []
        for option in list_safe_asset_options():
            weight_value = form_values.get(option["weight_field"], "0")
            try:
                numeric_weight = Decimal(weight_value)
            except Exception:
                continue
            if numeric_weight <= 0:
                continue
            allocations.append(
                SafeAssetAllocationDetail(
                    id=option["id"],
                    label=option["label"],
                    description=option["description"],
                    details=option["details"],
                    weight_percent=self._format_weight_text(numeric_weight),
                )
            )
        return allocations

    def _selected_safe_asset_summary(self, form_values: dict[str, str]) -> str:
        parts = [
            f"{allocation.label} {allocation.weight_percent}%"
            for allocation in self._selected_safe_asset_allocations(form_values)
        ]
        return " / ".join(parts)

    def _format_weight_text(self, value: Decimal) -> str:
        text = format(value.normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
