with fred as (
    select
        series_id as benchmark_name,
        observation_date,
        value,
        'fred' as source
    from {{ source('raw', 'fred_series_observations') }}
),
spy as (
    select
        'SPY' as benchmark_name,
        trade_date as observation_date,
        adjusted_close as value,
        source
    from {{ ref('stg_daily_prices') }}
    where symbol = 'SPY'
    and effective_as_of = (
        select max(effective_as_of) from {{ ref('stg_daily_prices') }}
        where symbol = 'SPY'
    )
)
select * from fred
union all
select * from spy
