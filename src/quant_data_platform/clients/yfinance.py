from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import yfinance as yf


class YFinanceClient:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_history_batch(
        self,
        symbols: list[str],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        if not symbols:
            return {}

        request_symbols = [_normalize_symbol_for_yahoo(symbol) for symbol in symbols]
        requested_to_original = dict(zip(request_symbols, symbols, strict=False))
        frame = yf.download(
            tickers=request_symbols,
            start=start_date,
            end=(end_date + timedelta(days=1)) if end_date is not None else None,
            interval="1d",
            actions=True,
            auto_adjust=False,
            repair=False,
            keepna=False,
            progress=False,
            threads=False,
            group_by="ticker",
            multi_level_index=True,
            timeout=self.timeout_seconds,
        )
        return parse_download_frame(frame, requested_to_original)


def parse_download_frame(
    frame: pd.DataFrame,
    requested_to_original: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    if frame is None or frame.empty:
        return {}

    payloads: dict[str, list[dict[str, Any]]] = {}
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = set(frame.columns.get_level_values(0))
        level1 = set(frame.columns.get_level_values(1))
        for requested_symbol, original_symbol in requested_to_original.items():
            if requested_symbol in level0:
                symbol_frame = frame[requested_symbol]
            elif requested_symbol in level1:
                symbol_frame = frame.xs(requested_symbol, axis=1, level=1)
            else:
                continue
            symbol_payload = _frame_to_records(symbol_frame)
            if symbol_payload:
                payloads[original_symbol] = symbol_payload
        return payloads

    if len(requested_to_original) == 1:
        original_symbol = next(iter(requested_to_original.values()))
        symbol_payload = _frame_to_records(frame)
        if symbol_payload:
            payloads[original_symbol] = symbol_payload
    return payloads


def parse_history_payload(payload: list[dict[str, Any]], *, symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    price_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for item in payload:
        trade_date = _coerce_trade_date(item.get("Date"))
        if trade_date is None:
            continue

        dividend_amount = _to_decimal(item.get("Dividends")) or Decimal("0")
        split_coefficient = _to_decimal(item.get("Stock Splits")) or Decimal("1")
        close = _to_decimal(item.get("Close"))

        price_rows.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "open": _to_decimal(item.get("Open")),
                "high": _to_decimal(item.get("High")),
                "low": _to_decimal(item.get("Low")),
                "close": close,
                "adjusted_open": None,
                "adjusted_high": None,
                "adjusted_low": None,
                "adjusted_close": _to_decimal(item.get("Adj Close")) or close,
                "volume": _to_int(item.get("Volume")),
                "adjusted_volume": None,
                "dividend_amount": dividend_amount,
                "split_coefficient": split_coefficient,
                "source": "yfinance_history",
            }
        )

        if dividend_amount:
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "dividend",
                    "action_value": dividend_amount,
                    "source": "yfinance_history",
                }
            )
        if split_coefficient != Decimal("1"):
            action_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "action_type": "split",
                    "action_value": split_coefficient,
                    "source": "yfinance_history",
                }
            )

    return price_rows, action_rows


def _normalize_symbol_for_yahoo(symbol: str) -> str:
    return symbol.replace(".", "-").replace("/", "-").upper()


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    normalized = frame.copy()
    normalized.index = pd.to_datetime(normalized.index).date
    normalized = normalized.reset_index().rename(columns={"index": "Date"})
    normalized = normalized.where(pd.notnull(normalized), None)
    return normalized.to_dict(orient="records")


def _coerce_trade_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "None", "null"):
        return None
    if pd.isna(value):
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value in (None, "", "None", "null"):
        return None
    if pd.isna(value):
        return None
    return int(value)
