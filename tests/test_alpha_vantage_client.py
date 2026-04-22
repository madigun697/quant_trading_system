from __future__ import annotations

import json
from datetime import date

from quant_data_platform.clients.alpha_vantage import parse_daily_adjusted, parse_listing_status_csv, parse_overview
from tests.conftest import FIXTURE_DIR


def test_parse_overview() -> None:
    payload = json.loads((FIXTURE_DIR / "alpha_vantage_overview.json").read_text())
    row = parse_overview(payload, as_of_date=date(2025, 1, 15))
    assert row["symbol"] == "IBM"
    assert row["cik"] == "0000051143"
    assert row["sector"] == "Technology"


def test_parse_daily_adjusted() -> None:
    payload = json.loads((FIXTURE_DIR / "alpha_vantage_daily_adjusted.json").read_text())
    price_rows, action_rows = parse_daily_adjusted(payload, symbol="IBM")
    assert len(price_rows) == 2
    assert price_rows[0]["symbol"] == "IBM"
    assert any(row["action_type"] == "dividend" for row in action_rows)


def test_parse_listing_status_csv() -> None:
    payload = (FIXTURE_DIR / "alpha_vantage_listing_status.csv").read_text()
    rows = parse_listing_status_csv(payload, source_file_date=date(2025, 1, 15), state="active")
    assert rows[0]["symbol"] == "IBM"
    assert rows[0]["status"] == "active"
