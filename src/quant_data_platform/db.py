from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from psycopg import Connection
from psycopg.types.json import Jsonb


def fetch_universe_symbols(
    conn: Connection,
    cohort: str,
    *,
    snapshot_as_of: date | None = None,
    limit: int | None = None,
) -> list[str]:
    with conn.cursor() as cur:
        if snapshot_as_of is not None:
            cur.execute(
                """
                with latest_snapshot as (
                    select max(snapshot_date) as snapshot_date
                    from meta.universe_rank_snapshots
                    where cohort = %(cohort)s
                      and snapshot_date <= %(snapshot_as_of)s
                )
                select symbol
                from meta.universe_rank_snapshots
                where cohort = %(cohort)s
                  and snapshot_date = (select snapshot_date from latest_snapshot)
                  and eligibility_status in ('selected', 'selected_buffer')
                order by rank, symbol
                limit coalesce(%(limit)s, 2147483647)
                """,
                {"cohort": cohort, "snapshot_as_of": snapshot_as_of, "limit": limit},
            )
            rows = [row["symbol"] for row in cur.fetchall()]
            if rows:
                return rows
        cur.execute(
            """
            select distinct symbol
            from meta.universe_members
            where cohort = %s
              and is_active = true
            order by symbol
            limit coalesce(%s, 2147483647)
            """,
            (cohort, limit),
        )
        return [row["symbol"] for row in cur.fetchall()]


def fetch_universe_ciks(
    conn: Connection,
    cohort: str,
    *,
    snapshot_as_of: date | None = None,
    limit: int | None = None,
) -> list[str]:
    symbols = fetch_universe_symbols(conn, cohort, snapshot_as_of=snapshot_as_of, limit=limit)
    if not symbols:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            with latest_overview as (
                select symbol, cik, asset_type,
                    row_number() over (partition by symbol order by as_of_date desc, ingested_at desc) as rn
                from raw.alpha_vantage_overview
            ),
            latest_sec_reference as (
                select symbol_alias, cik, entity_name,
                    row_number() over (partition by symbol_alias order by as_of_date desc, fetched_at desc) as rn
                from raw.sec_ticker_reference
            )
            select distinct coalesce(o.cik, r.cik) as cik
            from unnest(%s::text[]) as u(symbol)
            left join latest_overview o
              on o.symbol = u.symbol
             and o.rn = 1
            left join latest_sec_reference r
              on r.symbol_alias = u.symbol
             and r.rn = 1
            where coalesce(o.cik, r.cik) is not null
              and coalesce(o.asset_type, '') <> 'ETF'
              and coalesce(r.entity_name, '') not ilike '%%ETF%%'
              and coalesce(r.entity_name, '') not ilike '%%TRUST%%'
              and coalesce(r.entity_name, '') not ilike '%%FUND%%'
            order by coalesce(o.cik, r.cik)
            """,
            (symbols,),
        )
        return [row["cik"] for row in cur.fetchall()]


def fetch_listing_candidates(conn: Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            with latest_status as (
                select symbol, name, exchange, asset_type, status, ipo_date, delisting_date,
                    row_number() over (partition by symbol order by source_file_date desc, ingested_at desc) as rn
                from raw.alpha_vantage_listing_status
            ),
            latest_sec_reference as (
                select symbol_alias, source_ticker, cik, entity_name, exchange,
                    row_number() over (partition by symbol_alias order by as_of_date desc, fetched_at desc) as rn
                from raw.sec_ticker_reference
            )
            select
                coalesce(s.symbol, r.symbol_alias) as symbol,
                coalesce(s.name, r.entity_name) as entity_name,
                coalesce(s.exchange, r.exchange) as exchange,
                s.asset_type,
                s.status,
                s.ipo_date,
                s.delisting_date,
                r.cik
            from latest_status s
            full outer join latest_sec_reference r
                on s.symbol = r.symbol_alias
               and r.rn = 1
            where coalesce(s.rn, 1) = 1
            """
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_ranked_universe_symbols(conn: Connection, cohort: str, *, limit: int | None = None) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            with latest_snapshot as (
                select max(snapshot_date) as snapshot_date
                from meta.universe_rank_snapshots
                where cohort = %s
            )
            select symbol
            from meta.universe_rank_snapshots
            where cohort = %s
              and snapshot_date = (select snapshot_date from latest_snapshot)
              and eligibility_status in ('selected', 'selected_buffer')
            order by rank, symbol
            limit coalesce(%s, 2147483647)
            """,
            (cohort, cohort, limit),
        )
        return [row["symbol"] for row in cur.fetchall()]


def fetch_current_liquidity_ranking(
    conn: Connection,
    symbols: list[str],
    *,
    lookback_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            with candidate_symbols as (
                select unnest(%(symbols)s::text[]) as symbol
            ),
            preferred_prices as (
                select
                    p.*,
                    row_number() over (
                        partition by p.symbol, p.trade_date
                        order by
                            case
                                when p.source = 'tiingo' then 1
                                when p.source = 'yfinance_history' then 2
                                else 99
                            end,
                            p.ingested_at desc
                    ) as source_rank
                from raw.market_daily_prices p
                join candidate_symbols c using (symbol)
            ),
            price_base as (
                select
                    p.symbol,
                    p.trade_date,
                    coalesce(p.adjusted_close, p.close) * coalesce(p.adjusted_volume, p.volume) as dollar_volume
                from preferred_prices p
                where p.source_rank = 1
            ),
            scored as (
                select
                    symbol,
                    trade_date,
                    avg(dollar_volume) over (
                        partition by symbol
                        order by trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as adv60,
                    count(*) over (
                        partition by symbol
                        order by trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as observations,
                    row_number() over (partition by symbol order by trade_date desc) as latest_rank
                from price_base
            ),
            latest_scores as (
                select symbol, trade_date as snapshot_date, adv60, observations
                from scored
                where latest_rank = 1
                  and observations >= %(lookback_days)s
                  and adv60 is not null
            ),
            ranked as (
                select
                    snapshot_date,
                    symbol,
                    adv60,
                    observations,
                    row_number() over (order by adv60 desc nulls last, symbol) as liquidity_rank
                from latest_scores
            )
            select
                snapshot_date,
                symbol,
                adv60,
                observations,
                liquidity_rank
            from ranked
            where liquidity_rank <= %(limit)s
            order by liquidity_rank
            """,
            {
                "symbols": symbols,
                "lookback_days": lookback_days,
                "lookback_window": lookback_days - 1,
                "limit": limit,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_monthly_liquidity_snapshots(
    conn: Connection,
    *,
    buffer_cohort: str,
    target_size: int,
    lookback_days: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            with buffer_symbols as (
                select distinct symbol
                from meta.universe_members
                where cohort = %(buffer_cohort)s
                  and is_active = true
            ),
            preferred_prices as (
                select
                    p.*,
                    row_number() over (
                        partition by p.symbol, p.trade_date
                        order by
                            case
                                when p.source = 'tiingo' then 1
                                when p.source = 'yfinance_history' then 2
                                else 99
                            end,
                            p.ingested_at desc
                    ) as source_rank
                from raw.market_daily_prices p
                join buffer_symbols b using (symbol)
            ),
            scored as (
                select
                    p.symbol,
                    p.trade_date,
                    avg(coalesce(p.adjusted_close, p.close) * coalesce(p.adjusted_volume, p.volume)) over (
                        partition by p.symbol
                        order by p.trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as adv60,
                    count(*) over (
                        partition by p.symbol
                        order by p.trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as observations,
                    row_number() over (
                        partition by p.symbol, date_trunc('month', p.trade_date)
                        order by p.trade_date desc
                    ) as month_end_rank
                from preferred_prices p
                where p.source_rank = 1
            ),
            eligible_month_ends as (
                select
                    trade_date as snapshot_date,
                    symbol,
                    adv60,
                    observations
                from scored
                where month_end_rank = 1
                  and observations >= %(lookback_days)s
                  and adv60 is not null
            ),
            ranked as (
                select
                    snapshot_date,
                    symbol,
                    adv60,
                    observations,
                    row_number() over (
                        partition by snapshot_date
                        order by adv60 desc nulls last, symbol
                    ) as liquidity_rank
                from eligible_month_ends
            )
            select
                snapshot_date,
                symbol,
                adv60,
                observations,
                liquidity_rank
            from ranked
            where liquidity_rank <= %(target_size)s
            order by snapshot_date, liquidity_rank
            """,
            {
                "buffer_cohort": buffer_cohort,
                "target_size": target_size,
                "lookback_days": lookback_days,
                "lookback_window": lookback_days - 1,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_monthly_snapshot_coverage(
    conn: Connection,
    *,
    buffer_cohort: str,
    target_size: int,
    lookback_days: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            with buffer_symbols as (
                select distinct symbol
                from meta.universe_members
                where cohort = %(buffer_cohort)s
                  and is_active = true
            ),
            preferred_prices as (
                select
                    p.*,
                    row_number() over (
                        partition by p.symbol, p.trade_date
                        order by
                            case
                                when p.source = 'tiingo' then 1
                                when p.source = 'yfinance_history' then 2
                                else 99
                            end,
                            p.ingested_at desc
                    ) as source_rank
                from raw.market_daily_prices p
                join buffer_symbols b using (symbol)
            ),
            scored as (
                select
                    p.symbol,
                    p.trade_date,
                    avg(coalesce(p.adjusted_close, p.close) * coalesce(p.adjusted_volume, p.volume)) over (
                        partition by p.symbol
                        order by p.trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as adv60,
                    count(*) over (
                        partition by p.symbol
                        order by p.trade_date
                        rows between %(lookback_window)s preceding and current row
                    ) as observations,
                    row_number() over (
                        partition by p.symbol, date_trunc('month', p.trade_date)
                        order by p.trade_date desc
                    ) as month_end_rank
                from preferred_prices p
                where p.source_rank = 1
            )
            select
                trade_date as snapshot_date,
                count(*) filter (where observations >= %(lookback_days)s and adv60 is not null) as eligible_symbols,
                greatest(
                    %(target_size)s - count(*) filter (where observations >= %(lookback_days)s and adv60 is not null),
                    0
                ) as shortfall_count
            from scored
            where month_end_rank = 1
            group by trade_date
            order by trade_date
            """,
            {
                "buffer_cohort": buffer_cohort,
                "target_size": target_size,
                "lookback_days": lookback_days,
                "lookback_window": lookback_days - 1,
            },
        )
        return [dict(row) for row in cur.fetchall()]


def replace_universe_members(
    conn: Connection,
    *,
    cohort: str,
    symbols: list[str],
    effective_date: date,
    source: str,
) -> None:
    with conn.cursor() as cur:
        if symbols:
            cur.execute(
                """
                update meta.universe_members
                set is_active = false
                where cohort = %s
                  and is_active = true
                  and not (symbol = any(%s::text[]))
                """,
                (cohort, symbols),
            )
        else:
            cur.execute(
                """
                update meta.universe_members
                set is_active = false
                where cohort = %s
                  and is_active = true
                """,
                (cohort,),
            )
    _executemany(
        conn,
        """
        insert into meta.universe_members (
            symbol, cohort, is_active, effective_date, source
        ) values (
            %(symbol)s, %(cohort)s, true, %(effective_date)s, %(source)s
        )
        on conflict (symbol, cohort, effective_date) do update set
            is_active = excluded.is_active,
            source = excluded.source
        """,
        [
            {
                "symbol": symbol,
                "cohort": cohort,
                "effective_date": effective_date,
                "source": source,
            }
            for symbol in symbols
        ],
    )


def upsert_universe_rank_snapshots(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into meta.universe_rank_snapshots (
            snapshot_date, cohort, symbol, rank, adv60, eligibility_status, source
        ) values (
            %(snapshot_date)s, %(cohort)s, %(symbol)s, %(rank)s, %(adv60)s, %(eligibility_status)s, %(source)s
        )
        on conflict (snapshot_date, cohort, symbol) do update set
            rank = excluded.rank,
            adv60 = excluded.adv60,
            eligibility_status = excluded.eligibility_status,
            source = excluded.source,
            updated_at = now()
    """
    _executemany(conn, sql, rows)


def create_universe_build_run(
    conn: Connection,
    *,
    cohort: str,
    buffer_cohort: str,
    params: dict[str, Any],
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.universe_build_runs (
                cohort, buffer_cohort, status, params
            ) values (
                %(cohort)s, %(buffer_cohort)s, 'running', %(params)s
            )
            returning build_run_id
            """,
            {
                "cohort": cohort,
                "buffer_cohort": buffer_cohort,
                "params": Jsonb(params),
            },
        )
        return cur.fetchone()["build_run_id"]


def finalize_universe_build_run(
    conn: Connection,
    *,
    build_run_id: int,
    status: str,
    candidate_count: int | None = None,
    buffer_count: int | None = None,
    target_count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update meta.universe_build_runs
            set status = %s,
                completed_at = now(),
                candidate_count = coalesce(%s, candidate_count),
                buffer_count = coalesce(%s, buffer_count),
                target_count = coalesce(%s, target_count),
                metadata = coalesce(%s, metadata),
                updated_at = now()
            where build_run_id = %s
            """,
            (
                status,
                candidate_count,
                buffer_count,
                target_count,
                Jsonb(metadata) if metadata is not None else None,
                build_run_id,
            ),
        )


def upsert_listing_status(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.alpha_vantage_listing_status (
            symbol, name, exchange, asset_type, ipo_date, delisting_date, status, source_file_date
        ) values (
            %(symbol)s, %(name)s, %(exchange)s, %(asset_type)s, %(ipo_date)s, %(delisting_date)s, %(status)s, %(source_file_date)s
        )
        on conflict (symbol, source_file_date) do update set
            name = excluded.name,
            exchange = excluded.exchange,
            asset_type = excluded.asset_type,
            ipo_date = excluded.ipo_date,
            delisting_date = excluded.delisting_date,
            status = excluded.status,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_overview(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    rows = [_with_jsonb(row, "overview_json") for row in rows]
    sql = """
        insert into raw.alpha_vantage_overview (
            symbol, as_of_date, cik, name, exchange, sector, industry, asset_type, market_cap, shares_outstanding, overview_json
        ) values (
            %(symbol)s, %(as_of_date)s, %(cik)s, %(name)s, %(exchange)s, %(sector)s, %(industry)s, %(asset_type)s,
            %(market_cap)s, %(shares_outstanding)s, %(overview_json)s
        )
        on conflict (symbol, as_of_date) do update set
            cik = excluded.cik,
            name = excluded.name,
            exchange = excluded.exchange,
            sector = excluded.sector,
            industry = excluded.industry,
            asset_type = excluded.asset_type,
            market_cap = excluded.market_cap,
            shares_outstanding = excluded.shares_outstanding,
            overview_json = excluded.overview_json,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_daily_prices(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.alpha_vantage_daily_prices (
            symbol, trade_date, open, high, low, close, adjusted_close, volume, dividend_amount, split_coefficient
        ) values (
            %(symbol)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(adjusted_close)s, %(volume)s, %(dividend_amount)s, %(split_coefficient)s
        )
        on conflict (symbol, trade_date) do update set
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            adjusted_close = excluded.adjusted_close,
            volume = excluded.volume,
            dividend_amount = excluded.dividend_amount,
            split_coefficient = excluded.split_coefficient,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_corporate_actions(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.alpha_vantage_corporate_actions (
            symbol, trade_date, action_type, action_value
        ) values (
            %(symbol)s, %(trade_date)s, %(action_type)s, %(action_value)s
        )
        on conflict (symbol, trade_date, action_type) do update set
            action_value = excluded.action_value,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_tiingo_daily_prices(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    upsert_market_daily_prices(conn, rows)


def upsert_tiingo_corporate_actions(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    upsert_market_corporate_actions(conn, rows)


def upsert_market_daily_prices(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.market_daily_prices (
            symbol, trade_date, open, high, low, close, adjusted_open, adjusted_high, adjusted_low,
            adjusted_close, volume, adjusted_volume, dividend_amount, split_coefficient, source
        ) values (
            %(symbol)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(adjusted_open)s, %(adjusted_high)s, %(adjusted_low)s,
            %(adjusted_close)s, %(volume)s, %(adjusted_volume)s, %(dividend_amount)s, %(split_coefficient)s, %(source)s
        )
        on conflict (symbol, trade_date, source) do update set
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            adjusted_open = excluded.adjusted_open,
            adjusted_high = excluded.adjusted_high,
            adjusted_low = excluded.adjusted_low,
            adjusted_close = excluded.adjusted_close,
            volume = excluded.volume,
            adjusted_volume = excluded.adjusted_volume,
            dividend_amount = excluded.dividend_amount,
            split_coefficient = excluded.split_coefficient,
            source = excluded.source,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_market_corporate_actions(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.market_corporate_actions (
            symbol, trade_date, action_type, action_value, source
        ) values (
            %(symbol)s, %(trade_date)s, %(action_type)s, %(action_value)s, %(source)s
        )
        on conflict (symbol, trade_date, action_type, source) do update set
            action_value = excluded.action_value,
            source = excluded.source,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_sec_submission(conn: Connection, row: dict[str, Any]) -> None:
    row = _with_jsonb(row, "submission_json")
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into raw.sec_submissions (
                cik, entity_name, primary_ticker, tickers, exchanges, sic, sic_description, submission_json
            ) values (
                %(cik)s, %(entity_name)s, %(primary_ticker)s, %(tickers)s, %(exchanges)s, %(sic)s, %(sic_description)s, %(submission_json)s
            )
            on conflict (cik) do update set
                entity_name = excluded.entity_name,
                primary_ticker = excluded.primary_ticker,
                tickers = excluded.tickers,
                exchanges = excluded.exchanges,
                sic = excluded.sic,
                sic_description = excluded.sic_description,
                submission_json = excluded.submission_json,
                fetched_at = now()
            """,
            row,
        )


def upsert_sec_ticker_reference(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.sec_ticker_reference (
            symbol_alias, source_ticker, cik, entity_name, exchange, as_of_date
        ) values (
            %(symbol_alias)s, %(source_ticker)s, %(cik)s, %(entity_name)s, %(exchange)s, %(as_of_date)s
        )
        on conflict (symbol_alias, as_of_date) do update set
            source_ticker = excluded.source_ticker,
            cik = excluded.cik,
            entity_name = excluded.entity_name,
            exchange = excluded.exchange,
            fetched_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_sec_filing_metadata(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.sec_filing_metadata (
            cik, accession_number, form, filing_date, accepted_at, period_end, fiscal_year, fiscal_period,
            primary_document, filing_href, is_xbrl, available_at
        ) values (
            %(cik)s, %(accession_number)s, %(form)s, %(filing_date)s, %(accepted_at)s, %(period_end)s, %(fiscal_year)s, %(fiscal_period)s,
            %(primary_document)s, %(filing_href)s, %(is_xbrl)s, %(available_at)s
        )
        on conflict (cik, accession_number) do update set
            form = excluded.form,
            filing_date = excluded.filing_date,
            accepted_at = excluded.accepted_at,
            period_end = excluded.period_end,
            fiscal_year = excluded.fiscal_year,
            fiscal_period = excluded.fiscal_period,
            primary_document = excluded.primary_document,
            filing_href = excluded.filing_href,
            is_xbrl = excluded.is_xbrl,
            available_at = excluded.available_at,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_sec_companyfacts(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    rows = [_with_jsonb(row, "raw_fact") for row in rows]
    sql = """
        insert into raw.sec_companyfacts_facts (
            cik, accession_number, taxonomy, concept, unit, frame, period_start, period_end, fiscal_year, fiscal_period,
            filing_date, accepted_at, available_at, value, raw_fact
        ) values (
            %(cik)s, %(accession_number)s, %(taxonomy)s, %(concept)s, %(unit)s, %(frame)s, %(period_start)s, %(period_end)s, %(fiscal_year)s, %(fiscal_period)s,
            %(filing_date)s, %(accepted_at)s, %(available_at)s, %(value)s, %(raw_fact)s
        )
        on conflict (cik, accession_number, taxonomy, concept, unit, frame, period_end) do update set
            period_start = excluded.period_start,
            fiscal_year = excluded.fiscal_year,
            fiscal_period = excluded.fiscal_period,
            filing_date = excluded.filing_date,
            accepted_at = excluded.accepted_at,
            available_at = excluded.available_at,
            value = excluded.value,
            raw_fact = excluded.raw_fact,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def upsert_fred_series(conn: Connection, rows: Iterable[dict[str, Any]]) -> None:
    sql = """
        insert into raw.fred_series_observations (
            series_id, observation_date, realtime_start, realtime_end, value
        ) values (
            %(series_id)s, %(observation_date)s, %(realtime_start)s, %(realtime_end)s, %(value)s
        )
        on conflict (series_id, observation_date, realtime_start) do update set
            realtime_end = excluded.realtime_end,
            value = excluded.value,
            ingested_at = now()
    """
    _executemany(conn, sql, rows)


def record_artifact(conn: Connection, row: dict[str, Any]) -> None:
    row = _with_jsonb(row, "metadata")
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into raw.ingestion_artifacts (
                source, dataset, source_key, symbol, cik, object_key, payload_sha256, available_at, metadata
            ) values (
                %(source)s, %(dataset)s, %(source_key)s, %(symbol)s, %(cik)s, %(object_key)s, %(payload_sha256)s, %(available_at)s, %(metadata)s
            )
            on conflict (source, dataset, source_key, available_at)
            do update set
                payload_sha256 = excluded.payload_sha256,
                metadata = excluded.metadata
            where ingestion_artifacts.ingested_at < excluded.ingested_at
            """,
            row,
        )


def fetch_active_fred_series(conn: Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("select series_id from meta.fred_series_config where is_active = true order by series_id")
        return [row["series_id"] for row in cur.fetchall()]


def get_ingestion_watermark(conn: Connection, *, source_name: str, resource_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            select cursor_value
            from meta.ingestion_watermarks
            where source_name = %s
              and resource_name = %s
            """,
            (source_name, resource_name),
        )
        row = cur.fetchone()
        return row["cursor_value"] if row else None


def upsert_ingestion_watermark(
    conn: Connection,
    *,
    source_name: str,
    resource_name: str,
    cursor_value: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into meta.ingestion_watermarks (
                source_name, resource_name, cursor_value
            ) values (
                %s, %s, %s
            )
            on conflict (source_name, resource_name) do update set
                cursor_value = excluded.cursor_value,
                updated_at = now()
            """,
            (source_name, resource_name, cursor_value),
        )


def _executemany(conn: Connection, sql: str, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def _with_jsonb(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    converted = dict(row)
    for key in keys:
        if key in converted and converted[key] is not None:
            converted[key] = Jsonb(converted[key])
    return converted


def to_decimal(value: str | None) -> Decimal | None:
    if value in (None, "", "None", "null"):
        return None
    return Decimal(value)


def to_int(value: str | None) -> int | None:
    if value in (None, "", "None", "null"):
        return None
    return int(Decimal(value))


def to_datetime(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    return value
