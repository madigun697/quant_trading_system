from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from quant_data_platform.web.app import create_app
from quant_data_platform.web.services.alpaca_service import AlpacaPageService


class FakeAlpacaService(AlpacaPageService):
    def __init__(self, ok: bool = True, error: str | None = None) -> None:
        self.ok = ok
        self.error = error

    def get_page_context(self) -> dict[str, Any]:
        if not self.ok:
            return {"state": "error", "error_message": self.error}
        return {
            "page_title": "Alpaca Paper Trading",
            "state": "ok",
            "account": {
                "portfolio_value": "$100,000.00",
                "cash": "$10,000.00",
                "buying_power": "$20,000.00",
                "long_market_value": "$90,000.00",
                "unrealized_pl": "$5,000.00",
                "unrealized_plpc": "+5.00%",
                "unrealized_plpc_class": "positive",
                "daytrade_count": 0,
                "currency": "USD",
            },
            "positions": [],
            "orders": [],
            "position_count": 0,
        }

    def submit_orders(self, order_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.ok:
            return {"ok": False, "error": self.error, "results": []}
        return {
            "ok": True,
            "error": None,
            "results": [],
            "summary": {"total": len(order_inputs), "submitted": len(order_inputs), "errors": 0},
        }


def test_get_alpaca_page_success() -> None:
    app = create_app(alpaca_service=FakeAlpacaService(ok=True))
    client = TestClient(app)
    response = client.get("/alpaca")
    assert response.status_code == 200
    assert "포트폴리오 가치" in response.text
    assert "$100,000" in response.text


def test_get_alpaca_page_error() -> None:
    app = create_app(alpaca_service=FakeAlpacaService(ok=False, error="API Key missing"))
    client = TestClient(app)
    response = client.get("/alpaca")
    assert response.status_code == 200
    assert "Alpaca 연결에 문제가 있습니다" in response.text
    assert "API Key missing" in response.text


def test_post_alpaca_orders_success() -> None:
    app = create_app(alpaca_service=FakeAlpacaService(ok=True))
    client = TestClient(app)
    response = client.post(
        "/alpaca/orders",
        json=[{"symbol": "AAPL", "side": "buy", "order_type": "qty", "qty": 10}],
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_post_alpaca_orders_error() -> None:
    app = create_app(alpaca_service=FakeAlpacaService(ok=False, error="Some API Error"))
    client = TestClient(app)
    response = client.post(
        "/alpaca/orders",
        json=[{"symbol": "AAPL", "side": "buy", "order_type": "qty", "qty": 10}],
    )
    assert response.status_code == 422
    assert response.json()["ok"] is False
    assert response.json()["error"] == "Some API Error"
