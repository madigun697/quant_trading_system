{{ config(tags=["int"]) }}

with buffer_symbols as (
    select distinct symbol
    from {{ source('meta', 'universe_members') }}
    where cohort = '{{ get_buffer_cohort() }}'
      and is_active = true
),
scored as (
    select
        p.symbol,
        p.trade_date,
        avg(p.dollar_volume) over (
            partition by p.symbol
            order by p.trade_date
            rows between 59 preceding and current row
        ) as adv60,
        count(*) over (
            partition by p.symbol
            order by p.trade_date
            rows between 59 preceding and current row
        ) as liquidity_observations,
        row_number() over (
            partition by p.symbol, date_trunc('month', p.trade_date)
            order by p.trade_date desc
        ) as month_end_rank
    from {{ ref('stg_daily_prices') }} p
    join buffer_symbols b using (symbol)
)
select
    symbol,
    trade_date as snapshot_date,
    adv60,
    liquidity_observations
from scored
where month_end_rank = 1
