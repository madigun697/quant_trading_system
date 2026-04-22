with latest_overview as (
    select *,
        row_number() over (partition by symbol order by as_of_date desc, ingested_at desc) as rn
    from {{ source('raw', 'alpha_vantage_overview') }}
),
latest_status as (
    select *,
        row_number() over (partition by symbol order by source_file_date desc, ingested_at desc) as rn
    from {{ source('raw', 'alpha_vantage_listing_status') }}
)
select
    coalesce(o.symbol, s.symbol) as symbol,
    o.cik as stable_id_or_cik,
    coalesce(o.exchange, s.exchange) as exchange,
    o.asset_type as security_type,
    true as primary_listing_flag,
    s.status as active_delisted_status,
    s.ipo_date as listing_date,
    s.delisting_date,
    o.sector,
    o.industry,
    o.market_cap,
    o.shares_outstanding,
    o.as_of_date,
    greatest(coalesce(o.ingested_at, '1970-01-01'::timestamptz), coalesce(s.ingested_at, '1970-01-01'::timestamptz)) as effective_as_of,
    'alpha_vantage' as source
from latest_overview o
full outer join latest_status s
    on o.symbol = s.symbol and s.rn = 1
where coalesce(o.rn, 1) = 1
