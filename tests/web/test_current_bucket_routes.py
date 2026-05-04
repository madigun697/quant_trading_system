from __future__ import annotations

from fastapi.testclient import TestClient

from quant_data_platform.web.app import create_app
from quant_data_platform.web.schemas import CurrentBucketPageContext, CurrentBucketRow, PageState


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


class FakeCurrentBucketService:
    def __init__(self, desired_state: PageState = PageState.SUCCESS) -> None:
        self.desired_state = desired_state

    def empty_context(self) -> CurrentBucketPageContext:
        return CurrentBucketPageContext(
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
                "investable_capital": "100000",
                "top_n": "10",
            },
            preset_options=[{"id": "value_quality", "label": "Value + Quality", "description": "desc", "lookback_label": "lb", "rationale": "rationale", "higher_is_better": [], "lower_is_better": [], "execution_notes": [], "risk_notes": []}],
            overlay_options=[{"id": "none", "label": "None", "description": "desc", "lookback_label": "lb", "rationale": "overlay rationale", "signal_asset": "SPY", "comparison_asset": None, "execution_notes": [], "risk_notes": []}],
            safe_asset_options=[
                {"id": "SGOV", "label": "SGOV", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_sgov"},
                {"id": "JPST", "label": "JPST", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_jpst"},
                {"id": "IEF", "label": "IEF", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_ief"},
                {"id": "TLT", "label": "TLT", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_tlt"},
                {"id": "GLD", "label": "GLD", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_gld"},
                {"id": "XLE", "label": "XLE", "description": "safe", "details": "detail", "weight_field": "safe_asset_weight_xle"},
            ],
            selected_safe_asset_summary="SGOV 100%",
            safe_asset_summary="SGOV 100%",
        )

    def error_context(self, form, message: str, field_errors=None, http_status_code: int = 400, form_values=None, state: PageState = PageState.ERROR) -> CurrentBucketPageContext:
        context = self.empty_context()
        context.state = state
        context.error_message = message
        context.field_errors = field_errors or {}
        context.http_status_code = http_status_code
        if form_values is not None:
            context.form_values = form_values
        return context

    def build_context(self, form) -> CurrentBucketPageContext:
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
            "investable_capital": str(form.investable_capital),
            "top_n": str(form.top_n),
        }
        context.selected_safe_asset_summary = form.safe_asset_summary()
        context.safe_asset_summary = form.safe_asset_summary()
        if self.desired_state == PageState.SUCCESS:
            context.as_of_date = "2024-02-29"
            context.signal_date = "2024-02-29"
            context.price_basis_label = "오늘 장 종료 종가 기준"
            context.active_risk_state = "risk_on"
            context.cash_remainder = "$0.00"
            context.stock_bucket_rows = [
                CurrentBucketRow(
                    symbol="AAA",
                    target_weight="10.00%",
                    reference_close="$100.00",
                    target_notional="$10,000.00",
                    target_shares="100",
                    actual_notional="$10,000.00",
                    actual_weight="10.00%",
                )
            ]
        return context


def test_get_current_bucket_returns_empty_state() -> None:
    app = create_app(current_bucket_service=FakeCurrentBucketService())
    client = TestClient(app)
    response = client.get("/current-bucket")
    assert response.status_code == 200
    assert "먼저 현재 버킷을 계산해 보세요" in response.text


def test_post_valid_current_bucket_returns_success() -> None:
    app = create_app(current_bucket_service=FakeCurrentBucketService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/current-bucket",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "investable_capital": "100000",
            "top_n": "10",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 200
    assert "주식 후보 버킷" in response.text
    assert "현재 버킷 계산" in response.text


def test_post_invalid_current_bucket_returns_error_state() -> None:
    app = create_app(current_bucket_service=FakeCurrentBucketService(PageState.SUCCESS))
    client = TestClient(app)
    response = client.post(
        "/current-bucket",
        data={
            "strategy_preset": "value_quality",
            "market_timing_overlay": "none",
            "investable_capital": "0",
            "top_n": "10",
            **_safe_asset_form_data(),
        },
    )
    assert response.status_code == 422
    assert "입력값을 다시 확인해 주세요." in response.text


def test_navigation_tabs_link_backtest_and_current_bucket() -> None:
    app = create_app(current_bucket_service=FakeCurrentBucketService())
    client = TestClient(app)

    current_response = client.get("/current-bucket")
    backtest_response = client.get("/backtest")

    assert "백테스트" in current_response.text
    assert "현재 버킷" in current_response.text
    assert "page-tab--active" in current_response.text
    assert "백테스트" in backtest_response.text
    assert "현재 버킷" in backtest_response.text
