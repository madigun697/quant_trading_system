from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from quant_data_platform.config import Settings, get_settings
from quant_data_platform.storage import postgres_connection


def build_mart_coverage_report(
    *,
    cohort: str | None = None,
    lookback_months: int = 18,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    cohort = cohort or settings.default_cohort

    with postgres_connection(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            with table_inventory as (
                select 'stg.stg_daily_prices'::text as table_name, count(*) as rows, min(trade_date)::date as min_date, max(trade_date)::date as max_date, count(distinct symbol) as distinct_entities
                from stg.stg_daily_prices
                union all
                select 'mart.mart_value_quality_inputs', count(*), min(trade_date)::date, max(trade_date)::date, count(distinct symbol)
                from mart.mart_value_quality_inputs
                union all
                select 'mart.mart_value_momentum_inputs', count(*), min(trade_date)::date, max(trade_date)::date, count(distinct symbol)
                from mart.mart_value_momentum_inputs
                union all
                select 'mart.mart_quality_lowvol_inputs', count(*), min(trade_date)::date, max(trade_date)::date, count(distinct symbol)
                from mart.mart_quality_lowvol_inputs
                union all
                select 'stg.int_point_in_time_fundamentals', count(*), min(available_at)::date, max(available_at)::date, count(distinct stable_id_or_cik)
                from stg.int_point_in_time_fundamentals
            )
            select table_name, rows, min_date, max_date, distinct_entities
            from table_inventory
            order by table_name
            """
        )
        table_coverage = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            with marts as (
                select 'value_quality'::text as mart, cohort from mart.mart_value_quality_inputs
                union all
                select 'value_momentum', cohort from mart.mart_value_momentum_inputs
                union all
                select 'quality_lowvol', cohort from mart.mart_quality_lowvol_inputs
            )
            select mart, coalesce(cohort, '__NULL__') as cohort, count(*) as rows
            from marts
            group by mart, coalesce(cohort, '__NULL__')
            order by mart, coalesce(cohort, '__NULL__')
            """
        )
        cohort_split = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            with latest_universe as (
                select distinct symbol
                from stg.int_universe_snapshots
                where cohort = %(cohort)s
                  and effective_date = (
                    select max(effective_date)
                    from stg.int_universe_snapshots
                    where cohort = %(cohort)s
                  )
            ),
            security_master as (
                select distinct on (symbol) symbol, stable_id_or_cik
                from stg.stg_security_master
                order by symbol, stable_id_or_cik desc
            ),
            pit_ids as (
                select distinct stable_id_or_cik
                from stg.int_point_in_time_fundamentals
            )
            select
                case
                    when sm.stable_id_or_cik is null then 'no_security_mapping'
                    when pit.stable_id_or_cik is null then 'no_pit_fundamentals'
                    else 'has_pit_fundamentals'
                end as status,
                count(*) as symbols
            from latest_universe u
            left join security_master sm using (symbol)
            left join pit_ids pit on pit.stable_id_or_cik = sm.stable_id_or_cik
            group by 1
            order by 1
            """,
            {"cohort": cohort},
        )
        universe_mapping = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            with latest_universe as (
                select distinct symbol
                from stg.int_universe_snapshots
                where cohort = %(cohort)s
                  and effective_date = (
                    select max(effective_date)
                    from stg.int_universe_snapshots
                    where cohort = %(cohort)s
                  )
            ),
            security_master as (
                select distinct on (symbol) symbol, stable_id_or_cik
                from stg.stg_security_master
                order by symbol, stable_id_or_cik desc
            ),
            pit_ids as (
                select distinct stable_id_or_cik
                from stg.int_point_in_time_fundamentals
            )
            select
                u.symbol,
                sm.stable_id_or_cik,
                case
                    when sm.stable_id_or_cik is null then 'no_security_mapping'
                    when pit.stable_id_or_cik is null then 'no_pit_fundamentals'
                end as issue
            from latest_universe u
            left join security_master sm using (symbol)
            left join pit_ids pit on pit.stable_id_or_cik = sm.stable_id_or_cik
            where sm.stable_id_or_cik is null or pit.stable_id_or_cik is null
            order by issue, u.symbol
            """,
            {"cohort": cohort},
        )
        missing_symbol_diagnostics = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            with latest_trade as (
                select max(trade_date) as trade_date
                from mart.mart_value_quality_inputs
                where cohort = %(cohort)s
            )
            select
                count(*) as rows,
                count(distinct symbol) as symbols,
                sum((pe_ratio is null)::int) as pe_nulls,
                sum((pb_ratio is null)::int) as pb_nulls,
                sum((ev_to_ebitda is null)::int) as ev_to_ebitda_nulls,
                sum((fcf_yield is null)::int) as fcf_yield_nulls,
                sum((sales_yield is null)::int) as sales_yield_nulls,
                sum((roe is null)::int) as roe_nulls,
                sum((roic_proxy is null)::int) as roic_proxy_nulls,
                sum((gross_margin is null)::int) as gross_margin_nulls,
                sum((operating_margin is null)::int) as operating_margin_nulls,
                sum((debt_to_equity is null)::int) as debt_to_equity_nulls,
                sum((interest_coverage is null)::int) as interest_coverage_nulls,
                sum((accruals is null)::int) as accruals_nulls
            from mart.mart_value_quality_inputs
            where cohort = %(cohort)s
              and trade_date = (select trade_date from latest_trade)
            """,
            {"cohort": cohort},
        )
        latest_quality_nulls = dict(cur.fetchone())

        cur.execute(
            """
            with monthly as (
                select
                    'value_quality'::text as mart,
                    date_trunc('month', trade_date)::date as month,
                    count(*) filter (where cohort = %(cohort)s) as rows,
                    count(distinct symbol) filter (
                        where cohort = %(cohort)s
                          and pe_ratio is not null
                          and pb_ratio is not null
                          and ev_to_ebitda is not null
                          and fcf_yield is not null
                          and sales_yield is not null
                          and roe is not null
                          and roic_proxy is not null
                          and gross_margin is not null
                          and operating_margin is not null
                          and debt_to_equity is not null
                          and interest_coverage is not null
                          and accruals is not null
                    ) as eligible_symbols
                from mart.mart_value_quality_inputs
                group by 1, 2

                union all

                select
                    'value_momentum',
                    date_trunc('month', trade_date)::date,
                    count(*) filter (where cohort = %(cohort)s),
                    count(distinct symbol) filter (
                        where cohort = %(cohort)s
                          and momentum_12_1 is not null
                          and momentum_6m is not null
                          and momentum_3m is not null
                          and pe_ratio is not null
                          and pb_ratio is not null
                          and ev_to_ebitda is not null
                          and fcf_yield is not null
                          and sales_yield is not null
                    )
                from mart.mart_value_momentum_inputs
                group by 1, 2

                union all

                select
                    'quality_lowvol',
                    date_trunc('month', trade_date)::date,
                    count(*) filter (where cohort = %(cohort)s),
                    count(distinct symbol) filter (
                        where cohort = %(cohort)s
                          and roe is not null
                          and gross_margin is not null
                          and operating_margin is not null
                          and debt_to_equity is not null
                          and rolling_vol_63d is not null
                          and rolling_vol_126d is not null
                          and rolling_vol_252d is not null
                    )
                from mart.mart_quality_lowvol_inputs
                group by 1, 2
            )
            select mart, month, rows, eligible_symbols
            from monthly
            where month >= date_trunc('month', current_date) - (%(lookback_months)s::int * interval '1 month')
            order by mart, month desc
            """,
            {"cohort": cohort, "lookback_months": lookback_months},
        )
        monthly_eligibility = [dict(row) for row in cur.fetchall()]

    return {
        "cohort": cohort,
        "lookback_months": lookback_months,
        "table_coverage": _normalize(table_coverage),
        "cohort_split": _normalize(cohort_split),
        "universe_mapping": _normalize(universe_mapping),
        "missing_symbol_diagnostics": _normalize(missing_symbol_diagnostics),
        "latest_quality_nulls": _normalize(latest_quality_nulls),
        "monthly_eligibility": _normalize(monthly_eligibility),
    }


def render_mart_coverage_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Cohort: {report['cohort']}")
    lines.append(f"Lookback months: {report['lookback_months']}")
    lines.append("")
    lines.append("Table coverage")
    for row in report["table_coverage"]:
        lines.append(
            f"- {row['table_name']}: rows={row['rows']}, min_date={row['min_date']}, max_date={row['max_date']}, distinct_entities={row['distinct_entities']}"
        )
    lines.append("")
    lines.append("Mart cohort split")
    for row in report["cohort_split"]:
        lines.append(f"- {row['mart']} / {row['cohort']}: rows={row['rows']}")
    lines.append("")
    lines.append("Universe mapping")
    for row in report["universe_mapping"]:
        lines.append(f"- {row['status']}: symbols={row['symbols']}")
    if report["missing_symbol_diagnostics"]:
        lines.append("")
        lines.append("Missing symbol diagnostics")
        for row in report["missing_symbol_diagnostics"]:
            lines.append(f"- {row['symbol']}: {row['issue']} ({row['stable_id_or_cik'] or 'no-id'})")
    lines.append("")
    lines.append("Latest value_quality null profile")
    for key, value in report["latest_quality_nulls"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Monthly eligible symbols")
    for row in report["monthly_eligibility"]:
        lines.append(
            f"- {row['mart']} {row['month']}: eligible_symbols={row['eligible_symbols']}, rows={row['rows']}"
        )
    return "\n".join(lines)


def report_as_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value
