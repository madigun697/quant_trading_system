from __future__ import annotations

import os

import pytest

from quant_data_platform.clients.alpha_vantage import AlphaVantageClient
from quant_data_platform.clients.fred import FREDClient
from quant_data_platform.clients.sec import SECClient
from quant_data_platform.clients.tiingo import TiingoClient
from quant_data_platform.config import get_settings


pytestmark = pytest.mark.integration


def _skip_if_missing(name: str) -> None:
    if not os.getenv(name):
        pytest.skip(f"{name} is not configured")


def test_alpha_vantage_live() -> None:
    _skip_if_missing("ALPHAVANTAGE_API_KEY")
    client = AlphaVantageClient(get_settings())
    payload = client.fetch_overview("IBM")
    assert payload["Symbol"] == "IBM"


def test_sec_live() -> None:
    _skip_if_missing("SEC_USER_AGENT")
    client = SECClient(get_settings())
    payload = client.fetch_submissions("51143")
    assert str(payload["cik"]).zfill(10) == "0000051143"


def test_fred_live() -> None:
    _skip_if_missing("FRED_API_KEY")
    client = FREDClient(get_settings())
    payload = client.fetch_series("DGS3MO")
    assert "observations" in payload


def test_tiingo_live() -> None:
    _skip_if_missing("TIINGO_API_KEY")
    client = TiingoClient(get_settings())
    payload = client.fetch_daily_prices("IBM")
    assert isinstance(payload, list)
