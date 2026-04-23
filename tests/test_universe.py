from __future__ import annotations

from datetime import date

from quant_data_platform.universe import discovery_start_date, is_common_stock_candidate


def test_common_stock_candidate_accepts_class_shares() -> None:
    assert is_common_stock_candidate(
        symbol="BRK.B",
        exchange="NYSE",
        asset_type="Stock",
        entity_name="Berkshire Hathaway Inc. Class B",
    )


def test_common_stock_candidate_rejects_etfs_and_units() -> None:
    assert not is_common_stock_candidate(
        symbol="SPY",
        exchange="NYSE ARCA",
        asset_type="ETF",
        entity_name="SPDR S&P 500 ETF Trust",
    )
    assert not is_common_stock_candidate(
        symbol="XYZ-U",
        exchange="NYSE",
        asset_type="Stock",
        entity_name="XYZ Acquisition Corp Unit",
    )


def test_common_stock_candidate_rejects_invalid_batch_symbols() -> None:
    assert not is_common_stock_candidate(
        symbol="-P-HIZ",
        exchange="NASDAQ",
        asset_type="Stock",
        entity_name="Invalid Symbol Placeholder",
    )
    assert not is_common_stock_candidate(
        symbol="AEGN:BAT",
        exchange="NASDAQ",
        asset_type="Stock",
        entity_name="Venue Specific Symbol",
    )
    assert not is_common_stock_candidate(
        symbol="ACR-P-C",
        exchange="NYSE",
        asset_type="Stock",
        entity_name="ACR Preferred C",
    )
    assert is_common_stock_candidate(
        symbol="BF-B",
        exchange="NYSE",
        asset_type="Stock",
        entity_name="Brown-Forman Corp Class B",
    )


def test_discovery_start_date_expands_calendar_window() -> None:
    assert discovery_start_date(date(2026, 4, 22), 90) == date(2025, 10, 24)
