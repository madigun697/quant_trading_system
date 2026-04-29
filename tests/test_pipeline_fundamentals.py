from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import requests
from requests import HTTPError

from quant_data_platform.config import Settings
from quant_data_platform.pipeline import (
    ingest_sec_ciks,
    refresh_monthly_universe_snapshots,
    run_daily_incremental,
    run_fundamental_backfill,
    run_market_backfill,
)


class _DummyConn:
    def commit(self) -> None:
        return None


@contextmanager
def _fake_postgres_connection(_settings):
    yield _DummyConn()


def test_run_fundamental_backfill_chunked_uses_watermark(monkeypatch) -> None:
    watermark_updates: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_universe_ciks",
        lambda conn, cohort, snapshot_as_of=None, limit=None: ["0001", "0002", "0003", "0004"],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.get_ingestion_watermark",
        lambda conn, source_name, resource_name: "2",
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.upsert_ingestion_watermark",
        lambda conn, source_name, resource_name, cursor_value: watermark_updates.append(
            (source_name, resource_name, cursor_value)
        ),
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_sec_ciks",
        lambda ciks, settings=None: {"filings": len(list(ciks)), "facts": len(list(ciks)) * 2},
    )

    result = run_fundamental_backfill(
        cohort="us_liquidity_700_v1",
        mode="chunked",
        request_budget=2,
        as_of_date=date(2026, 4, 23),
    )

    assert result["reference_rows"] == 10
    assert result["cik_count"] == 2
    assert result["processed_offset_start"] == 2
    assert result["processed_offset_end"] == 4
    assert result["remaining_ciks"] == 0
    assert result["filings"] == 2
    assert result["facts"] == 4
    assert watermark_updates == [("sec", "sec_companyfacts:us_liquidity_700_v1", "4")]


def test_run_fundamental_backfill_full_uses_all_ciks(monkeypatch) -> None:
    captured: list[str] = []

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_universe_ciks",
        lambda conn, cohort, snapshot_as_of=None, limit=None: ["0001", "0002", "0003"],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_sec_ciks",
        lambda ciks, settings=None: captured.extend(ciks) or {"filings": len(captured), "facts": len(captured) * 3},
    )

    result = run_fundamental_backfill(cohort="us_liquidity_700_v1", as_of_date=date(2026, 4, 23))

    assert captured == ["0001", "0002", "0003"]
    assert result["reference_rows"] == 10
    assert result["cik_count"] == 3
    assert result["filings"] == 3
    assert result["facts"] == 9


def test_run_fundamental_backfill_full_universe_filters_common_stock_ciks(monkeypatch) -> None:
    captured: list[str] = []

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_listing_candidates",
        lambda conn: [
            {"symbol": "AAPL", "exchange": "NASDAQ", "asset_type": "Stock", "entity_name": "Apple Inc.", "cik": "0000320193"},
            {"symbol": "SPY", "exchange": "NYSE ARCA", "asset_type": "ETF", "entity_name": "SPDR S&P 500 ETF Trust", "cik": "0000884394"},
            {"symbol": "MSFT", "exchange": "NASDAQ", "asset_type": "Stock", "entity_name": "Microsoft Corp.", "cik": "0000789019"},
        ],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_sec_ciks",
        lambda ciks, settings=None: captured.extend(ciks) or {"filings": len(captured), "facts": len(captured) * 3},
    )

    result = run_fundamental_backfill(full_universe=True, as_of_date=date(2026, 4, 23))

    assert captured == ["0000320193", "0000789019"]
    assert result["full_universe"] == 1
    assert result["cik_count"] == 2


def test_ingest_sec_ciks_skips_companyfacts_404(monkeypatch) -> None:
    class _FakeSECClient:
        def __init__(self, settings=None):
            return None

        def fetch_submissions(self, cik: str):
            return {"cik": cik, "tickers": ["AAPL"], "filings": {"recent": {"accessionNumber": [], "form": [], "filingDate": [], "acceptanceDateTime": [], "reportDate": [], "primaryDocument": [], "isXBRL": []}}}

        def fetch_companyfacts(self, cik: str):
            response = requests.Response()
            response.status_code = 404
            raise HTTPError("not found", response=response)

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.SECClient", _FakeSECClient)
    monkeypatch.setattr("quant_data_platform.pipeline.upload_json", lambda *args, **kwargs: "checksum")
    monkeypatch.setattr("quant_data_platform.pipeline.upsert_sec_submission", lambda conn, row: None)
    monkeypatch.setattr("quant_data_platform.pipeline.upsert_sec_filing_metadata", lambda conn, rows: None)
    monkeypatch.setattr("quant_data_platform.pipeline.record_artifact", lambda conn, row: None)
    monkeypatch.setattr("quant_data_platform.pipeline.upsert_sec_companyfacts", lambda conn, rows: None)

    result = ingest_sec_ciks(["0000320193"])

    assert result["facts_skipped"] == 1
    assert result["facts"] == 0


def test_run_daily_incremental_uses_chunked_sec_budget(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_sec_ticker_reference", lambda settings=None: {"reference_rows": 10})
    monkeypatch.setattr("quant_data_platform.pipeline.fetch_active_fred_series", lambda conn: ["DGS3MO"])
    monkeypatch.setattr(
        "quant_data_platform.pipeline.run_market_backfill",
        lambda cohort=None, mode=None, end_date=None, settings=None: {"price_rows": 100},
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.refresh_monthly_universe_snapshots",
        lambda cohort=None, settings=None: {"snapshot_rows": 700},
    )

    def _fake_run_fundamental_backfill(**kwargs):
        calls.update(kwargs)
        return {"cik_count": 50, "processed_offset_end": 50, "remaining_ciks": 645, "filings": 123, "facts": 456}

    monkeypatch.setattr("quant_data_platform.pipeline.run_fundamental_backfill", _fake_run_fundamental_backfill)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_fred_series", lambda series, settings=None: {"rows": len(series)})

    settings = Settings(SEC_DAILY_REQUEST_BUDGET=50)
    result = run_daily_incremental(cohort="us_liquidity_700_v1", settings=settings)

    assert calls["cohort"] == "us_liquidity_700_v1"
    assert calls["mode"] == "chunked"
    assert calls["request_budget"] == 50
    assert result["fundamentals"]["cik_count"] == 50
    assert result["market"]["price_rows"] == 100
    assert result["snapshots"]["snapshot_rows"] == 700


def test_run_market_backfill_recent_uses_batched_tiingo(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.fetch_universe_symbols", lambda conn, cohort, snapshot_as_of=None, limit=None: ["AAPL", "MSFT", "NVDA"])
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_alpha_vantage_listing_status", lambda settings=None: 123)

    def _fake_ingest_tiingo_prices_batched(**kwargs):
        calls.update(kwargs)
        return {"price_rows": 30, "action_rows": 3, "request_count": 1, "symbol_count": 3}

    monkeypatch.setattr("quant_data_platform.pipeline.ingest_tiingo_prices_batched", _fake_ingest_tiingo_prices_batched)

    settings = Settings(TIINGO_DISCOVERY_BATCH_SIZE=200)
    result = run_market_backfill(
        cohort="us_liquidity_700_v1",
        mode="recent",
        end_date=date(2026, 4, 23),
        settings=settings,
    )

    assert calls["symbols"] == ["AAPL", "MSFT", "NVDA", "SPY"]
    assert calls["batch_size"] == 200
    assert result["listing_rows"] == 123
    assert result["price_rows"] == 30
    assert result["symbol_count"] == 4


def test_run_market_backfill_recent_falls_back_to_yfinance_on_tiingo_429(monkeypatch) -> None:
    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.fetch_universe_symbols", lambda conn, cohort, snapshot_as_of=None, limit=None: ["AAPL", "MSFT"])
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_alpha_vantage_listing_status", lambda settings=None: 123)

    response = requests.Response()
    response.status_code = 429
    http_error = requests.HTTPError("rate limit", response=response)
    def _raise_retry_error(**kwargs):
        raise http_error

    monkeypatch.setattr("quant_data_platform.pipeline.ingest_tiingo_prices_batched", _raise_retry_error)
    monkeypatch.setattr(
        "quant_data_platform.pipeline.ingest_yfinance_prices",
        lambda symbols, start_date=None, end_date=None, settings=None: {
            "price_rows": 20,
            "action_rows": 2,
            "request_count": 1,
            "symbol_count": len(list(symbols)),
            "empty_symbols": 0,
        },
    )

    settings = Settings(TIINGO_DISCOVERY_BATCH_SIZE=200)
    result = run_market_backfill(
        cohort="us_liquidity_700_v1",
        mode="recent",
        end_date=date(2026, 4, 23),
        settings=settings,
    )

    assert result["listing_rows"] == 123
    assert result["price_rows"] == 20
    assert result["market_data_fallback"] == 1


def test_run_market_backfill_full_universe_filters_common_stock_symbols(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_listing_candidates",
        lambda conn: [
            {"symbol": "AAPL", "exchange": "NASDAQ", "asset_type": "Stock", "entity_name": "Apple Inc."},
            {"symbol": "SPY", "exchange": "NYSE ARCA", "asset_type": "ETF", "entity_name": "SPDR S&P 500 ETF Trust"},
            {"symbol": "MSFT", "exchange": "NASDAQ", "asset_type": "Stock", "entity_name": "Microsoft Corp."},
        ],
    )
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_alpha_vantage_listing_status", lambda settings=None: 123)

    def _fake_ingest_tiingo_prices_batched(**kwargs):
        calls.update(kwargs)
        return {"price_rows": 20, "action_rows": 2, "request_count": 1, "symbol_count": len(kwargs["symbols"])}

    monkeypatch.setattr("quant_data_platform.pipeline.ingest_tiingo_prices_batched", _fake_ingest_tiingo_prices_batched)

    result = run_market_backfill(
        full_universe=True,
        mode="recent",
        end_date=date(2026, 4, 23),
        settings=Settings(TIINGO_DISCOVERY_BATCH_SIZE=200),
    )

    assert calls["symbols"] == ["AAPL", "MSFT", "SPY"]
    assert result["full_universe"] == 1
    assert result["symbol_count"] == 3


def test_run_market_backfill_dedupes_explicit_symbols_with_benchmarks(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr("quant_data_platform.pipeline.ingest_alpha_vantage_listing_status", lambda settings=None: 123)

    def _fake_ingest_yfinance_prices(symbols, start_date=None, end_date=None, settings=None):
        calls["symbols"] = list(symbols)
        return {"price_rows": 20, "action_rows": 2, "request_count": 1, "symbol_count": len(list(symbols)), "empty_symbols": 0}

    monkeypatch.setattr("quant_data_platform.pipeline.ingest_yfinance_prices", _fake_ingest_yfinance_prices)

    result = run_market_backfill(
        symbols=["spy", "AAPL", "SPY"],
        mode="full",
        end_date=date(2026, 4, 23),
        settings=Settings(BENCHMARK_MARKET_SYMBOLS="SPY,QQQ"),
    )

    assert calls["symbols"] == ["SPY", "AAPL", "QQQ"]
    assert result["symbol_count"] == 3


def test_refresh_monthly_universe_snapshots_replaces_active_members_with_latest_snapshot(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr("quant_data_platform.pipeline.postgres_connection", _fake_postgres_connection)
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_monthly_liquidity_snapshots",
        lambda conn, buffer_cohort, target_size, lookback_days: [
            {"snapshot_date": date(2026, 3, 31), "symbol": "AAPL", "liquidity_rank": 1, "adv60": 100},
            {"snapshot_date": date(2026, 3, 31), "symbol": "MSFT", "liquidity_rank": 2, "adv60": 90},
            {"snapshot_date": date(2026, 4, 30), "symbol": "AAPL", "liquidity_rank": 1, "adv60": 110},
            {"snapshot_date": date(2026, 4, 30), "symbol": "NVDA", "liquidity_rank": 2, "adv60": 95},
        ],
    )
    monkeypatch.setattr(
        "quant_data_platform.pipeline.fetch_monthly_snapshot_coverage",
        lambda conn, buffer_cohort, target_size, lookback_days: [
            {"snapshot_date": date(2026, 3, 31), "shortfall_count": 0},
            {"snapshot_date": date(2026, 4, 30), "shortfall_count": 0},
        ],
    )
    monkeypatch.setattr("quant_data_platform.pipeline.upsert_universe_rank_snapshots", lambda conn, rows: None)

    def _capture_replace(conn, cohort, symbols, effective_date, source):
        captured["cohort"] = cohort
        captured["symbols"] = symbols
        captured["effective_date"] = effective_date
        captured["source"] = source

    monkeypatch.setattr("quant_data_platform.pipeline.replace_universe_members", _capture_replace)

    result = refresh_monthly_universe_snapshots(cohort="us_liquidity_700_v1")

    assert captured["cohort"] == "us_liquidity_700_v1"
    assert captured["symbols"] == ["AAPL", "NVDA"]
    assert captured["effective_date"] == date(2026, 4, 30)
    assert result["snapshot_count"] == 2
    assert result["distinct_symbols"] == 3
    assert result["current_symbol_count"] == 2
