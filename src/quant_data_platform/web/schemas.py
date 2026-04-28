from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from quant_data_platform.web.presets import StrategyPresetId, TransactionCostPreset, default_start_date


class PageState(StrEnum):
    EMPTY = "empty"
    LOADING = "loading"
    SUCCESS = "success"
    NO_DATA = "no_data"
    INSUFFICIENT_HISTORY = "insufficient_history"
    ERROR = "error"


class BacktestFormInput(BaseModel):
    strategy_preset: StrategyPresetId = StrategyPresetId.VALUE_QUALITY
    start_date: date = Field(default_factory=default_start_date)
    end_date: date = Field(default_factory=date.today)
    initial_capital: Decimal = Decimal("100000")
    top_n: int = 10
    transaction_cost_preset: TransactionCostPreset = TransactionCostPreset.CONSERVATIVE

    @field_validator("initial_capital")
    @classmethod
    def validate_initial_capital(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("초기 자본은 0보다 커야 합니다.")
        return value

    @field_validator("top_n")
    @classmethod
    def validate_top_n(cls, value: int) -> int:
        if value not in {10, 20, 30}:
            raise ValueError("보유 종목 수는 10, 20, 30 중 하나여야 합니다.")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "BacktestFormInput":
        if self.start_date >= self.end_date:
            raise ValueError("종료일은 시작일보다 뒤여야 합니다.")
        if (self.end_date - self.start_date).days > 365 * 15:
            raise ValueError("v1에서는 15년을 초과하는 기간을 지원하지 않습니다.")
        return self


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
    transaction_cost_options: list[dict[str, Any]]
    selected_preset_detail: PresetDetail | None = None
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
    page_title: str = "프리셋 백테스트"
    helper_copy: str = "월말 신호를 보고 다음 거래일에 체결하는 초보자용 프리셋 백테스트입니다."
    http_status_code: int = 200


def form_values_from_model(form: BacktestFormInput) -> dict[str, str]:
    return {
        "strategy_preset": form.strategy_preset.value,
        "start_date": form.start_date.isoformat(),
        "end_date": form.end_date.isoformat(),
        "initial_capital": str(form.initial_capital),
        "top_n": str(form.top_n),
        "transaction_cost_preset": form.transaction_cost_preset.value,
    }


def form_values_from_raw(data: dict[str, Any]) -> dict[str, str]:
    return {
        "strategy_preset": str(data.get("strategy_preset", StrategyPresetId.VALUE_QUALITY.value)),
        "start_date": str(data.get("start_date", default_start_date().isoformat())),
        "end_date": str(data.get("end_date", date.today().isoformat())),
        "initial_capital": str(data.get("initial_capital", "100000")),
        "top_n": str(data.get("top_n", "10")),
        "transaction_cost_preset": str(data.get("transaction_cost_preset", TransactionCostPreset.CONSERVATIVE.value)),
    }


def field_errors_from_validation_error(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", ())
        key = location[0] if location else "__root__"
        if key not in errors:
            errors[str(key)] = error.get("msg", "입력값을 확인해 주세요.")
    return errors
