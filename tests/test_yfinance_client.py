from __future__ import annotations

from datetime import date

import pandas as pd

from quant_data_platform.clients.yfinance import parse_download_frame, parse_history_payload


def test_parse_download_frame_with_multiindex_columns() -> None:
    columns = pd.MultiIndex.from_product(
        [["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]]
    )
    frame = pd.DataFrame(
        [
            [100, 101, 99, 100, 99.5, 1000, 0, 0, 200, 201, 198, 200, 199.5, 2000, 0, 0],
            [101, 102, 100, 101, 100.5, 1100, 0.25, 0, 201, 202, 199, 201, 200.5, 2100, 0, 0],
        ],
        index=pd.to_datetime(["2026-04-01", "2026-04-02"]),
        columns=columns,
    )

    payloads = parse_download_frame(frame, {"AAPL": "AAPL", "MSFT": "MSFT"})

    assert set(payloads) == {"AAPL", "MSFT"}
    assert payloads["AAPL"][0]["Date"] == date(2026, 4, 1)
    assert payloads["MSFT"][1]["Volume"] == 2100


def test_parse_history_payload_extracts_prices_and_actions() -> None:
    payload = [
        {
            "Date": date(2026, 4, 1),
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.5,
            "Adj Close": 99.8,
            "Volume": 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        {
            "Date": date(2026, 4, 2),
            "Open": 101.0,
            "High": 102.0,
            "Low": 100.0,
            "Close": 101.5,
            "Adj Close": 100.7,
            "Volume": 1200,
            "Dividends": 0.25,
            "Stock Splits": 2.0,
        },
    ]

    price_rows, action_rows = parse_history_payload(payload, symbol="AAPL")

    assert len(price_rows) == 2
    assert price_rows[0]["source"] == "yfinance_history"
    assert price_rows[1]["adjusted_close"] is not None
    assert {row["action_type"] for row in action_rows} == {"dividend", "split"}


def test_parse_history_payload_skips_all_null_pre_inception_rows() -> None:
    payload = [
        {
            "Date": date(1993, 1, 29),
            "Open": None,
            "High": None,
            "Low": None,
            "Close": None,
            "Adj Close": None,
            "Volume": None,
            "Dividends": None,
            "Stock Splits": None,
        },
        {
            "Date": date(2020, 6, 1),
            "Open": 100.0,
            "High": 100.1,
            "Low": 99.9,
            "Close": 100.0,
            "Adj Close": 100.0,
            "Volume": 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
    ]

    price_rows, action_rows = parse_history_payload(payload, symbol="SGOV")

    assert len(price_rows) == 1
    assert price_rows[0]["trade_date"] == date(2020, 6, 1)
    assert action_rows == []
