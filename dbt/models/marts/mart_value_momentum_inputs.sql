{{ config(tags=["mart"], materialized='table') }}

/*
  mart_value_momentum_inputs
  ──────────────────────────
  Value + Momentum 팩터.
  - Momentum: stg_daily_prices 기반 rolling LAG (윈도우 함수)
  - Value 팩터: mart_value_quality_inputs (int_prices_universe_daily 기반)

  참고: momentum은 universe 밖 종목의 가격 이력도 필요하므로
        stg_daily_prices(=raw 전체)를 그대로 사용.
*/

with prices as (
    select
        symbol,
        trade_date,
        adjusted_close,
        count(*) over (
            partition by symbol
            order by trade_date
            rows between 272 preceding and current row
        )                                                                       as lookback_observations,
        lag(adjusted_close, 21)  over (partition by symbol order by trade_date) as adjusted_close_1m_ago,
        lag(adjusted_close, 252) over (partition by symbol order by trade_date) as adjusted_close_12m_ago,
        lag(adjusted_close, 273) over (partition by symbol order by trade_date) as adjusted_close_13m_ago,
        lag(adjusted_close, 126) over (partition by symbol order by trade_date) as adjusted_close_6m_ago,
        lag(adjusted_close, 63)  over (partition by symbol order by trade_date) as adjusted_close_3m_ago
    from {{ ref('stg_daily_prices') }}
),

value_inputs as (
    select
        symbol,
        trade_date,
        cohort,
        snapshot_date,
        liquidity_rank,
        snapshot_adv60,
        pe_ratio,
        pb_ratio,
        ev_to_ebitda,
        fcf_yield,
        sales_yield
    from {{ ref('mart_value_quality_inputs') }}
)

select
    p.symbol,
    p.trade_date,
    p.adjusted_close,
    p.lookback_observations,
    v.cohort,
    v.snapshot_date,
    v.liquidity_rank,
    v.snapshot_adv60,

    -- Momentum factors
    case
        when p.lookback_observations >= 273
             and p.adjusted_close_13m_ago is not null
             and p.adjusted_close_1m_ago  is not null
            then (p.adjusted_close_1m_ago / nullif(p.adjusted_close_13m_ago, 0)) - 1
    end as momentum_12_1,
    case
        when p.adjusted_close_6m_ago is not null
            then (p.adjusted_close / nullif(p.adjusted_close_6m_ago, 0)) - 1
    end as momentum_6m,
    case
        when p.adjusted_close_3m_ago is not null
            then (p.adjusted_close / nullif(p.adjusted_close_3m_ago, 0)) - 1
    end as momentum_3m,

    -- Value factors (from mart_value_quality_inputs)
    v.pe_ratio,
    v.pb_ratio,
    v.ev_to_ebitda,
    v.fcf_yield,
    v.sales_yield

from prices p
join value_inputs v
    on v.symbol = p.symbol
   and v.trade_date = p.trade_date
