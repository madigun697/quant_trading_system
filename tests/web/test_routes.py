from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
import pytest

from quant_data_platform.web.app import create_app
from quant_data_platform.web.repositories.backtest_repo import ReadinessStatus
from quant_data_platform.web.schemas import BacktestPageContext, PageState


class FakeService:
    def __init__(self, desired_state: PageState = PageState.SUCCESS) -> None:
        self.desired_state = desired_state
        self.readiness = ReadinessStatus(ok=True, code="ok", detail="ready")

    def empty_context(self) -> BacktestPageContext:
        return BacktestPageContext(
            state=PageState.EMPTY,
            form_values={
                "strategy_preset": "value_quality",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "initial_capital": "100000",
                "top_n": "10",
                "transaction_cost_preset": "conservative",
            },
            preset_options=[{"id": "value_quality", "label": "Value + Quality", "description": "desc", "lookback_label": "lb"}],
            transaction_cost_options=[{"id": "conservative", "label": "Conservative", "description": "왕복 총비용 50bp"}],
        )

    def readiness_status(self) -> ReadinessStatus:
        return self.readiness

    def error_context(self, form, message: str, field_errors=None, http_status_code: int = 400) -> BacktestPageContext:
        context = self.empty_context()
        context.state = PageState.ERROR
        context.error_message = message
        context.field_errors = field_errors or {}
        context.http_status_code = http_status_code
        return context

    def build_context(self, form) -> BacktestPageContext:
        context = self.empty_context()
        context.state = self.desired_state
        context.form_values = {
            "strategy_preset": form.strategy_preset.value,
            "start_date": form.start_date.isoformat(),
            "end_date": form.end_date.isoformat(),
            "initial_capital": str(form.initial_capital),
            "top_n": str(form.top_n),
            "transaction_cost_preset": form.transaction_cost_preset.value,
        }
        if self.desired_state == PageState.SUCCESS:
            context.summary_metrics = []
            context.equity_curve = []
            context.trade_log_summary = []
            context.trade_log_rows = []
        elif self.desired_state == PageState.NO_DATA:
            context.error_message = "선택한 기간과 조건에서 체결 가능한 후보를 찾지 못했습니다."
        elif self.desired_state == PageState.INSUFFICIENT_HISTORY:
            context.error_message = "선택한 기간에는 전략 계산에 필요한 과거 이력이 부족합니다."
        elif self.desired_state == PageState.ERROR:
            context.error_message = "백테스트 데이터베이스에 연결하지 못했습니다."
            context.http_status_code = 503
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
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 200
    assert "핵심 성과 요약" in response.text


def test_post_invalid_form_returns_error_state() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "start_date": "2024-12-31",
            "end_date": "2024-01-01",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 422
    assert "입력값을 다시 확인해 주세요." in response.text


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
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
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
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 200
    assert "이번 조건에서는 체결 가능한 결과가 없습니다" in response.text


def test_form_values_persist_after_post() -> None:
    app = create_app(service=FakeService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "start_date": "2024-02-01",
            "end_date": "2024-12-31",
            "initial_capital": "250000",
            "top_n": "20",
            "transaction_cost_preset": "base",
        },
    )
    assert response.status_code == 200
    assert 'value="2024-02-01"' in response.text
    assert 'value="250000"' in response.text


def test_post_runtime_error_uses_context_status_code() -> None:
    app = create_app(service=FakeService(PageState.ERROR))
    client = TestClient(app)
    response = client.post(
        "/backtest",
        data={
            "strategy_preset": "value_quality",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": "100000",
            "top_n": "10",
            "transaction_cost_preset": "conservative",
        },
    )
    assert response.status_code == 503
    assert "백테스트 데이터베이스에 연결하지 못했습니다." in response.text
