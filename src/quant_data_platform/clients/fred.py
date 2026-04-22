from __future__ import annotations

from decimal import Decimal
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.utils import parse_date

FRED_BASE = "https://api.stlouisfed.org/fred"


class FREDClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.fred_api_key:
            raise ValueError("FRED_API_KEY is required for FRED requests.")
        self.session = requests.Session()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def fetch_series(self, series_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{FRED_BASE}/series/observations",
            params={"series_id": series_id, "api_key": self.settings.fred_api_key, "file_type": "json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def parse_series_observations(payload: dict[str, Any], series_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in payload.get("observations", []):
        value_raw = observation.get("value")
        rows.append(
            {
                "series_id": series_id,
                "observation_date": parse_date(observation.get("date")),
                "realtime_start": parse_date(observation.get("realtime_start")),
                "realtime_end": parse_date(observation.get("realtime_end")),
                "value": None if value_raw in (None, ".", "") else Decimal(value_raw),
            }
        )
    return rows
