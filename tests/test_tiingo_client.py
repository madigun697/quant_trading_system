from __future__ import annotations

import json

from quant_data_platform.clients.tiingo import _symbol_candidates, parse_batch_daily_prices, parse_daily_prices
from tests.conftest import FIXTURE_DIR


def test_parse_daily_prices() -> None:
    payload = json.loads((FIXTURE_DIR / "tiingo_prices.json").read_text())
    price_rows, action_rows = parse_daily_prices(payload, symbol="IBM")

    assert len(price_rows) == 2
    assert price_rows[0]["symbol"] == "IBM"
    assert price_rows[0]["adjusted_close"] is not None
    assert price_rows[1]["dividend_amount"] is not None
    assert any(row["action_type"] == "dividend" for row in action_rows)


def test_symbol_candidates_for_class_shares() -> None:
    assert _symbol_candidates("BRK.B") == ["BRK.B", "BRK-B", "BRK/B"]


def test_parse_batch_daily_prices_groups_by_ticker() -> None:
    payload = [
        {"ticker": "AAPL", "date": "2026-04-01T00:00:00.000Z", "close": 100},
        {"ticker": "MSFT", "date": "2026-04-01T00:00:00.000Z", "close": 200},
        {"ticker": "AAPL", "date": "2026-04-02T00:00:00.000Z", "close": 101},
    ]
    grouped = parse_batch_daily_prices(payload)
    assert list(grouped) == ["AAPL", "MSFT"]
    assert len(grouped["AAPL"]) == 2
