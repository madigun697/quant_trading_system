from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from quant_data_platform.web.app import create_app
from quant_data_platform.web.repositories.backtest_repo import ReadinessStatus
from quant_data_platform.web.schemas import BacktestPageContext, PageState


def _safe_asset_form_data(**overrides: str) -> dict[str, str]:
    payload = {
        "safe_asset_weight_sgov": "100",
        "safe_asset_weight_jpst": "0",
        "safe_asset_weight_ief": "0",
        "safe_asset_weight_tlt": "0",
        "safe_asset_weight_gld": "0",
        "safe_asset_weight_xle": "0",
    }
    payload.update(overrides)
    return payload


class FakeService:
    def __init__(self, desired_state: PageState = PageState.SUCCESS) -> None:
        self.desired_state = desired_state
        self.readiness = ReadinessStatus(ok=True, code="ok", detail="ready")

    def empty_context(self) -> BacktestPageContext:
        return BacktestPageContext(
            state=PageState.EMPTY,
            form_values={
                "strategy_preset": "value_quality",
                "market_timing_overlay": "none",
                "safe_asset_weight_sgov": "100",
                "safe_asset_weight_jpst": "0",
                "safe_asset_weight_ief": "0",
                "safe_asset_weight_tlt": "0",
                "safe_asset_weight_gld": "0",
                "safe_asset_weight_xle": "0",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "initial_capital": "100000",
                "top_n": "10",
                "transaction_cost_preset": "conservative",
            },
            preset_options=[{"id": "value_quality", "label": "Value + Quality", "description": "desc", "lookback_label": "lb", "rationale": "rationale", "higher_is_better": [], "lower_is_better": [], "execution_notes": [], "risk_notes": []}],
            overlay_options=[
                {"id": "none", "label": "None", "description": "desc", "lookback_label": "lb", "rationale": "overlay rationale", "signal_asset": "SPY", "comparison_asset": None, "execution_notes": [], "risk_notes": []},
                {"id": "emergency_brake_asymmetric", "label": "Emergency", "description": "desc", "lookback_label": "lb", "rationale": "overlay rationale", "signal_asset": "SPY", "comparison_asset": None, "execution_notes": [], "risk_notes": []},
            ],
            safe_asset_options=[
                {"id": "SGOV", "label": "SGOV", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_sgov"},
                {"id": "JPST", "label": "JPST", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_jpst"},
                {"id": "IEF", "label": "IEF", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_ief"},
                {"id": "TLT", "label": "TLT", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_tlt"},
                {"id": "GLD", "label": "GLD", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_gld"},
                {"id": "XLE", "label": "XLE", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_xle"},
            ],
            transaction_cost_options=[{"id": "conservative", "label": "Conservative", "description": "왕복 총비용 50bp", "round_trip_bps": 50, "details": "detail"}],
            selected_safe_asset_summary="SGOV 100%",
        )

    def readiness_status(self) -> ReadinessStatus:
        return self.readiness

    def error_context(self, form, message: str, field_errors=None, http_status_code: int = 400, form_values=None) -> BacktestPageContext:
        context = self.empty_context()
        context.state = PageState.ERROR
        context.error_message = message
        context.field_errors = field_errors or {}
        context.http_status_code = http_status_code
        if form_values is not None:
            context.form_values = form_values
        return context

    def build_context(self, form) -> BacktestPageContext:
        context = self.empty_context()
        context.state = self.desired_state
        context.form_values = {
            "strategy_preset": form.strategy_preset.value,
            "market_timing_overlay": form.market_timing_overlay.value,
            "safe_asset_weight_sgov": str(form.safe_asset_weight_sgov),
            "safe_asset_weight_jpst": str(form.safe_asset_weight_jpst),
            "safe_asset_weight_ief": str(form.safe_asset_weight_ief),
            "safe_asset_weight_tlt": str(form.safe_asset_weight_tlt),
            "safe_asset_weight_gld": str(form.safe_asset_weight_gld),
            "safe_asset_weight_xle": str(form.safe_asset_weight_xle),
            "start_date": form.start_date.isoformat(),
            "end_date": form.end_date.isoformat(),
            "initial_capital": str(form.initial_capital),
            "top_n": str(form.top_n),
            "transaction_cost_preset": form.transaction_cost_preset.value,
        }
        context.selected_safe_asset_summary = form.safe_asset_summary()
        if self.desired_state == PageState.SUCCESS:
            context.summary_metrics = []
            context.equity_curve = []
            context.trade_log_summary = []
            context.trade_log_rows = []
            context.run_id = "bt-test"
            context.db_save_success_message = "DB에 백테스트 결과를 저장했습니다: bt-test"
        elif self.desired_state == PageState.NO_DATA:
            context.error_message = "선택한 기간과 조건에서 체결 가능한 후보를 찾지 못했습니다."
        elif self.desired_state == PageState.INSUFFICIENT_HISTORY:
            context.error_message = "선택한 기간에는 전략 계산에 필요한 과거 이력이 부족합니다."
        elif self.desired_state == PageState.ERROR:
            context.error_message = "백테스트 데이터베이스에 연결하지 못했습니다."
            context.http_status_code = 503
        return context

    def save_context(self, form) -> BacktestPageContext:
        context = self.build_context(form)
        if context.state == PageState.SUCCESS:
            context.save_directory = str(Path("/tmp/backtest_result/20260429_120000"))
            context.save_success_message = f"백테스트 결과를 저장했습니다: {context.save_directory}"
        else:
            reason = context.error_message or "현재 조건에서는 저장 가능한 결과를 만들지 못했습니다."
            context.save_error_message = f"결과 저장을 완료하지 못했습니다. {reason}"
        return context

    def recent_runs(self, limit: int = 20):
        return [
            {
                "run_id": "bt-test",
                "created_at": "2024-04-01 09:30:00+00:00",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 12, 31),
                "strategy_preset": "value_quality",
                "market_timing_overlay": "none",
                "safe_asset_summary": "SGOV 100%",
                "initial_capital": 100000,
                "top_n": 10,
                "transaction_cost_preset": "conservative",
                "net_total_return": 0.1,
                "max_drawdown_net": -0.05,
                "sharpe": 1.2,
                "trade_count": 12,
                "total_fees": 15,
            }
        ][:limit]

    def saved_run_context(self, run_id: str) -> BacktestPageContext:
        context = self.empty_context()
        context.state = self.desired_state
        context.run_id = run_id
        context.run_created_at = "2024-04-01T09:30:00"
        context.helper_copy = "DB에 저장된 과거 백테스트 실행 결과입니다."
        if self.desired_state == PageState.SUCCESS:
            context.summary_metrics = []
            context.equity_curve = []
            context.trade_log_summary = []
            context.trade_log_rows = []
        else:
            context.error_message = "요청한 백테스트 실행 결과를 찾지 못했습니다."
            context.http_status_code = 404
        return context


def test_get_backtest_returns_empty_state() -> None:
    app = create_app(service=FakeService())
    client = TestClient(app)
    response = client.get("/backtest")
    assert response.status_code == 200
    assert "먼저 프리셋을 골라 실행해 보세요" in response.text


def test_healthz_returns_ok_payload_when_ready() -> None:
    app = create_app(service=FakeService())
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["code"] == "ok"


@pytest.mark.parametrize("preset_id", ["value_quality", "value_momentum", "quality_lowvol"])
def test_post_valid_form_returns_success(preset_id: str) -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": preset_id,
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "핵심 성과 요약" in response.text
    assert "DB 저장 완료" in response.text
    assert "/backtest/runs/bt-test" in response.text
    assert 'formaction="http://testserver/backtest/save"' in response.text
    assert 'action="http://testserver/backtest"' in response.text


def test_saved_backtest_runs_routes_render() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)

    runs = client.get("/backtest/runs")
    assert runs.status_code == 200
    assert "저장된 백테스트 실행 결과" in runs.text
    assert "bt-test" in runs.text
    assert "/backtest/runs/bt-test" in runs.text

    detail = client.get("/backtest/runs/bt-test")
    assert detail.status_code == 200
    assert "Backtest Detail" in detail.text
    assert "bt-test" in detail.text


def test_post_invalid_form_returns_error_state() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-12-31",
            "end_date": "2024-01-01",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 422
    assert "입력값을 다시 확인해 주세요." in response.text


def test_post_invalid_safe_asset_total_returns_field_error() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(safe_asset_weight_sgov="60", safe_asset_weight_ief="30"),
        },
    )
    assert response.status_code == 422
    assert "안전자산 비중 합계는 정확히 100%여야 합니다." in response.text


def test_healthz_returns_service_unavailable_when_readiness_fails() -> None:
    service = FakeService()
    service.readiness = ReadinessStatus(
        ok=False,
        code="database_unreachable",
        detail="db down",
        checked_relations=("stg.stg_daily_prices",),
    )
    app = create_app(service=service)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["code"] == "database_unreachable"


def test_post_insufficient_history_returns_state_message() -> None:
    app = create_app(service=FakeService(PageState.INSUFFICIENT_HISTORY))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "초기 구간의 과거 이력이 부족합니다" in response.text


def test_post_no_data_returns_state_message() -> None:
    app = create_app(service=FakeService(PageState.NO_DATA))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "이번 조건에서는 실행 결과를 만들지 못했습니다" in response.text


def test_form_values_persist_after_post() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "emergency_brake_asymmetric",
            "start_date": "2024-02-01",
            "end_date": "2024-12-31",
            "initial_capital": "250000",
            "top_n": "20",
            "transaction_cost_preset": "base",
            **_safe_asset_form_data(safe_asset_weight_sgov="0", safe_asset_weight_jpst="100"),
        },
    )
    assert response.status_code == 200
    assert 'value="2024-02-01"' in response.text
    assert 'value="250000"' in response.text
    assert 'name="safe_asset_weight_jpst"' in response.text
    assert 'value="100"' in response.text


def test_post_legacy_safe_asset_symbol_is_upgraded_to_weight_inputs() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "safe_asset_symbol": "JPST",
            "start_date": "2024-02-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 200
    assert 'name="safe_asset_weight_jpst"' in response.text
    assert 'value="100"' in response.text


def test_post_invalid_legacy_safe_asset_symbol_returns_error() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "safe_asset_symbol": "INVALID",
            "start_date": "2024-02-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 422
    assert "safe_asset_symbol 값이 유효하지 않습니다." in response.text


def test_post_runtime_error_uses_context_status_code() -> None:
    app = create_app(service=FakeService(PageState.ERROR))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 503
    assert "백테스트 데이터베이스에 연결하지 못했습니다." in response.text


def test_post_save_valid_form_returns_success_message() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest/save",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "결과 저장 완료" in response.text
    assert "/tmp/backtest_result/20260429_120000" in response.text


def test_post_save_invalid_form_returns_error_state() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest/save",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-12-31",
            "end_date": "2024-01-01",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 422
    assert "결과 저장 실패" in response.text
    assert "입력값을 다시 확인해 주세요." in response.text


def test_post_save_non_success_returns_failure_message() -> None:
    app = create_app(service=FakeService(PageState.NO_DATA))
    client = TestClient(app)
    response = client.post(
        "/backtest/save",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "결과 저장 실패" in response.text
    assert "결과 저장을 완료하지 못했습니다." in response.text


def test_post_save_propagates_service_failure_status() -> None:
    class SaveFailureService(FakeService):
        def save_context(self, form) -> BacktestPageContext:
            context = self.build_context(form)
            context.save_error_message = "결과 파일 저장 중 오류가 발생했습니다. disk full"
            context.http_status_code = 500
            return context

    app = create_app(service=SaveFailureService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest/save",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 500
    assert "결과 파일 저장 중 오류가 발생했습니다." in response.text
