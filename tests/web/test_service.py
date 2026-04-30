from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from quant_data_platform.web.presets import StrategyPresetId, TransactionCostPreset
from quant_data_platform.web.repositories.backtest_repo import BenchmarkValueRow, DailyCloseRow, ExecutionPriceRow, FactorSnapshotRow, ReadinessStatus
from quant_data_platform.web.schemas import BacktestFormInput, PageState
from quant_data_platform.web.services.backtest_result_writer import BacktestResultWriter
from quant_data_platform.web.services.backtest_service import BacktestPageService


def _safe_asset_form_values(**overrides: str) -> dict[str, str]:
    payload = {
        "safe_asset_weight_sgov": "100",
        "safe_asset_weight_jpst": "0",
        "safe_asset_weight_ief": "0",
        "safe_asset_weight_tlt": "0",
        "safe_asset_weight_gld": "0",
    }
    payload.update(overrides)
    return payload


class FakeRepository:
    def __init__(self) -> None:
        self.freshness_calls = 0
        self.readiness = ReadinessStatus(ok=True, code="ok", detail="ready")
        self.daily_close_symbols: list[str] = []
        self.raise_on_freshness: Exception | None = None
        self.readiness_preset_id: StrategyPresetId | None = None

    def check_readiness(self, preset_id: StrategyPresetId | None = None) -> ReadinessStatus:
        self.readiness_preset_id = preset_id
        return self.readiness

    def classify_error(self, exc: Exception, preset_id: StrategyPresetId | None = None) -> ReadinessStatus:
        if isinstance(exc, psycopg.OperationalError):
            return ReadinessStatus(ok=False, code="database_unreachable", detail=str(exc))
        return ReadinessStatus(ok=False, code="database_error", detail=str(exc))

    def fetch_freshness_token(self, preset_id: StrategyPresetId) -> str:
        if self.raise_on_freshness is not None:
            raise self.raise_on_freshness
        self.freshness_calls += 1
        return "fresh-token"

    def fetch_spy_calendar(self, start_date: date, end_date: date) -> list[date]:
        return [date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 29), date(2024, 3, 1)]

    def compute_factor_buffer_start(self, preset_id: StrategyPresetId, start_date: date) -> date:
        return start_date

    def fetch_factor_rows(self, preset_id: StrategyPresetId, signal_dates: list[date]) -> list[FactorSnapshotRow]:
        return [
            FactorSnapshotRow(
                "AAA",
                date(2024, 1, 31),
                1,
                {
                    "pe_ratio": Decimal("5"),
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
            ),
            FactorSnapshotRow(
                "BBB",
                date(2024, 1, 31),
                2,
                {
                    "pe_ratio": Decimal("25"),
                    "pb_ratio": Decimal("3"),
                    "ev_to_ebitda": Decimal("16"),
                    "accruals": Decimal("0.4"),
                    "debt_to_equity": Decimal("0.8"),
                    "fcf_yield": Decimal("0.1"),
                    "sales_yield": Decimal("0.1"),
                    "roe": Decimal("0.05"),
                    "roic_proxy": Decimal("0.07"),
                    "gross_margin": Decimal("0.15"),
                    "operating_margin": Decimal("0.08"),
                    "interest_coverage": Decimal("1"),
                },
            ),
        ]

    def fetch_execution_prices(self, symbols: list[str], trade_dates: list[date]) -> list[ExecutionPriceRow]:
        return [
            ExecutionPriceRow("AAA", date(2024, 2, 1), Decimal("10")),
            ExecutionPriceRow("BBB", date(2024, 2, 1), None),
        ]

    def fetch_earliest_available_trade_date(self, preset_id: StrategyPresetId) -> date | None:
        return date(2024, 1, 31)

    def fetch_daily_closes(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyCloseRow]:
        self.daily_close_symbols = symbols
        return [DailyCloseRow(symbol, date(2024, 2, 1), Decimal("10")) for symbol in symbols]

    def fetch_spy_benchmark_values(self, start_date: date, end_date: date) -> list[BenchmarkValueRow]:
        return [BenchmarkValueRow(date(2024, 2, 1), Decimal("100"))]


def test_empty_context_uses_beginner_defaults() -> None:
    service = BacktestPageService(FakeRepository())
    context = service.empty_context(today=date(2024, 4, 1))
    assert context.state == PageState.EMPTY
    assert context.form_values["top_n"] == "10"
    assert context.form_values["transaction_cost_preset"] == TransactionCostPreset.CONSERVATIVE.value
    assert context.selected_preset_detail is not None
    assert context.selected_cost_detail is not None


def test_error_context_uses_raw_form_values_for_selected_details() -> None:
    service = BacktestPageService(FakeRepository())
    context = service.error_context(
        form=None,
        message="입력값을 다시 확인해 주세요.",
        form_values={
            "strategy_preset": StrategyPresetId.QUALITY_LOWVOL.value,
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2023-01-01",
            "initial_capital": "1000",
            "top_n": "10",
            "transaction_cost_preset": TransactionCostPreset.BASE.value,
            **_safe_asset_form_values(),
        },
    )
    assert context.selected_preset_detail is not None
    assert context.selected_preset_detail.id == StrategyPresetId.QUALITY_LOWVOL.value
    assert context.selected_cost_detail is not None
    assert context.selected_cost_detail.id == TransactionCostPreset.BASE.value


def test_readiness_status_targets_default_preset() -> None:
    repo = FakeRepository()
    service = BacktestPageService(repo)
    readiness = service.readiness_status()
    assert readiness.ok is True
    assert repo.readiness_preset_id == StrategyPresetId.VALUE_QUALITY


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
    assert first.equity_curve[-1].benchmark_equity is not None


def test_build_context_fetches_daily_closes_only_for_selected_symbols() -> None:
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
    context = service.build_context(form)
    assert context.state == PageState.SUCCESS
    assert repo.daily_close_symbols == ["AAA", "IEF", "SGOV", "SPY", "VT"]
    assert context.selected_safe_asset_summary == "SGOV 100%"


def test_build_context_includes_only_non_zero_safe_assets_in_support_symbol_fetch() -> None:
    repo = FakeRepository()
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        safe_asset_weight_sgov=Decimal("60"),
        safe_asset_weight_jpst=Decimal("0"),
        safe_asset_weight_ief=Decimal("40"),
        safe_asset_weight_tlt=Decimal("0"),
        safe_asset_weight_gld=Decimal("0"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    context = service.build_context(form)
    assert context.state == PageState.SUCCESS
    assert repo.daily_close_symbols == ["AAA", "IEF", "SGOV", "SPY", "VT"]
    assert context.selected_safe_asset_summary == "SGOV 60% / IEF 40%"


def test_build_context_returns_friendly_error_when_readiness_fails() -> None:
    repo = FakeRepository()
    repo.readiness = ReadinessStatus(
        ok=False,
        code="database_unreachable",
        detail="cannot connect",
    )
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    context = service.build_context(form)
    assert context.state == PageState.ERROR
    assert context.http_status_code == 503
    assert "docker compose up -d postgres backtest-web" in (context.error_message or "")


def test_build_context_returns_friendly_error_when_support_symbol_data_is_missing() -> None:
    repo = FakeRepository()
    repo.readiness = ReadinessStatus(
        ok=False,
        code="missing_support_symbol_data",
        detail="지원 심볼 가격 이력이 없습니다: VT, IEF",
    )
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    context = service.build_context(form)
    assert context.state == PageState.ERROR
    assert context.http_status_code == 503
    assert "지원 심볼 데이터" in (context.error_message or "")


def test_build_context_wraps_runtime_database_errors() -> None:
    repo = FakeRepository()
    repo.raise_on_freshness = psycopg.OperationalError("failed to resolve host 'postgres'")
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    context = service.build_context(form)
    assert context.state == PageState.ERROR
    assert context.http_status_code == 503
    assert "POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432" in (context.error_message or "")


def test_build_context_surfaces_query_errors_without_masking_as_unreachable() -> None:
    repo = FakeRepository()
    repo.raise_on_freshness = psycopg.ProgrammingError("permission denied for relation mart_value_quality_inputs")
    service = BacktestPageService(repo)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )
    context = service.build_context(form)
    assert context.state == PageState.ERROR
    assert context.http_status_code == 500
    assert "데이터베이스 오류가 발생했습니다" in (context.error_message or "")


def test_save_context_writes_result_bundle(tmp_path: Path) -> None:
    repo = FakeRepository()
    writer = BacktestResultWriter(tmp_path / "backtest_result")
    service = BacktestPageService(repo, result_writer=writer)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )

    context = service.save_context(form, saved_at=datetime(2024, 4, 1, 9, 30, 0))

    assert context.state == PageState.SUCCESS
    assert context.save_directory is not None
    assert context.save_success_message is not None
    result_dir = Path(context.save_directory)
    assert result_dir.name == "20240401_093000"
    assert (result_dir / "backtest_input_summary.md").exists()
    assert (result_dir / "rebalance_summary.csv").exists()
    assert (result_dir / "fill_log.csv").exists()
    markdown = (result_dir / "backtest_input_summary.md").read_text(encoding="utf-8")
    assert "## 입력값 요약" in markdown
    assert "## 핵심 성과 요약" in markdown
    assert "| 안전자산 | SGOV 100% |" in markdown
    rebalance_csv = (result_dir / "rebalance_summary.csv").read_text(encoding="utf-8")
    assert "signal_date,execution_date,selected_count,sold_count" in rebalance_csv
    fill_csv = (result_dir / "fill_log.csv").read_text(encoding="utf-8")
    assert "execution_date,signal_date,symbol,action,shares" in fill_csv


def test_save_context_skips_writing_when_result_is_not_success(tmp_path: Path) -> None:
    class NoDataRepository(FakeRepository):
        def fetch_factor_rows(self, preset_id: StrategyPresetId, signal_dates: list[date]) -> list[FactorSnapshotRow]:
            return []

        def fetch_earliest_available_trade_date(self, preset_id: StrategyPresetId) -> date | None:
            return None

    writer = BacktestResultWriter(tmp_path / "backtest_result")
    service = BacktestPageService(NoDataRepository(), result_writer=writer)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )

    context = service.save_context(form, saved_at=datetime(2024, 4, 1, 9, 30, 0))

    assert context.state == PageState.NO_DATA
    assert context.save_error_message is not None
    assert context.save_directory is None
    assert not (tmp_path / "backtest_result").exists()


def test_save_context_avoids_timestamp_collision(tmp_path: Path) -> None:
    repo = FakeRepository()
    writer = BacktestResultWriter(tmp_path / "backtest_result")
    service = BacktestPageService(repo, result_writer=writer)
    collision_dir = tmp_path / "backtest_result" / "20240401_093000"
    collision_dir.mkdir(parents=True)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )

    context = service.save_context(form, saved_at=datetime(2024, 4, 1, 9, 30, 0))

    assert context.save_directory is not None
    assert Path(context.save_directory).name == "20240401_093001"


def test_save_context_cleans_up_partial_directory_on_write_failure(tmp_path: Path) -> None:
    class BrokenWriter(BacktestResultWriter):
        def _write_fill_csv(self, path: Path, simulation) -> None:
            raise OSError("disk full")

    repo = FakeRepository()
    writer = BrokenWriter(tmp_path / "backtest_result")
    service = BacktestPageService(repo, result_writer=writer)
    form = BacktestFormInput(
        strategy_preset=StrategyPresetId.VALUE_QUALITY,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        initial_capital=Decimal("1000"),
        top_n=10,
        transaction_cost_preset=TransactionCostPreset.CONSERVATIVE,
    )

    context = service.save_context(form, saved_at=datetime(2024, 4, 1, 9, 30, 0))

    assert context.save_directory is None
    assert context.save_error_message is not None
    assert context.http_status_code == 500
    assert not (tmp_path / "backtest_result" / "20240401_093000").exists()
