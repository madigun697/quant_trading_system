from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any


class StrategyPresetId(StrEnum):
    VALUE_QUALITY = "value_quality"
    VALUE_MOMENTUM = "value_momentum"
    QUALITY_LOWVOL = "quality_lowvol"


class MarketTimingOverlayId(StrEnum):
    NONE = "none"
    EMERGENCY_BRAKE_ASYMMETRIC = "emergency_brake_asymmetric"
    CANARY_ASSET_SIGNAL = "canary_asset_signal"
    GRADUATED_POSITION_SIZING = "graduated_position_sizing"


class SafeAssetSymbol(StrEnum):
    SGOV = "SGOV"
    JPST = "JPST"
    IEF = "IEF"
    TLT = "TLT"
    GLD = "GLD"
    XLE = "XLE"
    SHY = "SHY"


class TransactionCostPreset(StrEnum):
    LOW = "low"
    BASE = "base"
    CONSERVATIVE = "conservative"


@dataclass(frozen=True)
class FactorSpec:
    column: str
    label: str
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
    rationale: str
    execution_notes: tuple[str, ...]
    risk_notes: tuple[str, ...]


@dataclass(frozen=True)
class MarketTimingOverlay:
    overlay_id: MarketTimingOverlayId
    label: str
    description: str
    lookback_days: int
    lookback_label: str
    rationale: str
    signal_asset: str
    comparison_asset: str | None
    execution_notes: tuple[str, ...]
    risk_notes: tuple[str, ...]


@dataclass(frozen=True)
class SafeAssetOption:
    symbol: SafeAssetSymbol
    label: str
    description: str
    details: str


@dataclass(frozen=True)
class TransactionCostOption:
    preset: TransactionCostPreset
    label: str
    description: str
    round_trip_bps: int
    details: str


TRANSACTION_COST_OPTIONS: dict[TransactionCostPreset, TransactionCostOption] = {
    TransactionCostPreset.LOW: TransactionCostOption(
        preset=TransactionCostPreset.LOW,
        label="Low",
        description="왕복 총비용 10bp",
        round_trip_bps=10,
        details="유동성이 충분한 대형주를 비교적 낙관적으로 가정한 비용입니다.",
    ),
    TransactionCostPreset.BASE: TransactionCostOption(
        preset=TransactionCostPreset.BASE,
        label="Base",
        description="왕복 총비용 25bp",
        round_trip_bps=25,
        details="일반적인 주식 리밸런싱 비용을 무난하게 반영한 기본값입니다.",
    ),
    TransactionCostPreset.CONSERVATIVE: TransactionCostOption(
        preset=TransactionCostPreset.CONSERVATIVE,
        label="Conservative",
        description="왕복 총비용 50bp",
        round_trip_bps=50,
        details="슬리피지와 체결 불리함까지 넉넉히 잡는 보수적 가정입니다.",
    ),
}


TRANSACTION_COST_BPS: dict[TransactionCostPreset, float] = {
    preset: option.round_trip_bps / 20_000
    for preset, option in TRANSACTION_COST_OPTIONS.items()
}


STRATEGY_PRESETS: dict[StrategyPresetId, StrategyPreset] = {
    StrategyPresetId.VALUE_QUALITY: StrategyPreset(
        preset_id=StrategyPresetId.VALUE_QUALITY,
        label="Value + Quality",
        description="저평가 지표와 재무 품질을 함께 보는 전통적인 팩터 조합입니다.",
        mart_table="mart_value_quality_inputs",
        factor_specs=(
            FactorSpec("pe_ratio", "PER", higher_is_better=False),
            FactorSpec("pb_ratio", "PBR", higher_is_better=False),
            FactorSpec("ev_to_ebitda", "EV/EBITDA", higher_is_better=False),
            FactorSpec("accruals", "발생액 비율", higher_is_better=False),
            FactorSpec("debt_to_equity", "부채비율", higher_is_better=False),
            FactorSpec("fcf_yield", "FCF Yield", higher_is_better=True),
            FactorSpec("sales_yield", "Sales Yield", higher_is_better=True),
            FactorSpec("roe", "ROE", higher_is_better=True),
            FactorSpec("roic_proxy", "ROIC Proxy", higher_is_better=True),
            FactorSpec("gross_margin", "매출총이익률", higher_is_better=True),
            FactorSpec("operating_margin", "영업이익률", higher_is_better=True),
            FactorSpec("interest_coverage", "이자보상배율", higher_is_better=True),
        ),
        lookback_days=0,
        lookback_label="추가 가격 룩백 없이도 계산 가능한 프리셋입니다.",
        rationale="싼 종목 중에서도 이익 체력이 좋은 회사를 우선해 가치 함정을 줄이려는 전략입니다.",
        execution_notes=(
            "월말 신호를 보고 다음 SPY 거래일 시가에 체결합니다.",
            "선정된 상위 종목을 동일비중으로 맞추되, 겹치는 종목은 필요한 만큼만 조정합니다.",
            "계속 선정된 종목은 유지하고 부족분만 추가 매수하거나 일부만 매도합니다.",
        ),
        risk_notes=(
            "재무지표 공시 시차와 원천 데이터 품질에 민감합니다.",
            "가치주가 장기간 소외되는 구간에서는 벤치마크 대비 부진할 수 있습니다.",
        ),
    ),
    StrategyPresetId.VALUE_MOMENTUM: StrategyPreset(
        preset_id=StrategyPresetId.VALUE_MOMENTUM,
        label="Value + Momentum",
        description="저평가 종목 중 최근 추세가 강한 종목을 우선하는 조합입니다.",
        mart_table="mart_value_momentum_inputs",
        factor_specs=(
            FactorSpec("pe_ratio", "PER", higher_is_better=False),
            FactorSpec("pb_ratio", "PBR", higher_is_better=False),
            FactorSpec("ev_to_ebitda", "EV/EBITDA", higher_is_better=False),
            FactorSpec("fcf_yield", "FCF Yield", higher_is_better=True),
            FactorSpec("sales_yield", "Sales Yield", higher_is_better=True),
            FactorSpec("momentum_12_1", "12-1개월 모멘텀", higher_is_better=True),
            FactorSpec("momentum_6m", "6개월 모멘텀", higher_is_better=True),
            FactorSpec("momentum_3m", "3개월 모멘텀", higher_is_better=True),
        ),
        lookback_days=400,
        lookback_label="최소 13개월 수준의 과거 가격 이력이 필요합니다.",
        rationale="싼 종목 중에서도 이미 수급과 추세가 붙은 후보를 우선해 반등보다 지속성을 노리는 전략입니다.",
        execution_notes=(
            "월말 신호를 보고 다음 SPY 거래일 시가에 체결합니다.",
            "모멘텀 팩터 계산을 위해 충분한 가격 이력이 없는 종목은 자동 제외됩니다.",
            "리밸런스는 목표 동일비중과 현재 보유 비중의 차이만큼만 거래합니다.",
        ),
        risk_notes=(
            "추세 반전이 빠른 구간에서는 교체 비용이 커질 수 있습니다.",
            "룩백 구간이 부족한 초기 기간은 실행 불가 월이 늘어날 수 있습니다.",
        ),
    ),
    StrategyPresetId.QUALITY_LOWVOL: StrategyPreset(
        preset_id=StrategyPresetId.QUALITY_LOWVOL,
        label="Quality + Low Volatility",
        description="재무 품질이 좋은 종목 중 변동성이 낮은 종목을 우선하는 조합입니다.",
        mart_table="mart_quality_lowvol_inputs",
        factor_specs=(
            FactorSpec("roe", "ROE", higher_is_better=True),
            FactorSpec("gross_margin", "매출총이익률", higher_is_better=True),
            FactorSpec("operating_margin", "영업이익률", higher_is_better=True),
            FactorSpec("debt_to_equity", "부채비율", higher_is_better=False),
            FactorSpec("rolling_vol_63d", "63일 변동성", higher_is_better=False),
            FactorSpec("rolling_vol_126d", "126일 변동성", higher_is_better=False),
            FactorSpec("rolling_vol_252d", "252일 변동성", higher_is_better=False),
        ),
        lookback_days=370,
        lookback_label="최소 252거래일 수준의 과거 가격 이력이 필요합니다.",
        rationale="좋은 재무체력을 가진 종목 중에서도 흔들림이 적은 후보를 골라 방어적인 성향을 노리는 전략입니다.",
        execution_notes=(
            "월말 신호를 보고 다음 SPY 거래일 시가에 체결합니다.",
            "변동성 계산을 위해 약 1년치 가격 이력이 부족하면 해당 월 후보에서 제외됩니다.",
            "리밸런스는 목표 동일비중에 맞추기 위한 차이만큼만 거래합니다.",
        ),
        risk_notes=(
            "방어적 성향 때문에 강한 상승장에서는 공격적 전략보다 느릴 수 있습니다.",
            "변동성 계산 구간이 길어 초기 구간 실행 가능 월이 제한될 수 있습니다.",
        ),
    ),
}


MARKET_TIMING_OVERLAYS: dict[MarketTimingOverlayId, MarketTimingOverlay] = {
    MarketTimingOverlayId.NONE: MarketTimingOverlay(
        overlay_id=MarketTimingOverlayId.NONE,
        label="None",
        description="기존 팩터 전략을 그대로 운용하고 별도 마켓타이밍 필터는 사용하지 않습니다.",
        lookback_days=0,
        lookback_label="추가 신호 데이터가 필요하지 않습니다.",
        rationale="가장 단순한 기준선입니다. 팩터 전략 자체의 월말 리밸런싱 성과를 그대로 비교할 때 사용합니다.",
        signal_asset="SPY",
        comparison_asset=None,
        execution_notes=(
            "월말 신호 기준으로만 팩터 포트폴리오를 리밸런싱합니다.",
        ),
        risk_notes=(
            "하락장에서도 팩터 포트폴리오를 계속 보유합니다.",
        ),
    ),
    MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC: MarketTimingOverlay(
        overlay_id=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC,
        label="Emergency Brake",
        description="하락 신호는 매일 빠르게 보고 피하고, 재진입은 월말에 더 엄격하게 확인하는 비대칭 오버레이입니다.",
        lookback_days=400,
        lookback_label="SPY 50일선, 200일선, 20거래일 수익률 계산을 위해 약 1년 이상 가격 이력이 필요합니다.",
        rationale="시장 급락 초기에 빠르게 브레이크를 밟고, 반등이 확인될 때만 다시 팩터 포트폴리오에 들어가 whipsaw를 줄이려는 오버레이입니다.",
        signal_asset="SPY",
        comparison_asset=None,
        execution_notes=(
            "매일 종가 기준으로 SPY가 50일선 아래에 3거래일 연속 머물면 다음 거래일에 안전자산으로 이동합니다.",
            "월말에는 SPY가 200일선 위이고 최근 20거래일 수익률이 양수일 때만 팩터 포트폴리오로 재진입합니다.",
            "월중에 risk-on이 다시 켜져도 월말 전에는 재진입하지 않습니다.",
        ),
        risk_notes=(
            "급반등 구간에서는 재진입이 늦어질 수 있습니다.",
            "SPY 가격 데이터 품질과 휴장일 캘린더에 민감합니다.",
        ),
    ),
    MarketTimingOverlayId.CANARY_ASSET_SIGNAL: MarketTimingOverlay(
        overlay_id=MarketTimingOverlayId.CANARY_ASSET_SIGNAL,
        label="Canary Asset Signal",
        description="글로벌 위험자산 VT와 방어 신호자산 IEF의 상대 모멘텀으로 risk-on / risk-off를 가르는 오버레이입니다.",
        lookback_days=180,
        lookback_label="VT와 IEF의 약 84거래일 수익률을 계산하기 위해 최소 6개월 정도의 가격 이력이 필요합니다.",
        rationale="개별 종목 노이즈보다 자산군 간 위험 선호 흐름을 따라가면서 팩터 포트폴리오의 큰 손실 구간을 피하려는 오버레이입니다.",
        signal_asset="VT",
        comparison_asset="IEF",
        execution_notes=(
            "VT 84거래일 수익률이 IEF 84거래일 수익률보다 높으면 risk-on, 아니면 risk-off입니다.",
            "risk-off가 감지되면 익일 시가에 선택한 안전자산으로 이동합니다.",
            "월말에만 다시 신호를 확인해 팩터 포트폴리오 재진입 여부를 결정합니다.",
        ),
        risk_notes=(
            "IEF는 신호 비교 자산일 뿐 실제 파킹 자산은 아닙니다.",
            "VT나 IEF의 긴 가격 이력이 부족한 초기 기간에는 실행이 제한될 수 있습니다.",
        ),
    ),
    MarketTimingOverlayId.GRADUATED_POSITION_SIZING: MarketTimingOverlay(
        overlay_id=MarketTimingOverlayId.GRADUATED_POSITION_SIZING,
        label="Graduated Position Sizing",
        description="SPY와 200일 이동평균선의 상대적 위치에 따라 4단계로 안전자산 비중을 조절하는 오버레이입니다.",
        lookback_days=400,
        lookback_label="SPY 50일선, 200일선 계산을 위해 약 1년 이상 가격 이력이 필요합니다.",
        rationale="Emergency Brake처럼 전량 전환하는 대신, 시장 상황에 따라 단계적으로 포지션을 조절해 whipsaw 비용을 줄이면서도 하락장 방어력을 유지하려는 오버레이입니다.",
        signal_asset="SPY",
        comparison_asset=None,
        execution_notes=(
            "월말 종가 기준: SPY > SMA200×1.02이면 100% 전략자산, SMA200 < SPY ≤ SMA200×1.02이면 70% 전략 + 30% 안전, SMA200×0.98 ≤ SPY ≤ SMA200이면 50% 전략 + 50% 안전, SPY < SMA200×0.98이면 전량 안전자산.",
            "매일 종가 기준으로 SPY가 50일선 아래에 3거래일 연속 머물면 30% 안전자산으로 추가 전환합니다.",
            "일간 신호는 월말 신호보다 가벼운 방어만 합니다. 이미 월말 기준 더 높은 안전자산 비중이면 유지합니다.",
            "월중에는 월말 포지션을 유지하고, 월말에만 포지션 비중을 재조정합니다.",
        ),
        risk_notes=(
            "4단계 구간 경계에서 빈번한 전환이 발생할 수 있습니다.",
            "SPY 가격 데이터 품질과 휴장일 캘린더에 민감합니다.",
            "상승장 초기에 30%~50% 안전자산 유지로 수익 기회를 일부 놓칠 수 있습니다.",
        ),
    ),
}


SAFE_ASSET_OPTIONS: dict[SafeAssetSymbol, SafeAssetOption] = {
    SafeAssetSymbol.SGOV: SafeAssetOption(
        symbol=SafeAssetSymbol.SGOV,
        label="SGOV",
        description="미국 초단기 국채 ETF",
        details="금리 민감도가 낮고 파킹 자산 성격이 강합니다. 다만 상장 이력이 짧아 과거 구간 제약이 큽니다.",
    ),
    SafeAssetSymbol.JPST: SafeAssetOption(
        symbol=SafeAssetSymbol.JPST,
        label="JPST",
        description="초단기 회사채 중심 초단기 채권 ETF",
        details="현금성에 가깝지만 SGOV보다는 약간의 신용 스프레드 노출이 있습니다. 상장 이력은 SGOV보다 깁니다.",
    ),
    SafeAssetSymbol.IEF: SafeAssetOption(
        symbol=SafeAssetSymbol.IEF,
        label="IEF",
        description="미국 7-10년 국채 ETF",
        details="중기 듀레이션 국채로 경기 둔화 구간 방어력이 기대되지만 금리 변동에는 더 민감합니다.",
    ),
    SafeAssetSymbol.TLT: SafeAssetOption(
        symbol=SafeAssetSymbol.TLT,
        label="TLT",
        description="미국 20년 이상 장기국채 ETF",
        details="위기 국면에서 강한 헤지 역할을 기대할 수 있지만 금리 변동성과 가격 흔들림도 큽니다.",
    ),
    SafeAssetSymbol.GLD: SafeAssetOption(
        symbol=SafeAssetSymbol.GLD,
        label="GLD",
        description="금 현물 추종 ETF",
        details="실질금리와 달러 흐름의 영향을 받는 대체 안전자산으로, 채권과 다른 방어 성격을 기대할 수 있습니다.",
    ),
    SafeAssetSymbol.XLE: SafeAssetOption(
        symbol=SafeAssetSymbol.XLE,
        label="XLE",
        description="에너지 섹터 ETF",
        details="에너지 섹터의 대표적인 ETF로, 유가 상승 시 강세를 보일 수 있습니다.",
    ),
    SafeAssetSymbol.SHY: SafeAssetOption(
        symbol=SafeAssetSymbol.SHY,
        label="SHY",
        description="미국 1-3년 단기 국채 ETF",
        details="금리 변동성이 제한적인 단기 국채로, 비교적 안정적인 방어력을 제공합니다.",
    ),
}


SAFE_ASSET_WEIGHT_FIELDS: dict[SafeAssetSymbol, str] = {
    SafeAssetSymbol.SGOV: "safe_asset_weight_sgov",
    SafeAssetSymbol.JPST: "safe_asset_weight_jpst",
    SafeAssetSymbol.IEF: "safe_asset_weight_ief",
    SafeAssetSymbol.TLT: "safe_asset_weight_tlt",
    SafeAssetSymbol.GLD: "safe_asset_weight_gld",
    SafeAssetSymbol.XLE: "safe_asset_weight_xle",
    SafeAssetSymbol.SHY: "safe_asset_weight_shy",
}


def _factor_groups(preset: StrategyPreset) -> tuple[list[str], list[str]]:
    higher = [factor.label for factor in preset.factor_specs if factor.higher_is_better]
    lower = [factor.label for factor in preset.factor_specs if not factor.higher_is_better]
    return higher, lower


def get_strategy_preset(preset_id: StrategyPresetId) -> StrategyPreset:
    return STRATEGY_PRESETS[preset_id]


def get_market_timing_overlay(overlay_id: MarketTimingOverlayId) -> MarketTimingOverlay:
    return MARKET_TIMING_OVERLAYS[overlay_id]


def get_safe_asset_option(symbol: SafeAssetSymbol) -> SafeAssetOption:
    return SAFE_ASSET_OPTIONS[symbol]


def get_transaction_cost_option(preset: TransactionCostPreset) -> TransactionCostOption:
    return TRANSACTION_COST_OPTIONS[preset]


def serialize_strategy_preset(preset: StrategyPreset) -> dict[str, Any]:
    higher, lower = _factor_groups(preset)
    return {
        "id": preset.preset_id.value,
        "label": preset.label,
        "description": preset.description,
        "lookback_label": preset.lookback_label,
        "rationale": preset.rationale,
        "higher_is_better": higher,
        "lower_is_better": lower,
        "execution_notes": list(preset.execution_notes),
        "risk_notes": list(preset.risk_notes),
    }


def serialize_market_timing_overlay(overlay: MarketTimingOverlay) -> dict[str, Any]:
    return {
        "id": overlay.overlay_id.value,
        "label": overlay.label,
        "description": overlay.description,
        "lookback_label": overlay.lookback_label,
        "rationale": overlay.rationale,
        "signal_asset": overlay.signal_asset,
        "comparison_asset": overlay.comparison_asset,
        "execution_notes": list(overlay.execution_notes),
        "risk_notes": list(overlay.risk_notes),
    }


def serialize_safe_asset_option(option: SafeAssetOption) -> dict[str, Any]:
    return {
        "id": option.symbol.value,
        "label": option.label,
        "description": option.description,
        "details": option.details,
        "weight_field": SAFE_ASSET_WEIGHT_FIELDS[option.symbol],
    }


def list_preset_options() -> list[dict[str, Any]]:
    return [serialize_strategy_preset(preset) for preset in STRATEGY_PRESETS.values()]


def list_overlay_options() -> list[dict[str, Any]]:
    return [serialize_market_timing_overlay(option) for option in MARKET_TIMING_OVERLAYS.values()]


def list_safe_asset_options() -> list[dict[str, Any]]:
    return [serialize_safe_asset_option(option) for option in SAFE_ASSET_OPTIONS.values()]


def serialize_transaction_cost_option(option: TransactionCostOption) -> dict[str, Any]:
    return {
        "id": option.preset.value,
        "label": option.label,
        "description": option.description,
        "round_trip_bps": option.round_trip_bps,
        "details": option.details,
    }


def list_cost_options() -> list[dict[str, Any]]:
    return [serialize_transaction_cost_option(option) for option in TRANSACTION_COST_OPTIONS.values()]


def default_start_date(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=365 * 5)
