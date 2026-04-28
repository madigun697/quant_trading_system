from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class StrategyPresetId(StrEnum):
    VALUE_QUALITY = "value_quality"
    VALUE_MOMENTUM = "value_momentum"
    QUALITY_LOWVOL = "quality_lowvol"


class TransactionCostPreset(StrEnum):
    LOW = "low"
    BASE = "base"
    CONSERVATIVE = "conservative"


@dataclass(frozen=True)
class FactorSpec:
    column: str
    higher_is_better: bool


@dataclass(frozen=True)
class StrategyPreset:
    preset_id: StrategyPresetId
    label: str
    description: str
    mart_table: str
    factor_specs: tuple[FactorSpec, ...]
    lookback_days: int
    lookback_label: str


TRANSACTION_COST_BPS: dict[TransactionCostPreset, float] = {
    TransactionCostPreset.LOW: 0.0010,
    TransactionCostPreset.BASE: 0.0025,
    TransactionCostPreset.CONSERVATIVE: 0.0050,
}


STRATEGY_PRESETS: dict[StrategyPresetId, StrategyPreset] = {
    StrategyPresetId.VALUE_QUALITY: StrategyPreset(
        preset_id=StrategyPresetId.VALUE_QUALITY,
        label="Value + Quality",
        description="저평가 + 수익성 품질을 함께 보는 전통적인 팩터 조합",
        mart_table="mart_value_quality_inputs",
        factor_specs=(
            FactorSpec("pe_ratio", higher_is_better=False),
            FactorSpec("pb_ratio", higher_is_better=False),
            FactorSpec("ev_to_ebitda", higher_is_better=False),
            FactorSpec("accruals", higher_is_better=False),
            FactorSpec("debt_to_equity", higher_is_better=False),
            FactorSpec("fcf_yield", higher_is_better=True),
            FactorSpec("sales_yield", higher_is_better=True),
            FactorSpec("roe", higher_is_better=True),
            FactorSpec("roic_proxy", higher_is_better=True),
            FactorSpec("gross_margin", higher_is_better=True),
            FactorSpec("operating_margin", higher_is_better=True),
            FactorSpec("interest_coverage", higher_is_better=True),
        ),
        lookback_days=0,
        lookback_label="추가 과거 구간 요구 없음",
    ),
    StrategyPresetId.VALUE_MOMENTUM: StrategyPreset(
        preset_id=StrategyPresetId.VALUE_MOMENTUM,
        label="Value + Momentum",
        description="저평가 종목 중 최근 추세가 강한 종목을 우선하는 조합",
        mart_table="mart_value_momentum_inputs",
        factor_specs=(
            FactorSpec("pe_ratio", higher_is_better=False),
            FactorSpec("pb_ratio", higher_is_better=False),
            FactorSpec("ev_to_ebitda", higher_is_better=False),
            FactorSpec("fcf_yield", higher_is_better=True),
            FactorSpec("sales_yield", higher_is_better=True),
            FactorSpec("momentum_12_1", higher_is_better=True),
            FactorSpec("momentum_6m", higher_is_better=True),
            FactorSpec("momentum_3m", higher_is_better=True),
        ),
        lookback_days=400,
        lookback_label="최소 13개월 수준의 과거 가격 필요",
    ),
    StrategyPresetId.QUALITY_LOWVOL: StrategyPreset(
        preset_id=StrategyPresetId.QUALITY_LOWVOL,
        label="Quality + Low Volatility",
        description="재무 품질이 좋은 종목 중 변동성이 낮은 종목을 우선하는 조합",
        mart_table="mart_quality_lowvol_inputs",
        factor_specs=(
            FactorSpec("roe", higher_is_better=True),
            FactorSpec("gross_margin", higher_is_better=True),
            FactorSpec("operating_margin", higher_is_better=True),
            FactorSpec("debt_to_equity", higher_is_better=False),
            FactorSpec("rolling_vol_63d", higher_is_better=False),
            FactorSpec("rolling_vol_126d", higher_is_better=False),
            FactorSpec("rolling_vol_252d", higher_is_better=False),
        ),
        lookback_days=370,
        lookback_label="최소 252거래일 수준의 과거 가격 필요",
    ),
}


def get_strategy_preset(preset_id: StrategyPresetId) -> StrategyPreset:
    return STRATEGY_PRESETS[preset_id]


def list_preset_options() -> list[dict[str, str]]:
    return [
        {
            "id": preset.preset_id.value,
            "label": preset.label,
            "description": preset.description,
            "lookback_label": preset.lookback_label,
        }
        for preset in STRATEGY_PRESETS.values()
    ]


def list_cost_options() -> list[dict[str, str]]:
    return [
        {
            "id": preset.value,
            "label": preset.name.title(),
            "description": {
                TransactionCostPreset.LOW: "왕복 총비용 10bp",
                TransactionCostPreset.BASE: "왕복 총비용 25bp",
                TransactionCostPreset.CONSERVATIVE: "왕복 총비용 50bp",
            }[preset],
        }
        for preset in TransactionCostPreset
    ]


def default_start_date(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=365 * 5)

