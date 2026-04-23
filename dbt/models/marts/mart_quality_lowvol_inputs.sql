{{ config(tags=["mart"]) }}

with returns as (
    select
        p.symbol,
        p.trade_date,
        p.daily_log_return,
        b.value as spy_adjusted_close,
        ln(b.value / nullif(lag(b.value) over (order by b.observation_date), 0)) as spy_daily_log_return
    from {{ ref('int_total_return_prices') }} p
    left join {{ ref('stg_benchmark_series') }} b
        on b.benchmark_name = 'SPY'
       and b.observation_date = p.trade_date
),
quality as (
    select
        symbol,
        trade_date,
        cohort,
        snapshot_date,
        liquidity_rank,
        snapshot_adv60,
        roe,
        gross_margin,
        operating_margin,
        debt_to_equity
    from {{ ref('mart_value_quality_inputs') }}
)
select
    r.symbol,
    r.trade_date,
    q.cohort,
    q.snapshot_date,
    q.liquidity_rank,
    q.snapshot_adv60,
    q.roe,
    q.gross_margin,
    q.operating_margin,
    q.debt_to_equity,
    stddev_samp(r.daily_log_return) over (
        partition by r.symbol
        order by r.trade_date
        rows between 62 preceding and current row
    ) as rolling_vol_63d,
    stddev_samp(r.daily_log_return) over (
        partition by r.symbol
        order by r.trade_date
        rows between 125 preceding and current row
    ) as rolling_vol_126d,
    stddev_samp(r.daily_log_return) over (
        partition by r.symbol
        order by r.trade_date
        rows between 251 preceding and current row
    ) as rolling_vol_252d,
    (
        corr(r.daily_log_return, r.spy_daily_log_return) over (
            partition by r.symbol
            order by r.trade_date
            rows between 251 preceding and current row
        ) *
        stddev_samp(r.daily_log_return) over (
            partition by r.symbol
            order by r.trade_date
            rows between 251 preceding and current row
        ) /
        nullif(
            stddev_samp(r.spy_daily_log_return) over (
                partition by r.symbol
                order by r.trade_date
                rows between 251 preceding and current row
            ), 0
        )
    ) as beta_252d_optional
from returns r
left join quality q
    on q.symbol = r.symbol
   and q.trade_date = r.trade_date
