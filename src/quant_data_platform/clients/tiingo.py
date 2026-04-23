from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any

import requests
from requests import HTTPError
from tenacity import retry, stop_after_attempt, wait_fixed

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.utils import parse_date

TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"


class TiingoClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.tiingo_api_key:
            raise ValueError("TIINGO_API_KEY is required for Tiingo requests.")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Token {self.settings.tiingo_api_key}",
            }
        )

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_daily_prices(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if start_date is not None:
            params["startDate"] = start_date.isoformat()
        if end_date is not None:
            params["endDate"] = end_date.isoformat()
        last_error: Exception | None = None
        for candidate in _symbol_candidates(symbol):
            response = self.session.get(
                f"{TIINGO_BASE}/{candidate}/prices",
                params=params,
                timeout=30,
            )
            try:
                response.raise_for_status()
            except HTTPError as exc:
                last_error = exc
                if response.status_code == 404:
                    continue
                raise
            payload = response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                last_error = ValueError(payload["detail"])
                continue
            return payload
        if last_error is not None:
            raise last_error
        raise ValueError(f"No Tiingo symbol candidate succeeded for {symbol}")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def fetch_batch_daily_prices(
        self,
        symbols: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        params: dict[str, str] = {"tickers": ",".join(symbols)}
        if start_date is not None:
            params["startDate"] = start_date.isoformat()
        if end_date is not None:
            params["endDate"] = end_date.isoformat()
        response = self.session.get(f"{TIINGO_BASE}/prices", params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            raise ValueError(payload["detail"])
        return payload


def parse_daily_prices(payload: list[dict[str, Any]], symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    price_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for item in payload:
        trade_date = parse_date((item.get("date") or "")[:10])
        if trade_date is None:
            continue

        dividend_amount = _to_decimal(item.get("divCash")) or Decimal("0")
        split_coefficient = _to_decimal(item.get("splitFactor")) or Decimal("1")
        close = _to_decimal(item.get("close"))
        open_ = _to_decimal(item.get("open"))
        high = _to_decimal(item.get("high"))
        low = _to_decimal(item.get("low"))
        adjusted_close = _to_decimal(item.get("adjClose")) or close
        adjusted_open = _to_decimal(item.get("adjOpen")) or open_
        adjusted_high = _to_decimal(item.get("adjHigh")) or high
        adjusted_low = _to_decimal(item.get("adjLow")) or low
        adjusted_volume = _to_decimal(item.get("adjVolume"))

        price_rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adjusted_open": adjusted_open,
                "adjusted_high": adjusted_high,
                "adjusted_low": adjusted_low,
                "adjusted_close": adjusted_close,
                "volume": int(item["volume"]) if item.get("volume") is not None else None,
                "adjusted_volume": adjusted_volume,
                "dividend_amount": dividend_amount,
                "split_coefficient": split_coefficient,
                "source": "tiingo",
            }
        )

        if dividend_amount:
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "dividend",
                    "action_value": dividend_amount,
                    "source": "tiingo",
                }
            )
        if split_coefficient != Decimal("1"):
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "split",
                    "action_value": split_coefficient,
                    "source": "tiingo",
                }
            )

    return price_rows, action_rows


def parse_batch_daily_prices(payload: list[dict[str, Any]] | dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if isinstance(payload, dict):
        normalized: dict[str, list[dict[str, Any]]] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                normalized[key] = value
        return normalized

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in payload:
        symbol = row.get("ticker") or row.get("symbol") or row.get("tickerSymbol")
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    return grouped


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "None", "null"):
        return None
    return Decimal(str(value))


def _symbol_candidates(symbol: str) -> list[str]:
    candidates = [symbol]
    if "." in symbol:
        candidates.append(symbol.replace(".", "-"))
        candidates.append(symbol.replace(".", "/"))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def sleep_for_rate_limit(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
