from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from psycopg import Connection


def fetch_universe_symbols(conn: Connection, cohort: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct symbol
            from meta.universe_members
            where cohort = %s
              and is_active = true
            order by symbol
            """,
            (cohort,),
        )
        return [row["symbol"] for row in cur.fetchall()]


def fetch_universe_ciks(conn: Connection, cohort: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct o.cik
            from meta.universe_members u
            join raw.alpha_vantage_overview o
              on o.symbol = u.symbol
            where u.cohort = %s
              and u.is_active = true
              and o.cik is not null
            order by o.cik
            """,
            (cohort,),
        )
        return [row["cik"] for row in cur.fetchall()]


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


def upsert_sec_submission(conn: Connection, row: dict[str, Any]) -> None:
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
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into raw.ingestion_artifacts (
                source, dataset, source_key, symbol, cik, object_key, payload_sha256, available_at, metadata
            ) values (
                %(source)s, %(dataset)s, %(source_key)s, %(symbol)s, %(cik)s, %(object_key)s, %(payload_sha256)s, %(available_at)s, %(metadata)s
            )
            """,
            row,
        )


def fetch_active_fred_series(conn: Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("select series_id from meta.fred_series_config where is_active = true order by series_id")
        return [row["series_id"] for row in cur.fetchall()]


def _executemany(conn: Connection, sql: str, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


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
