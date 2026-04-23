from __future__ import annotations

import csv
import time
from datetime import date
from decimal import Decimal
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.utils import parse_date

ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.alphavantage_api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY is required for Alpha Vantage requests.")
        self.session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_daily_adjusted(self, symbol: str, outputsize: str = "compact") -> dict[str, Any]:
        response = self.session.get(
            ALPHA_VANTAGE_BASE,
            params={
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": symbol,
                "outputsize": outputsize,
                "apikey": self.settings.alphavantage_api_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        _raise_if_api_error(payload)
        return payload

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_overview(self, symbol: str) -> dict[str, Any]:
        response = self.session.get(
            ALPHA_VANTAGE_BASE,
            params={"function": "OVERVIEW", "symbol": symbol, "apikey": self.settings.alphavantage_api_key},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        _raise_if_api_error(payload)
        return payload

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_listing_status(self, state: str = "active") -> str:
        response = self.session.get(
            ALPHA_VANTAGE_BASE,
            params={"function": "LISTING_STATUS", "state": state, "apikey": self.settings.alphavantage_api_key},
            timeout=30,
        )
        response.raise_for_status()
        return response.text


def parse_overview(payload: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    symbol = payload.get("Symbol")
    if not symbol:
        raise ValueError("Alpha Vantage overview payload missing Symbol.")
    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "cik": _normalize_cik(payload.get("CIK")),
        "name": payload.get("Name"),
        "exchange": payload.get("Exchange"),
        "sector": payload.get("Sector"),
        "industry": payload.get("Industry"),
        "asset_type": payload.get("AssetType"),
        "market_cap": _to_decimal(payload.get("MarketCapitalization")),
        "shares_outstanding": _to_decimal(payload.get("SharesOutstanding")),
        "overview_json": payload,
    }


def parse_daily_adjusted(payload: dict[str, Any], symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    series = payload.get("Time Series (Daily)", {})
    price_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for trade_date_raw, values in series.items():
        trade_date = parse_date(trade_date_raw)
        if trade_date is None:
            continue
        dividend_amount = _to_decimal(values.get("7. dividend amount")) or Decimal("0")
        split_coefficient = _to_decimal(values.get("8. split coefficient")) or Decimal("1")
        price_rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": _to_decimal(values.get("1. open")),
                "high": _to_decimal(values.get("2. high")),
                "low": _to_decimal(values.get("3. low")),
                "close": _to_decimal(values.get("4. close")),
                "adjusted_close": _to_decimal(values.get("5. adjusted close")),
                "volume": int(values.get("6. volume", "0")),
                "dividend_amount": dividend_amount,
                "split_coefficient": split_coefficient,
            }
        )
        if dividend_amount:
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "dividend",
                    "action_value": dividend_amount,
                }
            )
        if split_coefficient != Decimal("1"):
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "split",
                    "action_value": split_coefficient,
                }
            )
    return price_rows, action_rows


def parse_listing_status_csv(csv_payload: str, source_file_date: date, state: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(csv_payload.splitlines())
    for row in reader:
        rows.append(
            {
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "exchange": row.get("exchange"),
                "asset_type": row.get("assetType"),
                "ipo_date": parse_date(row.get("ipoDate")),
                "delisting_date": parse_date(row.get("delistingDate")),
                "status": state,
                "source_file_date": source_file_date,
            }
        )
    return rows


def _normalize_cik(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits.zfill(10) if digits else None


def _raise_if_api_error(payload: dict[str, Any]) -> None:
    if "Error Message" in payload:
        raise ValueError(payload["Error Message"])
    if "Note" in payload:
        raise ValueError(payload["Note"])
    if "Information" in payload:
        raise ValueError(payload["Information"])


def _to_decimal(value: str | None) -> Decimal | None:
    if value in (None, "", "None", "null"):
        return None
    return Decimal(value)


def sleep_for_rate_limit(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
