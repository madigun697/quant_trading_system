with latest_security_master as (
    select distinct on (symbol)
        symbol,
        sector
    from {{ ref('stg_security_master') }}
    order by symbol, as_of_date desc nulls last, effective_as_of desc nulls last
),
active_universe as (
    select distinct symbol
    from {{ source('meta', 'universe_members') }}
    where cohort = 'us_liquidity_700_v1'
      and is_active = true
),
coverage as (
    select
        count(*) as universe_symbols,
        count(*) filter (where latest_security_master.sector is not null) as covered_symbols
    from active_universe
    left join latest_security_master using (symbol)
)
select *
from coverage
where universe_symbols > 0
  and (covered_symbols::numeric / universe_symbols::numeric) < 0.90
