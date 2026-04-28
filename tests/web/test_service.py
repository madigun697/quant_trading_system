from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_data_platform.web.presets import StrategyPresetId, TransactionCostPreset
from quant_data_platform.web.repositories.backtest_repo import DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow
from quant_data_platform.web.schemas import BacktestFormInput, PageState
from quant_data_platform.web.services.backtest_service import BacktestPageService


class FakeRepository:
    def __init__(self) -> None:
        self.freshness_calls = 0

    def fetch_freshness_token(self, preset_id: StrategyPresetId) -> str:
        self.freshness_calls += 1
        return "fresh-token"

    def fetch_spy_calendar(self, start_date: date, end_date: date) -> list[date]:
        return [date(2024, 1, 31), date(2024, 2, 1)]

    def fetch_factor_rows(self, preset_id: StrategyPresetId, signal_dates: list[date]) -> list[FactorSnapshotRow]:
        return [
            FactorSnapshotRow(
                "AAA",
                date(2024, 1, 31),
                1,
                {
                    "pe_ratio": Decimal("10"),
                    "pb_ratio": Decimal("1"),
                    "ev_to_ebitda": Decimal("8"),
                    "accruals": Decimal("0.1"),
                    "debt_to_equity": Decimal("0.2"),
                    "fcf_yield": Decimal("0.4"),
                    "sales_yield": Decimal("0.3"),
                    "roe": Decimal("0.2"),
                    "roic_proxy": Decimal("0.3"),
                    "gross_margin": Decimal("0.4"),
                    "operating_margin": Decimal("0.2"),
                    "interest_coverage": Decimal("4"),
                },
            )
        ]

    def fetch_execution_prices(self, symbols: list[str], trade_dates: list[date]) -> list[ExecutionPriceRow]:
        return [ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10"))]

    def fetch_earliest_available_trade_date(self, preset_id: StrategyPresetId) -> date | None:
        return date(2024, 1, 31)

    def fetch_daily_closes(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyCloseRow]:
        return [DailyCloseRow("AAA", date(2024, 2, 1), Decimal("10"))]


def test_empty_context_uses_beginner_defaults() -> None:
    service = BacktestPageService(FakeRepository())
    context = service.empty_context(today=date(2024, 4, 1))
    assert context.state == PageState.EMPTY
    assert context.form_values["top_n"] == "10"
    assert context.form_values["transaction_cost_preset"] == TransactionCostPreset.CONSERVATIVE.value


def test_build_context_uses_cache_for_same_inputs() -> None:
    repo = FakeRepository()
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    first = service.build_context(form)
    second = service.build_context(form)
    assert first.state == PageState.SUCCESS
    assert second.state == PageState.SUCCESS
    assert repo.freshness_calls == 2
    assert first.model_dump() == second.model_dump()
