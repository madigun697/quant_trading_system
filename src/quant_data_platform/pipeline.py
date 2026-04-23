from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Iterable

from quant_data_platform.clients.alpha_vantage import (
    AlphaVantageClient,
    parse_listing_status_csv,
    parse_overview,
    sleep_for_rate_limit,
)
from quant_data_platform.clients.fred import FREDClient, parse_series_observations
from quant_data_platform.clients.sec import SECClient, parse_companyfacts, parse_filings, parse_submission_summary
from quant_data_platform.clients.tiingo import TiingoClient, parse_daily_prices, sleep_for_rate_limit as sleep_for_tiingo
from quant_data_platform.config import Settings, get_settings
from quant_data_platform.db import (
    fetch_active_fred_series,
    fetch_universe_ciks,
    fetch_universe_symbols,
    record_artifact,
    upsert_fred_series,
    upsert_listing_status,
    upsert_overview,
    upsert_sec_companyfacts,
    upsert_sec_filing_metadata,
    upsert_sec_submission,
    upsert_tiingo_corporate_actions,
    upsert_tiingo_daily_prices,
)
from quant_data_platform.object_store import upload_json
from quant_data_platform.storage import postgres_connection


def ingest_alpha_vantage_listing_status(state: str = "active", settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    client = AlphaVantageClient(settings)
    csv_payload = client.fetch_listing_status(state=state)
    sleep_for_rate_limit(settings.alpha_vantage_throttle_seconds)
    rows = parse_listing_status_csv(csv_payload, source_file_date=date.today(), state=state)
    with postgres_connection(settings) as conn:
        upsert_listing_status(conn, rows)
        conn.commit()
    return len(rows)


def ingest_alpha_vantage_overviews(symbols: Iterable[str], settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    client = AlphaVantageClient(settings)
    stats = {"overview_rows": 0, "overview_skipped": 0}
    with postgres_connection(settings) as conn:
        for symbol in symbols:
            try:
                overview_payload = client.fetch_overview(symbol)
                sleep_for_rate_limit(settings.alpha_vantage_throttle_seconds)
                overview_row = parse_overview(overview_payload, as_of_date=date.today())
            except Exception:
                stats["overview_skipped"] += 1
                continue
            overview_checksum = upload_json("alphavantage-raw", f"overview/{symbol}/{date.today().isoformat()}.json", overview_payload, settings)
            record_artifact(
                conn,
                {
                    "source": "alpha_vantage",
                    "dataset": "overview",
                    "source_key": symbol,
                    "symbol": symbol,
                    "cik": None,
                    "object_key": f"overview/{symbol}/{date.today().isoformat()}.json",
                    "payload_sha256": overview_checksum,
                    "available_at": datetime.now(UTC),
                    "metadata": {"function": "OVERVIEW"},
                },
            )
            upsert_overview(conn, [overview_row])
            stats["overview_rows"] += 1
        conn.commit()
    return stats


def ingest_tiingo_prices(
    symbols: Iterable[str],
    start_date: date | None = None,
    end_date: date | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    client = TiingoClient(settings)
    stats = {"price_rows": 0, "action_rows": 0}
    backfill_start = start_date or date(1960, 1, 1)

    with postgres_connection(settings) as conn:
        for symbol in symbols:
            daily_payload = client.fetch_daily_prices(symbol=symbol, start_date=backfill_start, end_date=end_date)
            sleep_for_tiingo(settings.tiingo_throttle_seconds)
            daily_checksum = upload_json("tiingo-raw", f"daily_prices/{symbol}/{date.today().isoformat()}.json", daily_payload, settings)
            record_artifact(
                conn,
                {
                    "source": "tiingo",
                    "dataset": "daily_prices",
                    "source_key": symbol,
                    "symbol": symbol,
                    "cik": None,
                    "object_key": f"daily_prices/{symbol}/{date.today().isoformat()}.json",
                    "payload_sha256": daily_checksum,
                    "available_at": datetime.now(UTC),
                    "metadata": {"start_date": backfill_start.isoformat(), "end_date": end_date.isoformat() if end_date else None},
                },
            )
            price_rows, action_rows = parse_daily_prices(daily_payload, symbol=symbol)
            upsert_tiingo_daily_prices(conn, price_rows)
            upsert_tiingo_corporate_actions(conn, action_rows)
            stats["price_rows"] += len(price_rows)
            stats["action_rows"] += len(action_rows)
        conn.commit()
    return stats


def ingest_sec_ciks(ciks: Iterable[str], settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    client = SECClient(settings)
    stats = {"filings": 0, "facts": 0}
    with postgres_connection(settings) as conn:
        for cik in ciks:
            submissions = client.fetch_submissions(cik)
            checksum = upload_json("sec-raw", f"submissions/{cik}/{date.today().isoformat()}.json", submissions, settings)
            upsert_sec_submission(conn, parse_submission_summary(submissions))
            filing_rows = parse_filings(submissions)
            upsert_sec_filing_metadata(conn, filing_rows)
            record_artifact(
                conn,
                {
                    "source": "sec",
                    "dataset": "submissions",
                    "source_key": cik,
                    "symbol": (submissions.get("tickers") or [None])[0],
                    "cik": str(submissions["cik"]).zfill(10),
                    "object_key": f"submissions/{cik}/{date.today().isoformat()}.json",
                    "payload_sha256": checksum,
                    "available_at": datetime.now(UTC),
                    "metadata": {"endpoint": "submissions"},
                },
            )

            facts = client.fetch_companyfacts(cik)
            facts_checksum = upload_json("sec-raw", f"companyfacts/{cik}/{date.today().isoformat()}.json", facts, settings)
            record_artifact(
                conn,
                {
                    "source": "sec",
                    "dataset": "companyfacts",
                    "source_key": cik,
                    "symbol": (submissions.get("tickers") or [None])[0],
                    "cik": str(submissions["cik"]).zfill(10),
                    "object_key": f"companyfacts/{cik}/{date.today().isoformat()}.json",
                    "payload_sha256": facts_checksum,
                    "available_at": datetime.now(UTC),
                    "metadata": {"endpoint": "companyfacts"},
                },
            )
            filings_by_accession = {row["accession_number"]: row for row in filing_rows}
            fact_rows = parse_companyfacts(facts, filings_by_accession=filings_by_accession)
            upsert_sec_companyfacts(conn, fact_rows)
            stats["filings"] += len(filing_rows)
            stats["facts"] += len(fact_rows)
        conn.commit()
    return stats


def ingest_fred_series(series_ids: Iterable[str], settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    client = FREDClient(settings)
    stats = {"series": 0, "observations": 0}
    with postgres_connection(settings) as conn:
        for series_id in series_ids:
            payload = client.fetch_series(series_id)
            checksum = upload_json("fred-raw", f"series/{series_id}/{date.today().isoformat()}.json", payload, settings)
            rows = parse_series_observations(payload, series_id=series_id)
            upsert_fred_series(conn, rows)
            record_artifact(
                conn,
                {
                    "source": "fred",
                    "dataset": "series_observations",
                    "source_key": series_id,
                    "symbol": None,
                    "cik": None,
                    "object_key": f"series/{series_id}/{date.today().isoformat()}.json",
                    "payload_sha256": checksum,
                    "available_at": datetime.now(UTC),
                    "metadata": {"series_id": series_id},
                },
            )
            stats["series"] += 1
            stats["observations"] += len(rows)
        conn.commit()
    return stats


def run_market_backfill(symbols: list[str] | None = None, settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    with postgres_connection(settings) as conn:
        symbols = symbols or fetch_universe_symbols(conn, settings.prototype_cohort)
    ingest_alpha_vantage_listing_status(settings=settings)
    overview_stats = ingest_alpha_vantage_overviews(symbols, settings=settings)
    price_stats = ingest_tiingo_prices(symbols, settings=settings)
    return {**overview_stats, **price_stats}


def run_fundamental_backfill(ciks: list[str] | None = None, settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    with postgres_connection(settings) as conn:
        ciks = ciks or fetch_universe_ciks(conn, settings.prototype_cohort)
    return ingest_sec_ciks(ciks, settings=settings)


def run_daily_incremental(settings: Settings | None = None) -> dict[str, dict[str, int]]:
    settings = settings or get_settings()
    with postgres_connection(settings) as conn:
        symbols = fetch_universe_symbols(conn, settings.prototype_cohort)
        ciks = fetch_universe_ciks(conn, settings.prototype_cohort)
        fred_series = fetch_active_fred_series(conn)
    recent_start = date.today().replace(day=1)
    return {
        "market": {
            **ingest_alpha_vantage_overviews(symbols=symbols, settings=settings),
            **ingest_tiingo_prices(symbols=symbols, start_date=recent_start, settings=settings),
        },
        "fundamentals": run_fundamental_backfill(ciks=ciks, settings=settings),
        "fred": ingest_fred_series(fred_series, settings=settings),
    }
