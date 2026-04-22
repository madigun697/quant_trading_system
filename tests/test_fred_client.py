from __future__ import annotations

import json

from quant_data_platform.clients.fred import parse_series_observations
from tests.conftest import FIXTURE_DIR


def test_parse_series_observations() -> None:
    payload = json.loads((FIXTURE_DIR / "fred_series.json").read_text())
    rows = parse_series_observations(payload, series_id="DGS3MO")
    assert len(rows) == 2
    assert rows[0]["series_id"] == "DGS3MO"
