from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Iterable

from requests import HTTPError
from tenacity import RetryError

from quant_data_platform.clients.alpha_vantage import (
    AlphaVantageClient,
    parse_listing_status_csv,
    parse_overview,
    sleep_for_rate_limit,
)
from quant_data_platform.clients.fred import FREDClient, parse_series_observations
from quant_data_platform.clients.sec import (
    SECClient,
    parse_company_tickers_exchange,
    parse_companyfacts,
    parse_filings,
    parse_submission_summary,
)
from quant_data_platform.clients.tiingo import (
    TiingoClient,
    parse_batch_daily_prices,
    parse_daily_prices,
    sleep_for_rate_limit as sleep_for_tiingo,
)
from quant_data_platform.clients.yfinance import YFinanceClient, parse_history_payload
from quant_data_platform.config import Settings, get_settings
from quant_data_platform.db import (
    create_universe_build_run,
    fetch_active_fred_series,
    fetch_current_liquidity_ranking,
    fetch_listing_candidates,
    fetch_monthly_liquidity_snapshots,
    fetch_monthly_snapshot_coverage,
    fetch_ranked_universe_symbols,
    fetch_universe_ciks,
    fetch_universe_symbols,
    finalize_universe_build_run,
    get_ingestion_watermark,
    record_artifact,
    replace_universe_members,
    upsert_fred_series,
    upsert_ingestion_watermark,
    upsert_listing_status,
    upsert_overview,
    upsert_sec_companyfacts,
    upsert_sec_filing_metadata,
    upsert_sec_submission,
    upsert_sec_ticker_reference,
    upsert_tiingo_corporate_actions,
    upsert_tiingo_daily_prices,
    upsert_universe_rank_snapshots,
)
from quant_data_platform.object_store import upload_json
from quant_data_platform.storage import postgres_connection
from quant_data_platform.universe import discovery_start_date, is_common_stock_candidate


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
    for symbol in symbols:
        with postgres_connection(settings) as conn:
            try:
                overview_payload = client.fetch_overview(symbol)
                sleep_for_rate_limit(settings.alpha_vantage_throttle_seconds)
                overview_row = parse_overview(overview_payload, as_of_date=date.today())
            except HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    # Rate limit → 즉시 중단 (caller 가 retry handled)
                    raise
                if exc.response is not None and exc.response.status_code == 404:
                    # Symbol 없음 → 스킵
                    stats["overview_skipped"] += 1
                    continue
                raise
            except RetryError:
                # tenacity retry 모두 실패 → 중단
                raise
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
            conn.commit()  # per-symbol commit → 부분 실패 시 롤백 범위 최소화
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


def ingest_yfinance_prices(
    symbols: Iterable[str],
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    batch_size: int | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    client = YFinanceClient(timeout_seconds=settings.yfinance_timeout_seconds)
    ordered_symbols = list(dict.fromkeys(symbols))
    batch_size = batch_size or settings.yfinance_batch_size
    stats = {"price_rows": 0, "action_rows": 0, "request_count": 0, "symbol_count": 0, "empty_symbols": 0}
    history_start = start_date or date(1960, 1, 1)

    with postgres_connection(settings) as conn:
        for batch_index, batch_symbols in enumerate(_chunked(ordered_symbols, batch_size)):
            payloads = client.fetch_history_batch(
                batch_symbols,
                start_date=history_start,
                end_date=end_date,
            )
            stats["request_count"] += 1
            missing_symbols = set(batch_symbols) - set(payloads)
            stats["empty_symbols"] += len(missing_symbols)
            for symbol, payload in payloads.items():
                checksum = upload_json("yfinance-raw", f"history/{symbol}/{date.today().isoformat()}.json", payload, settings)
                record_artifact(
                    conn,
                    {
                        "source": "yfinance",
                        "dataset": "history",
                        "source_key": symbol,
                        "symbol": symbol,
                        "cik": None,
                        "object_key": f"history/{symbol}/{date.today().isoformat()}.json",
                        "payload_sha256": checksum,
                        "available_at": datetime.now(UTC),
                        "metadata": {
                            "batch_index": batch_index,
                            "start_date": history_start.isoformat(),
                            "end_date": end_date.isoformat() if end_date else None,
                        },
                    },
                )
                price_rows, action_rows = parse_history_payload(payload, symbol=symbol)
                upsert_tiingo_daily_prices(conn, price_rows)
                upsert_tiingo_corporate_actions(conn, action_rows)
                stats["price_rows"] += len(price_rows)
                stats["action_rows"] += len(action_rows)
                stats["symbol_count"] += 1
            conn.commit()
    return stats


def ingest_tiingo_prices_batched(
    *,
    symbols: list[str],
    start_date: date,
    end_date: date,
    batch_size: int,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    client = TiingoClient(settings)
    stats = {"price_rows": 0, "action_rows": 0, "request_count": 0, "symbol_count": 0}

    with postgres_connection(settings) as conn:
        for start_idx in range(0, len(symbols), batch_size):
            batch_symbols = symbols[start_idx : start_idx + batch_size]
            batch_stats = _ingest_tiingo_batch(
                conn=conn,
                client=client,
                symbols=batch_symbols,
                start_date=start_date,
                end_date=end_date,
                settings=settings,
                batch_key=f"{start_idx:05d}",
            )
            stats["price_rows"] += batch_stats["price_rows"]
            stats["action_rows"] += batch_stats["action_rows"]
            stats["symbol_count"] += batch_stats["symbol_count"]
            stats["request_count"] += batch_stats["request_count"]
        conn.commit()
    return stats


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _ingest_tiingo_batch(
    *,
    conn,
    client: TiingoClient,
    symbols: list[str],
    start_date: date,
    end_date: date,
    settings: Settings,
    batch_key: str,
) -> dict[str, int]:
    if not symbols:
        return {"price_rows": 0, "action_rows": 0, "symbol_count": 0, "request_count": 0}
    try:
        payload = client.fetch_batch_daily_prices(symbols, start_date=start_date, end_date=end_date)
        sleep_for_tiingo(settings.tiingo_throttle_seconds)
    except (HTTPError, RetryError) as exc:
        http_error = _unwrap_http_error(exc)
        if http_error is not None and http_error.response is not None and http_error.response.status_code == 400 and len(symbols) > 1:
            midpoint = len(symbols) // 2
            left_stats = _ingest_tiingo_batch(
                conn=conn,
                client=client,
                symbols=symbols[:midpoint],
                start_date=start_date,
                end_date=end_date,
                settings=settings,
                batch_key=f"{batch_key}L",
            )
            right_stats = _ingest_tiingo_batch(
                conn=conn,
                client=client,
                symbols=symbols[midpoint:],
                start_date=start_date,
                end_date=end_date,
                settings=settings,
                batch_key=f"{batch_key}R",
            )
            return {
                "price_rows": left_stats["price_rows"] + right_stats["price_rows"],
                "action_rows": left_stats["action_rows"] + right_stats["action_rows"],
                "symbol_count": left_stats["symbol_count"] + right_stats["symbol_count"],
                "request_count": left_stats["request_count"] + right_stats["request_count"],
            }
        if http_error is not None and http_error.response is not None and http_error.response.status_code == 400 and len(symbols) == 1:
            return {"price_rows": 0, "action_rows": 0, "symbol_count": 0, "request_count": 1}
        raise

    checksum = upload_json(
        "tiingo-raw",
        f"batch_daily_prices/{batch_key}_{date.today().isoformat()}.json",
        payload,
        settings,
    )
    record_artifact(
        conn,
        {
            "source": "tiingo",
            "dataset": "batch_daily_prices",
            "source_key": f"batch_{batch_key}",
            "symbol": None,
            "cik": None,
            "object_key": f"batch_daily_prices/{batch_key}_{date.today().isoformat()}.json",
            "payload_sha256": checksum,
            "available_at": datetime.now(UTC),
            "metadata": {
                "symbols": symbols,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        },
    )
    price_rows_total = 0
    action_rows_total = 0
    symbol_count = 0
    for symbol, rows in parse_batch_daily_prices(payload).items():
        price_rows, action_rows = parse_daily_prices(rows, symbol=symbol)
        upsert_tiingo_daily_prices(conn, price_rows)
        upsert_tiingo_corporate_actions(conn, action_rows)
        price_rows_total += len(price_rows)
        action_rows_total += len(action_rows)
        symbol_count += 1
    return {
        "price_rows": price_rows_total,
        "action_rows": action_rows_total,
        "symbol_count": symbol_count,
        "request_count": 1,
    }


def _unwrap_http_error(exc: HTTPError | RetryError) -> HTTPError | None:
    if isinstance(exc, HTTPError):
        return exc
    if isinstance(exc, RetryError) and exc.last_attempt is not None:
        last_exc = exc.last_attempt.exception()
        if isinstance(last_exc, HTTPError):
            return last_exc
    return None


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


def ingest_sec_ticker_reference(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    client = SECClient(settings)
    payload = client.fetch_company_tickers_exchange()
    checksum = upload_json("sec-raw", f"reference/company_tickers_exchange/{date.today().isoformat()}.json", payload, settings)
    rows = parse_company_tickers_exchange(payload)
    with postgres_connection(settings) as conn:
        upsert_sec_ticker_reference(conn, rows)
        record_artifact(
            conn,
            {
                "source": "sec",
                "dataset": "company_tickers_exchange",
                "source_key": "company_tickers_exchange",
                "symbol": None,
                "cik": None,
                "object_key": f"reference/company_tickers_exchange/{date.today().isoformat()}.json",
                "payload_sha256": checksum,
                "available_at": datetime.now(UTC),
                "metadata": {"endpoint": "company_tickers_exchange"},
            },
        )
        conn.commit()
    return {"reference_rows": len(rows)}


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


def build_liquidity_universe(
    *,
    cohort: str | None = None,
    buffer_cohort: str | None = None,
    buffer_size: int | None = None,
    target_size: int | None = None,
    discovery_days: int | None = None,
    lookback_days: int | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort
    buffer_cohort = buffer_cohort or settings.universe_buffer_cohort
    buffer_size = buffer_size or settings.universe_buffer_size
    target_size = target_size or settings.universe_target_size
    discovery_days = discovery_days or settings.liquidity_discovery_days
    lookback_days = lookback_days or settings.liquidity_lookback_days

    listing_rows = ingest_alpha_vantage_listing_status(settings=settings)
    sec_reference = ingest_sec_ticker_reference(settings=settings)
    snapshot_end = date.today()
    recent_start = discovery_start_date(snapshot_end, discovery_days)

    with postgres_connection(settings) as conn:
        build_run_id = create_universe_build_run(
            conn,
            cohort=cohort,
            buffer_cohort=buffer_cohort,
            params={
                "target_cohort": cohort,
                "buffer_cohort": buffer_cohort,
                "buffer_size": buffer_size,
                "target_size": target_size,
                "discovery_days": discovery_days,
                "lookback_days": lookback_days,
            },
        )
        conn.commit()

    try:
        with postgres_connection(settings) as conn:
            candidates = fetch_listing_candidates(conn)
        candidate_symbols = sorted(
            {
                row["symbol"]
                for row in candidates
                if is_common_stock_candidate(
                    symbol=row["symbol"],
                    exchange=row["exchange"],
                    asset_type=row.get("asset_type"),
                    entity_name=row.get("entity_name"),
                )
                and row.get("status", "active") == "active"
            }
        )

        price_stats = ingest_yfinance_prices(
            candidate_symbols,
            start_date=recent_start,
            end_date=snapshot_end,
            batch_size=settings.yfinance_batch_size,
            settings=settings,
        )

        with postgres_connection(settings) as conn:
            ranked_rows = fetch_current_liquidity_ranking(
                conn,
                candidate_symbols,
                lookback_days=lookback_days,
                limit=buffer_size,
            )
            if not ranked_rows:
                raise ValueError("No liquidity-ranked symbols were produced during universe build.")
            buffer_symbols = [row["symbol"] for row in ranked_rows]
            buffer_snapshot_date = ranked_rows[0]["snapshot_date"]
            target_symbols = buffer_symbols[:target_size]
            replace_universe_members(
                conn,
                cohort=buffer_cohort,
                symbols=buffer_symbols,
                effective_date=buffer_snapshot_date,
                source="liquidity_build_buffer",
            )
            upsert_universe_rank_snapshots(
                conn,
                [
                    {
                        "snapshot_date": row["snapshot_date"],
                        "cohort": buffer_cohort,
                        "symbol": row["symbol"],
                        "rank": row["liquidity_rank"],
                        "adv60": row["adv60"],
                        "eligibility_status": "selected_buffer",
                        "source": "liquidity_build_recent_scan",
                    }
                    for row in ranked_rows
                ],
            )
            replace_universe_members(
                conn,
                cohort=cohort,
                symbols=target_symbols,
                effective_date=buffer_snapshot_date,
                source="liquidity_build_current_target",
            )
            upsert_universe_rank_snapshots(
                conn,
                [
                    {
                        "snapshot_date": row["snapshot_date"],
                        "cohort": cohort,
                        "symbol": row["symbol"],
                        "rank": row["liquidity_rank"],
                        "adv60": row["adv60"],
                        "eligibility_status": "selected",
                        "source": "liquidity_build_recent_scan",
                    }
                    for row in ranked_rows[:target_size]
                ],
            )
            conn.commit()
        with postgres_connection(settings) as conn:
            finalize_universe_build_run(
                conn,
                build_run_id=build_run_id,
                status="success",
                candidate_count=len(candidate_symbols),
                buffer_count=len(buffer_symbols),
                target_count=len(target_symbols),
                metadata={
                    "latest_buffer_snapshot_date": buffer_snapshot_date.isoformat(),
                    "recent_scan_start_date": recent_start.isoformat(),
                    "recent_scan_end_date": snapshot_end.isoformat(),
                    "discovery_request_count": price_stats["request_count"],
                    "discovery_source": "yfinance_history",
                },
            )
            conn.commit()
        return {
            "listing_rows": listing_rows,
            **sec_reference,
            "candidate_count": len(candidate_symbols),
            "buffer_count": len(buffer_symbols),
            "target_count": len(target_symbols),
            **price_stats,
        }
    except Exception:
        with postgres_connection(settings) as conn:
            finalize_universe_build_run(conn, build_run_id=build_run_id, status="failed")
            conn.commit()
        raise


def refresh_monthly_universe_snapshots(
    *,
    cohort: str | None = None,
    buffer_cohort: str | None = None,
    target_size: int | None = None,
    lookback_days: int | None = None,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort
    buffer_cohort = buffer_cohort or settings.universe_buffer_cohort
    target_size = target_size or settings.universe_target_size
    lookback_days = lookback_days or settings.liquidity_lookback_days

    with postgres_connection(settings) as conn:
        snapshot_rows = fetch_monthly_liquidity_snapshots(
            conn,
            buffer_cohort=buffer_cohort,
            target_size=target_size,
            lookback_days=lookback_days,
        )
        coverage_rows = fetch_monthly_snapshot_coverage(
            conn,
            buffer_cohort=buffer_cohort,
            target_size=target_size,
            lookback_days=lookback_days,
        )
        distinct_symbols = sorted({row["symbol"] for row in snapshot_rows})
        if not snapshot_rows:
            raise ValueError("No monthly liquidity snapshots were produced.")
        latest_snapshot_date = max(row["snapshot_date"] for row in snapshot_rows)
        latest_symbols = sorted({row["symbol"] for row in snapshot_rows if row["snapshot_date"] == latest_snapshot_date})
        upsert_universe_rank_snapshots(
            conn,
            [
                {
                    "snapshot_date": row["snapshot_date"],
                    "cohort": cohort,
                    "symbol": row["symbol"],
                    "rank": row["liquidity_rank"],
                    "adv60": row["adv60"],
                    "eligibility_status": "selected",
                    "source": "monthly_liquidity_snapshot",
                }
                for row in snapshot_rows
            ],
        )
        replace_universe_members(
            conn,
            cohort=cohort,
            symbols=latest_symbols,
            effective_date=latest_snapshot_date,
            source="monthly_liquidity_snapshot",
        )
        conn.commit()
    return {
        "snapshot_count": len({row["snapshot_date"] for row in snapshot_rows}),
        "snapshot_rows": len(snapshot_rows),
        "distinct_symbols": len(distinct_symbols),
        "current_symbol_count": len(latest_symbols),
        "snapshot_shortfall_months": sum(1 for row in coverage_rows if row["shortfall_count"] > 0),
    }


def run_market_backfill(
    *,
    symbols: list[str] | None = None,
    cohort: str | None = None,
    stage: str | None = None,
    mode: str = "full",
    start_date: date | None = None,
    end_date: date | None = None,
    request_budget: int | None = None,
    reset_cursor: bool = False,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort
    snapshot_as_of = end_date or date.today()
    with postgres_connection(settings) as conn:
        if symbols is None:
            if stage and stage != "full":
                stage_limit = int(stage)
                symbols = fetch_ranked_universe_symbols(conn, cohort, limit=stage_limit) or fetch_universe_symbols(
                    conn,
                    cohort,
                    snapshot_as_of=snapshot_as_of,
                    limit=stage_limit,
                )
            else:
                symbols = fetch_universe_symbols(conn, cohort, snapshot_as_of=snapshot_as_of)
    effective_start = start_date
    if mode == "recent" and effective_start is None:
        effective_start = discovery_start_date(snapshot_as_of, settings.liquidity_discovery_days)
    if mode == "chunked":
        request_budget = request_budget or settings.yfinance_batch_size
        with postgres_connection(settings) as conn:
            ordered_symbols = fetch_ranked_universe_symbols(conn, cohort) or fetch_universe_symbols(conn, cohort, snapshot_as_of=snapshot_as_of)
            resource_name = f"yfinance_history:{cohort}"
            offset = 0 if reset_cursor else int(get_ingestion_watermark(conn, source_name="yfinance", resource_name=resource_name) or "0")
            chunk_symbols = ordered_symbols[offset : offset + request_budget]
        price_stats = ingest_yfinance_prices(chunk_symbols, start_date=effective_start, end_date=end_date, settings=settings)
        next_offset = offset + len(chunk_symbols)
        with postgres_connection(settings) as conn:
            upsert_ingestion_watermark(
                conn,
                source_name="yfinance",
                resource_name=resource_name,
                cursor_value=str(next_offset),
            )
            conn.commit()
        return {
            "symbol_count": len(chunk_symbols),
            "processed_offset_start": offset,
            "processed_offset_end": next_offset,
            "remaining_symbols": max(len(ordered_symbols) - next_offset, 0),
            **price_stats,
        }
    # listing_status: called internally — required for backfill DAGs that do not have a dedicated listing_status task. DAG-level task removed in dag split to avoid duplicate call.
    listing_rows = ingest_alpha_vantage_listing_status(settings=settings)
    if mode == "recent":
        try:
            price_stats = ingest_tiingo_prices_batched(
                symbols=symbols,
                start_date=effective_start,
                end_date=end_date or snapshot_as_of,
                batch_size=settings.tiingo_discovery_batch_size,
                settings=settings,
            )
            price_stats["market_data_fallback"] = 0
        except (HTTPError, RetryError) as exc:
            http_error = _unwrap_http_error(exc)
            if http_error is None or http_error.response is None or http_error.response.status_code != 429:
                raise
            price_stats = ingest_yfinance_prices(
                symbols,
                start_date=effective_start,
                end_date=end_date or snapshot_as_of,
                settings=settings,
            )
            price_stats["market_data_fallback"] = 1
    else:
        price_stats = ingest_yfinance_prices(symbols, start_date=effective_start, end_date=end_date, settings=settings)
    return {"listing_rows": listing_rows, "symbol_count": len(symbols), **price_stats}


def run_fundamental_backfill(
    *,
    ciks: list[str] | None = None,
    cohort: str | None = None,
    mode: str = "full",
    stage: str | None = None,
    as_of_date: date | None = None,
    request_budget: int | None = None,
    reset_cursor: bool = False,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort
    snapshot_as_of = as_of_date or date.today()
    sec_reference = ingest_sec_ticker_reference(settings=settings)
    limit = None if stage in (None, "full") else int(stage)
    with postgres_connection(settings) as conn:
        ordered_ciks = ciks or fetch_universe_ciks(conn, cohort, snapshot_as_of=snapshot_as_of, limit=limit)
        if mode == "chunked":
            request_budget = request_budget or 25
            resource_name = f"sec_companyfacts:{cohort if ciks is None else 'adhoc'}"
            offset = 0 if reset_cursor else int(get_ingestion_watermark(conn, source_name="sec", resource_name=resource_name) or "0")
            chunk_ciks = ordered_ciks[offset : offset + request_budget]
        else:
            resource_name = None
            offset = 0
            chunk_ciks = ordered_ciks
    stats = ingest_sec_ciks(chunk_ciks, settings=settings)
    if mode == "chunked":
        next_offset = offset + len(chunk_ciks)
        with postgres_connection(settings) as conn:
            upsert_ingestion_watermark(
                conn,
                source_name="sec",
                resource_name=resource_name,
                cursor_value=str(next_offset),
            )
            conn.commit()
        return {
            **sec_reference,
            "cik_count": len(chunk_ciks),
            "processed_offset_start": offset,
            "processed_offset_end": next_offset,
            "remaining_ciks": max(len(ordered_ciks) - next_offset, 0),
            **stats,
        }
    return {**sec_reference, "cik_count": len(chunk_ciks), **stats}


def run_daily_incremental(*, cohort: str | None = None, settings: Settings | None = None) -> dict[str, dict[str, int]]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort
    sec_reference = ingest_sec_ticker_reference(settings=settings)
    with postgres_connection(settings) as conn:
        fred_series = fetch_active_fred_series(conn)
    market_stats = run_market_backfill(cohort=cohort, mode="recent", end_date=date.today(), settings=settings)
    snapshot_stats = refresh_monthly_universe_snapshots(cohort=cohort, settings=settings)
    fundamentals_stats = run_fundamental_backfill(
        cohort=cohort,
        mode="chunked",
        as_of_date=date.today(),
        request_budget=settings.sec_daily_request_budget,
        settings=settings,
    )
    return {
        "market": market_stats,
        "snapshots": snapshot_stats,
        "fundamentals": {
            **sec_reference,
            **fundamentals_stats,
        },
        "fred": ingest_fred_series(fred_series, settings=settings),
    }
