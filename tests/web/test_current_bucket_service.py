from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from quant_data_platform.web.presets import MarketTimingOverlayId, StrategyPresetId, get_strategy_preset
from quant_data_platform.web.repositories.backtest_repo import DailyCloseRow, FactorSnapshotRow, ReadinessStatus
from quant_data_platform.web.schemas import CurrentBucketFormInput, PageState
from quant_data_platform.web.services.current_bucket_service import CurrentBucketPageService


def _market_clock(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute)


def _symbols(count: int = 10) -> list[str]:
    return [f"SYM{index:02d}" for index in range(1, count + 1)]


def _factor_rows(signal_date: date, count: int = 10) -> list[FactorSnapshotRow]:
    preset = get_strategy_preset(StrategyPresetId.VALUE_QUALITY)
    rows: list[FactorSnapshotRow] = []
    for index, symbol in enumerate(_symbols(count), start=1):
        rows.append(
            FactorSnapshotRow(
                symbol=symbol,
                trade_date=signal_date,
                liquidity_rank=index,
                factors={factor.column: Decimal(str(count - index + 1)) for factor in preset.factor_specs},
            )
        )
    return rows


class FakeCurrentBucketRepository:
    def __init__(self) -> None:
        self.readiness = ReadinessStatus(ok=True, code="ok", detail="ready")
        self.calendar_dates: list[date] = []
        self.factor_rows: list[FactorSnapshotRow] = []
        self.daily_close_rows: list[DailyCloseRow] = []

    def check_readiness(self, preset_id=None) -> ReadinessStatus:
        return self.readiness

    def classify_error(self, exc: Exception, preset_id=None) -> ReadinessStatus:
        return ReadinessStatus(ok=False, code="database_error", detail=str(exc))

    def fetch_spy_calendar(self, start_date: date, end_date: date) -> list[date]:
        return [calendar_date for calendar_date in self.calendar_dates if start_date <= calendar_date <= end_date]

    def fetch_factor_rows(self, preset_id: StrategyPresetId, signal_dates: list[date]) -> list[FactorSnapshotRow]:
        return [row for row in self.factor_rows if row.trade_date in signal_dates]

    def fetch_daily_closes(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyCloseRow]:
        symbol_set = set(symbols)
        return [
            row
            for row in self.daily_close_rows
            if row.symbol in symbol_set and start_date <= row.trade_date <= end_date
        ]


def test_build_context_uses_today_close_after_market_close() -> None:
    repo = FakeCurrentBucketRepository()
    repo.calendar_dates = [date(2024, 2, 29)]
    repo.factor_rows = _factor_rows(date(2024, 2, 29))
    repo.daily_close_rows = [
        DailyCloseRow(symbol, date(2024, 2, 29), Decimal("100"))
        for symbol in _symbols()
    ]
    service = CurrentBucketPageService(repo, clock=lambda: _market_clock(2024, 2, 29, 16, 30))

    context = service.build_context(CurrentBucketFormInput())

    assert context.state == PageState.SUCCESS
    assert context.as_of_date == "2024-02-29"
    assert context.signal_date == "2024-02-29"
    assert context.price_basis_label == "오늘 장 종료 종가 기준"
    assert len(context.stock_bucket_rows) == 10


def test_build_context_uses_previous_trading_day_before_market_close() -> None:
    repo = FakeCurrentBucketRepository()
    repo.calendar_dates = [date(2024, 2, 29), date(2024, 3, 1)]
    repo.factor_rows = _factor_rows(date(2024, 2, 29))
    repo.daily_close_rows = [
        DailyCloseRow(symbol, date(2024, 2, 29), Decimal("100"))
        for symbol in _symbols()
    ]
    service = CurrentBucketPageService(repo, clock=lambda: _market_clock(2024, 3, 1, 15, 30))

    context = service.build_context(CurrentBucketFormInput())

    assert context.state == PageState.SUCCESS
    assert context.as_of_date == "2024-02-29"
    assert context.signal_date == "2024-02-29"
    assert context.price_basis_label == "직전 거래일 종가 기준"


def test_build_context_uses_last_trading_day_on_weekend() -> None:
    repo = FakeCurrentBucketRepository()
    repo.calendar_dates = [date(2024, 2, 29), date(2024, 3, 1)]
    repo.factor_rows = _factor_rows(date(2024, 2, 29))
    repo.daily_close_rows = [
        DailyCloseRow(symbol, date(2024, 3, 1), Decimal("101"))
        for symbol in _symbols()
    ]
    service = CurrentBucketPageService(repo, clock=lambda: _market_clock(2024, 3, 2, 10, 0))

    context = service.build_context(CurrentBucketFormInput())

    assert context.state == PageState.SUCCESS
    assert context.as_of_date == "2024-03-01"
    assert context.signal_date == "2024-02-29"


def test_build_context_keeps_stock_bucket_visible_during_risk_off() -> None:
    repo = FakeCurrentBucketRepository()
    repo.calendar_dates = [date(2024, 2, 29)]
    repo.factor_rows = _factor_rows(date(2024, 2, 29))
    repo.daily_close_rows = [
        DailyCloseRow(symbol, date(2024, 2, 29), Decimal("100"))
        for symbol in _symbols()
    ]
    repo.daily_close_rows.extend(
        DailyCloseRow("SPY", date(2024, 1, 1) + timedelta(days=index), Decimal("100"))
        for index in range(59)
    )
    repo.daily_close_rows.extend(
        [
            DailyCloseRow("SPY", date(2024, 2, 27), Decimal("80")),
            DailyCloseRow("SPY", date(2024, 2, 28), Decimal("79")),
            DailyCloseRow("SPY", date(2024, 2, 29), Decimal("78")),
        ]
    )
    service = CurrentBucketPageService(repo, clock=lambda: _market_clock(2024, 2, 29, 16, 30))

    context = service.build_context(
        CurrentBucketFormInput(market_timing_overlay=MarketTimingOverlayId.EMERGENCY_BRAKE_ASYMMETRIC)
    )

    assert context.state == PageState.SUCCESS
    assert context.active_risk_state == "risk_off"
    assert context.risk_off_notice is not None
    assert len(context.stock_bucket_rows) == 10


def test_build_context_fails_closed_when_reference_close_is_missing() -> None:
    repo = FakeCurrentBucketRepository()
    repo.calendar_dates = [date(2024, 2, 29)]
    repo.factor_rows = _factor_rows(date(2024, 2, 29))
    repo.daily_close_rows = [
        DailyCloseRow(symbol, date(2024, 2, 29), Decimal("100"))
        for symbol in _symbols()[1:]
    ]
    service = CurrentBucketPageService(repo, clock=lambda: _market_clock(2024, 2, 29, 16, 30))

    context = service.build_context(CurrentBucketFormInput())

    assert context.state == PageState.NO_DATA
    assert "필요한 수만큼의 투자 후보" in (context.error_message or "")
