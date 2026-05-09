from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from quant_data_platform.web.presets import (
    MarketTimingOverlayId,
    SafeAssetSymbol,
    SAFE_ASSET_WEIGHT_FIELDS,
    StrategyPresetId,
    TransactionCostPreset,
    default_start_date,
)


class PageState(StrEnum):
    EMPTY = "empty"
    LOADING = "loading"
    SUCCESS = "success"
    NO_DATA = "no_data"
    INSUFFICIENT_HISTORY = "insufficient_history"
    ERROR = "error"


def _normalize_legacy_safe_asset_symbol(value: object) -> object:
    if not isinstance(value, dict):
        return value
    if any(field_name in value for field_name in SAFE_ASSET_WEIGHT_FIELDS.values()):
        return value
    legacy_symbol = value.get("safe_asset_symbol")
    if legacy_symbol is None:
        return value
    try:
        symbol = SafeAssetSymbol(str(legacy_symbol).strip().upper())
    except ValueError as exc:
        raise ValueError("safe_asset_symbol 값이 유효하지 않습니다.") from exc
    normalized = dict(value)
    for asset_symbol, field_name in SAFE_ASSET_WEIGHT_FIELDS.items():
        normalized[field_name] = "100" if asset_symbol == symbol else "0"
    return normalized


def _validate_safe_asset_weight_value(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("안전자산 비중은 0% 이상이어야 합니다.")
    if value > 100:
        raise ValueError("안전자산 비중은 100%를 초과할 수 없습니다.")
    return value


def _safe_asset_weight_map_from_fields(
    *,
    sgov: Decimal,
    jpst: Decimal,
    ief: Decimal,
    tlt: Decimal,
    gld: Decimal,
    xle: Decimal,
    shy: Decimal,
) -> dict[SafeAssetSymbol, Decimal]:
    return {
        SafeAssetSymbol.SGOV: sgov,
        SafeAssetSymbol.JPST: jpst,
        SafeAssetSymbol.IEF: ief,
        SafeAssetSymbol.TLT: tlt,
        SafeAssetSymbol.GLD: gld,
        SafeAssetSymbol.XLE: xle,
        SafeAssetSymbol.SHY: shy,
    }


def _safe_asset_allocations_from_map(weight_map: dict[SafeAssetSymbol, Decimal]) -> list[tuple[SafeAssetSymbol, Decimal]]:
    return [
        (symbol, weight)
        for symbol, weight in weight_map.items()
        if weight > 0
    ]


def _safe_asset_summary_from_allocations(allocations: list[tuple[SafeAssetSymbol, Decimal]]) -> str:
    return " / ".join(
        f"{symbol.value} {_format_weight_percent(weight)}%"
        for symbol, weight in allocations
    )


class BacktestFormInput(BaseModel):
    strategy_preset: StrategyPresetId = StrategyPresetId.VALUE_QUALITY
    market_timing_overlay: MarketTimingOverlayId = MarketTimingOverlayId.NONE
    safe_asset_weight_sgov: Decimal = Decimal("100")
    safe_asset_weight_jpst: Decimal = Decimal("0")
    safe_asset_weight_ief: Decimal = Decimal("0")
    safe_asset_weight_tlt: Decimal = Decimal("0")
    safe_asset_weight_gld: Decimal = Decimal("0")
    safe_asset_weight_xle: Decimal = Decimal("0")
    safe_asset_weight_shy: Decimal = Decimal("0")
    start_date: date = Field(default_factory=default_start_date)
    end_date: date = Field(default_factory=date.today)
    initial_capital: Decimal = Decimal("100000")
    top_n: int = 10
    transaction_cost_preset: TransactionCostPreset = TransactionCostPreset.CONSERVATIVE

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_safe_asset_symbol(cls, value: object) -> object:
        return _normalize_legacy_safe_asset_symbol(value)

    @field_validator("initial_capital")
    @classmethod
    def validate_initial_capital(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("초기 자본은 0보다 커야 합니다.")
        return value

    @field_validator(*SAFE_ASSET_WEIGHT_FIELDS.values())
    @classmethod
    def validate_safe_asset_weight(cls, value: Decimal) -> Decimal:
        return _validate_safe_asset_weight_value(value)

    @field_validator("top_n")
    @classmethod
    def validate_top_n(cls, value: int) -> int:
        if value not in {10, 20, 30}:
            raise ValueError("보유 종목 수는 10, 20, 30 중 하나여야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestFormInput":
        total_weight = sum(self.safe_asset_weight_map().values(), start=Decimal("0"))
        if total_weight != Decimal("100"):
            raise ValueError("안전자산 비중 합계는 정확히 100%여야 합니다.")
        if self.start_date >= self.end_date:
            raise ValueError("종료일은 시작일보다 뒤여야 합니다.")
        if (self.end_date - self.start_date).days > 365 * 15:
            raise ValueError("v1에서는 15년을 초과하는 기간을 지원하지 않습니다.")
        return self

    def safe_asset_weight_map(self) -> dict[SafeAssetSymbol, Decimal]:
        return _safe_asset_weight_map_from_fields(
            sgov=self.safe_asset_weight_sgov,
            jpst=self.safe_asset_weight_jpst,
            ief=self.safe_asset_weight_ief,
            tlt=self.safe_asset_weight_tlt,
            gld=self.safe_asset_weight_gld,
            xle=self.safe_asset_weight_xle,
            shy=self.safe_asset_weight_shy,
        )

    def safe_asset_allocations(self) -> list[tuple[SafeAssetSymbol, Decimal]]:
        return _safe_asset_allocations_from_map(self.safe_asset_weight_map())

    def safe_asset_summary(self) -> str:
        return _safe_asset_summary_from_allocations(self.safe_asset_allocations())


class CurrentBucketFormInput(BaseModel):
    strategy_preset: StrategyPresetId = StrategyPresetId.VALUE_QUALITY
    market_timing_overlay: MarketTimingOverlayId = MarketTimingOverlayId.NONE
    safe_asset_weight_sgov: Decimal = Decimal("100")
    safe_asset_weight_jpst: Decimal = Decimal("0")
    safe_asset_weight_ief: Decimal = Decimal("0")
    safe_asset_weight_tlt: Decimal = Decimal("0")
    safe_asset_weight_gld: Decimal = Decimal("0")
    safe_asset_weight_xle: Decimal = Decimal("0")
    safe_asset_weight_shy: Decimal = Decimal("0")
    investable_capital: Decimal = Decimal("100000")
    top_n: int = 10

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_safe_asset_symbol(cls, value: object) -> object:
        return _normalize_legacy_safe_asset_symbol(value)

    @field_validator("investable_capital")
    @classmethod
    def validate_investable_capital(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("투자 가능 자본은 0보다 커야 합니다.")
        return value

    @field_validator(*SAFE_ASSET_WEIGHT_FIELDS.values())
    @classmethod
    def validate_safe_asset_weight(cls, value: Decimal) -> Decimal:
        return _validate_safe_asset_weight_value(value)

    @field_validator("top_n")
    @classmethod
    def validate_top_n(cls, value: int) -> int:
        if value not in {10, 20, 30}:
            raise ValueError("보유 종목 수는 10, 20, 30 중 하나여야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_safe_asset_total(self) -> "CurrentBucketFormInput":
        total_weight = sum(self.safe_asset_weight_map().values(), start=Decimal("0"))
        if total_weight != Decimal("100"):
            raise ValueError("안전자산 비중 합계는 정확히 100%여야 합니다.")
        return self

    def safe_asset_weight_map(self) -> dict[SafeAssetSymbol, Decimal]:
        return _safe_asset_weight_map_from_fields(
            sgov=self.safe_asset_weight_sgov,
            jpst=self.safe_asset_weight_jpst,
            ief=self.safe_asset_weight_ief,
            tlt=self.safe_asset_weight_tlt,
            gld=self.safe_asset_weight_gld,
            xle=self.safe_asset_weight_xle,
            shy=self.safe_asset_weight_shy,
        )

    def safe_asset_allocations(self) -> list[tuple[SafeAssetSymbol, Decimal]]:
        return _safe_asset_allocations_from_map(self.safe_asset_weight_map())

    def safe_asset_summary(self) -> str:
        return _safe_asset_summary_from_allocations(self.safe_asset_allocations())


class SummaryMetric(BaseModel):
    key: str
    label: str
    value: str
    tooltip: str | None = None


class WarningMessage(BaseModel):
    title: str
    body: str
    tone: str = "warning"


class TradeLogSummaryRow(BaseModel):
    signal_date: str
    execution_date: str
    selected_count: int
    sold_count: int
    buy_notional: str
    sell_notional: str
    fees: str
    turnover: str
    notes: str | None = None


class TradeLogDetailRow(BaseModel):
    execution_date: str
    signal_date: str
    symbol: str
    action: str
    shares: str
    execution_price: str
    fees: str
    net_cash_flow: str
    realized_pnl: str | None = None
    holding_days: str | None = None


class EquityCurvePoint(BaseModel):
    date: str
    gross_equity: float
    net_equity: float
    benchmark_equity: float | None = None


class CurrentBucketRow(BaseModel):
    symbol: str
    target_weight: str
    reference_close: str
    target_notional: str
    target_shares: str
    actual_notional: str
    actual_weight: str


class PresetDetail(BaseModel):
    id: str
    label: str
    description: str
    lookback_label: str
    rationale: str
    higher_is_better: list[str] = Field(default_factory=list)
    lower_is_better: list[str] = Field(default_factory=list)
    execution_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class OverlayDetail(BaseModel):
    id: str
    label: str
    description: str
    lookback_label: str
    rationale: str
    signal_asset: str
    comparison_asset: str | None = None
    execution_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class SafeAssetDetail(BaseModel):
    id: str
    label: str
    description: str
    details: str


class SafeAssetAllocationDetail(SafeAssetDetail):
    weight_percent: str


class CostDetail(BaseModel):
    id: str
    label: str
    description: str
    round_trip_bps: int
    details: str


class UnavailableReason(BaseModel):
    code: str
    title: str
    detail: str
    facts: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class BacktestPageContext(BaseModel):
    state: PageState
    form_values: dict[str, Any]
    preset_options: list[dict[str, Any]]
    overlay_options: list[dict[str, Any]]
    safe_asset_options: list[dict[str, Any]]
    transaction_cost_options: list[dict[str, Any]]
    selected_preset_detail: PresetDetail | None = None
    selected_overlay_detail: OverlayDetail | None = None
    selected_safe_asset_allocations: list[SafeAssetAllocationDetail] = Field(default_factory=list)
    selected_safe_asset_summary: str = ""
    selected_cost_detail: CostDetail | None = None
    summary_metrics: list[SummaryMetric] = Field(default_factory=list)
    equity_curve: list[EquityCurvePoint] = Field(default_factory=list)
    trade_log_summary: list[TradeLogSummaryRow] = Field(default_factory=list)
    trade_log_rows: list[TradeLogDetailRow] = Field(default_factory=list)
    warnings: list[WarningMessage] = Field(default_factory=list)
    data_quality_flags: list[str] = Field(default_factory=list)
    unavailable_reasons: list[UnavailableReason] = Field(default_factory=list)
    error_message: str | None = None
    field_errors: dict[str, str] = Field(default_factory=dict)
    benchmark_available: bool = False
    equity_curve_svg: str | None = None
    save_success_message: str | None = None
    save_error_message: str | None = None
    save_directory: str | None = None
    page_title: str = "프리셋 백테스트"
    helper_copy: str = "팩터 전략에 마켓타이밍 오버레이를 결합해 월말 리밸런스와 일일 risk-off 방어를 함께 점검할 수 있습니다."
    http_status_code: int = 200


class CurrentBucketPageContext(BaseModel):
    state: PageState
    form_values: dict[str, Any]
    preset_options: list[dict[str, Any]]
    overlay_options: list[dict[str, Any]]
    safe_asset_options: list[dict[str, Any]]
    selected_preset_detail: PresetDetail | None = None
    selected_overlay_detail: OverlayDetail | None = None
    selected_safe_asset_allocations: list[SafeAssetAllocationDetail] = Field(default_factory=list)
    selected_safe_asset_summary: str = ""
    safe_asset_summary: str = ""
    stock_bucket_rows: list[CurrentBucketRow] = Field(default_factory=list)
    warnings: list[WarningMessage] = Field(default_factory=list)
    data_quality_flags: list[str] = Field(default_factory=list)
    unavailable_reasons: list[UnavailableReason] = Field(default_factory=list)
    error_message: str | None = None
    field_errors: dict[str, str] = Field(default_factory=dict)
    save_success_message: str | None = None
    save_error_message: str | None = None
    as_of_date: str | None = None
    price_basis_label: str = ""
    signal_date: str | None = None
    active_risk_state: str | None = None
    cash_remainder: str | None = None
    risk_off_notice: str | None = None
    page_title: str = "현재 버킷"
    helper_copy: str = "현재 시점 기준 종가로 최신 월말 신호를 읽어 paper trading 또는 실제 투자용 후보 버킷을 바로 확인할 수 있습니다."
    http_status_code: int = 200


def form_values_from_model(form: BacktestFormInput) -> dict[str, str]:
    return {
        "strategy_preset": form.strategy_preset.value,
        "market_timing_overlay": form.market_timing_overlay.value,
        "safe_asset_weight_sgov": _format_weight_percent(form.safe_asset_weight_sgov),
        "safe_asset_weight_jpst": _format_weight_percent(form.safe_asset_weight_jpst),
        "safe_asset_weight_ief": _format_weight_percent(form.safe_asset_weight_ief),
        "safe_asset_weight_tlt": _format_weight_percent(form.safe_asset_weight_tlt),
        "safe_asset_weight_gld": _format_weight_percent(form.safe_asset_weight_gld),
        "safe_asset_weight_xle": _format_weight_percent(form.safe_asset_weight_xle),
        "safe_asset_weight_shy": _format_weight_percent(form.safe_asset_weight_shy),
        "start_date": form.start_date.isoformat(),
        "end_date": form.end_date.isoformat(),
        "initial_capital": str(form.initial_capital),
        "top_n": str(form.top_n),
        "transaction_cost_preset": form.transaction_cost_preset.value,
    }


def current_bucket_form_values_from_model(form: CurrentBucketFormInput) -> dict[str, str]:
    return {
        "strategy_preset": form.strategy_preset.value,
        "market_timing_overlay": form.market_timing_overlay.value,
        "safe_asset_weight_sgov": _format_weight_percent(form.safe_asset_weight_sgov),
        "safe_asset_weight_jpst": _format_weight_percent(form.safe_asset_weight_jpst),
        "safe_asset_weight_ief": _format_weight_percent(form.safe_asset_weight_ief),
        "safe_asset_weight_tlt": _format_weight_percent(form.safe_asset_weight_tlt),
        "safe_asset_weight_gld": _format_weight_percent(form.safe_asset_weight_gld),
        "safe_asset_weight_xle": _format_weight_percent(form.safe_asset_weight_xle),
        "safe_asset_weight_shy": _format_weight_percent(form.safe_asset_weight_shy),
        "investable_capital": str(form.investable_capital),
        "top_n": str(form.top_n),
    }


def form_values_from_raw(data: dict[str, Any]) -> dict[str, str]:
    form_values = {
        "strategy_preset": str(data.get("strategy_preset", StrategyPresetId.VALUE_QUALITY.value)),
        "market_timing_overlay": str(data.get("market_timing_overlay", MarketTimingOverlayId.NONE.value)),
        "safe_asset_weight_sgov": str(data.get("safe_asset_weight_sgov", "100")),
        "safe_asset_weight_jpst": str(data.get("safe_asset_weight_jpst", "0")),
        "safe_asset_weight_ief": str(data.get("safe_asset_weight_ief", "0")),
        "safe_asset_weight_tlt": str(data.get("safe_asset_weight_tlt", "0")),
        "safe_asset_weight_gld": str(data.get("safe_asset_weight_gld", "0")),
        "safe_asset_weight_xle": str(data.get("safe_asset_weight_xle", "0")),
        "safe_asset_weight_shy": str(data.get("safe_asset_weight_shy", "0")),
        "start_date": str(data.get("start_date", default_start_date().isoformat())),
        "end_date": str(data.get("end_date", date.today().isoformat())),
        "initial_capital": str(data.get("initial_capital", "100000")),
        "top_n": str(data.get("top_n", "10")),
        "transaction_cost_preset": str(data.get("transaction_cost_preset", TransactionCostPreset.CONSERVATIVE.value)),
    }
    if not any(field_name in data for field_name in SAFE_ASSET_WEIGHT_FIELDS.values()) and "safe_asset_symbol" in data:
        try:
            legacy_symbol = SafeAssetSymbol(str(data["safe_asset_symbol"]).strip().upper())
        except ValueError:
            return form_values
        for asset_symbol, field_name in SAFE_ASSET_WEIGHT_FIELDS.items():
            form_values[field_name] = "100" if asset_symbol == legacy_symbol else "0"
    return form_values


def current_bucket_form_values_from_raw(data: dict[str, Any]) -> dict[str, str]:
    form_values = {
        "strategy_preset": str(data.get("strategy_preset", StrategyPresetId.VALUE_QUALITY.value)),
        "market_timing_overlay": str(data.get("market_timing_overlay", MarketTimingOverlayId.NONE.value)),
        "safe_asset_weight_sgov": str(data.get("safe_asset_weight_sgov", "100")),
        "safe_asset_weight_jpst": str(data.get("safe_asset_weight_jpst", "0")),
        "safe_asset_weight_ief": str(data.get("safe_asset_weight_ief", "0")),
        "safe_asset_weight_tlt": str(data.get("safe_asset_weight_tlt", "0")),
        "safe_asset_weight_gld": str(data.get("safe_asset_weight_gld", "0")),
        "safe_asset_weight_xle": str(data.get("safe_asset_weight_xle", "0")),
        "safe_asset_weight_shy": str(data.get("safe_asset_weight_shy", "0")),
        "investable_capital": str(data.get("investable_capital", "100000")),
        "top_n": str(data.get("top_n", "10")),
    }
    if not any(field_name in data for field_name in SAFE_ASSET_WEIGHT_FIELDS.values()) and "safe_asset_symbol" in data:
        try:
            legacy_symbol = SafeAssetSymbol(str(data["safe_asset_symbol"]).strip().upper())
        except ValueError:
            return form_values
        for asset_symbol, field_name in SAFE_ASSET_WEIGHT_FIELDS.items():
            form_values[field_name] = "100" if asset_symbol == legacy_symbol else "0"
    return form_values


def field_errors_from_validation_error(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", ())
        message = error.get("msg", "입력값을 확인해 주세요.")
        if location:
            key = location[0]
        else:
            key = "safe_asset_allocation" if "안전자산" in message else "__root__"
        if key not in errors:
            errors[str(key)] = message
    return errors


def _format_weight_percent(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
